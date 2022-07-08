#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# PatchBay Canvas engine using QGraphicsView/Scene
# Copyright (C) 2010-2019 Filipe Coelho <falktx@falktx.com>
# Copyright (C) 2019-2022 Mathieu Picot <picotmathieu@gmail.com>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License as
# published by the Free Software Foundation; either version 2 of
# the License, or any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# For a full copy of the GNU General Public License see the doc/GPL.txt file.


# Imports (Globals)
import logging
from math import floor
import math
from shutil import move
import time
from typing import Iterator

from PyQt5.QtCore import (QT_VERSION, pyqtSignal, pyqtSlot,
                          Qt, QPoint, QPointF, QRectF, QTimer, QMarginsF)
from PyQt5.QtGui import QCursor, QPixmap, QPolygonF, QBrush
from PyQt5.QtWidgets import (QGraphicsRectItem, QGraphicsScene, QApplication,
                             QGraphicsView, QGraphicsItem)

# Imports (locals)
from .init_values import (
    CanvasItemType,
    Direction,
    canvas,
    options,
    CallbackAct,
    MAX_PLUGIN_ID_ALLOWED)

from .box_widget import BoxWidget
from .connectable_widget import ConnectableWidget
from .line_widget import LineWidget
from .icon_widget import IconPixmapWidget, IconSvgWidget


_logger = logging.getLogger(__name__)


class RubberbandRect(QGraphicsRectItem):
    " This class is used by rectangle selection when user "
    " press mouse button and move to select boxes. "
    def __init__(self, scene: QGraphicsScene):
        QGraphicsRectItem.__init__(self, QRectF(0, 0, 0, 0))

        self.setZValue(-1)
        self.hide()

        scene.addItem(self)

    def type(self) -> CanvasItemType:
        return CanvasItemType.RUBBERBAND


class MovingBox:
    widget: BoxWidget
    from_pt: QPointF
    to_pt: QPoint
    start_time: float


class WrappingBox:
    widget: BoxWidget
    wrap: bool


