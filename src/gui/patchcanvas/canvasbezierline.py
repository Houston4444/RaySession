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
from PyQt5.QtCore import Qt, QPointF
from PyQt5.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import QGraphicsPathItem

# ------------------------------------------------------------------------------------------------------------
# Imports (Custom)

from . import (
    canvas,
    options,
    CanvasBezierLineType,
    ACTION_PORTS_DISCONNECT,
    PORT_MODE_OUTPUT,
    PORT_TYPE_MIDI_JACK,
)

# ------------------------------------------------------------------------------------------------------------

class CanvasBezierLine(QGraphicsPathItem):
    def __init__(self, item1, item2, parent):
        QGraphicsPathItem.__init__(self)
        self.setParentItem(parent)

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
                canvas.callback(ACTION_PORTS_DISCONNECT,
                                connection.connection_id, 0, "")
                break

    def semi_hide(self, yesno: bool):
        self._semi_hidden = yesno
        self.update_line_gradient()

    def update_line_pos(self):
        if self.item1.get_port_mode() == PORT_MODE_OUTPUT:
            item1_x = self.item1.scenePos().x() + self.item1.get_port_width() + 12

            port_pos_1, portgrp_len_1 = self.item1.get_portgroup_position()

            phi = 0.75 if portgrp_len_1 > 2 else 0.62

            if portgrp_len_1 > 1:
                first_old_y = canvas.theme.port_height * phi
                last_old_y = canvas.theme.port_height * (portgrp_len_1 - phi)
                delta = (last_old_y - first_old_y) / (portgrp_len_1 -1)
                old_y1 = first_old_y + (port_pos_1 * delta) - (canvas.theme.port_height * port_pos_1)
                if not self.item1.isVisible():
                    # item is hidden port when its box is folded
                    old_y1 = canvas.theme.port_height - old_y1
            else:
                old_y1 = canvas.theme.port_height / 2

            item1_y = self.item1.scenePos().y() + old_y1

            item2_x = self.item2.scenePos().x()

            port_pos_2, portgrp_len_2 = self.item2.get_portgroup_position()

            phi = 0.75 if portgrp_len_1 > 2 else 0.62

            if portgrp_len_2 > 1:
                first_old_y = canvas.theme.port_height * phi
                last_old_y  = canvas.theme.port_height * (portgrp_len_2 - phi)
                delta = (last_old_y - first_old_y) / (portgrp_len_2 -1)
                old_y2 = (first_old_y + (port_pos_2 * delta)
                          - (canvas.theme.port_height * port_pos_2))
                if not self.item2.isVisible():
                    old_y2 = canvas.theme.port_height - old_y2
            else:
                old_y2 = canvas.theme.port_height / 2

            item2_y = self.item2.scenePos().y() + old_y2

            mid_x = abs(item1_x - item2_x) / 2

            diffxy = abs(item1_y - item2_y) - abs(item1_x - item2_x)
            if diffxy > 0:
                mid_x += diffxy

            if diffxy > 0 or item1_x > item2_x:
                mid_x = min(mid_x, 200)

            item1_new_x = item1_x + mid_x
            item2_new_x = item2_x - mid_x

            path = QPainterPath(QPointF(item1_x, item1_y))
            path.cubicTo(item1_new_x, item1_y, item2_new_x, item2_y,
                         item2_x, item2_y)
            self.setPath(path)

            self._line_selected = False
            self.update_line_gradient()

    def type(self):
        return CanvasBezierLineType

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

        base_color = canvas.theme.line_audio_jack
        if self._line_selected:
            base_color = canvas.theme.line_audio_jack_sel

        if port_type1 == PORT_TYPE_MIDI_JACK:
            base_color = canvas.theme.port_midi_jack_bg
            if self._line_selected:
                base_color = canvas.theme.port_midi_jack_bg_sel

        if self._semi_hidden:
            base_color = QColor(int(base_color.red() * canvas.semi_hide_opacity + 0.5),
                                int(base_color.green() * canvas.semi_hide_opacity + 0.5),
                                int(base_color.blue() * canvas.semi_hide_opacity + 0.5))

        if self.ready_to_disc:
            port_gradient.setColorAt(pos1, QColor(34, 34, 34))
            port_gradient.setColorAt(pos2, QColor(34, 34, 34))
            self.setPen(QPen(port_gradient, 2, Qt.DotLine))
        else:
            port_gradient.setColorAt(0, base_color.lighter(130))
            port_gradient.setColorAt(0.5, base_color.darker(130))
            port_gradient.setColorAt(1, base_color.lighter(130))

        self.setPen(QPen(port_gradient, 1.750001, Qt.SolidLine, Qt.FlatCap))

    def paint(self, painter, option, widget):
        if canvas.scene.loading_items:
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
