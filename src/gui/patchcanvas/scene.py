#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# PatchBay Canvas engine using QGraphicsView/Scene
# Copyright (C) 2010-2019 Filipe Coelho <falktx@falktx.com>
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

# ------------------------------------------------------------------------------------------------------------
# Imports (Global)

from math import floor

from PyQt5.QtCore import (QT_VERSION, pyqtSignal, pyqtSlot, qFatal,
                          Qt, QPoint, QPointF, QRectF, QTimer, QSizeF, QMarginsF)
from PyQt5.QtGui import QCursor, QPixmap, QPolygonF, QLinearGradient, QColor
from PyQt5.QtWidgets import QGraphicsRectItem, QGraphicsScene, QGraphicsView

# ------------------------------------------------------------------------------------------------------------
# Imports (Custom)

from . import (
    canvas,
    options,
    CanvasBoxType,
    CanvasIconType,
    CanvasPortType,
    CanvasPortGroupType,
    CanvasLineType,
    CanvasBezierLineType,
    CanvasRubberbandType,
    ACTION_BG_RIGHT_CLICK,
    ACTION_DOUBLE_CLICK,
    MAX_PLUGIN_ID_ALLOWED,
)

# ------------------------------------------------------------------------------------------------------------

class RubberbandRect(QGraphicsRectItem):
    def __init__(self, scene):
        QGraphicsRectItem.__init__(self, QRectF(0, 0, 0, 0))

        self.setZValue(-1)
        self.hide()

        scene.addItem(self)

    def type(self):
        return CanvasRubberbandType

# ------------------------------------------------------------------------------------------------------------

