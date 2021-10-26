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
import time

from PyQt5.QtCore import qCritical, Qt, QLineF, QPointF, QRectF, QTimer
from PyQt5.QtGui import (QCursor, QFont, QFontMetrics, QPainter, QPainterPath,
                         QPen, QPolygonF, QLinearGradient, QColor)
from PyQt5.QtWidgets import QGraphicsItem, QMenu, QApplication

# ------------------------------------------------------------------------------------------------------------
# Imports (Custom)

from . import (
    canvas,
    features,
    options,
    port_mode2str,
    port_type2str,
    CanvasPortType,
    CanvasPortGroupType,
    ANTIALIASING_FULL,
    ACTION_PORTGROUP_REMOVE,
    ACTION_PORT_INFO,
    ACTION_PORT_RENAME,
    ACTION_PORTS_CONNECT,
    ACTION_PORTS_DISCONNECT,
    PORT_MODE_INPUT,
    PORT_MODE_OUTPUT,
    PORT_TYPE_AUDIO_JACK,
    PORT_TYPE_MIDI_ALSA,
    PORT_TYPE_MIDI_JACK,
    PORT_TYPE_PARAMETER,
)

from .canvasbezierlinemov import CanvasBezierLineMov
from .canvaslinemov import CanvasLineMov
from .theme import Theme
from .connect_menu import MainPortContextMenu
from .utils import (CanvasGetFullPortName, CanvasGetPortConnectionList,
                    CanvasGetPortGroupPosition, CanvasGetPortPrintName,
                    CanvasGetPortGroupName, CanvasGetPortGroupFullName,
                    CanvasConnectionMatches, CanvasConnectionConcerns,
                    CanvasCallback, CanvasConnectPorts)

# ------------------------------------------------------------------------------------------------------------
_translate = QApplication.translate


