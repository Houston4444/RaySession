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

from enum import Enum
import time
from typing import TYPE_CHECKING

from PyQt5.QtCore import Qt, QPointF
from PyQt5.QtGui import (QColor, QLinearGradient, QPainter,
                         QPainterPath, QPen, QBrush)
from PyQt5.QtWidgets import QGraphicsPathItem

from .init_values import (
    canvas,
    CanvasItemType,
    CallbackAct,
    PortType)

if TYPE_CHECKING:
    from .port_widget import PortWidget


class _ThemeState(Enum):
    NORMAL = 0
    SELECTED = 1
    DISCONNECTING = 2


class _ThemeAttributes:
    base_pen: QPen
    color_main: QColor
    color_alter: QColor
    base_width: float


class LineWidget(QGraphicsPathItem):
    def __init__(self, connection_id: int,
                 item1: 'PortWidget', item2: 'PortWidget'):
        ''' Class for connection line widget '''
        QGraphicsPathItem.__init__(self)

        # is true when the connection will be undo by user if (s)he
        # leaves the mouse button
        self.ready_to_disc = False        

        self._item1 = item1
        self._item2 = item2
        self._connection_id = connection_id

        self._semi_hidden = False
        
        self._th_attribs = dict[_ThemeState, _ThemeAttributes]()
        self.update_theme()

        self.setBrush(QColor(0, 0, 0, 0))
        self.setGraphicsEffect(None)
        self.update_line_pos()

    def check_select_state(self):
        self.update_line_gradient()

    def trigger_disconnect(self):
        canvas.callback(CallbackAct.PORTS_DISCONNECT, self._connection_id)

    def semi_hide(self, yesno: bool):
        self._semi_hidden = yesno
        self.update_line_gradient()

    def update_line_pos(self, fast_move=False):
        item1_con_pos = self._item1.connect_pos()
        item1_x = item1_con_pos.x()
        item1_y = item1_con_pos.y()
        
        item2_con_pos = self._item2.connect_pos()
        item2_x = item2_con_pos.x()
        item2_y = item2_con_pos.y()

        x_diff = item2_x - item1_x
        mid_x = abs(x_diff) / 2

        diffxy = abs(item1_y - item2_y) - abs(x_diff)
        if diffxy > 0:
            mid_x += diffxy

        mid_x = min(mid_x, max(200.0, x_diff / 2))

        path = QPainterPath(item1_con_pos)
        path.cubicTo(item1_x + mid_x, item1_y,
                     item2_x - mid_x, item2_y,
                     item2_x, item2_y)
        self.setPath(path)

        if not fast_move:
            # line gradient is not updated at mouse move event or when box 
            # is moved by animation. It makes win few time and so avoid some
            # graphic jerks.
            self.update_line_gradient()

    def type(self) -> CanvasItemType:
        return CanvasItemType.BEZIER_LINE

    def update_theme(self):
        port_type1 = self._item1.get_port_type()
        
        for theme_state in _ThemeState:
            if theme_state is _ThemeState.DISCONNECTING:
                theme = canvas.theme.line.disconnecting
            else:
                theme = canvas.theme.line
                if port_type1 == PortType.AUDIO_JACK:
                    theme = theme.audio
                elif port_type1 == PortType.MIDI_JACK:
                    theme = theme.midi

                if theme_state is _ThemeState.SELECTED:
                    theme = theme.selected

            tha = _ThemeAttributes()
            tha.base_pen = theme.fill_pen()
            tha.color_main = theme.background_color()
            tha.color_alter = theme.background2_color()
            if tha.color_alter is None:
                tha.color_alter = tha.color_main
            tha.base_width = tha.base_pen.widthF() + 0.000001
            self._th_attribs[theme_state] = tha            

    def update_line_gradient(self):
        pos_top = self.boundingRect().top()
        pos_bot = self.boundingRect().bottom()

        if self.ready_to_disc:
            tha = self._th_attribs[_ThemeState.DISCONNECTING]
        elif self._item1.isSelected() or self._item2.isSelected():
            tha = self._th_attribs[_ThemeState.SELECTED]
        else:
            tha = self._th_attribs[_ThemeState.NORMAL]
        
        has_gradient = bool(tha.color_main != tha.color_alter)
        
        if has_gradient:
            port_gradient = QLinearGradient(0, pos_top, 0, pos_bot)

            if self.ready_to_disc:
                port_gradient.setColorAt(0.0, tha.color_main)
                port_gradient.setColorAt(1.0, tha.color_main)
            else:
                if self._semi_hidden:
                    shd = canvas.semi_hide_opacity
                    bgcolor = canvas.theme.scene_background_color
                    
                    color_main = QColor(
                        int(tha.color_main.red() * shd + bgcolor.red() * (1.0 - shd) + 0.5),
                        int(tha.color_main.green() * shd + bgcolor.green() * (1.0 - shd)+ 0.5),
                        int(tha.color_main.blue() * shd + bgcolor.blue() * (1.0 - shd) + 0.5),
                        tha.color_main.alpha())
                    
                    color_alter = QColor(
                        int(tha.color_alter.red() * shd + bgcolor.red() * (1.0 - shd) + 0.5),
                        int(tha.color_alter.green() * shd + bgcolor.green() * (1.0 - shd)+ 0.5),
                        int(tha.color_alter.blue() * shd + bgcolor.blue() * (1.0 - shd) + 0.5),
                        tha.color_alter.alpha())
                
                else:
                    color_main, color_alter = tha.color_main, tha.color_alter

                port_gradient.setColorAt(0.0, color_main)
                port_gradient.setColorAt(0.5, color_alter)
                port_gradient.setColorAt(1.0, color_main)
            
            self.setPen(QPen(port_gradient, tha.base_width, Qt.SolidLine, Qt.FlatCap))
        else:
            if self._semi_hidden:
                shd = canvas.semi_hide_opacity
                bgcolor = canvas.theme.scene_background_color
                
                color_main = QColor(
                    int(tha.color_main.red() * shd + bgcolor.red() * (1.0 - shd) + 0.5),
                    int(tha.color_main.green() * shd + bgcolor.green() * (1.0 - shd)+ 0.5),
                    int(tha.color_main.blue() * shd + bgcolor.blue() * (1.0 - shd) + 0.5),
                    tha.color_main.alpha())
            else:
                color_main = tha.color_main
        
            self.setPen(QPen(QBrush(color_main), tha.base_width, Qt.SolidLine, Qt.FlatCap))
        
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
        # painter.setOpacity(0.2)
        painter.drawPath(self.path())

        painter.restore()