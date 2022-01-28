#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# PatchBay Canvas engine using QGraphicsView/Scene
# Copyright (C) 2010-2019 Filipe Coelho <falktx@falktx.com>
# Copyright (C) 2019-2021 Mathieu Picot <picotmathieu@gmail.com>
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
import time

from PyQt5.QtCore import qCritical, Qt, QPointF, QRectF
from PyQt5.QtGui import (QCursor, QFont, QFontMetrics, QPainter,
                         QPolygonF, QLinearGradient, QPen)
from PyQt5.QtWidgets import QGraphicsItem, QApplication

# ------------------------------------------------------------------------------------------------------------
# Imports (Custom)
import patchcanvas.utils as utils
from . import (
    PORT_TYPE_MIDI_JACK,
    canvas,
    features,
    options,
    port_mode2str,
    port_type2str,
    CanvasPortType,
    CanvasPortGroupType,
    ACTION_PORTGROUP_REMOVE,
    ACTION_PORT_INFO,
    ACTION_PORT_RENAME,
    ACTION_PORTS_CONNECT,
    ACTION_PORTS_DISCONNECT,
    PORT_MODE_INPUT,
    PORT_MODE_OUTPUT,
    PORT_TYPE_AUDIO_JACK,
)

from .canvasbezierlinemov import CanvasBezierLineMov
from .theme import Theme
from .connect_menu import MainPortContextMenu

# ------------------------------------------------------------------------------------------------------------
_translate = QApplication.translate