class PatchScene(QGraphicsScene):
    scaleChanged = pyqtSignal(float)
    sceneGroupMoved = pyqtSignal(int, int, QPointF)
    pluginSelected = pyqtSignal(list)

    def __init__(self, parent, view):
        QGraphicsScene.__init__(self, parent)

        #self.setItemIndexMethod(QGraphicsScene.NoIndex)
        self.m_ctrl_down = False
        self.m_scale_area = False
        self.m_mouse_down_init = False
        self.m_mouse_rubberband = False
        self.m_mid_button_down = False
        self.m_pointer_border = QRectF(0.0, 0.0, 1.0, 1.0)
        self.m_scale_min = 0.1
        self.m_scale_max = 4.0

        self.scales = (0.1, 0.25, 0.4, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0)

        self.m_rubberband = RubberbandRect(self)
        self.m_rubberband_selection = False
        self.m_rubberband_orig_point = QPointF(0, 0)

        self.m_view = view
        if not self.m_view:
            qFatal("PatchCanvas::PatchScene() - invalid view")

        self.curCut = None
        self.curZoomArea = None
        
        self.move_boxes = []
        self.move_box_timer = QTimer()
        self.move_box_timer.setInterval(20) # 20 ms step animation (50 Hz)
        self.move_box_timer.timeout.connect(self.move_boxes_animation)
        self.move_box_n = 0
        self.move_box_n_max = 20 # 20 animations steps (20ms * 20 = 400ms)

        self.elastic_scene = True

        self.selectionChanged.connect(self.slot_selectionChanged)
        #self.setSceneRect(-10000, -10000, 20000, 20000)
        
    def getDevicePixelRatioF(self):
        if QT_VERSION < 0x50600:
            return 1.0

        return self.m_view.devicePixelRatioF()

    def getScaleFactor(self):
        return self.m_view.transform().m11()

    def fixScaleFactor(self, transform=None):
        fix, set_view = False, False
        if not transform:
            set_view = True
            view = self.m_view
            transform = view.transform()

        scale = transform.m11()
        if scale > self.m_scale_max:
            fix = True
            transform.reset()
            transform.scale(self.m_scale_max, self.m_scale_max)
        elif scale < self.m_scale_min:
            fix = True
            transform.reset()
            transform.scale(self.m_scale_min, self.m_scale_min)

        if set_view:
            if fix:
                view.setTransform(transform)
            self.scaleChanged.emit(transform.m11())

        return fix

    def fix_temporary_scroll_bars(self):
        if self.m_view is None:
            return
        
        if self.m_view.horizontalScrollBar().isVisible():
            self.m_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        else:
            self.m_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            
        if self.m_view.verticalScrollBar().isVisible():
            self.m_view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        else:
            self.m_view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            
    def reset_scroll_bars(self):
        self.m_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.m_view.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
    def move_boxes_animation(self):
        self.move_box_n += 1
        
        for box_dict in self.move_boxes:
            if box_dict['widget'] is not None:
                total_n = self.move_box_n_max - box_dict['n_start']
                n = self.move_box_n - box_dict['n_start']
                
                x = box_dict['from_x'] \
                    + (box_dict['to_x'] - box_dict['from_x']) \
                        * (n/total_n)
                y = box_dict['from_y'] \
                    + (box_dict['to_y'] - box_dict['from_y']) \
                        * (n/total_n)

                box_dict['widget'].setPos(x, y)
        
        self.resize_the_scene()
        
        if self.move_box_n == self.move_box_n_max:
            self.move_box_n = 0
            self.move_box_timer.stop()
            self.move_boxes.clear()
            QTimer.singleShot(0, self.update)
            
            for box_dict in self.move_boxes:
                if box_dict['widget'] is not None:
                    QTimer.singleShot(0, box_dict['widget'].repaintLines)
            canvas.qobject.move_boxes_finished.emit()
            
        elif self.move_box_n % 5 == 4:
            self.update()

    def add_box_to_animation(self, box_widget, to_x: int, to_y: int):
        for box_dict in self.move_boxes:
            if box_dict['widget'] == box_widget:
                break
        else:
            box_dict = {'widget': box_widget}
            self.move_boxes.append(box_dict)
            
        box_dict['from_x'] = box_widget.pos().x()
        box_dict['from_y'] = box_widget.pos().y()
        box_dict['to_x'] = to_x
        box_dict['to_y'] = to_y
        box_dict['n_start'] = self.move_box_n

        if not self.move_box_timer.isActive():
            self.move_box_timer.start()

    def removeItem(self, item):
        for child_item in item.childItems():
            QGraphicsScene.removeItem(self, child_item)
        QGraphicsScene.removeItem(self, item)

    def updateLimits(self):
        w0 = canvas.size_rect.width()
        h0 = canvas.size_rect.height()
        w1 = self.m_view.width()
        h1 = self.m_view.height()
        self.m_scale_min = w1/w0 if w0/h0 > w1/h1 else h1/h0

    def updateTheme(self):
        self.setBackgroundBrush(canvas.theme.canvas_bg)
        self.m_rubberband.setPen(canvas.theme.rubberband_pen)
        self.m_rubberband.setBrush(canvas.theme.rubberband_brush)

        cur_color = "black" if canvas.theme.canvas_bg.blackF() < 0.5 else "white"
        self.curCut = QCursor(QPixmap(":/cursors/cut-"+cur_color+".png"), 1, 1)
        self.curZoomArea = QCursor(QPixmap(":/cursors/zoom-area-"+cur_color+".png"), 8, 7)

    def get_new_scene_rect(self):
        first_pass = True
        
        for group in canvas.group_list:
            for widget in group.widgets:
                if widget is None:
                    continue
                
                item_rect = widget.boundingRect().translated(widget.scenePos())
                item_rect = item_rect.marginsAdded(QMarginsF(20, 20, 20, 20))
                
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
            self.setSceneRect(self.get_new_scene_rect())

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

    def zoom_fit(self):
        min_x = min_y = max_x = max_y = None
        first_value = True

        items_list = self.items()

        if len(items_list) > 0:
            for item in items_list:
                if item and item.isVisible() and item.type() == CanvasBoxType:
                    pos = item.scenePos()
                    rect = item.boundingRect()

                    x = pos.x()
                    y = pos.y()
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
                self.m_view.fitInView(min_x, min_y, abs(max_x - min_x),
                                      abs(max_y - min_y), Qt.KeepAspectRatio)
                self.fixScaleFactor()

    def zoom_in(self):
        view = self.m_view
        transform = view.transform()
        if transform.m11() < self.m_scale_max:
            transform.scale(1.2, 1.2)
            if transform.m11() > self.m_scale_max:
                transform.reset()
                transform.scale(self.m_scale_max, self.m_scale_max)
            view.setTransform(transform)
        self.scaleChanged.emit(transform.m11())

    def zoom_out(self):
        view = self.m_view
        transform = view.transform()
        if transform.m11() > self.m_scale_min:
            transform.scale(0.833333333333333, 0.833333333333333)
            if transform.m11() < self.m_scale_min:
                transform.reset()
                transform.scale(self.m_scale_min, self.m_scale_min)
            view.setTransform(transform)
        self.scaleChanged.emit(transform.m11())

    def zoom_reset(self):
        self.m_view.resetTransform()
        self.scaleChanged.emit(1.0)

    @pyqtSlot()
    def slot_selectionChanged(self):
        items_list = self.selectedItems()

        if len(items_list) == 0:
            self.pluginSelected.emit([])
            return

        plugin_list = []

        for item in items_list:
            if item and item.isVisible():
                group_item = None

                if item.type() == CanvasBoxType:
                    group_item = item
                elif item.type() == CanvasPortType:
                    group_item = item.parentItem()
                #elif item.type() in (CanvasLineType, CanvasBezierLineType, CanvasLineMovType, CanvasBezierLineMovType):
                    #plugin_list = []
                    #break

                if group_item is not None and group_item.m_plugin_id >= 0:
                    plugin_id = group_item.m_plugin_id
                    if plugin_id > MAX_PLUGIN_ID_ALLOWED:
                        plugin_id = 0
                    plugin_list.append(plugin_id)

        self.pluginSelected.emit(plugin_list)

    def triggerRubberbandScale(self):
        self.m_scale_area = True
        
        if self.curZoomArea:
            self.m_view.viewport().setCursor(self.curZoomArea)

    def keyPressEvent(self, event):
        if not self.m_view:
            event.ignore()
            return

        if event.key() == Qt.Key_Control:
            self.m_ctrl_down = True
            if self.m_mid_button_down:
                self.startConnectionCut()

        elif event.key() == Qt.Key_Home:
            event.accept()
            self.zoom_fit()
            return

        elif self.m_ctrl_down:
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
            self.m_ctrl_down = False

            # Connection cut mode off
            if self.m_mid_button_down:
                self.m_view.viewport().unsetCursor()

        QGraphicsScene.keyReleaseEvent(self, event)

    def startConnectionCut(self):
        if self.curCut:
            self.m_view.viewport().setCursor(self.curCut)

    def zoom_wheel(self, delta):
        transform = self.m_view.transform()
        scale = transform.m11()

        if ((delta > 0 and scale < self.m_scale_max)
                or (delta < 0 and scale > self.m_scale_min)):
            # prevent too large unzoom
            if delta < 0:
                rect = self.sceneRect()
                
                top_left_vw = self.m_view.mapFromScene(rect.topLeft())
                bottom_right_vw = self.m_view.mapFromScene(rect.bottomRight())
                
                if (top_left_vw.x() > self.m_view.width() / 4
                        and top_left_vw.y() > self.m_view.height() / 4):
                    return
                
                
                
                #top_left_sc = self.m_view.mapToScene(QPoint(0, 0))
                #bottom_right_sc = self.m_view.mapToScene(
                    #QPoint(self.m_view.width(), self.m_view.height()))
                #margin = 100
                #if (top_left_sc.x() < rect.left() - margin
                        #and top_left_sc.y() < rect.top() - margin
                        #and bottom_right_sc.x() > rect.right() + margin
                        #and bottom_right_sc.y() > rect.bottom() + margin):
                    #return
            
            # Apply scale
            factor = 1.4142135623730951 ** (delta / 240.0)
            transform.scale(factor, factor)
            self.fixScaleFactor(transform)
            self.m_view.setTransform(transform)
            self.scaleChanged.emit(transform.m11())

            # Update box icons especially when they are not scalable 
            # eg. coming from theme 
            for group in canvas.group_list:
                for widget in group.widgets:
                    if widget and widget.top_icon:
                        widget.top_icon.update_zoom(scale * factor)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            canvas.callback(ACTION_DOUBLE_CLICK, 0, 0, "")
            return
        
        QGraphicsScene.mouseDoubleClickEvent(self, event)

    def mousePressEvent(self, event):
        self.m_mouse_down_init = (
            (event.button() == Qt.LeftButton) or ((event.button() == Qt.RightButton) and self.m_ctrl_down)
        )
        self.m_mouse_rubberband = False

        if event.button() == Qt.MidButton and self.m_ctrl_down:
            self.m_mid_button_down = True
            self.startConnectionCut()

            pos = event.scenePos()
            self.m_pointer_border.moveTo(floor(pos.x()), floor(pos.y()))

            items = self.items(self.m_pointer_border)
            for item in items:
                if item and item.type() in (CanvasLineType, CanvasBezierLineType, CanvasPortType):
                    item.triggerDisconnect()

        QGraphicsScene.mousePressEvent(self, event)

    def mouseMoveEvent(self, event):
        if self.m_mouse_down_init:
            self.m_mouse_down_init = False
            topmost = self.itemAt(event.scenePos(), self.m_view.transform())
            self.m_mouse_rubberband = not (topmost and topmost.type() in (CanvasBoxType,
                                                                          CanvasIconType,
                                                                          CanvasPortType,
                                                                          CanvasPortGroupType))
        if self.m_mouse_rubberband:
            event.accept()
            pos = event.scenePos()
            pos_x = pos.x()
            pos_y = pos.y()
            if not self.m_rubberband_selection:
                self.m_rubberband.show()
                self.m_rubberband_selection = True
                self.m_rubberband_orig_point = pos
            rubberband_orig_point = self.m_rubberband_orig_point

            x = min(pos_x, rubberband_orig_point.x())
            y = min(pos_y, rubberband_orig_point.y())

            lineHinting = canvas.theme.rubberband_pen.widthF() / 2
            self.m_rubberband.setRect(x+lineHinting,
                                      y+lineHinting,
                                      abs(pos_x - rubberband_orig_point.x()),
                                      abs(pos_y - rubberband_orig_point.y()))
            return

        if self.m_mid_button_down and self.m_ctrl_down:
            trail = QPolygonF([event.scenePos(), event.lastScenePos(), event.scenePos()])
            items = self.items(trail)
            for item in items:
                if item and item.type() in (CanvasLineType, CanvasBezierLineType):
                    item.triggerDisconnect()

        QGraphicsScene.mouseMoveEvent(self, event)

    def mouseReleaseEvent(self, event):
        if self.m_scale_area and not self.m_rubberband_selection:
            self.m_scale_area = False
            self.m_view.viewport().unsetCursor()

        if self.m_rubberband_selection:
            if self.m_scale_area:
                self.m_scale_area = False
                self.m_view.viewport().unsetCursor()

                rect = self.m_rubberband.rect()
                self.m_view.fitInView(rect.x(), rect.y(), rect.width(), rect.height(), Qt.KeepAspectRatio)
                self.fixScaleFactor()

            else:
                items_list = self.items()
                for item in items_list:
                    if item and item.isVisible() and item.type() == CanvasBoxType:
                        item_rect = item.sceneBoundingRect()
                        item_top_left = QPointF(item_rect.x(), item_rect.y())
                        item_bottom_right = QPointF(item_rect.x() + item_rect.width(),
                                                    item_rect.y() + item_rect.height())

                        if self.m_rubberband.contains(item_top_left) and self.m_rubberband.contains(item_bottom_right):
                            item.setSelected(True)

            self.m_rubberband.hide()
            self.m_rubberband.setRect(0, 0, 0, 0)
            self.m_rubberband_selection = False

        else:
            items_list = self.selectedItems()
            for item in items_list:
                if item and item.isVisible() and item.type() == CanvasBoxType:
                    item.checkItemPos()
                    self.sceneGroupMoved.emit(item.getGroupId(), item.getSplittedMode(), item.scenePos())

            if len(items_list) > 1:
                canvas.scene.update()

        self.m_mouse_down_init = False
        self.m_mouse_rubberband = False

        if event.button() == Qt.MidButton:
            event.accept()

            self.m_mid_button_down = False

            # Connection cut mode off
            if self.m_ctrl_down:
                self.m_view.viewport().unsetCursor()
            return

        QGraphicsScene.mouseReleaseEvent(self, event)

    def wheelEvent(self, event):
        if not self.m_view:
            event.ignore()
            return

        if self.m_ctrl_down:
            event.accept()
            self.zoom_wheel(event.delta())
            return

        QGraphicsScene.wheelEvent(self, event)

    def contextMenuEvent(self, event):
        if self.m_ctrl_down:
            event.accept()
            self.triggerRubberbandScale()
            return

        if len(self.selectedItems()) == 0:
            event.accept()
            canvas.callback(ACTION_BG_RIGHT_CLICK, 0, 0, "")
            return

        QGraphicsScene.contextMenuEvent(self, event)

# ------------------------------------------------------------------------------------------------------------
