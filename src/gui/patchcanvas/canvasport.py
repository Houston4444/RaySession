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

from PyQt5.QtCore import qCritical, Qt, QLineF, QPointF, QRectF, QTimer, QSizeF
from PyQt5.QtGui import (
    QCursor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPolygonF,
    QLinearGradient, QColor, QRadialGradient, QIcon)
from PyQt5.QtWidgets import (
    QGraphicsItem, QMenu, QCheckBox, QWidgetAction, QGraphicsEllipseItem,
    QApplication)

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
    ACTION_PORTGROUP_ADD,
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
from .utils import (
    CanvasGetFullPortName,
    CanvasGetPortGroupPortList,
    CanvasGetPortConnectionList,
    CanvasGetPortGroupName,
    CanvasGetPortGroupPosition,
    CanvasGetPortPrintName,
    CanvasConnectionMatches,
    CanvasConnectionConcerns,
    CanvasGetGroupIcon,
    CanvasConnectPorts,
    CanvasCallback)

# ------------------------------------------------------------------------------------------------------------
_translate = QApplication.translate

class CanvasPort(QGraphicsItem):
    def __init__(self, group_id, port_id, port_name, port_mode,
                 port_type, is_alternate, parent):
        QGraphicsItem.__init__(self)
        self.setParentItem(parent)

        # Save Variables, useful for later
        self.m_group_id = group_id
        self.m_port_id = port_id
        self.m_port_mode = port_mode
        self.m_port_type = port_type
        self.m_port_name = port_name
        self.m_portgrp_id = 0
        self.m_is_alternate = is_alternate
        self.m_print_name = port_name

        # Base Variables
        self.m_port_width = 15
        self.m_port_height = canvas.theme.port_height
        self.m_port_font = QFont()
        self.m_port_font.setFamily(canvas.theme.port_font_name)
        self.m_port_font.setPixelSize(canvas.theme.port_font_size)
        self.m_port_font.setWeight(canvas.theme.port_font_state)

        # needed for line mov
        self.m_line_mov_list = []
        self.m_last_rclick_item = None
        self.m_r_click_time = 0
        self.m_dotcon_list = []
        self.m_hover_item = None
        self.m_mouse_down = False
        self.m_cursor_moving = False
        self.m_has_connections = False

        self.setFlags(QGraphicsItem.ItemIsSelectable)

        if options.auto_select_items:
            self.setAcceptHoverEvents(True)

    def getGroupId(self):
        return self.m_group_id

    def getPortId(self):
        return self.m_port_id

    def getPortMode(self):
        return self.m_port_mode

    def getPortType(self):
        return self.m_port_type

    def isAlternate(self):
        return self.m_is_alternate

    def getPortName(self):
        return self.m_port_name

    def getPortGroupId(self):
        return self.m_portgrp_id

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

    def getFullPortName(self):
        return "%s:%s" % (self.parentItem().getGroupName(), self.m_port_name)

    def getPortWidth(self):
        return self.m_port_width

    def getPortHeight(self):
        return self.m_port_height

    def getPortGroupPosition(self):
        return CanvasGetPortGroupPosition(self.m_group_id, self.m_port_id,
                                          self.m_portgrp_id)

    def setPortGroupId(self, portgrp_id):
        self.m_portgrp_id = portgrp_id

    def setPortName(self, port_name):
        if QFontMetrics(self.m_port_font).width(port_name) < QFontMetrics(self.m_port_font).width(self.m_port_name):
            QTimer.singleShot(0, canvas.scene.update)

        self.m_port_name = port_name
        self.update()

    def get_width_for_text(self, text: str):
        return QFontMetrics(self.m_port_font).width(text)

    def reduce_print_text(self, print_text: str):
        pass

    def setPortWidth(self, port_width):
        #if port_width < self.m_port_width:
            #QTimer.singleShot(0, canvas.scene.update)

        self.m_port_width = port_width
        #self.update()

    def set_print_name(self, print_name:str, width_limited: int):
        self.m_print_name = print_name

        if width_limited:
            sizer = QFontMetrics(self.m_port_font)

            if sizer.width(self.m_print_name) > width_limited:
                name_len = len(self.m_print_name)
                middle = int(name_len / 2)
                left_text = self.m_print_name[:middle]
                middle_text = '[..]'
                right_text = self.m_print_name[middle + 1:]
                left_size = sizer.width(left_text)
                middle_size = sizer.width(middle_text)
                right_size = sizer.width(right_text)

                while left_size + middle_size + right_size > width_limited:
                    if left_size > right_size:
                        left_text = left_text[:-1]
                        left_size = sizer.width(left_text)
                    else:
                        right_text = right_text[1:]
                        right_size = sizer.width(right_text)
                        
                    if not (left_text or right_text):
                        break

                self.m_print_name = left_text + middle_text + right_text

    def get_text_width(self):
        return QFontMetrics(self.m_port_font).width(self.m_print_name)

    def resetLineMovPositions(self):
        for i in range(len(self.m_line_mov_list)):
            line_mov = self.m_line_mov_list[i]
            if i < 1:
                line_mov.setDestinationPortGroupPosition(i, 1)
            else:
                item = line_mov
                canvas.scene.removeItem(item)
                del item

        self.m_line_mov_list = self.m_line_mov_list[:1]

    def resetDotLines(self):
        for connection in self.m_dotcon_list:
            if connection.widget.isReadyToDisc():
                connection.widget.setReadyToDisc(False)
                connection.widget.updateLineGradient()

        for line_mov in self.m_line_mov_list:
            line_mov.setReadyToDisc(False)
        self.m_dotcon_list.clear()

    def SetAsStereo(self, port_id):
        port_id_list = []
        for port in canvas.port_list:
            if port.port_id in (self.m_port_id, port_id):
                port_id_list.append(port.port_id)

        data = "%i:%i:%i:%i:%i" % (self.m_group_id,
                                   self.m_port_mode, self.m_port_type,
                                   port_id_list[0], port_id_list[1])

        CanvasCallback(ACTION_PORTGROUP_ADD, 0, 0, data)

    def set_paint_attributes(self, print_name:str, port_width:int):
        pass

    def connectToHover(self):
        if self.m_hover_item:
            hover_port_id_list = []

            if self.m_hover_item.type() == CanvasPortType:
                hover_port_id_list = [ self.m_hover_item.getPortId() ]
            elif self.m_hover_item.type() == CanvasPortGroupType:
                hover_port_id_list = self.m_hover_item.getPortsList()

            hover_group_id = self.m_hover_item.getGroupId()
            con_list = []
            ports_connected_list = []

            # cut and paste connections directly by attempt to connect
            # one port to another with same type and mode
            if self.m_hover_item.getPortMode() == self.m_port_mode:
                for connection in canvas.connection_list:
                    if CanvasConnectionConcerns(
                            connection, self.m_group_id, [self.m_port_id]):
                        canvas.callback(ACTION_PORTS_DISCONNECT,
                                        connection.connection_id, 0, '')

                        con_group_id = connection.group_out_id
                        con_port_id = connection.port_out_id
                        if self.m_port_mode == PORT_MODE_OUTPUT:
                            con_group_id = connection.group_in_id
                            con_port_id = connection.port_in_id

                        for hover_port_id in hover_port_id_list:
                            CanvasConnectPorts(con_group_id, con_port_id,
                                               hover_group_id, hover_port_id)
                return

            # FIXME clean this big if stuff
            for hover_port_id in hover_port_id_list:
                for connection in canvas.connection_list:
                    if CanvasConnectionMatches(connection,
                                    self.m_group_id, [self.m_port_id],
                                    hover_group_id, [hover_port_id]):
                        con_list.append(connection)
                        ports_connected_list.append(hover_port_id)

            if len(con_list) == len(hover_port_id_list):
                for connection in con_list:
                    canvas.callback(
                        ACTION_PORTS_DISCONNECT,
                        connection.connection_id, 0, "")
            else:
                for porthover_id in hover_port_id_list:
                    if not porthover_id in ports_connected_list:
                        if self.m_port_mode == PORT_MODE_OUTPUT:
                            conn = "%i:%i:%i:%i" % (
                                self.m_group_id, self.m_port_id,
                                hover_group_id, porthover_id)
                        else:
                            conn = "%i:%i:%i:%i" % (
                                hover_group_id, porthover_id,
                                self.m_group_id, self.m_port_id)
                        canvas.callback(ACTION_PORTS_CONNECT, '', '', conn)

    def type(self):
        return CanvasPortType

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
                        connection, self.m_group_id, [self.m_port_id]):
                    self.m_has_connections = True
                    break
            else:
                self.m_has_connections = False

        elif event.button() == Qt.RightButton:
            if canvas.is_line_mov:
                if self.m_hover_item:
                    self.m_r_click_time = time.time()
                    self.connectToHover()
                    self.m_last_rclick_item = self.m_hover_item

                    for line_mov in self.m_line_mov_list:
                        line_mov.toggleReadyToDisc()
                        line_mov.updateLinePos(event.scenePos())

                    for connection in self.m_dotcon_list:
                        if connection in canvas.connection_list:
                            connection.widget.setReadyToDisc(True)
                            connection.widget.updateLineGradient()

        QGraphicsItem.mousePressEvent(self, event)

    def mouseMoveEvent(self, event):
        if not self.m_mouse_down:
            QGraphicsItem.mouseMoveEvent(self, event)
            return

        event.accept()

        if not self.m_cursor_moving:
            self.setCursor(QCursor(Qt.CrossCursor))
            self.m_cursor_moving = True

            for connection in canvas.connection_list:
                if CanvasConnectionConcerns(connection,
                                self.m_group_id, [self.m_port_id]):
                    connection.widget.setLocked(True)

        if not self.m_line_mov_list:
            if options.use_bezier_lines:
                line_mov = CanvasBezierLineMov(self.m_port_mode,
                                               self.m_port_type, 0, 1, self)
            else:
                line_mov = CanvasLineMov(self.m_port_mode, self.m_port_type,
                                         0, 1, self)

            self.m_line_mov_list.append(line_mov)
            line_mov.setZValue(canvas.last_z_value)
            canvas.last_z_value += 1
            canvas.is_line_mov = True
            self.m_last_rclick_item = None
            self.parentItem().setZValue(canvas.last_z_value)

        item = None
        items = canvas.scene.items(event.scenePos(), Qt.ContainsItemShape,
                                   Qt.AscendingOrder)

        for _, itemx in enumerate(items):
            if not itemx.type() in (CanvasPortType, CanvasPortGroupType):
                continue
            if itemx == self:
                continue
            if (item is None
                    or itemx.parentItem().zValue() > item.parentItem().zValue()):
                item = itemx

        if self.m_hover_item and self.m_hover_item != item:
            self.m_hover_item.setSelected(False)

        if (item is not None
                  and item.getPortType() == self.m_port_type
                  and item.getPortMode() == self.m_port_mode):
            # check if item can cut/paste connections
            item_valid = False

            if self.m_has_connections:
                if item.type() == CanvasPortType:
                    for connection in canvas.connection_list:
                        if CanvasConnectionConcerns(
                                connection, item.getGroupId(),
                                [item.getPortId()]):
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
                and item.getPortType() == self.m_port_type):
            item.setSelected(True)

            if item == self.m_hover_item:
                pass

            elif item.type() == CanvasPortGroupType:
                self.m_hover_item = item
                self.resetLineMovPositions()
                self.resetDotLines()

                if len(self.m_line_mov_list) <= 1:
                    # make original line going to first port of the hover portgrp
                    for line_mov in self.m_line_mov_list:
                        line_mov.setDestinationPortGroupPosition(
                            0, self.m_hover_item.getPortLength())

                    port_pos, portgrp_len = CanvasGetPortGroupPosition(
                        self.m_group_id, self.m_port_id, self.m_portgrp_id)

                    # create one line for each port of the hover portgrp
                    for i in range(1, self.m_hover_item.getPortLength()):
                        if options.use_bezier_lines:
                            line_mov = CanvasBezierLineMov(
                                self.m_port_mode, self.m_port_type,
                                port_pos, portgrp_len, self)
                        else:
                            line_mov = CanvasLineMov(
                                self.m_port_mode, self.m_port_type,
                                port_pos, portgrp_len, self)

                        line_mov.setDestinationPortGroupPosition(
                            i, self.m_hover_item.getPortLength())
                        self.m_line_mov_list.append(line_mov)

                for connection in canvas.connection_list:
                    if CanvasConnectionMatches(
                            connection,
                            self.m_group_id, [self.m_port_id],
                            self.m_hover_item.getGroupId(),
                            self.m_hover_item.getPortsList()):
                        self.m_dotcon_list.append(connection)

                if (len(self.m_dotcon_list)
                        == len(self.m_hover_item.getPortsList())):
                    for connection in self.m_dotcon_list:
                        connection.widget.setReadyToDisc(True)
                        connection.widget.updateLineGradient()

                    for line_mov in self.m_line_mov_list:
                        line_mov.setReadyToDisc(True)

            elif item.type() == CanvasPortType:
                self.m_hover_item = item
                self.resetLineMovPositions()
                self.resetDotLines()

                if item.getPortMode() == self.m_port_mode:
                    # situation of cut and paste existing connections
                    for connection in canvas.connection_list:
                        if CanvasConnectionConcerns(
                                connection,
                                self.m_group_id, [self.m_port_id]):
                            connection.widget.setReadyToDisc(True)
                            connection.widget.updateLineGradient()
                            self.m_dotcon_list.append(connection)

                    for line_mov in self.m_line_mov_list:
                        line_mov.setReadyToDisc(True)
                else:
                    for connection in canvas.connection_list:
                        if CanvasConnectionMatches(
                                connection,
                                self.m_group_id, [self.m_port_id],
                                self.m_hover_item.getGroupId(),
                                [self.m_hover_item.getPortId()]):
                            for line_mov in self.m_line_mov_list:
                                line_mov.setReadyToDisc(True)

                            connection.widget.setReadyToDisc(True)
                            connection.widget.updateLineGradient()
                            self.m_dotcon_list.append(connection)

                        elif connection.widget.isReadyToDisc():
                            connection.widget.setReadyToDisc(False)
                            connection.widget.updateLineGradient()
        else:
            self.m_hover_item = None
            self.resetLineMovPositions()
            self.resetDotLines()
            self.m_last_rclick_item = None

        for line_mov in self.m_line_mov_list:
            line_mov.updateLinePos(event.scenePos())

        return event.accept()

        QGraphicsItem.mouseMoveEvent(self, event)

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton:
            QGraphicsItem.mouseReleaseEvent(self, event)
            return

        if self.m_mouse_down:
            if self.m_line_mov_list:
                for line_mov in self.m_line_mov_list:
                    item = line_mov
                    canvas.scene.removeItem(item)
                    del item
                self.m_line_mov_list.clear()

            for connection in canvas.connection_list:
                if CanvasConnectionConcerns(connection,
                            self.m_group_id, [self.m_port_id]):
                    connection.widget.setLocked(False)

            if self.m_hover_item:
                if (self.m_last_rclick_item != self.m_hover_item
                        and time.time() > self.m_r_click_time + 0.3):
                    self.connectToHover()

                canvas.scene.clearSelection()

            if self.m_last_rclick_item:
                canvas.scene.clearSelection()

        if self.m_cursor_moving:
            self.unsetCursor()

        self.m_hover_item = None
        self.m_mouse_down = False
        self.m_cursor_moving = False
        canvas.is_line_mov = False
        QGraphicsItem.mouseReleaseEvent(self, event)

    def contextMenuEvent(self, event):
        if canvas.is_line_mov:
            return

        event.accept()
        canvas.scene.clearSelection()
        self.setSelected(True)

        menu = MainPortContextMenu(self.m_group_id, self.m_port_id)

        act_x_sep_1 = menu.addSeparator()

        if (self.m_port_type == PORT_TYPE_AUDIO_JACK
                and not self.m_is_alternate
                and not self.m_portgrp_id):
            StereoMenu = QMenu(_translate('patchbay', "Set as Stereo with"), menu)
            menu.addMenu(StereoMenu)

            # get list of available mono ports settables as stereo with port
            port_cousin_list = []
            for port in canvas.port_list:
                if (port.port_type == PORT_TYPE_AUDIO_JACK
                        and port.group_id == self.m_group_id
                        and port.port_mode == self.m_port_mode
                        and not port.is_alternate):
                    port_cousin_list.append(port.port_id)

            selfport_index = port_cousin_list.index(self.m_port_id)
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
                    act_x_setasstereo.triggered.connect(canvas.qobject.SetasStereoWith)
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
            canvas.callback(ACTION_PORT_INFO, self.m_group_id, self.m_port_id, "")

        elif act_selected == act_x_rename:
            canvas.callback(ACTION_PORT_RENAME, self.m_group_id, self.m_port_id, "")

    def setPortSelected(self, yesno):
        for connection in canvas.connection_list:
            if CanvasConnectionConcerns(connection,
                            self.m_group_id, [self.m_port_id]):
                connection.widget.setLineSelected(yesno)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemSelectedHasChanged:
            self.setPortSelected(value)
        return QGraphicsItem.itemChange(self, change, value)

    def triggerDisconnect(self, conn_list=None):
        if not conn_list:
            conn_list = CanvasGetPortConnectionList(self.m_group_id, self.m_port_id)
        for conn_id, group_id, port_id in conn_list:
            canvas.callback(ACTION_PORTS_DISCONNECT, conn_id, 0, "")

    def boundingRect(self):
        if self.m_portgrp_id:
            if self.m_port_mode == PORT_MODE_INPUT:
                return QRectF(0, 0, self.m_port_width, self.m_port_height)
            else:
                return QRectF(12, 0,
                              self.m_port_width, self.m_port_height)
        else:
            return QRectF(0, 0, self.m_port_width + 12, self.m_port_height)

    def paint(self, painter, option, widget):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing,
                              bool(options.antialiasing == ANTIALIASING_FULL))

        selected = self.isSelected()
        theme = canvas.theme
        if self.m_port_type == PORT_TYPE_AUDIO_JACK:
            if self.m_is_alternate:
                poly_color = theme.port_cv_jack_bg_sel if selected else theme.port_cv_jack_bg
                poly_pen = theme.port_cv_jack_pen_sel  if selected else theme.port_cv_jack_pen
            else:
                poly_color = theme.port_audio_jack_bg_sel if selected else theme.port_audio_jack_bg
                poly_pen = theme.port_audio_jack_pen_sel  if selected else theme.port_audio_jack_pen
            text_pen = theme.port_audio_jack_text_sel if selected else theme.port_audio_jack_text
            conn_pen = QPen(theme.port_audio_jack_pen_sel)
        elif self.m_port_type == PORT_TYPE_MIDI_JACK:
            poly_color = theme.port_midi_jack_bg_sel if selected else theme.port_midi_jack_bg
            poly_pen = theme.port_midi_jack_pen_sel  if selected else theme.port_midi_jack_pen
            text_pen = theme.port_midi_jack_text_sel if selected else theme.port_midi_jack_text
            conn_pen = QPen(theme.port_midi_jack_pen_sel)
        elif self.m_port_type == PORT_TYPE_MIDI_ALSA:
            poly_color = theme.port_midi_alsa_bg_sel if selected else theme.port_midi_alsa_bg
            poly_pen = theme.port_midi_alsa_pen_sel  if selected else theme.port_midi_alsa_pen
            text_pen = theme.port_midi_alsa_text_sel if selected else theme.port_midi_alsa_text
            conn_pen = QPen(theme.port_midi_alsa_pen_sel)
        elif self.m_port_type == PORT_TYPE_PARAMETER:
            poly_color = theme.port_parameter_bg_sel if selected else theme.port_parameter_bg
            poly_pen = theme.port_parameter_pen_sel  if selected else theme.port_parameter_pen
            text_pen = theme.port_parameter_text_sel if selected else theme.port_parameter_text
            conn_pen = QPen(theme.port_parameter_pen_sel)
        else:
            qCritical("PatchCanvas::CanvasPort.paint() - invalid port type '%s'"
                      % port_type2str(self.m_port_type))
            return

        # To prevent quality worsening
        poly_pen = QPen(poly_pen)
        poly_pen.setWidthF(poly_pen.widthF() + 0.00001)

        lineHinting = poly_pen.widthF() / 2

        poly_locx = [0, 0, 0, 0, 0, 0]
        poly_corner_xhinting = ((float(canvas.theme.port_height)/2)
                                % floor(float(canvas.theme.port_height)/2))
        if poly_corner_xhinting == 0:
            poly_corner_xhinting = 0.5 * (1 - 7 / (float(canvas.theme.port_height)/2))

        is_cv_port = bool(self.m_port_type == PORT_TYPE_AUDIO_JACK
                          and self.m_is_alternate)

        if self.m_port_mode == PORT_MODE_INPUT:
            text_pos = QPointF(3, canvas.theme.port_text_ypos)

            if canvas.theme.port_mode == Theme.THEME_PORT_POLYGON and not is_cv_port:
                poly_locx[0] = lineHinting
                poly_locx[1] = self.m_port_width + 5 - lineHinting
                poly_locx[2] = self.m_port_width + 12 - poly_corner_xhinting
                poly_locx[3] = self.m_port_width + 5 - lineHinting
                poly_locx[4] = lineHinting
                poly_locx[5] = self.m_port_width
            elif canvas.theme.port_mode == Theme.THEME_PORT_SQUARE or is_cv_port:
                poly_locx[0] = lineHinting
                poly_locx[1] = self.m_port_width + 5 - lineHinting
                poly_locx[2] = self.m_port_width + 5 - lineHinting
                poly_locx[3] = self.m_port_width + 5 - lineHinting
                poly_locx[4] = lineHinting
                poly_locx[5] = self.m_port_width
            else:
                qCritical("PatchCanvas::CanvasPort.paint() - invalid theme port mode '%s'"
                          % canvas.theme.port_mode)
                return

        elif self.m_port_mode == PORT_MODE_OUTPUT:
            text_pos = QPointF(9, canvas.theme.port_text_ypos)

            if canvas.theme.port_mode == Theme.THEME_PORT_POLYGON and not is_cv_port:
                poly_locx[0] = self.m_port_width + 12 - lineHinting
                poly_locx[1] = 7 + lineHinting
                poly_locx[2] = 0 + poly_corner_xhinting
                poly_locx[3] = 7 + lineHinting
                poly_locx[4] = self.m_port_width + 12 - lineHinting
                poly_locx[5] = 12 - lineHinting
            elif canvas.theme.port_mode == Theme.THEME_PORT_SQUARE or is_cv_port:
                poly_locx[0] = self.m_port_width + 12 - lineHinting
                poly_locx[1] = 5 + lineHinting
                poly_locx[2] = 5 + lineHinting
                poly_locx[3] = 5 + lineHinting
                poly_locx[4] = self.m_port_width + 12 - lineHinting
                poly_locx[5] = 12 - lineHinting
            else:
                qCritical("PatchCanvas::CanvasPort.paint() - invalid theme port mode '%s'"
                          % canvas.theme.port_mode)
                return

        else:
            qCritical("PatchCanvas::CanvasPort.paint() - invalid port mode '%s'"
                      % port_mode2str(self.m_port_mode))
            return

        polygon = QPolygonF()

        if self.m_portgrp_id:
            first_of_portgrp = False
            last_of_portgrp = False

            # look in portgroup if port is the first,
            # the last, or not.
            for portgrp in canvas.portgrp_list:
                if portgrp.portgrp_id == self.m_portgrp_id:
                    if self.m_port_id == portgrp.port_id_list[0]:
                        first_of_portgrp = True
                    if self.m_port_id == portgrp.port_id_list[-1]:
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

        if canvas.theme.port_bg_pixmap:
            portRect = polygon.boundingRect().adjusted(
                -lineHinting+1, -lineHinting+1, lineHinting-1, lineHinting-1)
            portPos = portRect.topLeft()
            painter.drawTiledPixmap(
                portRect, canvas.theme.port_bg_pixmap, portPos)
        else:
            port_gradient = QLinearGradient(0, 0, 0, self.m_port_height)

            dark_color = poly_color.darker(112)
            light_color = poly_color.lighter(111)

            if poly_color.lightness() > 127:
                port_gradient.setColorAt(0, dark_color)
                port_gradient.setColorAt(0.5, light_color)
                port_gradient.setColorAt(1, dark_color)
            else:
                port_gradient.setColorAt(0, light_color)
                port_gradient.setColorAt(0.5, dark_color)
                port_gradient.setColorAt(1, light_color)
            painter.setBrush(port_gradient)

        painter.setPen(poly_pen)
        painter.drawPolygon(polygon)

        if self.m_is_alternate and not self.m_portgrp_id:
            if is_cv_port:
                poly_pen.setWidthF(2.000001)
                painter.setPen(poly_pen)

                y_line = canvas.theme.port_height / 2.0
                if self.m_port_mode == PORT_MODE_OUTPUT:
                    painter.drawLine(0, y_line, poly_locx[1], y_line)
                elif self.m_port_mode == PORT_MODE_INPUT:
                    painter.drawLine(
                        self.m_port_width + 5, y_line,
                        self.m_port_width + 12, y_line)
            else:
                # draw the little circle for a2j (or MidiBridge) port
                poly_pen.setWidthF(1.000001)
                painter.setBrush(canvas.theme.box_bg_1)

                ellipse_x = poly_locx[1]
                if self.m_port_mode == PORT_MODE_OUTPUT:
                    ellipse_x -= 2
                elif self.m_port_mode == PORT_MODE_INPUT:
                    ellipse_x += 2

                painter.drawEllipse(
                    QPointF(ellipse_x, canvas.theme.port_height / 2.0), 2, 2)

        painter.setPen(text_pen)
        painter.setFont(self.m_port_font)

        if self.m_portgrp_id:
            print_name_size = QFontMetrics(self.m_port_font).width(
                self.m_print_name)

            if self.m_port_mode == PORT_MODE_OUTPUT:
                text_pos = QPointF(self.m_port_width + 9 - print_name_size,
                                   canvas.theme.port_text_ypos)

            if print_name_size > (self.m_port_width - 4):
                painter.setPen(QPen(port_gradient, 3))
                painter.drawLine(poly_locx[5], 3, poly_locx[5], canvas.theme.port_height - 3)
                painter.setPen(text_pen)
                painter.setFont(self.m_port_font)
            painter.drawText(text_pos, self.m_print_name)

        else:
            painter.drawText(text_pos, self.m_print_name)

        if canvas.theme.idx == Theme.THEME_OOSTUDIO and canvas.theme.port_bg_pixmap:
            painter.setPen(Qt.NoPen)
            painter.setBrush(conn_pen.brush())

            if self.m_port_mode == PORT_MODE_INPUT:
                connRect = QRectF(portRect.topLeft(), QSizeF(2, portRect.height()))
            else:
                connRect = QRectF(QPointF(portRect.right()-2, portRect.top()), QSizeF(2, portRect.height()))

            painter.drawRect(connRect)

        painter.restore()

# ------------------------------------------------------------------------------------------------------------