class CanvasPortGroup(QGraphicsItem):
    def __init__(self, group_id, portgrp_id, port_mode,
                 port_type, port_id_list, parent):
        QGraphicsItem.__init__(self)
        self.setParentItem(parent)

        # Save Variables, useful for later
        self.m_portgrp_id = portgrp_id
        self.m_port_mode = port_mode
        self.m_port_type = port_type
        self.m_port_id_list = port_id_list
        self.m_group_id = group_id

        # Base Variables
        self.m_portgrp_width  = 15
        self.m_portgrp_height = canvas.theme.port_height
        self.m_portgrp_font = QFont()
        self.m_portgrp_font.setFamily(canvas.theme.port_font_name)
        self.m_portgrp_font.setPixelSize(canvas.theme.port_font_size)
        self.m_portgrp_font.setWeight(canvas.theme.port_font_state)

        self.m_line_mov_list = []
        self.m_dotcon_list = []
        self.m_last_rclick_item = None
        self.m_r_click_time = 0
        self.m_hover_item = None
        self.m_has_connections = False

        self.m_mouse_down = False
        self.m_cursor_moving = False
        self.setFlags(QGraphicsItem.ItemIsSelectable)

    def getPortGroupId(self):
        return self.m_portgrp_id

    def getPortMode(self):
        return self.m_port_mode

    def getPortType(self):
        return self.m_port_type

    def isAlternate(self):
        return False

    def is_connectable_to(self, other, accept_same_port_mode=False)->bool:
        if self.m_port_type != other.getPortType():
            return False

        if not accept_same_port_mode:
            if self.m_port_mode == other.getPortMode():
                return False

        if self.m_port_type == PORT_TYPE_AUDIO_JACK:
            if other.getPortMode() == self.m_port_mode:
                return bool(self.isAlternate() == other.isAlternate())
            # absolutely forbidden to connect an output CV port
            # to an input audio port.
            # It could destroy material.
            if self.m_port_mode == PORT_MODE_OUTPUT:
                if self.isAlternate():
                    return other.isAlternate()
                return True

            if self.m_port_mode == PORT_MODE_INPUT:
                if self.isAlternate():
                    return True
                return not other.isAlternate()

        return True

    def getGroupId(self):
        return self.m_group_id

    def getPortWidth(self):
        return self.m_portgrp_width

    def getPortGroupWidth(self):
        return self.m_portgrp_width

    def getPortGroupHeight(self):
        return self.m_port_height

    def getPortsList(self):
        return self.m_port_id_list

    def getPortLength(self):
        return len(self.m_port_id_list)

    def type(self):
        return CanvasPortGroupType

    def setPortGroupWidth(self, portgrp_width):
        if portgrp_width < self.m_portgrp_width:
            QTimer.singleShot(0, canvas.scene.update)

        self.m_portgrp_width = portgrp_width
        self.update()

    def resetDotLines(self):
        for connection in self.m_dotcon_list:
            if connection.widget.isReadyToDisc():
                connection.widget.setReadyToDisc(False)
                connection.widget.updateLineGradient()

        for line_mov in self.m_line_mov_list:
            line_mov.setReadyToDisc(False)
        self.m_dotcon_list.clear()

    def SplitToMonos(self):
        CanvasCallback(ACTION_PORTGROUP_REMOVE,
                       self.m_group_id, self.m_portgrp_id, "")

    def ConnectToHover(self):
        if self.m_hover_item:
            if self.m_hover_item.type() == CanvasPortType:
                hover_port_id_list = [self.m_hover_item.getPortId()]
            elif self.m_hover_item.type() == CanvasPortGroupType:
                hover_port_id_list = self.m_hover_item.getPortsList()

            if not hover_port_id_list:
                return

            hover_group_id = self.m_hover_item.getGroupId()
            con_list = []
            ports_connected_list = []

            maxportgrp = max(len(self.m_port_id_list),
                             len(hover_port_id_list))

            if self.m_hover_item.getPortMode() == self.m_port_mode:
                for i in range(len(self.m_port_id_list)):
                    for connection in canvas.connection_list:
                        if CanvasConnectionConcerns(
                                connection, self.m_group_id,
                                [self.m_port_id_list[i]]):
                            canvas.callback(
                                ACTION_PORTS_DISCONNECT,
                                connection.connection_id,
                                0, '')

                            for j in range(len(hover_port_id_list)):
                                if len(hover_port_id_list) >= len(self.m_port_id_list):
                                    if j % len(self.m_port_id_list) != i:
                                        continue
                                else:
                                    if i % len(hover_port_id_list) != j:
                                        continue

                                if self.m_port_mode == PORT_MODE_OUTPUT:
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


            for i in range(len(self.m_port_id_list)):
                port_id = self.m_port_id_list[i]
                for j in range(len(hover_port_id_list)):
                    hover_port_id = hover_port_id_list[j]

                    for connection in canvas.connection_list:
                        if CanvasConnectionMatches(connection,
                                        self.m_group_id, [port_id],
                                        hover_group_id, [hover_port_id]):
                            if (i % len(hover_port_id_list)
                                    == j % len(self.m_port_id_list)):
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
                for i in range(len(self.m_port_id_list)):
                    port_id = self.m_port_id_list[i]
                    for j in range(len(hover_port_id_list)):
                        hover_port_id = hover_port_id_list[j]
                        if (i % len(hover_port_id_list)
                                == j % len(self.m_port_id_list)):
                            if not [port_id, hover_port_id] in ports_connected_list:
                                if self.m_port_mode == PORT_MODE_OUTPUT:
                                    conn = "%i:%i:%i:%i" % (
                                        self.m_group_id, port_id,
                                        hover_group_id, hover_port_id)
                                else:
                                    conn = "%i:%i:%i:%i" % (
                                        hover_group_id, hover_port_id,
                                        self.m_group_id, port_id)
                                canvas.callback(ACTION_PORTS_CONNECT, 0, 0, conn)

    def resetLineMovPositions(self):
        for i in range(len(self.m_line_mov_list)):
            line_mov = self.m_line_mov_list[i]
            if i < self.getPortLength():
                line_mov.setDestinationPortGroupPosition(i, self.getPortLength())
            else:
                item = line_mov
                canvas.scene.removeItem(item)
                del item

        while len(self.m_line_mov_list) < self.getPortLength():
            if options.use_bezier_lines:
                line_mov = CanvasBezierLineMov(self.m_port_mode, self.m_port_type,
                                               len(self.m_line_mov_list),
                                               self.getPortLength(), self)
            else:
                line_mov = CanvasLineMov(self.m_port_mode, self.m_port_type,
                            len(self.m_line_mov_list), self.getPortLength(), self)
            self.m_line_mov_list.append(line_mov)

        self.m_line_mov_list = self.m_line_mov_list[:self.getPortLength()]

    def hoverEnterEvent(self, event):
        if options.auto_select_items:
            self.setSelected(True)
        QGraphicsItem.hoverEnterEvent(self, event)

    def hoverLeaveEvent(self, event):
        if options.auto_select_items:
            self.setSelected(False)
        QGraphicsItem.hoverLeaveEvent(self, event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.m_hover_item = None
            self.m_mouse_down = True
            self.m_cursor_moving = False

            for connection in canvas.connection_list:
                if CanvasConnectionConcerns(
                        connection, self.m_group_id, self.m_port_id_list):
                    self.m_has_connections = True
                    break
            else:
                self.m_has_connections = False

        elif event.button() == Qt.RightButton:
            if canvas.is_line_mov:
                if self.m_hover_item:
                    self.ConnectToHover()
                    self.m_last_rclick_item = self.m_hover_item
                    self.m_r_click_time = time.time()

                    for line_mov in self.m_line_mov_list:
                        line_mov.toggleReadyToDisc()
                        line_mov.updateLinePos(event.scenePos())
        QGraphicsItem.mousePressEvent(self, event)

    def mouseMoveEvent(self, event):
        if not self.m_mouse_down:
            QGraphicsItem.mouseMoveEvent(self, event)
            return

        if not self.m_cursor_moving:
            self.setCursor(QCursor(Qt.CrossCursor))
            self.m_cursor_moving = True

            for connection in canvas.connection_list:
                if CanvasConnectionConcerns(connection,
                                self.m_group_id, self.m_port_id_list):
                    connection.widget.setLocked(True)

        if not self.m_line_mov_list:
            self.m_last_rclick_item = None
            canvas.last_z_value += 1
            self.setZValue(canvas.last_z_value)
            canvas.last_z_value += 1

            for port in canvas.port_list:
                if (port.group_id == self.m_group_id
                        and port.port_id in self.m_port_id_list):
                    port.widget.setZValue(canvas.last_z_value)

            for i in range(len(self.m_port_id_list)):
                if options.use_bezier_lines:
                    line_mov  = CanvasBezierLineMov(self.m_port_mode,
                        self.m_port_type, i, len(self.m_port_id_list), self)
                else:
                    line_mov  = CanvasLineMov(self.m_port_mode,
                        self.m_port_type, i, len(self.m_port_id_list), self)

                self.m_line_mov_list.append(line_mov)

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

        if self.m_hover_item and self.m_hover_item != item:
            self.m_hover_item.setSelected(False)

        # if item has same port mode
        # verify we can use it for cut and paste connections
        if (item is not None
                and item.getPortType() == self.m_port_type
                and item.getPortMode() == self.m_port_mode):
            item_valid = False

            if (self.m_has_connections
                    and item.type() == CanvasPortGroupType
                    and len(item.getPortsList()) == len(self.m_port_id_list)):
                for connection in canvas.connection_list:
                    if CanvasConnectionConcerns(
                            connection, item.getGroupId(),
                            item.getPortsList()):
                        break
                else:
                    item_valid = True

            if not item_valid:
                item = None

        if item is not None and not self.is_connectable_to(
            item, accept_same_port_mode=True):
            # prevent connection from an out CV port to a non CV port input
            # because it is very dangerous for monitoring
            pass

        elif (item is not None
                and self.m_hover_item != item
                and item.getPortType() == self.m_port_type):
            item.setSelected(True)

            if item == self.m_hover_item:
                # prevent unneeded operations
                pass

            elif item.type() == CanvasPortType:
                self.m_hover_item = item
                self.resetDotLines()
                self.resetLineMovPositions()
                for line_mov in self.m_line_mov_list:
                    line_mov.setDestinationPortGroupPosition(0, 1)

                self.m_dotcon_list.clear()

                for connection in canvas.connection_list:
                    if CanvasConnectionMatches(
                            connection,
                            self.m_group_id, self.m_port_id_list,
                            self.m_hover_item.getGroupId(),
                            [self.m_hover_item.getPortId()]):
                        self.m_dotcon_list.append(connection)

                if len(self.m_dotcon_list) == len(self.m_port_id_list):
                    for connection in self.m_dotcon_list:
                        connection.widget.setReadyToDisc(True)
                        connection.widget.updateLineGradient()
                    for line_mov in self.m_line_mov_list:
                        line_mov.setReadyToDisc(True)

            elif item.type() == CanvasPortGroupType:
                self.m_hover_item = item
                self.resetDotLines()
                self.resetLineMovPositions()

                if item.getPortMode() == self.m_port_mode:
                    for connection in canvas.connection_list:
                        if CanvasConnectionConcerns(
                                connection,
                                self.m_group_id, self.m_port_id_list):
                            connection.widget.setReadyToDisc(True)
                            connection.widget.updateLineGradient()
                            self.m_dotcon_list.append(connection)

                    for line_mov in self.m_line_mov_list:
                        line_mov.setReadyToDisc(True)
                else:
                    if (self.m_hover_item.getPortLength()
                            <= len(self.m_line_mov_list)):
                        for i in range(len(self.m_line_mov_list)):
                            line_mov = self.m_line_mov_list[i]
                            line_mov.setDestinationPortGroupPosition(
                                i % self.m_hover_item.getPortLength(),
                                self.m_hover_item.getPortLength())
                    else:
                        start_n_linemov = len(self.m_line_mov_list)

                        for i in range(self.m_hover_item.getPortLength()):
                            if i < start_n_linemov:
                                line_mov = self.m_line_mov_list[i]
                                line_mov.setDestinationPortGroupPosition(
                                    i, self.m_hover_item.getPortLength())
                            else:
                                port_posinportgrp = i % len(self.m_port_id_list)
                                if options.use_bezier_lines:
                                    line_mov  = CanvasBezierLineMov(
                                        self.m_port_mode,
                                        self.m_port_type,
                                        port_posinportgrp,
                                        self.m_hover_item.getPortLength(),
                                        self)
                                else:
                                    line_mov  = CanvasLineMov(
                                        self.m_port_mode,
                                        self.m_port_type,
                                        port_posinportgrp,
                                        self.m_hover_item.getPortLength(),
                                        self)

                                line_mov.setDestinationPortGroupPosition(
                                    i, self.m_hover_item.getPortLength())
                                self.m_line_mov_list.append(line_mov)

                    self.m_dotcon_list.clear()
                    symetric_con_list = []
                    for portself_id in self.m_port_id_list:
                        for porthover_id in self.m_hover_item.getPortsList():
                            for connection in canvas.connection_list:
                                if CanvasConnectionMatches(
                                        connection,
                                        self.m_group_id, [portself_id],
                                        self.m_hover_item.getGroupId(),
                                        [porthover_id]):
                                    if (self.m_port_id_list.index(portself_id)
                                                % len(self.m_hover_item.getPortsList())
                                            == (self.m_hover_item.getPortsList().index(porthover_id)
                                                % len(self.m_port_id_list))):
                                        self.m_dotcon_list.append(connection)
                                        symetric_con_list.append(connection)
                                    else:
                                        self.m_dotcon_list.append(connection)
                                        connection.widget.setReadyToDisc(True)
                                        connection.widget.updateLineGradient()

                    biggest_list = self.m_hover_item.getPortsList()
                    if (len(self.m_port_id_list)
                            >= len(self.m_hover_item.getPortsList())):
                        biggest_list = self.m_port_id_list

                    if len(symetric_con_list) == len(biggest_list):
                        for connection in self.m_dotcon_list:
                            connection.widget.setReadyToDisc(True)
                            connection.widget.updateLineGradient()
                        for line_mov in self.m_line_mov_list:
                            line_mov.setReadyToDisc(True)
        else:
            if item != self.m_hover_item:
                self.m_hover_item = None
                self.m_last_rclick_item = None
                self.resetDotLines()
                self.resetLineMovPositions()

        for line_mov in self.m_line_mov_list:
            line_mov.updateLinePos(event.scenePos())
        return event.accept()

        QGraphicsItem.mouseMoveEvent(self, event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self.m_mouse_down:

                for line_mov in self.m_line_mov_list:
                    item = line_mov
                    canvas.scene.removeItem(item)
                    del item
                self.m_line_mov_list.clear()

                for connection in canvas.connection_list:
                    if CanvasConnectionConcerns(connection, self.m_group_id, self.m_port_id_list):
                        connection.widget.setLocked(False)

                if self.m_hover_item:
                    if (self.m_last_rclick_item != self.m_hover_item
                            and time.time() > self.m_r_click_time + 0.3):
                        self.ConnectToHover()
                    canvas.scene.clearSelection()

                elif self.m_last_rclick_item:
                    canvas.scene.clearSelection()

            if self.m_cursor_moving:
                self.setCursor(QCursor(Qt.ArrowCursor))

            self.m_hover_item = None
            self.m_mouse_down = False
            self.m_cursor_moving = False
            canvas.is_line_mov = False
        QGraphicsItem.mouseReleaseEvent(self, event)


    def contextMenuEvent(self, event):
        if canvas.is_line_mov:
            return

        canvas.scene.clearSelection()
        self.setSelected(True)

        menu = MainPortContextMenu(self.m_group_id, 0, self.m_portgrp_id)

        act_x_setasmono = menu.addAction(
            _translate('patchbay', "Split to Monos"))
        act_selected = menu.exec_(event.screenPos())

        if act_selected == act_x_setasmono:
            self.SplitToMonos()

        event.accept()

    def setPortGroupSelected(self, yesno):
        for connection in canvas.connection_list:
            if CanvasConnectionConcerns(connection,
                            self.m_group_id, self.m_port_id_list):
                connection.widget.setLineSelected(yesno)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemSelectedHasChanged:
            self.setPortGroupSelected(value)
        return QGraphicsItem.itemChange(self, change, value)

    def boundingRect(self):
        self.m_portgrp_width = self.getPortGroupWidth()
        if self.m_port_mode == PORT_MODE_INPUT:
            return QRectF(canvas.theme.port_in_portgrp_width, 0,
                          self.m_portgrp_width + 12 - canvas.theme.port_in_portgrp_width,
                          canvas.theme.port_height * len(self.m_port_id_list))
        else:
            return QRectF(0, 0,
                          self.m_portgrp_width + 12 - canvas.theme.port_in_portgrp_width,
                          canvas.theme.port_height * len(self.m_port_id_list))

    def paint(self, painter, option, widget):
        painter.save()
        painter.setRenderHint(
            QPainter.Antialiasing, bool(options.antialiasing == ANTIALIASING_FULL))

        lineHinting = canvas.theme.port_audio_jack_pen.widthF() / 2

        poly_locx = [0, 0, 0, 0, 0]
        poly_corner_xhinting = (
            float(canvas.theme.port_height)/2) % floor(float(canvas.theme.port_height)/2)
        if poly_corner_xhinting == 0:
            poly_corner_xhinting = 0.5 * (1 - 7 / (float(canvas.theme.port_height)/2))

        if self.m_port_mode == PORT_MODE_INPUT:
            port_width = canvas.theme.port_in_portgrp_width

            for port in canvas.port_list:
                if port.port_id in self.m_port_id_list:
                    port_print_name = CanvasGetPortPrintName(
                        port.group_id, port.port_id, self.m_portgrp_id)
                    port_in_p_width = QFontMetrics(self.m_portgrp_font).width(port_print_name) + 3
                    port_width = max(port_width, port_in_p_width)

            text_pos = QPointF(
                port_width + 3,
                canvas.theme.port_text_ypos
                    + (canvas.theme.port_height * (len(self.m_port_id_list) -1)/2))

            if canvas.theme.port_mode == Theme.THEME_PORT_POLYGON:
                poly_locx[0] = canvas.theme.port_in_portgrp_width - lineHinting
                poly_locx[1] = self.m_portgrp_width + 3 + lineHinting
                poly_locx[2] = self.m_portgrp_width + 10 + lineHinting
                poly_locx[3] = self.m_portgrp_width + 3 + lineHinting
                poly_locx[4] = canvas.theme.port_in_portgrp_width - lineHinting
            elif canvas.theme.port_mode == Theme.THEME_PORT_SQUARE:
                poly_locx[0] = canvas.theme.port_in_portgrp_width - lineHinting
                poly_locx[1] = self.m_portgrp_width + 5 + lineHinting
                poly_locx[2] = self.m_portgrp_width + 5 + lineHinting
                poly_locx[3] = self.m_portgrp_width + 5 + lineHinting
                poly_locx[4] = canvas.theme.port_in_portgrp_width - lineHinting
            else:
                qCritical("PatchCanvas::CanvasPortGroup.paint() - invalid theme port mode '%s'"
                          % canvas.theme.port_mode)
                return

        elif self.m_port_mode == PORT_MODE_OUTPUT:
            text_pos = QPointF(9, canvas.theme.port_text_ypos \
                       + (canvas.theme.port_height * (len(self.m_port_id_list) -1)/2))

            if canvas.theme.port_mode == Theme.THEME_PORT_POLYGON:
                poly_locx[0] = self.m_portgrp_width + 12 \
                               - canvas.theme.port_in_portgrp_width - lineHinting
                poly_locx[1] = 7 + lineHinting
                poly_locx[2] = 0 + lineHinting
                poly_locx[3] = 7 + lineHinting
                poly_locx[4] = self.m_portgrp_width + 12 - canvas.theme.port_in_portgrp_width - lineHinting
            elif canvas.theme.port_mode == Theme.THEME_PORT_SQUARE:
                poly_locx[0] = self.m_portgrp_width + 12 - canvas.theme.port_in_portgrp_width - lineHinting
                poly_locx[1] = 5 + lineHinting
                poly_locx[2] = 5 + lineHinting
                poly_locx[3] = 5 + lineHinting
                poly_locx[4] = self.m_portgrp_width + 12 - canvas.theme.port_in_portgrp_width - lineHinting
            else:
                qCritical("PatchCanvas::CanvasPortGroup.paint() - invalid theme port mode '%s'" % canvas.theme.port_mode)
                return

        else:
            qCritical("PatchCanvas::CanvasPortGroup.paint() - invalid port mode '%s'" % port_mode2str(self.m_port_mode))
            return

        poly_pen = canvas.theme.portgrp_audio_jack_pen_sel  if self.isSelected() else canvas.theme.portgrp_audio_jack_pen
        text_pen = canvas.theme.port_audio_jack_text_sel if self.isSelected() else canvas.theme.port_audio_jack_text

        color = canvas.theme.portgrp_audio_jack_bg_sel if self.isSelected() else canvas.theme.portgrp_audio_jack_bg
        light_color = color.lighter(108)
        dark_color = color.darker(109)

        portgrp_gradient = QLinearGradient(0, 0, 0, self.m_portgrp_height * 2)
        portgrp_gradient.setColorAt(0, dark_color)
        portgrp_gradient.setColorAt(0.5, light_color)
        portgrp_gradient.setColorAt(1, dark_color)

        polygon  = QPolygonF()
        polygon += QPointF(poly_locx[0], lineHinting)
        polygon += QPointF(poly_locx[1], lineHinting)
        polygon += QPointF(poly_locx[2], float(canvas.theme.port_height / 2) )
        polygon += QPointF(poly_locx[2], float(canvas.theme.port_height * (len(self.m_port_id_list) - 1/2)) )
        polygon += QPointF(poly_locx[3], canvas.theme.port_height * len(self.m_port_id_list) - lineHinting)
        polygon += QPointF(poly_locx[4], canvas.theme.port_height * len(self.m_port_id_list) - lineHinting)

        if canvas.theme.port_bg_pixmap:
            portRect = polygon.boundingRect()
            portPos  = portRect.topLeft()
            painter.drawTiledPixmap(portRect, canvas.theme.port_bg_pixmap, portPos)
        else:
            painter.setBrush(portgrp_gradient)

        painter.setPen(poly_pen)
        painter.drawPolygon(polygon)

        painter.setPen(text_pen)
        painter.setFont(self.m_portgrp_font)
        portgrp_name = CanvasGetPortGroupName(self.m_group_id,
                                              self.m_port_id_list)
        painter.drawText(text_pos, portgrp_name)

        painter.restore()