class PatchSceneMoth(QGraphicsScene):
    " This class is used for the scene. "
    " The child class in scene.py has all things to manage"
    " repulsives boxes."
    scale_changed = pyqtSignal(float)
    scene_group_moved = pyqtSignal(int, int, QPointF)
    plugin_selected = pyqtSignal(list)

    def __init__(self, parent, view: QGraphicsView):
        QGraphicsScene.__init__(self, parent)

        self._scale_area = False
        self._mouse_down_init = False
        self._mouse_rubberband = False
        self._mid_button_down = False
        self._pointer_border = QRectF(0.0, 0.0, 1.0, 1.0)
        self._scale_min = 0.1
        self._scale_max = 4.0

        self._rubberband = RubberbandRect(self)
        self._rubberband_selection = False
        self._rubberband_orig_point = QPointF(0, 0)

        self._view = view
        if not self._view:
            _logger.critical("Invalid view")
            return

        # self._view.setStyleSheet("QMenu{background-color:#80000090}")

        self._cursor_cut = None
        self._cursor_zoom_area = None

        self.move_boxes = list[MovingBox]()
        self.wrapping_boxes = list[WrappingBox]()
        self._MOVE_DURATION = 0.300 # 300ms
        self._MOVE_TIMER_INTERVAL = 20 # 20 ms step animation (50 Hz)
        self._move_timer_start_at = 0
        self._move_box_timer = QTimer()
        self._move_box_timer.setInterval(self._MOVE_TIMER_INTERVAL)
        self._move_box_timer.timeout.connect(self.move_boxes_animation)

        self.resizing_scene = False
        self.translating_view = False
        self._last_border_translate = QPointF(0.0, 0.0)

        self._borders_nav_timer = QTimer()
        self._borders_nav_timer.setInterval(50)
        self._borders_nav_timer.timeout.connect(self._cursor_view_navigation)
        self._last_view_cpos = QPointF()
        self._allowed_nav_directions = set[Direction]()

        self.flying_connectable = None

        self.selectionChanged.connect(self._slot_selection_changed)

    def clear(self):
        # reimplement Qt function and fix missing rubberband after clear
        QGraphicsScene.clear(self)
        self._rubberband = RubberbandRect(self)
        self.update_theme()

    def screen_position(self, point: QPointF) -> QPoint:
        return self._view.mapToGlobal(self._view.mapFromScene(point))

    def get_device_pixel_ratio_f(self):
        if QT_VERSION < 0x50600:
            return 1.0

        return self._view.devicePixelRatioF()

    def get_scale_factor(self):
        return self._view.transform().m11()

    def fix_scale_factor(self, transform=None):
        fix, set_view = False, False
        if not transform:
            set_view = True
            view = self._view
            transform = view.transform()

        scale = transform.m11()
        if scale > self._scale_max:
            fix = True
            transform.reset()
            transform.scale(self._scale_max, self._scale_max)
        elif scale < self._scale_min:
            fix = True
            transform.reset()
            transform.scale(self._scale_min, self._scale_min)

        if set_view:
            if fix:
                view.setTransform(transform)
            self.scale_changed.emit(transform.m11())

        return fix

    def _cursor_view_navigation(self):
        ''' This function is called every 50 ms when mouse
            left button is pressed. It moves the view if the mouse cursor
            is near a border of the view (in the limits of the scene size). '''
        # max speed of the drag when mouse is at a side pixel of the view  
        SPEED = 0.8
        
        # Acceleration, doesn't affect max speed
        POWER = 14

        view_width = self._view.width()
        view_height = self._view.height()
        if self._view.verticalScrollBar().isVisible():
            view_width -= self._view.verticalScrollBar().width()
        if self._view.horizontalScrollBar().isVisible():
            view_height -= self._view.horizontalScrollBar().height()
        
        view_cpos = self._view.mapFromGlobal(QCursor.pos())
        scene_cpos = self._view.mapToScene(view_cpos)
        
        # The scene relative area we want to be visible in the view 
        ensure_rect = QRectF(scene_cpos.x() - 1.0,
                             scene_cpos.y() - 1.0,
                             2.0, 2.0)
        
        # the scene relative area currently visible in the view
        vs_rect = QRectF(
            QPointF(self._view.mapToScene(0, 0)),
            QPointF(self._view.mapToScene(view_width - 1, view_height -1)))
        
        # The speed of the move depends on the scene size
        # to allow fast moves from one scene corner to another one.
        speed_hor = (SPEED * (self.sceneRect().width() - vs_rect.width())
                     / vs_rect.width()) 
        speed_ver = (SPEED * (self.sceneRect().height() - vs_rect.height())
                     / vs_rect.height())

        interval_hor = vs_rect.width() / 2
        interval_ver = vs_rect.height() / 2
        
        # Navigation is allowed in a direction only if mouse cursor has
        # already been moved in this direction, in order to prevent unintended
        # moves when user just pressed the mouse button.
        if self._last_view_cpos.isNull():
            self._allowed_nav_directions.clear()
        elif len(self._allowed_nav_directions) < 4:
            if view_cpos.x() < self._last_view_cpos.x():
                self._allowed_nav_directions.add(Direction.LEFT)
            elif view_cpos.x() > self._last_view_cpos.x():
                self._allowed_nav_directions.add(Direction.RIGHT)

            if view_cpos.y() < self._last_view_cpos.y():
                self._allowed_nav_directions.add(Direction.UP)
            elif view_cpos.y() > self._last_view_cpos.y():
                self._allowed_nav_directions.add(Direction.DOWN)

        self._last_view_cpos = view_cpos
        
        # Define the limits we want to see in the view
        # Note that the zone where there is no move is defined by the fact
        # the move in a direction is converted from float to int.
        # This way, a move lower than 1.0 pixel will be ignored.
        # By chance, the lower possible speed is good
        # 1.0 pixel * (1s / 0.050s) = 20 pixels/second. 
        
        apply = False
        
        if (Direction.LEFT in self._allowed_nav_directions
                and scene_cpos.x() < vs_rect.center().x()):
            offset = vs_rect.center().x() - max(scene_cpos.x(), vs_rect.left())
            ratio_x = offset / interval_hor
            move_x = - speed_hor * ((ratio_x ** POWER) * interval_hor)
            left = vs_rect.left() + int(move_x)
            ensure_rect.moveLeft(max(left, self.sceneRect().left()))
            if int(move_x):
                apply = True

        elif (Direction.RIGHT in self._allowed_nav_directions
                and scene_cpos.x() > vs_rect.center().x()):
            offset = min(scene_cpos.x(), vs_rect.right()) - vs_rect.center().x()
            ratio_x = offset / interval_hor
            move_x = speed_hor * ((ratio_x ** POWER) * interval_hor)
            right = vs_rect.right() + int(move_x)
            ensure_rect.moveRight(min(right, self.sceneRect().right()))
            if int(move_x):
                apply = True
            
        if (Direction.UP in self._allowed_nav_directions
                and scene_cpos.y() < vs_rect.center().y()):
            offset = vs_rect.center().y() - max(scene_cpos.y(), vs_rect.top())
            ratio_y = offset / interval_ver
            move_y = - speed_ver * ((ratio_y ** POWER) * interval_ver)
            top = vs_rect.top() + int(move_y)
            ensure_rect.moveTop(max(top, self.sceneRect().top()))
            if int(move_y):
                apply = True
        
        elif (Direction.DOWN in self._allowed_nav_directions
                and scene_cpos.y() > vs_rect.center().y()):
            offset = min(scene_cpos.y(), vs_rect.bottom()) - vs_rect.center().y()
            ratio_y = offset / interval_ver
            move_y = speed_ver * ((ratio_y ** POWER) * interval_ver)
            bottom = vs_rect.bottom() + int(move_y)
            ensure_rect.moveBottom(min(bottom, self.sceneRect().bottom()))
            if int(move_y):
                apply = True
        
        if apply:
            self._view.ensureVisible(ensure_rect, 0.0, 0.0)

    def _start_navigation_on_borders(self):
        if (options.borders_navigation
                and not self._borders_nav_timer.isActive()):
            self._last_view_cpos = QPointF()
            self._borders_nav_timer.start()

    def fix_temporary_scroll_bars(self):
        if self._view is None:
            return

        if self._view.horizontalScrollBar().isVisible():
            self._view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        else:
            self._view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        if self._view.verticalScrollBar().isVisible():
            self._view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        else:
            self._view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    def reset_scroll_bars(self):
        self._view.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._view.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

    def move_boxes_animation(self):
        # Animation is nice but not the priority.
        # Do not ensure all steps are played
        # but just move the box where it has to go now
        time_since_start = time.time() - self._move_timer_start_at
        ratio = min(1.0, time_since_start / self._MOVE_DURATION)

        for moving_box in self.move_boxes:
            if moving_box.widget is not None:
                x = (moving_box.from_pt.x()
                     + ((moving_box.to_pt.x() - moving_box.from_pt.x())
                        * (ratio ** 0.6)))
                
                y = (moving_box.from_pt.y()
                     + ((moving_box.to_pt.y() - moving_box.from_pt.y())
                        * (ratio ** 0.6)))

                moving_box.widget.setPos(x, y)
                moving_box.widget.repaint_lines(fast_move=True)

        for wrapping_box in self.wrapping_boxes:
            if wrapping_box.widget is not None:
                if time_since_start >= self._MOVE_DURATION:
                    wrapping_box.widget.animate_wrapping(1.00)
                else:
                    wrapping_box.widget.animate_wrapping(ratio)

        self.resize_the_scene()

        if time_since_start >= self._MOVE_DURATION:
            # Animation is finished
            self._move_box_timer.stop()
            
            # box update positions is forbidden while widget is in self.move_boxes
            # So we copy the list before to clear it
            # then we can ask update_positions on widgets
            boxes = [mb.widget for mb in self.move_boxes]
            self.move_boxes.clear()
            self.wrapping_boxes.clear()

            for box in boxes:
                if box is not None:
                    if box.update_positions_pending:
                        box.update_positions()
                    box.send_move_callback()

            canvas.qobject.move_boxes_finished.emit()

    def add_box_to_animation(self, box_widget: BoxWidget, to_x: int, to_y: int,
                             force_anim=True):
        for moving_box in self.move_boxes:
            if moving_box.widget is box_widget:
                break
        else:
            if not force_anim:
                # if box is not in a current animation
                # and force_anim is False,
                # then box position is directly changed
                if box_widget is not None:
                    box_widget.setPos(int(to_x), int(to_y))
                return

            moving_box = MovingBox()
            moving_box.widget = box_widget
            self.move_boxes.append(moving_box)

        moving_box.from_pt = box_widget.pos()
        moving_box.to_pt = QPoint(to_x, to_y)
        moving_box.start_time = time.time() - self._move_timer_start_at

        if not self._move_box_timer.isActive():
            moving_box.start_time = 0.0
            self._move_timer_start_at = time.time()
            self._move_box_timer.start()

    def add_box_to_animation_wrapping(self, box_widget: BoxWidget, wrap: bool):
        for wrapping_box in self.wrapping_boxes:
            if wrapping_box.widget is box_widget:
                wrapping_box.wrap = wrap
                break
        else:
            wrapping_box = WrappingBox
            wrapping_box.widget = box_widget
            wrapping_box.wrap = wrap
            self.wrapping_boxes.append(wrapping_box)
        
        if not self._move_box_timer.isActive():
            self._move_timer_start_at = time.time()
            self._move_box_timer.start()

    def center_view_on(self, widget):
        self._view.centerOn(widget)

    def get_connectable_item_at(
            self, pos: QPointF, origin: ConnectableWidget) -> ConnectableWidget:
        for item in self.items(pos, Qt.ContainsItemShape, Qt.AscendingOrder):
            if isinstance(item, ConnectableWidget) and item is not origin:
                return item

    def get_box_at(self, pos: QPointF) -> BoxWidget:
        for item in self.items(pos, Qt.ContainsItemShape, Qt.AscendingOrder):
            if isinstance(item, BoxWidget):
                return item
    
    def get_selected_boxes(self) -> list[BoxWidget]:
        return [i for i in self.selectedItems() if isinstance(i, BoxWidget)]

    def list_selected_boxes(self) -> Iterator[BoxWidget]:
        for item in self.selectedItems():
            if isinstance(item, BoxWidget):
                yield item

    def removeItem(self, item: QGraphicsItem):
        for child_item in item.childItems():
            QGraphicsScene.removeItem(self, child_item)
        QGraphicsScene.removeItem(self, item)

    def update_limits(self):
        w0 = canvas.size_rect.width()
        h0 = canvas.size_rect.height()
        w1 = self._view.width()
        h1 = self._view.height()
        self._scale_min = w1/w0 if w0/h0 > w1/h1 else h1/h0

    def update_theme(self):
        if canvas.theme.scene_background_image is not None:
            bg_brush = QBrush()
            bg_brush.setTextureImage(canvas.theme.scene_background_image)
            self.setBackgroundBrush(bg_brush)
        else:
            self.setBackgroundBrush(canvas.theme.scene_background_color)
        
        self._rubberband.setPen(canvas.theme.rubberband.fill_pen())
        self._rubberband.setBrush(canvas.theme.rubberband.background_color())

        cur_color = ("black" if canvas.theme.scene_background_color.blackF() < 0.5
                     else "white")
        self._cursor_cut = QCursor(QPixmap(f":/cursors/cut-{cur_color}.png"), 1, 1)
        self._cursor_zoom_area = QCursor(
            QPixmap(f":/cursors/zoom-area-{cur_color}.png"), 8, 7)

        for connection in canvas.list_connections():
            if connection.widget is not None:
                connection.widget.update_theme()

    def drawBackground(self, painter, rect):
        painter.save()
        painter.setPen(Qt.NoPen)
        
        if not canvas.theme.scene_background_image.isNull():
            canvas.theme.scene_background_image.setDevicePixelRatio(3.0)
            bg_brush = QBrush()
            bg_brush.setTextureImage(canvas.theme.scene_background_image)
            painter.setBrush(bg_brush)
            painter.drawRect(rect)

        painter.setBrush(canvas.theme.scene_background_color)        
        painter.drawRect(rect)
        painter.restore()

    def get_new_scene_rect(self) -> QRectF:
        full_rect = QRectF()

        for widget in canvas.list_boxes():
            full_rect |= widget.sceneBoundingRect().marginsAdded(
                QMarginsF(50.0, 20.0, 50.0, 20.0))

        return full_rect

    def resize_the_scene(self):
        if not options.elastic:
            return

        scene_rect = self.get_new_scene_rect()
        
        if not scene_rect.isNull():
            self.resizing_scene = True
            self.setSceneRect(scene_rect)
            self.resizing_scene = False

    def set_elastic(self, yesno: bool):
        options.elastic = True
        self.resize_the_scene()
        options.elastic = yesno

        if not yesno:
            # resize the scene to a null QRectF to auto set sceneRect
            # always growing with items
            self.setSceneRect(QRectF())

            # add a fake item with the current canvas scene size
            # (calculated with items), and remove it.
            fake_item = QGraphicsRectItem(self.get_new_scene_rect())
            self.addItem(fake_item)
            self.update()
            self.removeItem(fake_item)

    def set_cursor(self, cursor: QCursor):
        if self._view is None:
            return
        
        self._view.viewport().setCursor(cursor)

    def unset_cursor(self):
        if self._view is None:
            return
        
        self._view.viewport().unsetCursor()

    def zoom_ratio(self, percent: float):
        ratio = percent / 100.0
        transform = self._view.transform()
        transform.reset()
        transform.scale(ratio, ratio)
        self._view.setTransform(transform)

        for box in canvas.list_boxes():
            if box.top_icon:
                box.top_icon.update_zoom(ratio)

    def zoom_fit(self):
        if self._view is None:
            return

        full_rect = QRectF()
        
        for item in self.items():
            if isinstance(item, BoxWidget) and item.isVisible():
                rect = item.sceneBoundingRect()
                
                if full_rect.isNull():
                    full_rect = rect
                    continue
                
                full_rect.setLeft(min(full_rect.left(), rect.left()))
                full_rect.setRight(max(full_rect.right(), rect.right()))
                full_rect.setTop(min(full_rect.top(), rect.top()))
                full_rect.setBottom(max(full_rect.bottom(), rect.bottom()))
                
        if full_rect.isNull():
            return
        
        self._view.fitInView(full_rect, Qt.KeepAspectRatio)
        self.fix_scale_factor()
        self.scale_changed.emit(self._view.transform().m11())

    def zoom_in(self):
        view = self._view
        transform = view.transform()
        if transform.m11() < self._scale_max:
            transform.scale(1.2, 1.2)
            if transform.m11() > self._scale_max:
                transform.reset()
                transform.scale(self._scale_max, self._scale_max)
            view.setTransform(transform)
        self.scale_changed.emit(transform.m11())

    def zoom_out(self):
        view = self._view
        transform = view.transform()
        if transform.m11() > self._scale_min:
            transform.scale(0.833333333333333, 0.833333333333333)
            if transform.m11() < self._scale_min:
                transform.reset()
                transform.scale(self._scale_min, self._scale_min)
            view.setTransform(transform)
        self.scale_changed.emit(transform.m11())

    def zoom_reset(self):
        self._view.resetTransform()
        self.scale_changed.emit(1.0)

    @pyqtSlot()
    def _slot_selection_changed(self):
        items_list = self.selectedItems()

        if len(items_list) == 0:
            self.plugin_selected.emit([])
            return

        plugin_list = []

        for item in items_list:
            if item and item.isVisible():
                group_item = None

                if isinstance(item, BoxWidget):
                    group_item = item
                elif isinstance(item, ConnectableWidget):
                    group_item = item.parentItem()

                if group_item is not None and group_item._plugin_id >= 0:
                    plugin_id = group_item._plugin_id
                    if plugin_id > MAX_PLUGIN_ID_ALLOWED:
                        plugin_id = 0
                    plugin_list.append(plugin_id)

        self.plugin_selected.emit(plugin_list)

    def _trigger_rubberband_scale(self):
        # TODO, should enable an auto-zoom on 
        # Ctrl+Right clic + drag (rubberband)
        self._scale_area = True

        if self._cursor_zoom_area:
            self.set_cursor(self._cursor_zoom_area)

    def get_zoom_scale(self):
        return self._view.transform().m11()

    def keyPressEvent(self, event):
        if not self._view:
            event.ignore()
            return

        if event.key() == Qt.Key_Control:
            if self._mid_button_down:
                self._start_connection_cut()

        elif event.key() == Qt.Key_Home:
            event.accept()
            self.zoom_fit()
            return

        elif QApplication.keyboardModifiers() & Qt.ControlModifier:
            if event.key() == Qt.Key_Plus:
                event.accept()
                self.zoom_in()
                return

            if event.key() == Qt.Key_Minus:
                event.accept()
                self.zoom_out()
                return

            if event.key() == Qt.Key_1:
                event.accept()
                self.zoom_reset()
                return

        QGraphicsScene.keyPressEvent(self, event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key_Control:
            # Connection cut mode off
            if self._mid_button_down:
                self.unset_cursor()

        QGraphicsScene.keyReleaseEvent(self, event)

    def _start_connection_cut(self):
        if self._cursor_cut:
            self.set_cursor(self._cursor_cut)

    def zoom_wheel(self, delta: int):
        transform = self._view.transform()
        scale = transform.m11()

        if ((delta > 0 and scale < self._scale_max)
                or (delta < 0 and scale > self._scale_min)):
            # prevent too large unzoom
            if delta < 0:
                rect = self.sceneRect()

                top_left_vw = self._view.mapFromScene(rect.topLeft())
                if (top_left_vw.x() > self._view.width() / 4
                        and top_left_vw.y() > self._view.height() / 4):
                    return

            # Apply scale
            factor = 1.4142135623730951 ** (delta / 240.0)
            transform.scale(factor, factor)
            self.fix_scale_factor(transform)
            self._view.setTransform(transform)
            self.scale_changed.emit(transform.m11())

            # Update box icons especially when they are not scalable
            # eg. coming from system theme
            for box in canvas.list_boxes():
                if box.top_icon:
                    box.top_icon.update_zoom(scale * factor)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton and not canvas.menu_shown:
            # parse items under mouse to prevent CallbackAct.DOUBLE_CLICK
            # if mouse is on a box
            
            has_box = False
            items = self.items(
                event.scenePos(), Qt.ContainsItemShape, Qt.AscendingOrder)

            for item in items:
                if isinstance(item, ConnectableWidget):
                    # start a flying connection with mouse button not pressed
                    # here we just change the cursor and define the ConnectableWidget
                    self.flying_connectable = item
                    self.set_cursor(QCursor(Qt.CrossCursor))
                    self._start_navigation_on_borders()
                    return

                if not has_box:
                    has_box = isinstance(item, BoxWidget)
            
            if not has_box:
                canvas.callback(CallbackAct.BG_DOUBLE_CLICK)

        QGraphicsScene.mouseDoubleClickEvent(self, event)

    def mousePressEvent(self, event):
        if self.flying_connectable:
            if event.button() == Qt.LeftButton:
                self.flying_connectable.mouseReleaseEvent(event)
                self.flying_connectable = None
                self.set_cursor(Qt.ArrowCursor)
                return

            if event.button() == Qt.RightButton:
                self.flying_connectable.mousePressEvent(event)
                return

        ctrl_pressed = bool(QApplication.keyboardModifiers() & Qt.ControlModifier)
        self._mouse_down_init = bool(
            (event.button() == Qt.LeftButton and not ctrl_pressed)
            or (event.button() == Qt.RightButton and ctrl_pressed))
        
        self._mouse_rubberband = False

        if event.button() == Qt.MidButton:
            if ctrl_pressed:
                self._mid_button_down = True
                self._start_connection_cut()

                pos = event.scenePos()
                self._pointer_border.moveTo(floor(pos.x()), floor(pos.y()))

                for item in self.items(self._pointer_border):
                    if isinstance(item, (ConnectableWidget, LineWidget)):
                        item.trigger_disconnect()

        QGraphicsScene.mousePressEvent(self, event)
        canvas.menu_shown = False

        if event.buttons() == Qt.LeftButton:
            self._start_navigation_on_borders()

    def mouseMoveEvent(self, event):
        if self.flying_connectable is not None:
            self.flying_connectable.mouseMoveEvent(event)
            return
        
        if self._mouse_down_init:
            self._mouse_down_init = False
            topmost = self.itemAt(event.scenePos(), self._view.transform())
            self._mouse_rubberband = (
                not isinstance(topmost, (BoxWidget, ConnectableWidget,
                                         IconPixmapWidget, IconSvgWidget))
                and int(event.buttons()))

        if self._mouse_rubberband:
            event.accept()
            pos = event.scenePos()
            pos_x = pos.x()
            pos_y = pos.y()
            if not self._rubberband_selection:
                self._rubberband.show()
                self._rubberband_selection = True
                self._rubberband_orig_point = pos
            rubb_orig_point = self._rubberband_orig_point

            x = min(pos_x, rubb_orig_point.x())
            y = min(pos_y, rubb_orig_point.y())

            line_hinting = canvas.theme.rubberband.fill_pen().widthF() / 2.0
            self._rubberband.setRect(
                x + line_hinting, y + line_hinting,
                abs(pos_x - rubb_orig_point.x()),
                abs(pos_y - rubb_orig_point.y()))

        if (self._mid_button_down
                and QApplication.keyboardModifiers() & Qt.ControlModifier):
            for item in self.items(
                    QPolygonF([event.scenePos(), event.lastScenePos(),
                               event.scenePos()])):
                if isinstance(item, LineWidget):
                    item.trigger_disconnect()
        
        QGraphicsScene.mouseMoveEvent(self, event)

    def mouseReleaseEvent(self, event):
        if self.flying_connectable:
            QGraphicsScene.mouseReleaseEvent(self, event)
            return
        
        if self._scale_area and not self._rubberband_selection:
            self._scale_area = False
            self.unset_cursor()

        if self._rubberband_selection:
            if self._scale_area:
                self._scale_area = False
                self.unset_cursor()

                rect = self._rubberband.rect()
                self._view.fitInView(
                    rect.x(), rect.y(),
                    rect.width(), rect.height(), Qt.KeepAspectRatio)
                self.fix_scale_factor()

            else:
                for item in self.items():
                    if isinstance(item, BoxWidget):
                        item_rect = item.sceneBoundingRect()
                        if self._rubberband.rect().contains(item_rect):
                            item.setSelected(True)

            self._rubberband.hide()
            self._rubberband.setRect(0, 0, 0, 0)
            self._rubberband_selection = False

        else:
            for item in self.get_selected_boxes():
                item.check_item_pos()
                self.scene_group_moved.emit(
                    item.get_group_id(), item.get_splitted_mode(),
                    item.scenePos())

            if len(self.selectedItems()) > 1:
                self.update()

        self._mouse_down_init = False
        self._mouse_rubberband = False

        if event.button() == Qt.LeftButton:
            self._borders_nav_timer.stop()

        if event.button() == Qt.MidButton:
            event.accept()

            self._mid_button_down = False

            # Connection cut mode off
            if QApplication.keyboardModifiers() & Qt.ControlModifier:
                self.unset_cursor()
            return

        QGraphicsScene.mouseReleaseEvent(self, event)

    def wheelEvent(self, event):
        if not self._view:
            event.ignore()
            return

        if QApplication.keyboardModifiers() & Qt.ControlModifier:
            self.zoom_wheel(event.delta())
            event.accept()
            return

        QGraphicsScene.wheelEvent(self, event)

    def contextMenuEvent(self, event):
        if canvas.is_line_mov:
            event.ignore()
            return
        
        for item in self.items(event.scenePos()):
            if isinstance(item, (BoxWidget, ConnectableWidget)):
                break
        else:
            if QApplication.keyboardModifiers() & Qt.ControlModifier:
                event.accept()
                self._trigger_rubberband_scale()
                return

            event.accept()
            sc_pos = event.screenPos()
            canvas.callback(CallbackAct.BG_RIGHT_CLICK, sc_pos.x(), sc_pos.y())
            return

        QGraphicsScene.contextMenuEvent(self, event)
