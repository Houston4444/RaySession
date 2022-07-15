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
from tokenize import group
from typing import TYPE_CHECKING

from PyQt5.QtCore import Qt, QPointF, QPoint, QRectF
from PyQt5.QtGui import (
    QBrush, QFontMetrics, QPainter, QPen, QPolygonF,
    QLinearGradient, QIcon, QCursor)
from PyQt5.QtWidgets import QGraphicsItem, QMenu, QApplication



# Imports (Custom)
from .init_values import (
    CanvasItemType,
    PortObject,
    PortSubType,
    canvas,
    ConnectionObject,
    features,
    options,
    CallbackAct,
    PortMode,
    PortType)

from .utils import canvas_callback
from .connectable_widget import ConnectableWidget
from .connect_menu import ConnectMenu, ConnectableContextMenu
from .line_widget import LineWidget

if TYPE_CHECKING:
    from .box_widget import BoxWidget
    from .portgroup_widget import PortgroupWidget
    

# --------------------
_translate = QApplication.translate

# --------------------

class PortWidget(ConnectableWidget):
    def __init__(self, port: PortObject, parent: 'BoxWidget'):
        ConnectableWidget.__init__(self, port, parent)        
        self._logger = logging.getLogger(__name__)

        # Save Variables, useful for later
        self._port = port
        self._port_id = port.port_id
        self._port_name = port.port_name
        self._portgrp_id = port.portgrp_id
        self._pg_pos = port.pg_pos
        self._pg_len = port.pg_len
        self._port_subtype = port.port_subtype
        self._print_name = port.port_name
        self._print_name_right = ''
        self._name_truncked = False
        self._trunck_sep = '⠿'

        # Base Variables
        self._port_width = 15
        self._port_height = canvas.theme.port_height

        theme = canvas.theme.port
        if self._port_type == PortType.AUDIO_JACK:
            if self._port_subtype is PortSubType.CV:
                theme = theme.cv
            else:
                theme = theme.audio
        elif self._port_type == PortType.MIDI_JACK:
            theme = theme.midi
        
        self._theme = theme
        self._port_font = theme.font()

        self._portgrp_widget = None
        self._loop_select_done = False

        self._lines_widgets = list[LineWidget]()
        self._connect_pos = QPointF(0.0, 0.0)
        self._update_connect_pos()

    def get_port_id(self) -> int:
        return self._port_id

    def get_connection_distance(self) -> float:
        return self._port_width

    def get_port_width(self) -> float:
        return self._port_width

    def set_portgroup_id(self, portgrp_id: int, index: int, portgrp_len: int):
        self._portgrp_id = portgrp_id
        self._pg_pos = index
        self._pg_len = portgrp_len
        self._update_connect_pos()

    def set_portgroup_widget(self, widget: 'PortgroupWidget'):
        self._portgrp_widget = widget

    def set_port_name(self, port_name: str):
        self._port_name = port_name
        self._update_connect_pos()

    def set_port_width(self, port_width):
        self._port_width = port_width
        self._update_connect_pos()

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
        self._update_connect_pos()

    def get_text_width(self):
        if self._name_truncked:
            return (self._theme.get_text_width(self._print_name)
                    + self._theme.get_text_width(self._trunck_sep)
                    + self._theme.get_text_width(self._print_name_right))
        
        return self._theme.get_text_width(self._print_name)

    def set_as_stereo(self, port_id: int):
        canvas_callback(
            CallbackAct.PORTGROUP_ADD,
            self._group_id, self._port_mode, self._port_type,
            tuple([p.port_id for p in canvas.list_ports(group_id=self._group_id)
                   if p.port_id in (self._port_id, port_id)]))

    def type(self) -> CanvasItemType:
        return CanvasItemType.PORT

    def _update_connect_pos(self):
        phi = 0.75 if self._pg_len > 2 else 0.62
        
        x_delta = 0
        if self._port_mode is PortMode.OUTPUT:
            x_delta = self._port_width + 12
        
        height = canvas.theme.port_height
        y_delta = canvas.theme.port_height / 2
        
        if self._pg_len >= 2:
            first_old_y = height * phi
            last_old_y = height * (self._pg_len - phi)
            delta = (last_old_y - first_old_y) / (self._pg_len -1)
            y_delta = (first_old_y
                       + (self._pg_pos * delta)
                       - (height * self._pg_pos))
            
        if not self.isVisible():
            # item is hidden port when its box is folded
            y_delta = height - y_delta

        self._connect_pos = QPointF(x_delta, y_delta)

    def connect_pos(self) -> QPointF:
        return self.scenePos() + self._connect_pos
        # # scene_pos = self.scenePos()
        # phi = 0.75 if self._pg_len > 2 else 0.62
        
        # xoff = 0
        # if self._port_mode is PortMode.OUTPUT:
        #     xoff = self._port_width + 12
        
        # # cx = scene_pos.x()
        # # if self._port_mode is PortMode.OUTPUT:
        # #     cx += self._port_width + 12
        
        # height = canvas.theme.port_height
        # y_delta = canvas.theme.port_height / 2
        
        # if self._pg_len >= 2:
        #     first_old_y = height * phi
        #     last_old_y = height * (self._pg_len - phi)
        #     delta = (last_old_y - first_old_y) / (self._pg_len -1)
        #     y_delta = (first_old_y
        #                + (self._pg_pos * delta)
        #                - (height * self._pg_pos))
            
        # if not self.isVisible():
        #     # item is hidden port when its box is folded
        #     y_delta = height - y_delta
        
        # # cy = scene_pos.y() + y_delta
        
        # return self.scenePos() + QPointF(xoff, y_delta)
        # # return QPointF(self.scenePos().x() + xoff, cy)
        # # return QPointF(cx, cy)

    def add_line_to_port(self, line: 'LineWidget'):
        self._lines_widgets.append(line)

    def remove_line_from_port(self, line: 'LineWidget'):
        if line in self._lines_widgets:
            self._lines_widgets.remove(line)

    def setVisible(self, visible: bool):
        super().setVisible(visible)
        self._update_connect_pos()

    def itemChange(self, change: int, value: bool):
        if change == QGraphicsItem.ItemSelectedHasChanged:
            if self.changing_select_state:
                self.changing_select_state = False
                return
            
            self.changing_select_state = True

            if self._portgrp_widget is not None:
                if self._portgrp_widget.mouse_releasing:
                    self.setSelected(self._portgrp_widget.isSelected())
                elif not self._portgrp_widget.changing_select_state:
                    self._portgrp_widget.ensure_selection_with_ports()
            
            if self._lines_widgets:
                for line in self._lines_widgets:
                    line.update_line_gradient()
                    if self.isSelected():
                        line.setZValue(canvas.last_z_value)
                canvas.last_z_value += 1

            self.changing_select_state = False

        return QGraphicsItem.itemChange(self, change, value)

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

        canvas.menu_shown = True
        is_only_connect = bool(
            QApplication.keyboardModifiers() & Qt.ControlModifier)
        
        if is_only_connect:
            menu = ConnectMenu(self._port)
        else:
            menu = ConnectableContextMenu(self._port)

        act_x_sep_1 = menu.addSeparator()

        if (not is_only_connect
                and self._port_type == PortType.AUDIO_JACK
                and not self._port_subtype is PortSubType.CV
                and not self._portgrp_id):
            stereo_menu = QMenu(_translate('patchbay', "Set as Stereo with"), menu)
            menu.addMenu(stereo_menu)

            # get list of available mono ports settables as stereo with port
            port_cousin_list = []
            for port in canvas.list_ports(group_id=self._group_id):
                if (port.port_type == PortType.AUDIO_JACK
                        and port.port_mode == self._port_mode
                        and not port.port_subtype is PortSubType.CV):
                    port_cousin_list.append(port.port_id)

            selfport_index = port_cousin_list.index(self._port_id)
            stereo_able_ids_list = []
            if selfport_index > 0:
                stereo_able_ids_list.append(port_cousin_list[selfport_index -1])
            if selfport_index < len(port_cousin_list) -1:
                stereo_able_ids_list.append(port_cousin_list[selfport_index +1])

            at_least_one = False
            for port in canvas.list_ports(self._group_id):
                if port.port_id in stereo_able_ids_list and not port.portgrp_id:
                    act_x_setasstereo = stereo_menu.addAction(port.port_name)
                    act_x_setasstereo.setData([self, port.port_id])
                    act_x_setasstereo.triggered.connect(
                        canvas.qobject.set_as_stereo_with)
                    at_least_one = True

            if not at_least_one:
                act_x_setasstereo = stereo_menu.addAction('no available mono port')
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

        if is_only_connect:
            act_x_info.setVisible(False)
            act_x_rename.setVisible(False)
            act_x_sep_1.setVisible(False)

        # prevent a bug that moves the box on mouse click after click to 
        # quit the menu if the two clic are at same point.
        self.parentItem().setFlag(QGraphicsItem.ItemIsMovable, False)

        # precise the menu start point to still view the port
        # and be able to read its portgroup name.        
        menu.show()
        
        start_point = canvas.scene.screen_position(
            self.scenePos() + QPointF(0.0, self._port_height))
        
        if (self._portgrp_id and self._port_mode is PortMode.INPUT
                and self._pg_pos + 1 <= self._pg_len // 2):
            start_point = canvas.scene.screen_position(
                self.scenePos() + QPointF(
                    0.0, self._port_height * (0.5 + self._pg_len / 2.0)))
            
        bottom_screen = QApplication.desktop().screenGeometry().bottom()
        more = 12 if self._port_mode is PortMode.OUTPUT else 0

        if start_point.y() + menu.height() > bottom_screen:
            start_point = canvas.scene.screen_position(
                self.scenePos() + QPointF(self._port_width + more, self._port_height))
        
        act_selected = menu.exec(start_point)
        
        if act_selected == act_x_info:
            canvas.callback(CallbackAct.PORT_INFO, self._group_id, self._port_id)

        elif act_selected == act_x_rename:
            canvas.callback(CallbackAct.PORT_RENAME, self._group_id, self._port_id)
            
        if act_selected is None:
            canvas.menu_click_pos = QCursor.pos()
        else:
            self.parentItem().setFlag(QGraphicsItem.ItemIsMovable, True)

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
            if self._port_subtype is PortSubType.CV:
                theme = theme.cv
            else:
                theme = theme.audio
        elif self._port_type == PortType.MIDI_JACK:
            theme = theme.midi
        
        if self.isSelected():
            theme = theme.selected
        
        poly_image = theme.background_image()
        poly_color = theme.background_color()
        poly_color_alter = theme.background2_color()
        poly_pen = theme.fill_pen()
        #poly_pen.setJoinStyle(Qt.RoundJoin)
        text_pen = QPen(theme.text_color())

        # To prevent quality worsening
        poly_pen = QPen(poly_pen)
        poly_pen.setWidthF(poly_pen.widthF() + 0.00001)

        line_hinting = poly_pen.widthF() / 2
        p_height = canvas.theme.port_height
        text_y_pos = ((p_height - 0.667 * self._port_font.pixelSize()) / 2
                      + self._port_font.pixelSize() * 0.667)

        poly_locx = [0, 0, 0, 0, 0, 0]
        poly_corner_xhinting = ((float(canvas.theme.port_height)/2)
                                % floor(float(canvas.theme.port_height)/2))
        if poly_corner_xhinting == 0:
            poly_corner_xhinting = 0.5 * (1 - 7 / (float(canvas.theme.port_height)/2))

        is_cv_port = bool(self._port_subtype is PortSubType.CV)

        if self._port_mode is PortMode.INPUT:
            text_pos = QPointF(3, text_y_pos)

            if is_cv_port:
                poly_locx[0] = line_hinting
                poly_locx[1] = self._port_width + 5 - line_hinting
                poly_locx[2] = self._port_width + 5 - line_hinting
                poly_locx[3] = self._port_width + 5 - line_hinting
                poly_locx[4] = line_hinting
                poly_locx[5] = self._port_width
            else:
                poly_locx[0] = line_hinting
                poly_locx[1] = self._port_width + 5 - line_hinting
                poly_locx[2] = self._port_width + 12 - poly_corner_xhinting
                poly_locx[3] = self._port_width + 5 - line_hinting
                poly_locx[4] = line_hinting
                poly_locx[5] = self._port_width

        elif self._port_mode is PortMode.OUTPUT:
            text_pos = QPointF(9, text_y_pos)

            if is_cv_port:
                poly_locx[0] = self._port_width + 12 - line_hinting
                poly_locx[1] = 5 + line_hinting
                poly_locx[2] = 5 + line_hinting
                poly_locx[3] = 5 + line_hinting
                poly_locx[4] = self._port_width + 12 - line_hinting
                poly_locx[5] = 12 - line_hinting
            else:
                poly_locx[0] = self._port_width + 12 - line_hinting
                poly_locx[1] = 7 + line_hinting
                poly_locx[2] = 0 + poly_corner_xhinting
                poly_locx[3] = 7 + line_hinting
                poly_locx[4] = self._port_width + 12 - line_hinting
                poly_locx[5] = 12 - line_hinting

        else:
            self._logger.critical(f"paint() - "
                                  "invalid port mode {str(self._port_mode)}")
            return

        polygon = QPolygonF()

        if self._portgrp_id:
            first_of_portgrp = bool(self._pg_pos == 0)
            last_of_portgrp = bool(self._pg_pos + 1 == self._pg_len)

            if first_of_portgrp:
                polygon += QPointF(poly_locx[0] , line_hinting)
                polygon += QPointF(poly_locx[5] , line_hinting)
            else:
                polygon += QPointF(poly_locx[0] , 0)
                polygon += QPointF(poly_locx[5] , 0)

            if last_of_portgrp:
                polygon += QPointF(poly_locx[5], canvas.theme.port_height - line_hinting)
                polygon += QPointF(poly_locx[0], canvas.theme.port_height - line_hinting)
            else:
                polygon += QPointF(poly_locx[5], canvas.theme.port_height)
                polygon += QPointF(poly_locx[0], canvas.theme.port_height)
        else:
            polygon += QPointF(poly_locx[0], line_hinting)
            polygon += QPointF(poly_locx[1], line_hinting)
            polygon += QPointF(poly_locx[2], float(canvas.theme.port_height)/2)
            polygon += QPointF(poly_locx[3], canvas.theme.port_height - line_hinting)
            polygon += QPointF(poly_locx[4], canvas.theme.port_height - line_hinting)
            polygon += QPointF(poly_locx[0], line_hinting)

        if poly_image is not None:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(poly_image))
            painter.drawPolygon(polygon)

        if poly_color_alter is not None:
            port_gradient = QLinearGradient(0, 0, 0, self._port_height)

            port_gradient.setColorAt(0, poly_color)
            port_gradient.setColorAt(0.5, poly_color_alter)
            port_gradient.setColorAt(1, poly_color)

            painter.setBrush(port_gradient)
        else:
            painter.setBrush(poly_color)
        
        painter.setPen(poly_pen)
        painter.drawPolygon(polygon)

        if not self._portgrp_id:
            if self._port_subtype is PortSubType.CV:
                poly_pen.setWidthF(2.000001)
                painter.setPen(poly_pen)

                y_line = canvas.theme.port_height / 2.0
                if self._port_mode is PortMode.OUTPUT:
                    painter.drawLine(0, y_line, poly_locx[1], y_line)
                elif self._port_mode is PortMode.INPUT:
                    painter.drawLine(
                        self._port_width + 5, y_line,
                        self._port_width + 12, y_line)

            elif self._port_subtype is PortSubType.A2J:
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
