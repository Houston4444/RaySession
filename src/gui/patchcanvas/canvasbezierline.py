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

from typing import TYPE_CHECKING

from PyQt5.QtCore import Qt, QPointF
from PyQt5.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import QGraphicsPathItem

from .init_values import (
    canvas,
    CanvasItemType,
    CallbackAct,
    PortType)

from .canvasbox import CanvasBox
from .canvasport import CanvasPort
    


class CanvasBezierLine(QGraphicsPathItem):
    def __init__(self, item1: CanvasPort, item2: CanvasPort, parent: CanvasBox):
        QGraphicsPathItem.__init__(self)
        self.setParentItem(parent)
        #self.setCacheMode(QGraphicsPathItem.DeviceCoordinateCache)

        self.item1 = item1
        self.item2 = item2
        
        # is true when the connection will be undo by user if (s)he
        # leaves the mouse button
        self.ready_to_disc = False
        self.locked = False
        
        self._line_selected = False
        self._semi_hidden = False

        self.setBrush(QColor(0, 0, 0, 0))
        self.setGraphicsEffect(None)
        self.update_line_pos()

    def set_line_selected(self, yesno: bool):
        if self.locked:
            return

        self._line_selected = yesno
        self.update_line_gradient()

    def trigger_disconnect(self):
        for connection in canvas.connection_list:
            if (connection.port_out_id == self.item1.get_port_id()
                    and connection.port_in_id == self.item2.get_port_id()):
                canvas.callback(CallbackAct.PORTS_DISCONNECT,
                                connection.connection_id)
                break

    def semi_hide(self, yesno: bool):
        self._semi_hidden = yesno
        self.update_line_gradient()

    def update_line_pos(self):
        item1_con_pos = self.item1.connect_pos()
        item1_x = item1_con_pos.x()
        item1_y = item1_con_pos.y()
        
        item2_con_pos = self.item2.connect_pos()
        item2_x = item2_con_pos.x()
        item2_y = item2_con_pos.y()

        x_diff = item2_x - item1_x

        mid_x = abs(x_diff) / 2

        diffxy = abs(item1_y - item2_y) - abs(x_diff)
        if diffxy > 0:
            mid_x += diffxy

        mid_x = min(mid_x, max(200, (x_diff)/2))

        item1_new_x = item1_x + mid_x
        item2_new_x = item2_x - mid_x

        path = QPainterPath(QPointF(item1_x, item1_y))
        
        path.cubicTo(item1_new_x, item1_y, item2_new_x, item2_y,
                     item2_x, item2_y)
        self.setPath(path)

        self._line_selected = False
        self.update_line_gradient()

    def type(self) -> CanvasItemType:
        return CanvasItemType.BEZIER_LINE

    def update_line_gradient(self):
        pos_top = self.boundingRect().top()
        pos_bot = self.boundingRect().bottom()
        if self.item2.scenePos().y() >= self.item1.scenePos().y():
            pos1 = 0
            pos2 = 1
        else:
            pos1 = 1
            pos2 = 0

        port_type1 = self.item1.get_port_type()
        port_type2 = self.item2.get_port_type()
        port_gradient = QLinearGradient(0, pos_top, 0, pos_bot)

        theme = canvas.theme.line
        if self.ready_to_disc:
            theme = theme.disconnecting
        else:
            if port_type1 == PortType.AUDIO_JACK:
                theme = theme.audio
            elif port_type1 == PortType.MIDI_JACK:
                theme = theme.midi

            if self._line_selected:
                theme = theme.selected

        base_pen = theme.fill_pen()
        color_main = theme.background_color()
        color_alter = theme.background2_color()
        if color_alter is None:
            color_alter = color_main
        base_width = base_pen.widthF() + 0.000001

        if self.ready_to_disc:
            port_gradient.setColorAt(pos1, color_main)
            port_gradient.setColorAt(pos2, color_main)
        else:
            if self._semi_hidden:
                shd = canvas.semi_hide_opacity
                bgcolor = canvas.theme.background_color
                
                
                color_main = QColor(
                    int(color_main.red() * shd + bgcolor.red() * (1.0 - shd) + 0.5),
                    int(color_main.green() * shd + bgcolor.green() * (1.0 - shd)+ 0.5),
                    int(color_main.blue() * shd + bgcolor.blue() * (1.0 - shd) + 0.5),
                    color_main.alpha())
                
                color_alter = QColor(
                    int(color_alter.red() * shd + bgcolor.red() * (1.0 - shd) + 0.5),
                    int(color_alter.green() * shd + bgcolor.green() * (1.0 - shd)+ 0.5),
                    int(color_alter.blue() * shd + bgcolor.blue() * (1.0 - shd) + 0.5),
                    color_alter.alpha())
            
            port_gradient.setColorAt(0, color_main)
            port_gradient.setColorAt(0.5, color_alter)
            port_gradient.setColorAt(1, color_main)

        self.setPen(QPen(port_gradient, base_width, Qt.SolidLine, Qt.FlatCap))

    def paint(self, painter, option, widget):
        if canvas.loading_items:
            return
        
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)

        pen = self.pen()
        cosm_pen = QPen(pen)
        cosm_pen.setCosmetic(True)
        cosm_pen.setWidthF(1.00001)

        QGraphicsPathItem.paint(self, painter, option, widget)

        painter.setPen(cosm_pen)
        painter.setBrush(Qt.NoBrush)
        painter.setOpacity(0.2)
        painter.drawPath(self.path())

        painter.restore()

# ------------------------------------------------------------------------------------------------------------