class CanvasPortGroup(QGraphicsItem):
    def __init__(self, group_id, portgrp_id, port_mode,
                 port_type, port_id_list, parent):
        QGraphicsItem.__init__(self)
        self.setCacheMode(QGraphicsItem.DeviceCoordinateCache)
        self.setParentItem(parent)

        # Save Variables, useful for later
        self._portgrp_id = portgrp_id
        self._port_mode = port_mode
        self._port_type = port_type
        self._port_id_list = port_id_list
        self._group_id = group_id

        # Base Variables
        self._portgrp_width  = 15
        self._portgrp_height = canvas.theme.port_height
        
        theme = canvas.theme.portgroup
        if self._port_type == PORT_TYPE_AUDIO_JACK:
            theme = theme.audio
        elif self._port_type == PORT_TYPE_MIDI_JACK:
            theme == theme.midi
        
        self._theme = theme
        self._portgrp_font = theme.font()

        self._ports_width = canvas.theme.port_grouped_width
        self._print_name = ''
        self._normal_print_name = '' # same as m_print_name but not reduced
        self._print_name_right = ''
        self._name_truncked = False
        self._trunck_sep = '⠿'

        self._line_mov_list = []
        self._dotcon_list = []
        self._last_rclick_item = None
        self._r_click_time = 0
        self._hover_item = None
        self._has_connections = False

        self._mouse_down = False
        self._cursor_moving = False
        self.setFlags(QGraphicsItem.ItemIsSelectable)

    def get_port_mode(self):
        return self._port_mode

    def get_port_type(self):
        return self._port_type

    def is_alternate(self):
        return False

    def is_connectable_to(self, other, accept_same_port_mode=False)->bool:
        if self._port_type != other.get_port_type():
            return False

        if not accept_same_port_mode:
            if self._port_mode == other.get_port_mode():
                return False

        if self._port_type == PORT_TYPE_AUDIO_JACK:
            if other.get_port_mode() == self._port_mode:
                return bool(self.is_alternate() == other.is_alternate())
            # absolutely forbidden to connect an output CV port
            # to an input audio port.
            # It could destroy material.
            if self._port_mode == PORT_MODE_OUTPUT:
                if self.is_alternate():
                    return other.is_alternate()
                return True

            if self._port_mode == PORT_MODE_INPUT:
                if self.is_alternate():
                    return True
                return not other.is_alternate()

        return True

    def get_group_id(self)->int:
        return self._group_id

    def get_port_width(self):
        return self._portgrp_width

    def get_port_ids_list(self):
        return self._port_id_list

    def get_port_list_len(self):
        return len(self._port_id_list)

    def type(self):
        return CanvasPortGroupType

    def set_portgrp_width(self, portgrp_width):
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

        #if width_limited:
            #sizer = QFontMetrics(self._portgrp_font)
            
            #if sizer.width(self._print_name) > width_limited:
                #name_len = len(self._print_name)
                #middle = int(name_len / 2)
                #left_text = self._print_name[:middle]
                #middle_text = self._trunck_sep
                #right_text = self._print_name[middle + 1:]
                #left_size = sizer.width(left_text)
                #middle_size = sizer.width(middle_text)
                #right_size = sizer.width(right_text)

                #while left_size + middle_size + right_size > width_limited:
                    #if left_size > right_size:
                        #left_text = left_text[:-1]
                        #left_size = sizer.width(left_text)
                    #else:
                        #right_text = right_text[1:]
                        #right_size = sizer.width(right_text)
                    
                    #if not (left_text or right_text):
                        #break

                #self._print_name = left_text
                #self._print_name_right = right_text
                #self._name_truncked = True

    def reduce_print_name(self, width_limited:int):
        self.set_print_name(self._normal_print_name, width_limited)

    def get_text_width(self):
        if self._name_truncked:
            return (self._theme.get_text_width(self._print_name)
                    + self._theme.get_text_width(self._trunck_sep)
                    + self._theme.get_text_width(self._print_name_right))
        
        return self._theme.get_text_width(self._print_name)
        
        #sizer = QFontMetrics(self._portgrp_font)

        #if self._name_truncked:
            #return (sizer.width(self._print_name)
                    #+ sizer.width(self._trunck_sep)
                    #+ sizer.width(self._print_name_right))
            
        #return sizer.width(self._print_name)

    def reset_dot_lines(self):
        for connection in self._dotcon_list:
            if connection.widget.ready_to_disc:
                connection.widget.ready_to_disc = False
                connection.widget.update_line_gradient()

        for line_mov in self._line_mov_list:
            line_mov.ready_to_disc = False
        self._dotcon_list.clear()

    def _split_to_monos(self):
        utils.canvas_callback(ACTION_PORTGROUP_REMOVE,
                              self._group_id, self._portgrp_id, "")

    def _connect_to_hover(self):
        if self._hover_item:
            if self._hover_item.type() == CanvasPortType:
                hover_port_id_list = [self._hover_item.get_port_id()]
            elif self._hover_item.type() == CanvasPortGroupType:
                hover_port_id_list = self._hover_item.get_port_ids_list()

            if not hover_port_id_list:
                return

            hover_group_id = self._hover_item.get_group_id()
            con_list = []
            ports_connected_list = []

            maxportgrp = max(len(self._port_id_list),
                             len(hover_port_id_list))

            if self._hover_item.get_port_mode() == self._port_mode:
                for i in range(len(self._port_id_list)):
                    for connection in canvas.connection_list:
                        if utils.connection_concerns(
                                connection, self._group_id,
                                [self._port_id_list[i]]):
                            canvas.callback(
                                ACTION_PORTS_DISCONNECT,
                                connection.connection_id,
                                0, '')

                            for j in range(len(hover_port_id_list)):
                                if len(hover_port_id_list) >= len(self._port_id_list):
                                    if j % len(self._port_id_list) != i:
                                        continue
                                else:
                                    if i % len(hover_port_id_list) != j:
                                        continue

                                if self._port_mode == PORT_MODE_OUTPUT:
                                    canvas.callback(
                                        ACTION_PORTS_CONNECT, 0, 0,
                                        "%i:%i:%i:%i" % (
                                            hover_group_id, hover_port_id_list[j],
                                            connection.group_in_id, connection.port_in_id))
                                else:
                                    canvas.callback(
                                        ACTION_PORTS_CONNECT, 0, 0,
                                        "%i:%i:%i:%i" % (
                                            connection.group_out_id, connection.port_out_id,
                                            hover_group_id, hover_port_id_list[j]))
                return


            for i in range(len(self._port_id_list)):
                port_id = self._port_id_list[i]
                for j in range(len(hover_port_id_list)):
                    hover_port_id = hover_port_id_list[j]

                    for connection in canvas.connection_list:
                        if utils.connection_matches(
                                connection, self._group_id, [port_id],
                                hover_group_id, [hover_port_id]):
                            if (i % len(hover_port_id_list)
                                    == j % len(self._port_id_list)):
                                con_list.append(connection)
                                ports_connected_list.append(
                                    [port_id, hover_port_id])
                            else:
                                canvas.callback(ACTION_PORTS_DISCONNECT,
                                                connection.connection_id, 0, "")

            if len(con_list) == maxportgrp:
                for connection in con_list:
                    canvas.callback(ACTION_PORTS_DISCONNECT,
                                    connection.connection_id, 0, "")
            else:
                for i in range(len(self._port_id_list)):
                    port_id = self._port_id_list[i]
                    for j in range(len(hover_port_id_list)):
                        hover_port_id = hover_port_id_list[j]
                        if (i % len(hover_port_id_list)
                                == j % len(self._port_id_list)):
                            if not [port_id, hover_port_id] in ports_connected_list:
                                if self._port_mode == PORT_MODE_OUTPUT:
                                    conn = "%i:%i:%i:%i" % (
                                        self._group_id, port_id,
                                        hover_group_id, hover_port_id)
                                else:
                                    conn = "%i:%i:%i:%i" % (
                                        hover_group_id, hover_port_id,
                                        self._group_id, port_id)
                                canvas.callback(ACTION_PORTS_CONNECT, 0, 0, conn)

    def reset_line_mov_positions(self):
        for i in range(len(self._line_mov_list)):
            line_mov = self._line_mov_list[i]
            if i < self.get_port_list_len():
                line_mov.set_destination_portgrp_pos(i, self.get_port_list_len())
            else:
                item = line_mov
                canvas.scene.removeItem(item)
                del item

        while len(self._line_mov_list) < self.get_port_list_len():
            line_mov = CanvasBezierLineMov(
                self._port_mode, self._port_type, len(self._line_mov_list),
                self.get_port_list_len(), self)

            self._line_mov_list.append(line_mov)

        self._line_mov_list = self._line_mov_list[:self.get_port_list_len()]

    def hoverEnterEvent(self, event):
        if options.auto_select_items:
            self.setSelected(True)
        QGraphicsItem.hoverEnterEvent(self, event)

    def hoverLeaveEvent(self, event):
        if options.auto_select_items:
            self.setSelected(False)
        QGraphicsItem.hoverLeaveEvent(self, event)

    def mousePressEvent(self, event):
        if canvas.scene.get_zoom_scale() <= 0.4:
            # prefer move box if zoom is too low
            event.ignore()
            return
        
        if event.button() == Qt.LeftButton:
            self._hover_item = None
            self._mouse_down = True
            self._cursor_moving = False

            for connection in canvas.connection_list:
                if utils.connection_concerns(
                        connection, self._group_id, self._port_id_list):
                    self._has_connections = True
                    break
            else:
                self._has_connections = False

        elif event.button() == Qt.RightButton:
            if canvas.is_line_mov:
                if self._hover_item:
                    self._connect_to_hover()
                    self._last_rclick_item = self._hover_item
                    self._r_click_time = time.time()

                    for line_mov in self._line_mov_list:
                        line_mov.ready_to_disc = not line_mov.ready_to_disc
                        line_mov.update_line_pos(event.scenePos())
        QGraphicsItem.mousePressEvent(self, event)

    def mouseMoveEvent(self, event):
        if not self._mouse_down:
            QGraphicsItem.mouseMoveEvent(self, event)
            return

        if not self._cursor_moving:
            self.setCursor(QCursor(Qt.CrossCursor))
            self._cursor_moving = True

            for connection in canvas.connection_list:
                if utils.connection_concerns(
                        connection, self._group_id, self._port_id_list):
                    connection.widget.locked = True

        if not self._line_mov_list:
            self._last_rclick_item = None
            canvas.last_z_value += 1
            self.setZValue(canvas.last_z_value)
            canvas.last_z_value += 1

            for port in canvas.port_list:
                if (port.group_id == self._group_id
                        and port.port_id in self._port_id_list):
                    port.widget.setZValue(canvas.last_z_value)

            for i in range(len(self._port_id_list)):
                line_mov = CanvasBezierLineMov(
                    self._port_mode, self._port_type, i,
                    len(self._port_id_list), self)

                self._line_mov_list.append(line_mov)

            canvas.is_line_mov = True
            canvas.last_z_value += 1
            self.parentItem().setZValue(canvas.last_z_value)

        item = None
        items = canvas.scene.items(event.scenePos(), Qt.ContainsItemShape,
                                   Qt.AscendingOrder)
        for i in range(len(items)):
            if items[i].type() in (CanvasPortType, CanvasPortGroupType):
                if items[i] != self:
                    if not item:
                        item = items[i]
                    elif (items[i].parentItem().zValue()
                          > item.parentItem().zValue()):
                        item = items[i]

        if self._hover_item and self._hover_item != item:
            self._hover_item.setSelected(False)

        # if item has same port mode
        # verify we can use it for cut and paste connections
        if (item is not None
                and item.get_port_type() == self._port_type
                and item.get_port_mode() == self._port_mode):
            item_valid = False

            if (self._has_connections
                    and item.type() == CanvasPortGroupType
                    and len(item.get_port_ids_list()) == len(self._port_id_list)):
                for connection in canvas.connection_list:
                    if utils.connection_concerns(
                            connection, item.get_group_id(),
                            item.get_port_ids_list()):
                        break
                else:
                    item_valid = True

            if not item_valid:
                item = None

        if (item is not None
                and not self.is_connectable_to(
                    item, accept_same_port_mode=True)):
            # prevent connection from an out CV port to a non CV port input
            # because it is very dangerous for monitoring
            pass

        elif (item is not None
              and self._hover_item != item
              and item.get_port_type() == self._port_type):
            item.setSelected(True)

            if item == self._hover_item:
                # prevent unneeded operations
                pass

            elif item.type() == CanvasPortType:
                self._hover_item = item
                self.reset_dot_lines()
                self.reset_line_mov_positions()
                for line_mov in self._line_mov_list:
                    line_mov.set_destination_portgrp_pos(0, 1)

                self._dotcon_list.clear()

                for connection in canvas.connection_list:
                    if utils.connection_matches(
                            connection,
                            self._group_id, self._port_id_list,
                            self._hover_item.get_group_id(),
                            [self._hover_item.get_port_id()]):
                        self._dotcon_list.append(connection)

                if len(self._dotcon_list) == len(self._port_id_list):
                    for connection in self._dotcon_list:
                        connection.widget.ready_to_disc = True
                        connection.widget.update_line_gradient()
                    for line_mov in self._line_mov_list:
                        line_mov.ready_to_disc = True

            elif item.type() == CanvasPortGroupType:
                self._hover_item = item
                self.reset_dot_lines()
                self.reset_line_mov_positions()

                if item.get_port_mode() == self._port_mode:
                    for connection in canvas.connection_list:
                        if utils.connection_concerns(
                                connection,
                                self._group_id, self._port_id_list):
                            connection.widget.ready_to_disc = True
                            connection.widget.update_line_gradient()
                            self._dotcon_list.append(connection)

                    for line_mov in self._line_mov_list:
                        line_mov.ready_to_disc = True
                else:
                    if (self._hover_item.get_port_list_len()
                            <= len(self._line_mov_list)):
                        for i in range(len(self._line_mov_list)):
                            line_mov = self._line_mov_list[i]
                            line_mov.set_destination_portgrp_pos(
                                i % self._hover_item.get_port_list_len(),
                                self._hover_item.get_port_list_len())
                    else:
                        start_n_linemov = len(self._line_mov_list)

                        for i in range(self._hover_item.get_port_list_len()):
                            if i < start_n_linemov:
                                line_mov = self._line_mov_list[i]
                                line_mov.set_destination_portgrp_pos(
                                    i, self._hover_item.get_port_list_len())
                            else:
                                port_posinportgrp = i % len(self._port_id_list)
                                line_mov  = CanvasBezierLineMov(
                                    self._port_mode,
                                    self._port_type,
                                    port_posinportgrp,
                                    self._hover_item.get_port_list_len(),
                                    self)

                                line_mov.set_destination_portgrp_pos(
                                    i, self._hover_item.get_port_list_len())
                                self._line_mov_list.append(line_mov)

                    self._dotcon_list.clear()
                    symetric_con_list = []
                    for portself_id in self._port_id_list:
                        for porthover_id in self._hover_item.get_port_ids_list():
                            for connection in canvas.connection_list:
                                if utils.connection_matches(
                                        connection,
                                        self._group_id, [portself_id],
                                        self._hover_item.get_group_id(),
                                        [porthover_id]):
                                    if (self._port_id_list.index(portself_id)
                                        % len(self._hover_item.get_port_ids_list())
                                            == (self._hover_item.get_port_ids_list().index(porthover_id)
                                                % len(self._port_id_list))):
                                        self._dotcon_list.append(connection)
                                        symetric_con_list.append(connection)
                                    else:
                                        self._dotcon_list.append(connection)
                                        connection.widget.ready_to_disc = True
                                        connection.widget.update_line_gradient()

                    biggest_list = self._hover_item.get_port_ids_list()
                    if (len(self._port_id_list)
                            >= len(self._hover_item.get_port_ids_list())):
                        biggest_list = self._port_id_list

                    if len(symetric_con_list) == len(biggest_list):
                        for connection in self._dotcon_list:
                            connection.widget.ready_to_disc = True
                            connection.widget.update_line_gradient()
                        for line_mov in self._line_mov_list:
                            line_mov.ready_to_disc = True
        else:
            if item != self._hover_item:
                self._hover_item = None
                self._last_rclick_item = None
                self.reset_dot_lines()
                self.reset_line_mov_positions()

        for line_mov in self._line_mov_list:
            line_mov.update_line_pos(event.scenePos())
        return event.accept()

        QGraphicsItem.mouseMoveEvent(self, event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self._mouse_down:

                for line_mov in self._line_mov_list:
                    item = line_mov
                    canvas.scene.removeItem(item)
                    del item
                self._line_mov_list.clear()

                for connection in canvas.connection_list:
                    if utils.connection_concerns(connection, self._group_id, self._port_id_list):
                        connection.widget.locked = False

                if self._hover_item:
                    if (self._last_rclick_item != self._hover_item
                            and time.time() > self._r_click_time + 0.3):
                        self._connect_to_hover()
                    canvas.scene.clearSelection()

                elif self._last_rclick_item:
                    canvas.scene.clearSelection()

            if self._cursor_moving:
                self.setCursor(QCursor(Qt.ArrowCursor))

            self._hover_item = None
            self._mouse_down = False
            self._cursor_moving = False
            canvas.is_line_mov = False
        QGraphicsItem.mouseReleaseEvent(self, event)

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

    def itemChange(self, change, value: bool):
        if change == QGraphicsItem.ItemSelectedHasChanged:
            for connection in canvas.connection_list:
                if utils.connection_concerns(
                        connection, self._group_id, self._port_id_list):
                    connection.widget.set_line_selected(value)

        return QGraphicsItem.itemChange(self, change, value)

    def boundingRect(self):
        if self._port_mode == PORT_MODE_INPUT:
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
        
        if self._port_type == PORT_TYPE_AUDIO_JACK:
            theme = theme.audio
        elif self._port_type == PORT_TYPE_MIDI_JACK:
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

        if self._port_mode == PORT_MODE_INPUT:
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

        elif self._port_mode == PORT_MODE_OUTPUT:
            text_pos = QPointF(
                9, 12 + (canvas.theme.port_height * (len(self._port_id_list) -1)/2))

            poly_locx[0] = self._portgrp_width + 12 \
                            - self._ports_width - lineHinting
            poly_locx[1] = 7 + lineHinting
            poly_locx[2] = 0 + lineHinting
            poly_locx[3] = 7 + lineHinting
            poly_locx[4] = self._portgrp_width + 12 - self._ports_width - lineHinting

        else:
            qCritical("PatchCanvas::CanvasPortGroup.paint() - invalid port mode '%s'"
                      % port_mode2str(self._port_mode))
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

