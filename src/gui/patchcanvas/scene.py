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

from math import floor
import time

from PyQt5.QtCore import (QT_VERSION, pyqtSignal, pyqtSlot, qFatal,
                          Qt, QPoint, QPointF, QRectF, QTimer, QMarginsF)
from PyQt5.QtGui import QCursor, QPixmap, QPolygonF, QBrush
from PyQt5.QtWidgets import QGraphicsRectItem, QGraphicsScene, QApplication, QGraphicsView


from .init_values import (
    CanvasItemType,
    canvas,
    options,
    CallbackAct,
    MAX_PLUGIN_ID_ALLOWED,
    PortMode,
    Direction)

from .canvasbox import CanvasBox


class RubberbandRect(QGraphicsRectItem):
    def __init__(self, scene: QGraphicsScene):
        QGraphicsRectItem.__init__(self, QRectF(0, 0, 0, 0))

        self.setZValue(-1)
        self.hide()

        scene.addItem(self)

    def type(self) -> CanvasItemType:
        return CanvasItemType.RUBBERBAND


class PatchScene(QGraphicsScene):
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
        self.move_boxes = []
        self.wrapping_boxes = []
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

        for box_dict in self.move_boxes:
            if box_dict['widget'] is not None:
                x = (box_dict['from_x']
                     + ((box_dict['to_x'] - box_dict['from_x'])
                        * (ratio ** 0.6)))
                
                y = (box_dict['from_y']
                     + ((box_dict['to_y'] - box_dict['from_y'])
                        * (ratio ** 0.6)))

                box_dict['widget'].setPos(x, y)
                box_dict['widget'].repaint_lines()

        for wrap_dict in self.wrapping_boxes:
            if wrap_dict['widget'] is not None:
                if time_since_start >= self.move_duration:
                    wrap_dict['widget'].animate_wrapping(1.00)
                else:
                    wrap_dict['widget'].animate_wrapping(ratio)

        self.resize_the_scene()
        
        if time_since_start >= self.move_duration:
            self.move_box_timer.stop()
            
            move_box_widgets = [b['widget'] for b in self.move_boxes]
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
        for box_dict in self.move_boxes:
            if box_dict['widget'] == box_widget:
                break
        else:
            if not force_anim:
                # if box is not in a current animation
                # and force_anim is False,
                # then box position is directly changed
                if box_widget is not None:
                    box_widget.setPos(int(to_x), int(to_y))
                return

            box_dict = {'widget': box_widget}
            self.move_boxes.append(box_dict)

        box_dict['from_x'] = box_widget.pos().x()
        box_dict['from_y'] = box_widget.pos().y()
        box_dict['to_x'] = int(to_x)
        box_dict['to_y'] = int(to_y)
        box_dict['start_time'] = time.time() - self._move_timer_start_at

        if not self.move_box_timer.isActive():
            box_dict['start_time'] = 0.0
            self._move_timer_start_at = time.time()
            self.move_box_timer.start()

    def add_box_to_animation_wrapping(self, box_widget, wrap: bool):
        for wrap_dict in self.wrapping_boxes:
            if wrap_dict['widget'] == box_widget:
                wrap_dict['wrap'] = wrap
                break
        else:
            self.wrapping_boxes.append({'widget': box_widget, 'wrap': wrap})
        
        if not self.move_box_timer.isActive():
            self._move_timer_start_at = time.time()
            self.move_box_timer.start()

    def deplace_boxes_from_repulsers(self, repulser_boxes: list[CanvasBox],
                                     wanted_direction=Direction.NONE,
                                     new_scene_rect=None):
        def get_direction(fixed_rect: QRectF, moving_rect: QRectF,
                          parent_directions=[]) -> Direction:
            if (moving_rect.top() <= fixed_rect.center().y() <= moving_rect.bottom()
                    or fixed_rect.top() <= moving_rect.center().y() <= fixed_rect.bottom()):
                if (fixed_rect.right() < moving_rect.center().x()
                        and fixed_rect.center().x() < moving_rect.left()):
                    if Direction.LEFT in parent_directions:
                        return Direction.LEFT
                    return Direction.RIGHT
                
                if (fixed_rect.left() > moving_rect.center().x()
                        and fixed_rect.center().x() > moving_rect.right()):
                    if Direction.RIGHT in parent_directions:
                        return Direction.RIGHT
                    return Direction.LEFT
            
            if fixed_rect.center().y() <= moving_rect.center().y():
                if Direction.UP in parent_directions:
                    return Direction.UP
                return Direction.DOWN
            
            if Direction.DOWN in parent_directions:
                return Direction.DOWN
            return Direction.UP
        
        def repulse(direction: Direction, fixed, moving,
                    fixed_port_mode: int, moving_port_mode: int) -> QRectF:
            ''' returns a QRectF to be placed at side of fixed_rect
                where fixed_rect is an already determinated futur place
                for a box '''
                
            if isinstance(fixed, CanvasBox):
                fixed_rect = fixed.boundingRect().translated(fixed.pos())
            else:
                fixed_rect = fixed
            
            if isinstance(moving, CanvasBox):
                rect = moving.boundingRect().translated(moving.pos())
            else:
                rect = moving
            
            x = rect.left()
            y = rect.top()
            
            if direction in (Direction.LEFT, Direction.RIGHT):
                spacing = box_spacing

                if direction == Direction.LEFT:
                    if (fixed_port_mode & PortMode.INPUT
                            or moving_port_mode & PortMode.OUTPUT):
                        spacing = box_spacing_hor
                    x = fixed_rect.left() - spacing - rect.width()
                    if x < 0:
                        x -= 1.0
                    x = float(int(x))
                else:
                    if (fixed_port_mode & PortMode.OUTPUT
                            or moving_port_mode & PortMode.INPUT):
                        spacing = box_spacing_hor
                    x = fixed_rect.right() + spacing
                    if x < 0:
                        x -= 1.0
                    x = float(int(x + 0.99))

                top_diff = abs(fixed_rect.top() - rect.top())
                bottom_diff = abs(fixed_rect.bottom() - rect.bottom())

                if bottom_diff > top_diff and top_diff <= magnet:
                    y = fixed_rect.top()
                elif bottom_diff <= magnet:
                    y = fixed_rect.bottom() - rect.height()
            
            elif direction in (Direction.UP, Direction.DOWN):
                if direction == Direction.UP:
                    y = fixed_rect.top() - box_spacing - rect.height()
                    if y < 0:
                        y -= 1.0
                    y = float(int(y))
                else:
                    y = fixed_rect.bottom() + box_spacing
                    if y < 0:
                        y -= 1.0
                    y = float(int(y + 0.99))
                
                left_diff = abs(fixed_rect.left() - rect.left())
                right_diff = abs(fixed_rect.right() - rect.right())
                
                if right_diff > left_diff and left_diff <= magnet:
                    x = fixed_rect.left()
                elif right_diff <= magnet:
                    x = fixed_rect.right() - rect.width()

            return QRectF(x, y, rect.width(), rect.height())

        def rect_has_to_move_from(
                repulser_rect: QRectF, rect: QRectF,
                repulser_port_mode: int, rect_port_mode: int)->bool:
            left_spacing = right_spacing = box_spacing
            
            if (repulser_port_mode & PortMode.INPUT
                    or rect_port_mode & PortMode.OUTPUT):
                left_spacing = box_spacing_hor
            
            if (repulser_port_mode & PortMode.OUTPUT
                    or rect_port_mode & PortMode.INPUT):
                right_spacing = box_spacing_hor
            
            large_repulser_rect = repulser_rect.adjusted(
                - left_spacing, - box_spacing,
                right_spacing, box_spacing)

            return rect.intersects(large_repulser_rect)

        # function start #
        if not options.prevent_overlap:
            return
        
        box_spacing = canvas.theme.box_spacing
        box_spacing_hor = canvas.theme.box_spacing_horizontal
        magnet = canvas.theme.magnet

        to_move_boxes = []
        repulsers = []
        wanted_directions = [wanted_direction]

        for box in repulser_boxes:
            srect = box.boundingRect()
            
            if new_scene_rect is not None:
                srect = new_scene_rect
            else:
                # if box is already moving, consider its end position
                for box_dict in self.move_boxes:
                    if box_dict['widget'] == box:
                        srect.translate(QPoint(box_dict['to_x'], box_dict['to_y']))
                        break
                else:
                    srect.translate(box.pos())

            repulser = {'rect': srect,
                        'item': box}
            repulsers.append(repulser)

            items_to_move = []

            for group in canvas.group_list:
                for widget in group.widgets:
                    if (widget is None
                            or widget in repulser_boxes
                            or widget in [b['item'] for b in to_move_boxes]
                            or widget in [b['widget'] for b in self.move_boxes]):
                        continue
                    
                    irect = widget.boundingRect()
                    irect.translate(widget.pos())

                    if rect_has_to_move_from(
                            repulser['rect'], irect,
                            repulser['item'].get_current_port_mode(),
                            widget.get_current_port_mode()):
                        items_to_move.append({'item': widget, 'rect': irect})
            
            for box_dict in self.move_boxes:
                if (box_dict['widget'] in repulser_boxes
                        or box_dict['widget'] in [b['item'] for b in to_move_boxes]):
                    continue
            
                widget = box_dict['widget']
                
                # only for IDE
                assert isinstance(widget, CanvasBox)
                assert isinstance(repulser['item'], CanvasBox)
                
                irect = widget.boundingRect()
                irect.translate(QPoint(box_dict['to_x'], box_dict['to_y']))
                
                if rect_has_to_move_from(
                        repulser['rect'], irect,
                        repulser['item'].get_current_port_mode(),
                        widget.get_current_port_mode()):
                    items_to_move.append({'item': widget, 'rect': irect})
            
            for item_to_move in items_to_move:
                item = item_to_move['item']
                irect = item_to_move['rect']
                    
                # evaluate in which direction should go the box
                direction = get_direction(srect, irect, wanted_directions)
                to_move_box = {
                    'directions': [direction],
                    'pos': 0,
                    'item': item,
                    'repulser': repulser}
                
                # stock a position only for sorting reason
                if direction == Direction.RIGHT:
                    to_move_box['pos'] = irect.left()
                elif direction == Direction.LEFT:
                    to_move_box['pos'] = - irect.right()
                elif direction == Direction.DOWN:
                    to_move_box['pos'] = irect.top()
                elif direction == Direction.UP:
                    to_move_box['pos'] = - irect.bottom()

                to_move_boxes.append(to_move_box)

        # sort the list of dicts
        to_move_boxes = sorted(to_move_boxes, key=lambda d: d['pos'])
        to_move_boxes = sorted(to_move_boxes, key=lambda d: d['directions'])
        
        # !!! to_move_boxes list is dynamic
        # elements can be added to the list while iteration !!!
        for to_move_box in to_move_boxes:
            item = to_move_box['item']
            repulser = to_move_box['repulser']
            # ref_rect = repulser['rect']
            
            assert isinstance(item, CanvasBox)
            assert isinstance(repulser['item'], CanvasBox)
            irect = item.boundingRect().translated(item.pos())

            directions = to_move_box['directions'].copy()
            new_direction = get_direction(repulser['rect'], irect, directions)
            directions.append(new_direction)

            # TODO use of protected attributes.
            # calculate the new position of the box repulsed by its repulser
            new_rect = repulse(new_direction, repulser['rect'], item,
                               repulser['item']._current_port_mode,
                               item._current_port_mode)
            
            active_repulsers = []
            
            # while there is a repulser rect at new box position
            # move the future box position
            while True:
                # list just here to prevent infinite loop
                # we save the repulsers that already have moved the rect
                for repulser in repulsers:
                    if rect_has_to_move_from(
                            repulser['rect'], new_rect,
                            repulser['item'].get_current_port_mode(),
                            item.get_current_port_mode()):

                        if repulser in active_repulsers:
                            continue
                        active_repulsers.append(repulser)
                        
                        new_direction = get_direction(
                            repulser['rect'], new_rect, directions)
                        new_rect = repulse(
                            new_direction, repulser['rect'], new_rect,
                            repulser['item']._current_port_mode,
                            item._current_port_mode)
                        directions.append(new_direction)
                        break
                else:
                    break

            # Now we know where the box will be definitely positioned
            # So, this is now a repulser for other boxes
            repulser = {'rect': new_rect, 'item': item}
            repulsers.append(repulser)
            
            # check which existing boxes exists at the new place of the box
            # and add them to this to_move_boxes iteration
            adding_list = []
            
            for group in canvas.group_list:
                for widget in group.widgets:
                    if (widget is None
                            or widget in repulser_boxes
                            or widget in [b['item'] for b in to_move_boxes]
                            or widget in [b['widget'] for b in self.move_boxes]):
                        continue
                    
                    mirect = widget.boundingRect().translated(widget.pos())
                    if rect_has_to_move_from(
                            new_rect, mirect,
                            to_move_box['item'].get_current_port_mode(),
                            widget.get_current_port_mode()):
                        adding_list.append(
                            {'directions': directions,
                            'pos': mirect.right(),
                            'item': widget,
                            'repulser': repulser})
            
            for box_dict in self.move_boxes:
                mitem = box_dict['widget']
                assert isinstance(mitem, CanvasBox)
                
                if (mitem in repulser_boxes
                        or mitem in [b['item'] for b in to_move_boxes]):
                    continue
                
                rect = mitem.boundingRect()
                rect.translate(QPoint(box_dict['to_x'], box_dict['to_y']))
                
                if rect_has_to_move_from(
                        new_rect, rect,
                        to_move_box['item'].get_current_port_mode(),
                        mitem.get_current_port_mode()):

                    adding_list.append(
                        {'directions': directions,
                         'pos': 0,
                         'item': box_dict['widget'],
                         'repulser': repulser})

            for to_move_box in adding_list:
                to_move_boxes.append(to_move_box)

            # now we decide where the box is moved
            pos_offset = item.boundingRect().topLeft()
            to_send_rect = new_rect.translated(- pos_offset)
            self.add_box_to_animation(
                item, to_send_rect.left(), to_send_rect.top())

    def bring_neighbors_and_deplace_boxes(
            self, box_widget: CanvasBox, new_scene_rect: QRectF):
        neighbors = [box_widget]
        limit_top = box_widget.pos().y()
        
        for neighbor in neighbors:
            srect = neighbor.boundingRect()
            for move_box in self.move_boxes:
                if move_box['widget'] == neighbor:
                    srect.translate(QPointF(move_box['to_x'], move_box['to_y']))
                    break
            else:
                srect.translate(neighbor.pos())

            for item in self.items(
                    srect.adjusted(
                        0, 0, 0,
                        canvas.theme.box_spacing + 1)):
                if item not in neighbors and item.type() is CanvasItemType.BOX:
                    nrect = item.boundingRect().translated(item.pos())
                    if nrect.top() >= limit_top:
                        neighbors.append(item)
        
        neighbors.remove(box_widget)
        
        less_y = box_widget.boundingRect().height() - new_scene_rect.height()

        repulser_boxes = []

        for neighbor in neighbors:
            self.add_box_to_animation(
                neighbor, neighbor.pos().x(), neighbor.pos().y() - less_y)
            repulser_boxes.append(neighbor)
        repulser_boxes.append(box_widget)
        
        self.deplace_boxes_from_repulsers(repulser_boxes, wanted_direction=Direction.UP)

    def center_view_on(self, widget):
        self._view.centerOn(widget)

    def removeItem(self, item):
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
        if canvas.theme.background_image is not None:
            bg_brush = QBrush()
            bg_brush.setTextureImage(canvas.theme.background_image)
            self.setBackgroundBrush(bg_brush)
        else:
            self.setBackgroundBrush(canvas.theme.background_color)
        
        self._rubberband.setPen(canvas.theme.rubberband.fill_pen())
        self._rubberband.setBrush(canvas.theme.rubberband.background_color())

        cur_color = "black" if canvas.theme.background_color.blackF() < 0.5 else "white"
        self.curCut = QCursor(QPixmap(":/cursors/cut-"+cur_color+".png"), 1, 1)
        self.curZoomArea = QCursor(QPixmap(":/cursors/zoom-area-"+cur_color+".png"), 8, 7)

    def drawBackground(self, painter, rect):
        #if self._background_image is None:
            #return
        
        painter.save()
        painter.setPen(Qt.NoPen)
        
        if canvas.theme.background_image is not None:
            canvas.theme.background_image.setDevicePixelRatio(3.0)
            bg_brush = QBrush()
            bg_brush.setTextureImage(canvas.theme.background_image)
            painter.setBrush(bg_brush)
            painter.drawRect(rect)
        #else:
        painter.setBrush(canvas.theme.background_color)
        
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
                if item and item.isVisible() and item.type() is CanvasItemType.BOX:
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

                if item.type() is CanvasItemType.BOX:
                    group_item = item
                elif item.type() is CanvasItemType.PORT:
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
                if item.type() is CanvasItemType.BOX:
                    break
            else:
                canvas.callback(CallbackAct.DOUBLE_CLICK, 0, 0, "")
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

            items = self.items(self._pointer_border)
            for item in items:
                if item and item.type() in (CanvasItemType.BEZIER_LINE,
                                            CanvasItemType.PORT):
                    item.trigger_disconnect()

        QGraphicsScene.mousePressEvent(self, event)

    def mouseMoveEvent(self, event):
        if self._mouse_down_init:
            self._mouse_down_init = False
            topmost = self.itemAt(event.scenePos(), self._view.transform())
            self._mouse_rubberband = not (
                topmost and topmost.type() in (
                    CanvasItemType.BOX, CanvasItemType.ICON,
                    CanvasItemType.PORT, CanvasItemType.PORTGROUP))

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
            trail = QPolygonF([event.scenePos(), event.lastScenePos(), event.scenePos()])
            items = self.items(trail)
            for item in items:
                if item and item.type() == CanvasItemType.BEZIER_LINE:
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
                items_list = self.items()
                for item in items_list:
                    if item and item.isVisible() and item.type() is CanvasItemType.BOX:
                        item_rect = item.sceneBoundingRect()
                        item_top_left = QPointF(item_rect.x(), item_rect.y())
                        item_bottom_right = QPointF(item_rect.x() + item_rect.width(),
                                                    item_rect.y() + item_rect.height())

                        if self._rubberband.contains(item_top_left) and self._rubberband.contains(item_bottom_right):
                            item.setSelected(True)

            self._rubberband.hide()
            self._rubberband.setRect(0, 0, 0, 0)
            self._rubberband_selection = False

        else:
            items_list = self.selectedItems()
            for item in items_list:
                if item and item.isVisible() and item.type() is CanvasItemType.BOX:
                    item.check_item_pos()
                    self.sceneGroupMoved.emit(
                        item.get_group_id(), item.get_splitted_mode(),
                        item.scenePos())

            if len(items_list) > 1:
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
            canvas.callback(CallbackAct.BG_RIGHT_CLICK, x, y, "")
            return

        QGraphicsScene.contextMenuEvent(self, event)
        

# ------------------------------------------------------------------------------------------------------------
