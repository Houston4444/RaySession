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
import time
from typing import TYPE_CHECKING

from PyQt5.QtCore import Qt, QPointF, QRectF
from PyQt5.QtGui import (
    QCursor, QFontMetrics, QPainter, QPen, QPolygonF,
    QLinearGradient, QIcon)
from PyQt5.QtWidgets import QGraphicsItem, QMenu, QApplication


# Imports (Custom)
from .init_values import (
    CanvasItemType,
    canvas,
    ConnectionObject,
    features,
    options,
    CallbackAct,
    PortMode,
    PortType)

import patchcanvas.utils as utils
from .canvasconnectable import CanvasConnectable
from .canvasbezierlinemov import CanvasBezierLineMov
from .connect_menu import MainPortContextMenu

if TYPE_CHECKING:
    from .canvasbox import CanvasBox

# --------------------
_translate = QApplication.translate

# --------------------

class CanvasPort(CanvasConnectable):
    def __init__(self, group_id: int, port_id: int, port_name: str,
                 port_mode: PortMode, port_type: PortType,
                 is_alternate: bool, parent: 'CanvasBox'):
        CanvasConnectable.__init__(self, group_id, (port_id,), port_mode,
                                   port_type, is_alternate, parent)

        self._logger = logging.getLogger(__name__)

        # Save Variables, useful for later
        self._port_id = port_id
        self._port_name = port_name
        self._portgrp_id = 0
        self._portgrp_index = 0
        self._portgrp_len = 1
        self._is_alternate = is_alternate
        self._print_name = port_name
        self._print_name_right = ''
        self._name_truncked = False
        self._trunck_sep = '⠿'

        # Base Variables
        self._port_width = 15
        self._port_height = canvas.theme.port_height

        theme = canvas.theme.port
        if self._port_type == PortType.AUDIO_JACK:
            if self._is_alternate:
                theme = theme.cv
            else:
                theme = theme.audio
        elif self._port_type == PortType.MIDI_JACK:
            theme = theme.midi
        
        self._theme = theme
        self._port_font = theme.font()

    def get_port_id(self) -> int:
        return self._port_id

    def is_alternate(self) -> bool:
        return self._is_alternate

    def get_port_width(self):
        return self._port_width

    def get_portgroup_position(self) -> tuple:
        return utils.get_portgroup_position(
            self._group_id, self._port_id, self._portgrp_id)

    def set_portgroup_id(self, portgrp_id: int, index: int, portgrp_len: int):
        self._portgrp_id = portgrp_id
        self._portgrp_index = index
        self._portgrp_len = portgrp_len

    def set_port_name(self, port_name: str):
        self._port_name = port_name

    def set_port_width(self, port_width):
        self._port_width = port_width

    def set_print_name(self, print_name:str, width_limited: int):
        self._print_name = print_name
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

    def get_text_width(self):
        if self._name_truncked:
            return (self._theme.get_text_width(self._print_name)
                    + self._theme.get_text_width(self._trunck_sep)
                    + self._theme.get_text_width(self._print_name_right))
        
        return self._theme.get_text_width(self._print_name)

    def set_as_stereo(self, port_id: int):
        utils.canvas_callback(
            CallbackAct.PORTGROUP_ADD,
            self._group_id, self._port_mode, self._port_type,
            tuple([p.port_id for p in canvas.port_list
                   if p.port_id in (self._port_id, port_id)]))

    def type(self) -> CanvasItemType:
        return CanvasItemType.PORT

    def connect_pos(self):
        scene_pos = self.scenePos()
        phi = 0.75 if self._portgrp_len > 2 else 0.62
        
        cx = scene_pos.x()
        if self._port_mode is PortMode.OUTPUT:
            cx += self._port_width + 12
        
        height = canvas.theme.port_height
        y_delta = canvas.theme.port_height / 2
        
        if self._portgrp_len >= 2:
            first_old_y = height * phi
            last_old_y = height * (self._portgrp_len - phi)
            delta = (last_old_y - first_old_y) / (self._portgrp_len -1)
            y_delta = (first_old_y
                      + (self._portgrp_index * delta)
                      - (height * self._portgrp_index))
            
        if not self.isVisible():
            # item is hidden port when its box is folded
            y_delta = height - y_delta
        
        cy = scene_pos.y() + y_delta
        
        return QPointF(cx, cy)

    def parentItem(self) -> 'CanvasBox':
        return super().parentItem()

    def contextMenuEvent(self, event):
        if canvas.scene.get_zoom_scale() <= 0.4:
            # prefer move box if zoom is too low
            event.ignore()
            return
        
        if canvas.is_line_mov:
            return

        event.accept()
        canvas.scene.clearSelection()
        self.setSelected(True)

        menu = MainPortContextMenu(self._group_id, self._port_id)

        act_x_sep_1 = menu.addSeparator()

        if (self._port_type == PortType.AUDIO_JACK
                and not self._is_alternate
                and not self._portgrp_id):
            StereoMenu = QMenu(_translate('patchbay', "Set as Stereo with"), menu)
            menu.addMenu(StereoMenu)

            # get list of available mono ports settables as stereo with port
            port_cousin_list = []
            for port in canvas.port_list:
                if (port.port_type == PortType.AUDIO_JACK
                        and port.group_id == self._group_id
                        and port.port_mode == self._port_mode
                        and not port.is_alternate):
                    port_cousin_list.append(port.port_id)

            selfport_index = port_cousin_list.index(self._port_id)
            stereo_able_ids_list = []
            if selfport_index > 0:
                stereo_able_ids_list.append(port_cousin_list[selfport_index -1])
            if selfport_index < len(port_cousin_list) -1:
                stereo_able_ids_list.append(port_cousin_list[selfport_index +1])

            at_least_one = False
            for port in canvas.port_list:
                if port.port_id in stereo_able_ids_list and not port.portgrp_id:
                    act_x_setasstereo = StereoMenu.addAction(port.port_name)
                    act_x_setasstereo.setData([self, port.port_id])
                    act_x_setasstereo.triggered.connect(
                        canvas.qobject.set_as_stereo_with)
                    at_least_one = True

            if not at_least_one:
                act_x_setasstereo = StereoMenu.addAction('no available mono port')
                act_x_setasstereo.setEnabled(False)

        act_x_info = menu.addAction(_translate('patchbay', "Get &Info"))
        act_x_info.setIcon(QIcon.fromTheme('dialog-information'))
        act_x_rename = menu.addAction(_translate('patchbay', "&Rename"))

        if not features.port_info:
            act_x_info.setVisible(False)

        if not features.port_rename:
            act_x_rename.setVisible(False)

        if not (features.port_info and features.port_rename):
            act_x_sep_1.setVisible(False)

        act_selected = menu.exec_(event.screenPos())

        if act_selected == act_x_info:
            canvas.callback(CallbackAct.PORT_INFO, self._group_id, self._port_id)

        elif act_selected == act_x_rename:
            canvas.callback(CallbackAct.PORT_RENAME, self._group_id, self._port_id)

    def trigger_disconnect(self, conn_list=None):
        if not conn_list:
            conn_list = utils.get_port_connection_list(self._group_id, self._port_id)
        for conn_id, group_id, port_id in conn_list:
            canvas.callback(CallbackAct.PORTS_DISCONNECT, conn_id)

    def boundingRect(self):
        if self._portgrp_id:
            if self._port_mode is PortMode.INPUT:
                return QRectF(0, 0, self._port_width, self._port_height)
            else:
                return QRectF(12, 0,
                              self._port_width, self._port_height)
        else:
            return QRectF(0, 0, self._port_width + 12, self._port_height)

    def paint(self, painter, option, widget):
        if canvas.loading_items:
            return
        
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
    
        theme = canvas.theme.port

        if self._port_type == PortType.AUDIO_JACK:
            if self._is_alternate:
                theme = theme.cv
            else:
                theme = theme.audio
        elif self._port_type == PortType.MIDI_JACK:
            theme = theme.midi
        
        if self.isSelected():
            theme = theme.selected
        
        poly_color = theme.background_color()
        poly_color_alter = theme.background2_color()
        poly_pen = theme.fill_pen()
        #poly_pen.setJoinStyle(Qt.RoundJoin)
        text_pen = QPen(theme.text_color())

        # To prevent quality worsening
        poly_pen = QPen(poly_pen)
        poly_pen.setWidthF(poly_pen.widthF() + 0.00001)

        lineHinting = poly_pen.widthF() / 2
        text_y_pos = 12

        poly_locx = [0, 0, 0, 0, 0, 0]
        poly_corner_xhinting = ((float(canvas.theme.port_height)/2)
                                % floor(float(canvas.theme.port_height)/2))
        if poly_corner_xhinting == 0:
            poly_corner_xhinting = 0.5 * (1 - 7 / (float(canvas.theme.port_height)/2))

        is_cv_port = bool(self._port_type == PortType.AUDIO_JACK
                          and self._is_alternate)

        if self._port_mode is PortMode.INPUT:
            text_pos = QPointF(3, text_y_pos)

            if is_cv_port:
                poly_locx[0] = lineHinting
                poly_locx[1] = self._port_width + 5 - lineHinting
                poly_locx[2] = self._port_width + 5 - lineHinting
                poly_locx[3] = self._port_width + 5 - lineHinting
                poly_locx[4] = lineHinting
                poly_locx[5] = self._port_width
            else:
                poly_locx[0] = lineHinting
                poly_locx[1] = self._port_width + 5 - lineHinting
                poly_locx[2] = self._port_width + 12 - poly_corner_xhinting
                poly_locx[3] = self._port_width + 5 - lineHinting
                poly_locx[4] = lineHinting
                poly_locx[5] = self._port_width

        elif self._port_mode is PortMode.OUTPUT:
            text_pos = QPointF(9, text_y_pos)

            if is_cv_port:
                poly_locx[0] = self._port_width + 12 - lineHinting
                poly_locx[1] = 5 + lineHinting
                poly_locx[2] = 5 + lineHinting
                poly_locx[3] = 5 + lineHinting
                poly_locx[4] = self._port_width + 12 - lineHinting
                poly_locx[5] = 12 - lineHinting
            else:
                poly_locx[0] = self._port_width + 12 - lineHinting
                poly_locx[1] = 7 + lineHinting
                poly_locx[2] = 0 + poly_corner_xhinting
                poly_locx[3] = 7 + lineHinting
                poly_locx[4] = self._port_width + 12 - lineHinting
                poly_locx[5] = 12 - lineHinting

        else:
            self._logger.critical(f"paint() - "
                                  "invalid port mode {str(self._port_mode)}")
            return

        polygon = QPolygonF()

        if self._portgrp_id:
            first_of_portgrp = False
            last_of_portgrp = False

            # look in portgroup if port is the first,
            # the last, or not.
            for portgrp in canvas.portgrp_list:
                if portgrp.portgrp_id == self._portgrp_id:
                    if self._port_id == portgrp.port_id_list[0]:
                        first_of_portgrp = True
                    if self._port_id == portgrp.port_id_list[-1]:
                        last_of_portgrp = True
                    break

            if first_of_portgrp:
                polygon += QPointF(poly_locx[0] , lineHinting)
                polygon += QPointF(poly_locx[5] , lineHinting)
            else:
                polygon += QPointF(poly_locx[0] , 0)
                polygon += QPointF(poly_locx[5] , 0)

            if last_of_portgrp:
                polygon += QPointF(poly_locx[5], canvas.theme.port_height - lineHinting)
                polygon += QPointF(poly_locx[0], canvas.theme.port_height - lineHinting)
            else:
                polygon += QPointF(poly_locx[5], canvas.theme.port_height)
                polygon += QPointF(poly_locx[0], canvas.theme.port_height)
        else:
            polygon += QPointF(poly_locx[0], lineHinting)
            polygon += QPointF(poly_locx[1], lineHinting)
            polygon += QPointF(poly_locx[2], float(canvas.theme.port_height)/2)
            polygon += QPointF(poly_locx[3], canvas.theme.port_height - lineHinting)
            polygon += QPointF(poly_locx[4], canvas.theme.port_height - lineHinting)
            polygon += QPointF(poly_locx[0], lineHinting)

        if poly_color_alter is not None:
            port_gradient = QLinearGradient(0, 0, 0, self._port_height)

            port_gradient.setColorAt(0, poly_color)
            port_gradient.setColorAt(0.5, poly_color_alter)
            port_gradient.setColorAt(1, poly_color)

            painter.setBrush(port_gradient)
        else:
            painter.setBrush(poly_color)
            
        painter.setPen(poly_pen)
        
        #try_rect = QRectF(4.0, 4.0, 20.0, 4.0)
        #polygon = polygon.subtracted(QPolygonF(try_rect))
        painter.drawPolygon(polygon)

        if self._is_alternate and not self._portgrp_id:
            if is_cv_port:
                poly_pen.setWidthF(2.000001)
                painter.setPen(poly_pen)

                y_line = canvas.theme.port_height / 2.0
                if self._port_mode is PortMode.OUTPUT:
                    painter.drawLine(0, y_line, poly_locx[1], y_line)
                elif self._port_mode is PortMode.INPUT:
                    painter.drawLine(
                        self._port_width + 5, y_line,
                        self._port_width + 12, y_line)
            else:
                # draw the little circle for a2j (or MidiBridge) port
                poly_pen.setWidthF(1.000001)
                
                # we emulate a hole in the port, so we need the background
                # of the box.
                parent = self.parentItem()
                box_theme = parent.get_theme()
                if parent.isSelected():
                    box_theme = box_theme.selected

                painter.setBrush(box_theme.background_color())

                ellipse_x = poly_locx[1]
                if self._port_mode is PortMode.OUTPUT:
                    ellipse_x -= 2
                elif self._port_mode is PortMode.INPUT:
                    ellipse_x += 2

                painter.drawEllipse(
                    QPointF(ellipse_x, canvas.theme.port_height / 2.0), 2, 2)

        painter.setPen(text_pen)
        painter.setFont(self._port_font)

        sizer = QFontMetrics(self._port_font)
        sep_width = sizer.width(self._trunck_sep)

        if self._portgrp_id:
            print_name_size = self.get_text_width()

            if self._port_mode is PortMode.OUTPUT:
                text_pos = QPointF(self._port_width + 9 - print_name_size,
                                   text_y_pos)

            if print_name_size > (self._port_width - 4):
                if poly_color_alter is not None:
                    painter.setPen(QPen(port_gradient, 3))
                else:
                    painter.setPen(QPen(poly_color, 3))
                painter.drawLine(
                    QPointF(float(poly_locx[5]), 3.0),
                    QPointF(float(poly_locx[5]),
                            float(canvas.theme.port_height - 3)))
                painter.setPen(text_pen)
                painter.setFont(self._port_font)

        painter.drawText(text_pos, self._print_name)
        
        if self._name_truncked:
            sep_x = text_pos.x() + sizer.width(self._print_name)
            
            painter.drawText(QPointF(sep_x + sep_width, text_pos.y()),
                             self._print_name_right)

            trunck_pen = QPen(text_pen)
            color = text_pen.color()
            color.setAlphaF(color.alphaF() * 0.25)
            trunck_pen.setColor(color)
            painter.setPen(trunck_pen)
            painter.drawText(QPointF(sep_x, text_pos.y() + 1), self._trunck_sep)

        painter.restore()
