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
from math import floor
import time

from PyQt5.QtCore import (QT_VERSION, pyqtSignal, pyqtSlot, qFatal,
                          Qt, QPoint, QPointF, QRectF, QTimer, QMarginsF)
from PyQt5.QtGui import QCursor, QPixmap, QPolygonF, QBrush
from PyQt5.QtWidgets import (QGraphicsRectItem, QGraphicsScene, QApplication,
                             QGraphicsView, QGraphicsItem)

# Imports (locals)
from .init_values import (
    CanvasItemType,
    canvas,
    options,
    CallbackAct,
    MAX_PLUGIN_ID_ALLOWED)

from .canvasbox import CanvasBox
from .canvasconnectable import CanvasConnectable
from .canvasbezierline import CanvasBezierLine
from .canvasicon import CanvasIconPixmap, CanvasSvgIcon


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
    widget: CanvasBox
    from_pt: QPointF
    to_pt: QPoint
    start_time: float


class WrappingBox:
    widget: CanvasBox
    wrap: bool


class AbstractPatchScene(QGraphicsScene):
    " This class is used for the scene. "
    " The child class in scene.py has all things to manage"
    " repulsives boxes."
    scaleChanged = pyqtSignal(float)
    sceneGroupMoved = pyqtSignal(int, int, QPointF)
    pluginSelected = pyqtSignal(list)

    def __init__(self, parent, view: QGraphicsView):
        QGraphicsScene.__init__(self, parent)

        #self.setItemIndexMethod(QGraphicsScene.NoIndex)
        self._scale_area = False
        self._mouse_down_init = False
        self._mouse_rubberband = False
        self._mid_button_down = False
        self._pointer_border = QRectF(0.0, 0.0, 1.0, 1.0)
        self._scale_min = 0.1
        self._scale_max = 4.0

        self.scales = (0.1, 0.25, 0.4, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0)

        self._rubberband = RubberbandRect(self)
        self._rubberband_selection = False
        self._rubberband_orig_point = QPointF(0, 0)

        self._view = view
        if not self._view:
            qFatal("PatchCanvas::PatchScene() - invalid view")

        self.curCut = None
        self.curZoomArea = None

        self._move_timer_start_at = 0
        self._move_timer_interval = 20 # 20 ms step animation (50 Hz)
        # self.move_boxes = list[dict]()
        self.move_boxes = list[MovingBox]()
        self.wrapping_boxes = list[WrappingBox]()
        self.move_box_timer = QTimer()
        self.move_box_timer.setInterval(self._move_timer_interval)
        self.move_box_timer.timeout.connect(self.move_boxes_animation)
        self.move_duration = 0.300 # 300ms

        self.elastic_scene = True
        self.resizing_scene = False

        self.selectionChanged.connect(self._slot_selection_changed)
        
        self._prevent_overlap = True

    def clear(self):
        # reimplement Qt function and fix missing rubberband after clear
        QGraphicsScene.clear(self)
        self._rubberband = RubberbandRect(self)
        self.update_theme()

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
            self.scaleChanged.emit(transform.m11())

        return fix

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
        ratio = min(1.0, time_since_start / self.move_duration)

        for moving_box in self.move_boxes:
            if moving_box.widget is not None:
                x = (moving_box.from_pt.x()
                     + ((moving_box.to_pt.x() - moving_box.from_pt.x())
                        * (ratio ** 0.6)))
                
                y = (moving_box.from_pt.y()
                     + ((moving_box.to_pt.y() - moving_box.from_pt.y())
                        * (ratio ** 0.6)))

                moving_box.widget.setPos(x, y)
                moving_box.widget.repaint_lines()

        for wrapping_box in self.wrapping_boxes:
            if wrapping_box.widget is not None:
                if time_since_start >= self.move_duration:
                    wrapping_box.widget.animate_wrapping(1.00)
                else:
                    wrapping_box.widget.animate_wrapping(ratio)

        self.resize_the_scene()
        
        if time_since_start >= self.move_duration:
            self.move_box_timer.stop()
            
            move_box_widgets = [b.widget for b in self.move_boxes]
            self.move_boxes.clear()
            self.wrapping_boxes.clear()

            for box in move_box_widgets:
                if box is not None:
                    box.update_positions()
                    box.send_move_callback()

            canvas.qobject.move_boxes_finished.emit()

        self.update()

    def add_box_to_animation(self, box_widget: CanvasBox, to_x: int, to_y: int,
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

        if not self.move_box_timer.isActive():
            moving_box.start_time = 0.0
            self._move_timer_start_at = time.time()
            self.move_box_timer.start()

    def add_box_to_animation_wrapping(self, box_widget: CanvasBox, wrap: bool):
        for wrapping_box in self.wrapping_boxes:
            if wrapping_box.widget is box_widget:
                wrapping_box.wrap = wrap
                break
        else:
            wrapping_box = WrappingBox
            wrapping_box.widget = box_widget
            wrapping_box.wrap = wrap
            self.wrapping_boxes.append(wrapping_box)
        
        if not self.move_box_timer.isActive():
            self._move_timer_start_at = time.time()
            self.move_box_timer.start()

    def center_view_on(self, widget):
        self._view.centerOn(widget)

    def get_connectable_item_at(self, pos: QPointF, origin: CanvasConnectable):
        for item in self.items(pos, Qt.ContainsItemShape, Qt.AscendingOrder):
            if isinstance(item, CanvasConnectable) and item is not origin:
                return item
        
    def get_selected_boxes(self) -> list[CanvasBox]:
        return [i for i in self.selectedItems() if isinstance(i, CanvasBox)]

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

        cur_color = "black" if canvas.theme.scene_background_color.blackF() < 0.5 else "white"
        self.curCut = QCursor(QPixmap(":/cursors/cut-"+cur_color+".png"), 1, 1)
        self.curZoomArea = QCursor(QPixmap(":/cursors/zoom-area-"+cur_color+".png"), 8, 7)

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

    def get_new_scene_rect(self):
        first_pass = True

        for group in canvas.group_list:
            for widget in group.widgets:
                if widget is None or not widget.isVisible():
                    continue

                item_rect = widget.boundingRect().translated(widget.scenePos())
                item_rect = item_rect.marginsAdded(QMarginsF(50.0, 20.0, 50.0, 20.0))

                if first_pass:
                    full_rect = item_rect
                else:
                    full_rect = full_rect.united(item_rect)

                first_pass = False

        if not first_pass:
            return full_rect

        return QRectF()

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

    def set_prevent_overlap(self, yesno: bool):
        options.prevent_overlap = yesno

    def zoom_ratio(self, percent: float):
        ratio = percent / 100.0
        transform = self._view.transform()
        transform.reset()
        transform.scale(ratio, ratio)
        self._view.setTransform(transform)

        for group in canvas.group_list:
            for widget in group.widgets:
                if widget and widget.top_icon:
                    widget.top_icon.update_zoom(ratio)

    def zoom_fit(self):
        min_x = min_y = max_x = max_y = None
        first_value = True

        items_list = self.items()

        if len(items_list) > 0:
            for item in items_list:
                if isinstance(item, CanvasBox) and item.isVisible():
                    pos = item.scenePos()
                    rect = item.boundingRect()

                    x = pos.x() + rect.left()
                    y = pos.y() + rect.top()
                    if first_value:
                        first_value = False
                        min_x, min_y = x, y
                        max_x = x + rect.width()
                        max_y = y + rect.height()
                    else:
                        min_x = min(min_x, x)
                        min_y = min(min_y, y)
                        max_x = max(max_x, x + rect.width())
                        max_y = max(max_y, y + rect.height())

            if not first_value:
                self._view.fitInView(min_x, min_y, abs(max_x - min_x),
                                      abs(max_y - min_y), Qt.KeepAspectRatio)
                self.fix_scale_factor()

        if self._view:
            self.scaleChanged.emit(self._view.transform().m11())

    def zoom_in(self):
        view = self._view
        transform = view.transform()
        if transform.m11() < self._scale_max:
            transform.scale(1.2, 1.2)
            if transform.m11() > self._scale_max:
                transform.reset()
                transform.scale(self._scale_max, self._scale_max)
            view.setTransform(transform)
        self.scaleChanged.emit(transform.m11())

    def zoom_out(self):
        view = self._view
        transform = view.transform()
        if transform.m11() > self._scale_min:
            transform.scale(0.833333333333333, 0.833333333333333)
            if transform.m11() < self._scale_min:
                transform.reset()
                transform.scale(self._scale_min, self._scale_min)
            view.setTransform(transform)
        self.scaleChanged.emit(transform.m11())

    def zoom_reset(self):
        self._view.resetTransform()
        self.scaleChanged.emit(1.0)

    @pyqtSlot()
    def _slot_selection_changed(self):
        items_list = self.selectedItems()

        if len(items_list) == 0:
            self.pluginSelected.emit([])
            return

        plugin_list = []

        for item in items_list:
            if item and item.isVisible():
                group_item = None

                if isinstance(item, CanvasBox):
                    group_item = item
                elif isinstance(item, CanvasConnectable):
                    group_item = item.parentItem()

                if group_item is not None and group_item._plugin_id >= 0:
                    plugin_id = group_item._plugin_id
                    if plugin_id > MAX_PLUGIN_ID_ALLOWED:
                        plugin_id = 0
                    plugin_list.append(plugin_id)

        self.pluginSelected.emit(plugin_list)

    def _trigger_rubberband_scale(self):
        self._scale_area = True

        if self.curZoomArea:
            self._view.viewport().setCursor(self.curZoomArea)

    def send_zoom_to_zoom_widget(self):
        if not self._view:
            return
        canvas.qobject.zoom_changed.emit(self._view.transform().m11() * 100)

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
            
            if event.key() == Qt.Key_T:
                event.accept()
                self.update_theme()
                return

        QGraphicsScene.keyPressEvent(self, event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key_Control:
            # Connection cut mode off
            if self._mid_button_down:
                self._view.viewport().unsetCursor()

        QGraphicsScene.keyReleaseEvent(self, event)

    def _start_connection_cut(self):
        if self.curCut:
            self._view.viewport().setCursor(self.curCut)

    def zoom_wheel(self, delta):
        transform = self._view.transform()
        scale = transform.m11()

        if ((delta > 0 and scale < self._scale_max)
                or (delta < 0 and scale > self._scale_min)):
            # prevent too large unzoom
            if delta < 0:
                rect = self.sceneRect()

                top_left_vw = self._view.mapFromScene(rect.topLeft())
                bottom_right_vw = self._view.mapFromScene(rect.bottomRight())

                if (top_left_vw.x() > self._view.width() / 4
                        and top_left_vw.y() > self._view.height() / 4):
                    return

            # Apply scale
            factor = 1.4142135623730951 ** (delta / 240.0)
            transform.scale(factor, factor)
            self.fix_scale_factor(transform)
            self._view.setTransform(transform)
            self.scaleChanged.emit(transform.m11())

            # Update box icons especially when they are not scalable
            # eg. coming from theme
            for group in canvas.group_list:
                for widget in group.widgets:
                    if widget and widget.top_icon:
                        widget.top_icon.update_zoom(scale * factor)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            # parse items under mouse to prevent CallbackAct.DOUBLE_CLICK
            # if mouse is on a box
            items = self.items(
                event.scenePos(), Qt.ContainsItemShape, Qt.AscendingOrder)

            for item in items:
                if isinstance(item, CanvasBox):
                    break
            else:
                canvas.callback(CallbackAct.DOUBLE_CLICK)
                return

        QGraphicsScene.mouseDoubleClickEvent(self, event)

    def mousePressEvent(self, event):
        self._mouse_down_init = (
            (event.button() == Qt.LeftButton)
            or ((event.button() == Qt.RightButton)
                and QApplication.keyboardModifiers() & Qt.ControlModifier))
        self._mouse_rubberband = False

        if (event.button() == Qt.MidButton
                and QApplication.keyboardModifiers() & Qt.ControlModifier):
            self._mid_button_down = True
            self._start_connection_cut()

            pos = event.scenePos()
            self._pointer_border.moveTo(floor(pos.x()), floor(pos.y()))

            for item in self.items(self._pointer_border):
                if isinstance(item, (CanvasConnectable, CanvasBezierLine)):
                    item.trigger_disconnect()

        QGraphicsScene.mousePressEvent(self, event)

    def mouseMoveEvent(self, event):
        if self._mouse_down_init:
            self._mouse_down_init = False
            topmost = self.itemAt(event.scenePos(), self._view.transform())
            self._mouse_rubberband = not (
                isinstance(topmost, (CanvasBox, CanvasConnectable,
                                     CanvasIconPixmap, CanvasSvgIcon))) 

        if self._mouse_rubberband:
            event.accept()
            pos = event.scenePos()
            pos_x = pos.x()
            pos_y = pos.y()
            if not self._rubberband_selection:
                self._rubberband.show()
                self._rubberband_selection = True
                self._rubberband_orig_point = pos
            rubberband_orig_point = self._rubberband_orig_point

            x = min(pos_x, rubberband_orig_point.x())
            y = min(pos_y, rubberband_orig_point.y())

            lineHinting = canvas.theme.rubberband.fill_pen().widthF() / 2.0
            self._rubberband.setRect(x+lineHinting,
                                     y+lineHinting,
                                     abs(pos_x - rubberband_orig_point.x()),
                                     abs(pos_y - rubberband_orig_point.y()))
            return

        if (self._mid_button_down
                and QApplication.keyboardModifiers() & Qt.ControlModifier):
            for item in self.items(
                    QPolygonF([event.scenePos(), event.lastScenePos(),
                               event.scenePos()])):
                if isinstance(item, CanvasBezierLine):
                    item.trigger_disconnect()
            
        QGraphicsScene.mouseMoveEvent(self, event)

    def mouseReleaseEvent(self, event):
        if self._scale_area and not self._rubberband_selection:
            self._scale_area = False
            self._view.viewport().unsetCursor()

        if self._rubberband_selection:
            if self._scale_area:
                self._scale_area = False
                self._view.viewport().unsetCursor()

                rect = self._rubberband.rect()
                self._view.fitInView(rect.x(), rect.y(), rect.width(), rect.height(), Qt.KeepAspectRatio)
                self.fix_scale_factor()

            else:
                for item in self.items():
                    if isinstance(item, CanvasBox):
                        item_rect = item.sceneBoundingRect()
                        item_top_left = QPointF(item_rect.x(), item_rect.y())
                        item_bottom_right = QPointF(item_rect.x() + item_rect.width(),
                                                    item_rect.y() + item_rect.height())

                        if (self._rubberband.contains(item_top_left)
                                and self._rubberband.contains(item_bottom_right)):
                            item.setSelected(True)

            self._rubberband.hide()
            self._rubberband.setRect(0, 0, 0, 0)
            self._rubberband_selection = False

        else:
            for item in self.get_selected_boxes():
                item.check_item_pos()
                self.sceneGroupMoved.emit(
                    item.get_group_id(), item.get_splitted_mode(),
                    item.scenePos())

            if len(self.selectedItems()) > 1:
                self.update()

        self._mouse_down_init = False
        self._mouse_rubberband = False

        if event.button() == Qt.MidButton:
            event.accept()

            self._mid_button_down = False

            # Connection cut mode off
            if QApplication.keyboardModifiers() & Qt.ControlModifier:
                self._view.viewport().unsetCursor()
            return

        QGraphicsScene.mouseReleaseEvent(self, event)

    def wheelEvent(self, event):
        if not self._view:
            event.ignore()
            return

        if QApplication.keyboardModifiers() & Qt.ControlModifier:
            event.accept()
            self.zoom_wheel(event.delta())
            return

        QGraphicsScene.wheelEvent(self, event)

    def contextMenuEvent(self, event):
        if QApplication.keyboardModifiers() & Qt.ControlModifier:
            event.accept()
            self._trigger_rubberband_scale()
            return

        if len(self.selectedItems()) == 0:
            event.accept()
            x, y = event.screenPos().x(), event.screenPos().y()
            canvas.callback(CallbackAct.BG_RIGHT_CLICK, x, y)
            return

        QGraphicsScene.contextMenuEvent(self, event)
        

# ------------------------------------------------------------------------------------------------------------
