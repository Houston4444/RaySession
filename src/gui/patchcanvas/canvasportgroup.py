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


# Imports (Global)
import logging
from math import floor
from typing import TYPE_CHECKING

from PyQt5.QtCore import QPointF, QRectF
from PyQt5.QtGui import (QFontMetrics, QPainter,
                         QPolygonF, QLinearGradient, QPen)
from PyQt5.QtWidgets import QApplication

# Imports (Custom)
import patchcanvas.utils as utils
from .canvasconnectable import CanvasConnectable
from .init_values import (
    CanvasItemType,
    canvas,
    CallbackAct,
    PortMode,
    PortType)
from .connect_menu import MainPortContextMenu

if TYPE_CHECKING:
    from .canvasbox import CanvasBox

# -------------------------

_translate = QApplication.translate

# -------------------------


class CanvasPortGroup(CanvasConnectable):
    def __init__(self, group_id: int, portgrp_id: int, port_mode: PortMode,
                 port_type: PortType, port_id_list: tuple[int],
                 parent: 'CanvasBox'):
        CanvasConnectable.__init__(self, group_id, port_id_list,
                                   port_mode, port_type, False, parent)
        self._logger = logging.getLogger(__name__)

        # Save Variables, useful for later
        self._portgrp_id = portgrp_id
        self._port_id_list = port_id_list

        # Base Variables
        self._portgrp_width  = 15
        self._portgrp_height = canvas.theme.port_height
        
        theme = canvas.theme.portgroup
        if self._port_type == PortType.AUDIO_JACK:
            theme = theme.audio
        elif self._port_type == PortType.MIDI_JACK:
            theme == theme.midi
        
        self._theme = theme
        self._portgrp_font = theme.font()

        self._ports_width = canvas.theme.port_grouped_width
        self._print_name = ''
        self._normal_print_name = '' # same as m_print_name but not reduced
        self._print_name_right = ''
        self._name_truncked = False
        self._trunck_sep = '⠿'

    def is_alternate(self):
        return False

    def get_group_id(self)->int:
        return self._group_id

    def get_port_width(self):
        return self._portgrp_width

    def get_port_ids_list(self):
        return self._port_id_list

    def get_port_list_len(self):
        return len(self._port_id_list)

    def type(self) -> CanvasItemType:
        return CanvasItemType.PORTGROUP

    def set_portgrp_width(self, portgrp_width: float):
        self._portgrp_width = portgrp_width

    def set_ports_width(self, ports_width:int):
        self._ports_width = ports_width

    def set_print_name(self, print_name:str, width_limited: int):
        self._print_name = print_name
        self._normal_print_name = print_name
        self._name_truncked = False

        if width_limited:
            #sizer = QFontMetrics(self._port_font)
            long_size = self._theme.get_text_width(self._print_name)
            
            if long_size > width_limited:
                name_len = len(self._print_name)
                middle = int(name_len / 2)
                left_text = self._print_name[:middle]
                middle_text = self._trunck_sep
                right_text = self._print_name[middle + 1:]
                left_size = self._theme.get_text_width(left_text)
                middle_size = self._theme.get_text_width(middle_text)
                right_size = self._theme.get_text_width(right_text)
                
                while left_size + middle_size + right_size > width_limited:
                    if left_size > right_size:
                        left_text = left_text[:-1]
                        left_size = self._theme.get_text_width(left_text)
                    else:
                        right_text = right_text[1:]
                        right_size = self._theme.get_text_width(right_text)
                        
                    if not (left_text or right_text):
                        break

                self._print_name = left_text
                self._print_name_right = right_text
                self._name_truncked = True

    def reduce_print_name(self, width_limited:int):
        self.set_print_name(self._normal_print_name, width_limited)

    def get_text_width(self):
        if self._name_truncked:
            return (self._theme.get_text_width(self._print_name)
                    + self._theme.get_text_width(self._trunck_sep)
                    + self._theme.get_text_width(self._print_name_right))
        
        return self._theme.get_text_width(self._print_name)

    def _split_to_monos(self):
        utils.canvas_callback(CallbackAct.PORTGROUP_REMOVE,
                              self._group_id, self._portgrp_id)

    def contextMenuEvent(self, event):
        if canvas.scene.get_zoom_scale() <= 0.4:
            # prefer move box if zoom is too low
            event.ignore()
            return
        
        if canvas.is_line_mov:
            return

        canvas.scene.clearSelection()
        self.setSelected(True)

        menu = MainPortContextMenu(self._group_id, 0, self._portgrp_id)

        act_x_setasmono = menu.addAction(
            _translate('patchbay', "Split to Monos"))
        act_selected = menu.exec_(event.screenPos())

        if act_selected == act_x_setasmono:
            self._split_to_monos()

        event.accept()

    def boundingRect(self):
        if self._port_mode is PortMode.INPUT:
            return QRectF(canvas.theme.port_grouped_width, 0,
                          self._portgrp_width + 12 - canvas.theme.port_grouped_width,
                          canvas.theme.port_height * len(self._port_id_list))
        else:
            return QRectF(0, 0,
                          self._portgrp_width + 12 - canvas.theme.port_grouped_width,
                          canvas.theme.port_height * len(self._port_id_list))

    def paint(self, painter, option, widget):
        if canvas.loading_items:
            return

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)

        theme = canvas.theme.portgroup
        
        if self._port_type == PortType.AUDIO_JACK:
            theme = theme.audio
        elif self._port_type == PortType.MIDI_JACK:
            theme = theme.midi
            
        if self.isSelected():
            theme = theme.selected

        poly_pen = theme.fill_pen()
        color_main = theme.background_color()
        color_alter = theme.background2_color()
        text_pen = QPen(theme.text_color())

        lineHinting = poly_pen.widthF() / 2.0

        poly_locx = [0, 0, 0, 0, 0]
        poly_corner_xhinting = (
            float(canvas.theme.port_height)/2) % floor(float(canvas.theme.port_height)/2)
        if poly_corner_xhinting == 0:
            poly_corner_xhinting = 0.5 * (1 - 7 / (float(canvas.theme.port_height)/2))

        if self._port_mode is PortMode.INPUT:
            port_width = canvas.theme.port_grouped_width

            for port in canvas.port_list:
                if port.port_id in self._port_id_list:
                    port_print_name = utils.get_port_print_name(
                        port.group_id, port.port_id, self._portgrp_id)
                    port_in_p_width = QFontMetrics(self._portgrp_font).width(port_print_name) + 3
                    port_width = max(port_width, port_in_p_width)

            text_pos = QPointF(
                self._ports_width + 3,
                12 + (canvas.theme.port_height * (len(self._port_id_list) -1)/2))

            poly_locx[0] = self._ports_width - lineHinting
            poly_locx[1] = self._portgrp_width + 3 + lineHinting
            poly_locx[2] = self._portgrp_width + 10 + lineHinting
            poly_locx[3] = self._portgrp_width + 3 + lineHinting
            poly_locx[4] = self._ports_width - lineHinting

        elif self._port_mode is PortMode.OUTPUT:
            text_pos = QPointF(
                9, 12 + (canvas.theme.port_height * (len(self._port_id_list) -1)/2))

            poly_locx[0] = self._portgrp_width + 12 \
                            - self._ports_width - lineHinting
            poly_locx[1] = 7 + lineHinting
            poly_locx[2] = 0 + lineHinting
            poly_locx[3] = 7 + lineHinting
            poly_locx[4] = self._portgrp_width + 12 - self._ports_width - lineHinting

        else:
            self._logger.critical(f"CanvasPortGroup.paint() - "
                                  "invalid port mode {str(self._port_mode)}")
            return

        polygon  = QPolygonF()
        polygon += QPointF(poly_locx[0], lineHinting)
        polygon += QPointF(poly_locx[1], lineHinting)
        polygon += QPointF(poly_locx[2], float(canvas.theme.port_height / 2) )
        polygon += QPointF(poly_locx[2],
                           float(canvas.theme.port_height * (len(self._port_id_list) - 1/2)))
        polygon += QPointF(poly_locx[3],
                           canvas.theme.port_height * len(self._port_id_list) - lineHinting)
        polygon += QPointF(poly_locx[4],
                           canvas.theme.port_height * len(self._port_id_list) - lineHinting)

        if color_alter is not None:
            portgrp_gradient = QLinearGradient(0, 0, 0, self._portgrp_height * 2)
            portgrp_gradient.setColorAt(0, color_main)
            portgrp_gradient.setColorAt(0.5, color_alter)
            portgrp_gradient.setColorAt(1, color_main)

            painter.setBrush(portgrp_gradient)
        else:
            painter.setBrush(color_main)
            
        painter.setPen(poly_pen)
        painter.drawPolygon(polygon)

        painter.setPen(text_pen)
        painter.setFont(self._portgrp_font)
        painter.drawText(text_pos, self._print_name)
        if self._name_truncked:
            sizer = QFontMetrics(self._portgrp_font)
            sep_x = text_pos.x() + sizer.width(self._print_name)
            sep_width = sizer.width(self._trunck_sep)

            painter.drawText(QPointF(sep_x + sep_width, text_pos.y()),
                             self._print_name_right)

            trunck_pen = QPen(text_pen)
            color = text_pen.color()
            color.setAlphaF(color.alphaF() * 0.25)
            trunck_pen.setColor(color)
            painter.setPen(trunck_pen)
            
            painter.drawText(QPointF(sep_x, text_pos.y() + 1), self._trunck_sep)

        painter.restore()

