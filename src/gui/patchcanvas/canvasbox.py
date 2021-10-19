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
import math
import sys
import time

from sip import voidptr
from struct import pack

from PyQt5.QtCore import (qCritical, Qt, QPoint, QPointF, QRectF, QTimer,
                          pyqtSignal, QMarginsF, QTimer)
from PyQt5.QtGui import (QCursor, QFont, QFontMetrics, QImage,
                         QLinearGradient, QPainter, QPen, QPolygonF,
                         QColor, QIcon, QPixmap)
from PyQt5.QtWidgets import QGraphicsItem, QMenu, QApplication

# ------------------------------------------------------------------------------------------------------------
# Imports (Custom)

from . import (
    canvas,
    features,
    options,
    port_dict_t,
    CanvasBoxType,
    ANTIALIASING_FULL,
    ACTION_PLUGIN_EDIT,
    ACTION_PLUGIN_SHOW_UI,
    ACTION_PLUGIN_CLONE,
    ACTION_PLUGIN_REMOVE,
    ACTION_PLUGIN_RENAME,
    ACTION_PLUGIN_REPLACE,
    ACTION_GROUP_INFO,
    ACTION_GROUP_JOIN,
    ACTION_GROUP_SPLIT,
    ACTION_GROUP_RENAME,
    ACTION_GROUP_MOVE,
    ACTION_GROUP_WRAP,
    ACTION_PORTS_DISCONNECT,
    ACTION_INLINE_DISPLAY,
    EYECANDY_FULL,
    PORT_MODE_NULL,
    PORT_MODE_INPUT,
    PORT_MODE_OUTPUT,
    PORT_TYPE_NULL,
    PORT_TYPE_AUDIO_JACK,
    PORT_TYPE_MIDI_ALSA,
    PORT_TYPE_MIDI_JACK,
    PORT_TYPE_PARAMETER,
    MAX_PLUGIN_ID_ALLOWED,
    ICON_HARDWARE,
    ICON_INTERNAL
)

from .canvasboxshadow import CanvasBoxShadow
from .canvasicon import CanvasSvgIcon, CanvasIconPixmap
from .canvasport import CanvasPort
from .canvasportgroup import CanvasPortGroup
from .theme import Theme
from .utils import (CanvasItemFX,
                    CanvasGetFullPortName,
                    CanvasGetPortConnectionList,
                    CanvasGetPortGroupName,
                    CanvasGetPortGroupPosition,
                    CanvasCallback,
                    CanvasConnectionConcerns,
                    CanvasGetIcon,
                    is_dark_theme)

_translate = QApplication.translate

DIRECTION_LEFT = 1
DIRECTION_RIGHT = 2
DIRECTION_UP = 3
DIRECTION_DOWN = 4

ALIGN_NONE = 0
ALIGN_LEFT = 1
ALIGN_RIGHT = 2
ALIGN_TOP = 3
ALIGN_BOTTOM = 4

# ------------------------------------------------------------------------------------------------------------

class cb_line_t(object):
    def __init__(self, line, connection_id):
        self.line = line
        self.connection_id = connection_id


class TitleLine:
    text = ''
    size = 0
    x = 0
    y = 0
    is_little = False

    def __init__(self, text: str, little=False):
        self.text = text
        self.is_little = little
        self.x = 0
        self.y = 0
        self.font = QFont()
        self.font.setFamily(canvas.theme.box_font_name)
        self.font.setPixelSize(canvas.theme.box_font_size)
        if not little:
            self.font.setWeight(QFont.Bold)

        self.size = QFontMetrics(self.font).width(text)

    def reduce_pixel(self, reduce):
        self.font.setPixelSize(canvas.theme.box_font_size - reduce)
        self.size = QFontMetrics(self.font).width(self.text)

# ------------------------------------------------------------------------------------------------------------

class CanvasBox(QGraphicsItem):
    INLINE_DISPLAY_DISABLED = 0
    INLINE_DISPLAY_ENABLED  = 1
    INLINE_DISPLAY_CACHED   = 2

    def __init__(self, group_id: int, group_name: str, icon_type: int,
                 icon_name: str, parent=None):
        QGraphicsItem.__init__(self)
        self.setParentItem(parent)

        # Save Variables, useful for later
        self.m_group_id = group_id
        self.m_group_name = group_name

        self._title_lines = [TitleLine(group_name)]

        # plugin Id, < 0 if invalid
        self.m_plugin_id = -1
        self.m_plugin_ui = False
        self.m_plugin_inline = self.INLINE_DISPLAY_DISABLED

        # Base Variables
        self.p_width = 50
        self.p_width_in = 0
        self.p_width_out = 0
        self.p_height = canvas.theme.box_header_height + canvas.theme.box_header_spacing + 1
        self.p_ex_width = self.p_width
        self.p_ex_height = self.p_height
        self.p_ex_scene_pos = self.scenePos()

        self.m_last_pos = QPointF()
        self.m_splitted = False
        self.m_splitted_mode = PORT_MODE_NULL
        self.m_current_port_mode = PORT_MODE_NULL # depends of present ports

        self.m_cursor_moving = False
        self.m_forced_split = False
        self.m_mouse_down = False
        self.m_inline_data = None
        self.m_inline_image = None
        self.m_inline_scaling = 1.0

        self.m_port_list_ids = []
        self.m_connection_lines = []

        # Set Font
        self.m_font_name = QFont()
        self.m_font_name.setFamily(canvas.theme.box_font_name)
        self.m_font_name.setPixelSize(canvas.theme.box_font_size)
        self.m_font_name.setWeight(canvas.theme.box_font_state)

        self.m_font_italic = QFont()
        self.m_font_italic.setFamily(canvas.theme.box_font_name)
        self.m_font_italic.setPixelSize(canvas.theme.box_font_size)
        self.m_font_italic.setWeight(canvas.theme.box_font_state)
        #self.m_font_italic.setItalic(True)
        self.m_font_italic.setBold(False)

        self.m_font_port = QFont()
        self.m_font_port.setFamily(canvas.theme.port_font_name)
        self.m_font_port.setPixelSize(canvas.theme.port_font_size)
        self.m_font_port.setWeight(canvas.theme.port_font_state)

        self._is_hardware = bool(icon_type == ICON_HARDWARE)
        self._hw_polygon = QPolygonF()
        self._icon_name = icon_name

        self._wrapped = False
        self._wrapping = False
        self._unwrapping = False
        self._wrapping_timer = QTimer()
        self._wrapping_timer.setInterval(40)
        self._wrapping_timer.timeout.connect(self.animateWrapping)
        self._wrapping_n = 0
        self._wrapping_max = 5

        self._ensuring_visible = False

        # Icon
        if canvas.theme.box_use_icon:
            if icon_type in (ICON_HARDWARE, ICON_INTERNAL):
                port_mode = PORT_MODE_NULL
                if self.m_splitted:
                    port_mode = self.m_splitted_mode
                self.top_icon = CanvasSvgIcon(
                    icon_type, icon_name, port_mode, self)
            else:
                self.top_icon = CanvasIconPixmap(icon_type, icon_name, self)
                if self.top_icon.is_null():
                    top_icon = self.top_icon
                    self.top_icon = None
                    del top_icon
        else:
            self.top_icon = None

        # Shadow
        self.shadow = None
        # FIXME FX on top of graphic items make them lose high-dpi
        # See https://bugreports.qt.io/browse/QTBUG-65035
        if options.eyecandy and canvas.scene.getDevicePixelRatioF() == 1.0:
            self.shadow = CanvasBoxShadow(self.toGraphicsObject())
            self.shadow.setFakeParent(self)
            self.setGraphicsEffect(self.shadow)

        # Final touches
        self.setFlags(QGraphicsItem.ItemIsFocusable
                      | QGraphicsItem.ItemIsMovable
                      | QGraphicsItem.ItemIsSelectable)

        # Wait for at least 1 port
        if options.auto_hide_groups:
            self.setVisible(False)

        if options.auto_select_items:
            self.setAcceptHoverEvents(True)

        self.updatePositions()

        canvas.scene.addItem(self)
        QTimer.singleShot(0, self.fixPos)

    def getGroupId(self):
        return self.m_group_id

    def getGroupName(self):
        return self.m_group_name

    def isSplitted(self):
        return self.m_splitted

    def getSplittedMode(self):
        return self.m_splitted_mode

    def getPortCount(self):
        return len(self.m_port_list_ids)

    def getPortList(self):
        return self.m_port_list_ids

    def redrawInlineDisplay(self):
        if self.m_plugin_inline == self.INLINE_DISPLAY_CACHED:
            self.m_plugin_inline = self.INLINE_DISPLAY_ENABLED
            self.update()

    def removeAsPlugin(self):
        #del self.m_inline_image
        #self.m_inline_data = None
        #self.m_inline_image = None
        #self.m_inline_scaling = 1.0

        self.m_plugin_id = -1
        self.m_plugin_ui = False
        #self.m_plugin_inline = self.INLINE_DISPLAY_DISABLED

    def setAsPlugin(self, plugin_id, hasUI, hasInlineDisplay):
        if hasInlineDisplay and not options.inline_displays:
            hasInlineDisplay = False

        if not hasInlineDisplay:
            del self.m_inline_image
            self.m_inline_data = None
            self.m_inline_image = None
            self.m_inline_scaling = 1.0

        self.m_plugin_id = plugin_id
        self.m_plugin_ui = hasUI
        self.m_plugin_inline = self.INLINE_DISPLAY_ENABLED if hasInlineDisplay else self.INLINE_DISPLAY_DISABLED
        self.update()

    def setIcon(self, icon_type, icon_name):
        if icon_type == ICON_HARDWARE:
            self.removeIconFromScene()
            port_mode = PORT_MODE_NULL
            if self.m_splitted:
                port_mode = self.m_splitted_mode
            self.top_icon = CanvasSvgIcon(icon_type, icon_name, port_mode, self)
            return

        if self.top_icon is not None:
            self.top_icon.setIcon(icon_type, icon_name, self.m_group_name)
        else:
            self.top_icon = CanvasIconPixmap(icon_type, icon_name, self)

        self.updatePositions()

    def has_top_icon(self)->bool:
        if self.top_icon is None:
            return False

        return not self.top_icon.is_null()

    def setSplit(self, split, mode=PORT_MODE_NULL):
        self.m_splitted = split
        self.m_splitted_mode = mode
        self.m_current_port_mode = mode

        if self._is_hardware:
            self.setIcon(ICON_HARDWARE, self._icon_name)

    def splitTitle(self, n_lines=True)->tuple:
        title, slash, subtitle = self.m_group_name.partition('/')
        if subtitle:
            # if there is a subtitle, title is not bold when subtitle is.
            # so title is 'little'
            title_lines = [TitleLine(title, little=True)]
            if n_lines >= 3:
                title_lines += [TitleLine(subtt)
                                for subtt in self.split_in_two(subtitle, 2) if subtt]
            else:
                title_lines.append(TitleLine(subtitle))
        else:
            if n_lines >= 2:
                title_lines = [
                    TitleLine(tt)
                    for tt in self.split_in_two(self.m_group_name, n_lines) if tt]
            else:
                title_lines= [TitleLine(self.m_group_name)]

            if len(title_lines) >= 4:
                for title_line in title_lines:
                    title_line.reduce_pixel(2)

        return tuple(title_lines)

    def setGroupName(self, group_name):
        self.m_group_name = group_name
        self.updatePositions()

    def setShadowOpacity(self, opacity):
        if self.shadow:
            self.shadow.setOpacity(opacity)

    def addPortFromGroup(self, port_id, port_mode, port_type,
                         port_name, is_alternate):
        if len(self.m_port_list_ids) == 0:
            if options.auto_hide_groups:
                if options.eyecandy == EYECANDY_FULL:
                    CanvasItemFX(self, True, False)
                self.setVisible(True)

        new_widget = CanvasPort(self.m_group_id, port_id, port_name, port_mode,
                                port_type, is_alternate, self)
        if self._wrapped:
            new_widget.setVisible(False)

        self.m_port_list_ids.append(port_id)

        return new_widget

    def removePortFromGroup(self, port_id):
        if port_id in self.m_port_list_ids:
            self.m_port_list_ids.remove(port_id)
        else:
            qCritical("PatchCanvas::CanvasBox.removePort(%i) - unable to find port to remove" % port_id)
            return

        if len(self.m_port_list_ids) > 0:
            self.updatePositions()

        elif self.isVisible():
            if options.auto_hide_groups:
                if options.eyecandy == EYECANDY_FULL:
                    CanvasItemFX(self, False, False)
                else:
                    self.setVisible(False)

    def addPortGroupFromGroup(self, portgrp_id, port_mode, port_type, port_id_list):
        new_widget = CanvasPortGroup(self.m_group_id, portgrp_id, port_mode,
                                     port_type, port_id_list, self)

        if self._wrapped:
            new_widget.setVisible(False)

        return new_widget

    def addLineFromGroup(self, line, connection_id):
        new_cbline = cb_line_t(line, connection_id)
        self.m_connection_lines.append(new_cbline)

    def removeLineFromGroup(self, connection_id):
        for connection in self.m_connection_lines:
            if connection.connection_id == connection_id:
                self.m_connection_lines.remove(connection)
                return
        qCritical("PatchCanvas::CanvasBox.removeLineFromGroup(%i) - unable to find line to remove" % connection_id)

    def checkItemPos(self):
        if not canvas.size_rect.isNull():
            pos = self.scenePos()
            if not (canvas.size_rect.contains(pos) and
                    canvas.size_rect.contains(pos + QPointF(self.p_width, self.p_height))):
                if pos.x() < canvas.size_rect.x():
                    self.setPos(canvas.size_rect.x(), pos.y())
                elif pos.x() + self.p_width > canvas.size_rect.width():
                    self.setPos(canvas.size_rect.width() - self.p_width, pos.y())

                pos = self.scenePos()
                if pos.y() < canvas.size_rect.y():
                    self.setPos(pos.x(), canvas.size_rect.y())
                elif pos.y() + self.p_height > canvas.size_rect.height():
                    self.setPos(pos.x(), canvas.size_rect.height() - self.p_height)

    def removeIconFromScene(self):
        if self.top_icon is None:
            return

        item = self.top_icon
        self.top_icon = None
        canvas.scene.removeItem(item)
        del item

    def animateWrapping(self):
        self._wrapping_n += 1
        if self._wrapping_n +1 == self._wrapping_max:
            self._wrapping_n = 0

            if self._unwrapping:
                self.hide_ports_for_wrap(False)

            self._wrapping = False
            self._unwrapping = False
            self._wrapping_timer.stop()

        self.updatePositions()

    def hide_ports_for_wrap(self, hide: bool):
        for portgrp in canvas.portgrp_list:
            if portgrp.group_id == self.m_group_id:
                if (self.m_splitted
                        and self.m_splitted_mode != portgrp.port_mode):
                    continue

                if portgrp.widget is not None:
                    portgrp.widget.setVisible(not hide)

        for port in canvas.port_list:
            if port.group_id == self.m_group_id:
                if (self.m_splitted
                        and self.m_splitted_mode != port.port_mode):
                    continue

                if port.widget is not None:
                    port.widget.setVisible(not hide)

    def is_wrapped(self)->bool:
        return self._wrapped

    def set_wrapped(self, yesno: bool, animate=True):
        if yesno == self._wrapped:
            return

        self._wrapped = yesno

        if yesno:
            self.hide_ports_for_wrap(True)

        if not animate:
            return

        self._wrapping = yesno
        self._unwrapping = not yesno
        self._wrapping_timer.start()

    def get_string_size(self, string: str)->int:
        return QFontMetrics(self.m_font_name).width(string)

    @staticmethod
    def split_in_two(string: str, n_lines=2)->tuple:
        sep_indexes = []
        last_was_digit = False

        for sep in (' ', '-', '_', 'capital'):
            for i in range(len(string)):
                c = string[i]
                if sep == 'capital':
                    if c.upper() == c:
                        if not c.isdigit() or not last_was_digit:
                            sep_indexes.append(i)
                        last_was_digit = c.isdigit()

                elif c == sep:
                    sep_indexes.append(i)

            if sep_indexes:
                break

        if not sep_indexes:
            # no available separator in given text
            return_list = [string] + ['' for n in range(1, n_lines)]
            return tuple(return_list)

        if len(sep_indexes) + 1 <= n_lines:
            return_list = []
            last_index = 0

            for sep_index in sep_indexes:
                return_list.append(string[last_index:sep_index])
                last_index = sep_index
                if sep == ' ':
                    last_index += 1

            return_list.append(string[last_index:])

            return_list += ['' for n in range(n_lines - len(sep_indexes) - 1)]
            return tuple(return_list)

        best_indexes = [0]
        string_rest = string
        string_list = []

        for i in range(n_lines, 1, -1):
            target = best_indexes[-1] + int(len(string_rest)/i)
            best_index = 0
            best_dif = len(string)

            for s in sep_indexes:
                if s <= best_indexes[-1]:
                    continue

                dif = abs(target - s)
                if dif < best_dif:
                    best_index = s
                    best_dif = dif
                else:
                    break

            if sep == ' ':
                string_rest = string[best_index+1:]
            else:
                string_rest = string[best_index:]

            best_indexes.append(best_index)

        best_indexes = best_indexes[1:]
        last_index = 0
        return_list = []

        for i in best_indexes:
            return_list.append(string[last_index:i])
            last_index = i
            if sep == ' ':
                last_index += 1

        return_list.append(string[last_index:])
        return tuple(return_list)

    def updatePositions(self):
        self.prepareGeometryChange()

        # Get Port List
        port_list = []
        self.m_current_port_mode = PORT_MODE_NULL

        for port in canvas.port_list:
            if port.group_id == self.m_group_id and port.port_id in self.m_port_list_ids:
                port_list.append(port)
                # used to know present port types
                self.m_current_port_mode |= port.port_mode

        max_in_width = max_out_width = 0
        port_spacing = canvas.theme.port_height + canvas.theme.port_spacing

        # Get Max Box Width, vertical ports re-positioning
        port_types = [PORT_TYPE_AUDIO_JACK, PORT_TYPE_MIDI_JACK,
                      PORT_TYPE_MIDI_ALSA, PORT_TYPE_PARAMETER]
        last_in_type = last_out_type = PORT_TYPE_NULL
        last_in_alter = last_out_alter = False
        last_in_pos = last_out_pos = (canvas.theme.box_header_height
                                      + canvas.theme.box_header_spacing)

        wrapped_port_pos = last_in_pos
        last_of_portgrp = True

        align_port_types = True
        port_types_aligner = []

        for port_type in port_types:
            aligner_item = []
            for alternate in (False, True):
                n_ins = 0
                n_outs = 0

                for port in port_list:
                    if (port.port_type == port_type
                            and port.is_alternate == alternate):
                        if port.port_mode == PORT_MODE_INPUT:
                            n_ins += 1
                        elif port.port_mode == PORT_MODE_OUTPUT:
                            n_outs += 1

                port_types_aligner.append((n_ins, n_outs))

        winner = PORT_MODE_NULL

        for n_ins, n_outs in port_types_aligner:
            if ((winner == PORT_MODE_INPUT and n_outs > n_ins)
                    or (winner == PORT_MODE_OUTPUT and n_ins > n_outs)):
                align_port_types = False
                break

            if n_ins > n_outs:
                winner = PORT_MODE_INPUT
            elif n_outs > n_ins:
                winner = PORT_MODE_OUTPUT

        for port_type in port_types:
            for alternate in (False, True):
                for port in port_list:
                    if (port.port_type != port_type
                            or port.is_alternate != alternate):
                        continue

                    port_pos, pg_len = CanvasGetPortGroupPosition(
                        self.m_group_id, port.port_id, port.portgrp_id)
                    first_of_portgrp = bool(port_pos == 0)
                    last_of_portgrp = bool(port_pos+1 == pg_len)

                    size = QFontMetrics(self.m_font_port).width(port.port_name)
                    if port.portgrp_id:
                        size = 0
                        totsize = QFontMetrics(self.m_font_port).width(port.port_name) + 3
                        # FIXME
                        for portgrp in canvas.portgrp_list:
                            if portgrp.portgrp_id == port.portgrp_id:
                                portgrp_name = CanvasGetPortGroupName(
                                    self.m_group_id, portgrp.port_id_list)
                                size = QFontMetrics(self.m_font_port).width(portgrp_name) \
                                        + canvas.theme.port_in_portgrp_width
                                break
                        size = max(size, totsize)

                    if port.port_mode == PORT_MODE_INPUT:
                        max_in_width = max(max_in_width, size)
                        if (port.port_type != last_in_type
                                or port.is_alternate != last_in_alter):
                            if last_in_type != PORT_TYPE_NULL:
                                last_in_pos += canvas.theme.port_spacingT
                            last_in_type = port.port_type
                            last_in_alter = port.is_alternate

                        if self._wrapping:
                            port.widget.setY(last_in_pos
                                            - (last_in_pos - wrapped_port_pos)
                                                * self._wrapping_n / self._wrapping_max)
                        elif self._unwrapping:
                            port.widget.setY(wrapped_port_pos
                                            + (last_in_pos - wrapped_port_pos)
                                                * self._wrapping_n / self._wrapping_max)
                        elif self._wrapped:
                            port.widget.setY(wrapped_port_pos)
                        else:
                            port.widget.setY(last_in_pos)

                        if port.portgrp_id and first_of_portgrp:
                            for portgrp in canvas.portgrp_list:
                                if (portgrp.group_id == self.m_group_id
                                        and portgrp.portgrp_id == port.portgrp_id):
                                    if portgrp.widget is not None:
                                        if self._wrapped:
                                            portgrp.widget.setY(wrapped_port_pos)
                                        else:
                                            portgrp.widget.setY(last_in_pos)
                                    break

                        if last_of_portgrp:
                            last_in_pos += port_spacing
                        else:
                            last_in_pos += canvas.theme.port_height

                    elif port.port_mode == PORT_MODE_OUTPUT:
                        max_out_width = max(max_out_width, size)
                        if (port.port_type != last_out_type
                                or port.is_alternate != last_out_alter):
                            if last_out_type != PORT_TYPE_NULL:
                                last_out_pos += canvas.theme.port_spacingT
                            last_out_type = port.port_type
                            last_out_alter = port.is_alternate

                        if self._wrapping:
                            port.widget.setY(last_out_pos
                                            - (last_out_pos - wrapped_port_pos)
                                                * self._wrapping_n / self._wrapping_max)
                        elif self._unwrapping:
                            port.widget.setY(wrapped_port_pos
                                            + (last_out_pos - wrapped_port_pos)
                                                * self._wrapping_n / self._wrapping_max)
                        elif self._wrapped:
                            port.widget.setY(wrapped_port_pos)
                        else:
                            port.widget.setY(last_out_pos)

                        if port.portgrp_id and first_of_portgrp:
                            for portgrp in canvas.portgrp_list:
                                if (portgrp.group_id == self.m_group_id
                                        and portgrp.portgrp_id == port.portgrp_id):
                                    if portgrp.widget is not None:
                                        if self._wrapped:
                                            portgrp.widget.setY(wrapped_port_pos)
                                        else:
                                            portgrp.widget.setY(last_out_pos)
                                    break

                        if last_of_portgrp:
                            last_out_pos += port_spacing
                        else:
                            last_out_pos += canvas.theme.port_height

                if align_port_types:
                    # align port types horizontally
                    if last_in_pos > last_out_pos:
                        last_out_type = last_in_type
                        last_out_alter = last_in_alter
                    else:
                        last_in_type = last_out_type
                        last_in_alter = last_out_alter
                    last_in_pos = last_out_pos = max(last_in_pos, last_out_pos)

        self.p_width = 30
        if self.m_plugin_inline != self.INLINE_DISPLAY_DISABLED:
            self.p_width = 100

        self.p_width += max_in_width + max_out_width
        self.p_width_in = max_in_width
        self.p_width_out = max_out_width

        # Check Text Name size
        title_template = {"title_width": 0, "header_width": 0}
        all_title_templates = [title_template.copy() for i in range(5)]

        for i in range(1, 5):
            max_title_size = 0
            title_lines = self.splitTitle(i)

            for title_line in title_lines:
                max_title_size = max(max_title_size, title_line.size)

            all_title_templates[i]
            header_width = max_title_size

            if self.has_top_icon():
                header_width += 37
            else:
                header_width += 16

            header_width =  max(200 if self.m_plugin_inline != self.INLINE_DISPLAY_DISABLED else 50,
                                header_width)

            new_title_template = title_template.copy()
            new_title_template['title_width'] = max_title_size
            new_title_template['header_width'] = header_width
            all_title_templates[i] = new_title_template

            if header_width < self.p_width:
                break

        more_height = 0
        lines_choice = 1

        if all_title_templates[1]['header_width'] <= self.p_width:
            # One line title is shorter than the box, choose it
            lines_choice = 1
        elif all_title_templates[2]['header_width'] <= self.p_width:
            # Two lines title is shorter than the box, choose it
            lines_choice = 2
        else:
            more_height = 14
            area_2 = all_title_templates[2]['header_width'] * max(last_in_pos, last_out_pos)
            area_3 = max(self.p_width, all_title_templates[3]['header_width']) \
                         * (max(last_in_pos, last_out_pos) + more_height)

            if area_2 <= area_3:
                # Box area is smaller with 2 lines titles than with 3 lines title
                # choose 2 lines title
                lines_choice = 2
                more_height = 0

            elif all_title_templates[3]['header_width'] <= self.p_width:
                # 3 lines title is shorter than the box, choose it
                lines_choice = 3
            else:
                area_4 = max(self.p_width, all_title_templates[4]['header_width']) \
                            * (max(last_in_pos, last_out_pos) + more_height)

                if area_3 - area_4 >= 5000:
                    lines_choice = 4
                else:
                    lines_choice = 3

        self._title_lines = self.splitTitle(lines_choice)
        self.p_width = max(self.p_width,
                           all_title_templates[lines_choice]['header_width'])
        max_title_size = all_title_templates[lines_choice]['title_width']

        if more_height:
            # down ports
            for port in port_list:
                port.widget.setY(port.widget.y() + more_height)

            # down portgroups
            for portgrp in canvas.portgrp_list:
                if (portgrp.group_id == self.m_group_id
                        and self.m_current_port_mode & portgrp.port_mode):
                    if portgrp.widget is not None:
                        portgrp.widget.setY(portgrp.widget.y() + more_height)

            last_in_pos += more_height
            last_out_pos += more_height

        # Horizontal ports re-positioning
        inX = canvas.theme.port_offset
        outX = self.p_width - max_out_width - canvas.theme.port_offset - 12
        out_in_portgrpX = (self.p_width - canvas.theme.port_offset - 12
                           - canvas.theme.port_in_portgrp_width)

        for port in port_list:
            if port.port_mode == PORT_MODE_INPUT:
                port.widget.setX(inX)
                if port.portgrp_id:
                    port.widget.setPortWidth(canvas.theme.port_in_portgrp_width)

                    for portgrp in canvas.portgrp_list:
                        if (portgrp.group_id == self.m_group_id
                                and portgrp.port_id_list
                                and portgrp.port_id_list[0] == port.port_id):
                            if portgrp.widget:
                                portgrp.widget.setPortGroupWidth(max_in_width)
                                portgrp.widget.setX(canvas.theme.port_offset +1)
                            break

                else:
                    port.widget.setPortWidth(max_in_width)

            elif port.port_mode == PORT_MODE_OUTPUT:
                if port.portgrp_id:
                    port.widget.setX(out_in_portgrpX)
                    port.widget.setPortWidth(canvas.theme.port_in_portgrp_width)

                    for portgrp in canvas.portgrp_list:
                        if (portgrp.group_id == self.m_group_id
                                and portgrp.port_id_list
                                and portgrp.port_id_list[0] == port.port_id):
                            if portgrp.widget:
                                portgrp.widget.setX(outX)
                                portgrp.widget.setPortGroupWidth(max_out_width)
                            break
                else:
                    port.widget.setX(outX)
                    port.widget.setPortWidth(max_out_width)

        normal_height = max(last_in_pos, last_out_pos)
        wrapped_height = wrapped_port_pos + canvas.theme.port_height
        if len(self._title_lines) >= 3:
            wrapped_height += 14

        if self._wrapping:
            self.p_height = normal_height \
                            - (normal_height - wrapped_height) \
                                * (self._wrapping_n / self._wrapping_max)
        elif self._unwrapping:
            self.p_height = wrapped_height \
                            + (normal_height - wrapped_height) \
                                * (self._wrapping_n / self._wrapping_max)
        elif self._wrapped:
            self.p_height = wrapped_height
        else:
            self.p_height = max(last_in_pos, last_out_pos)

        self.p_height += max(canvas.theme.port_spacing,
                             canvas.theme.port_spacingT) \
                         - canvas.theme.port_spacing
        self.p_height += canvas.theme.box_pen.widthF()

        if self.has_top_icon():
            self.top_icon.align_at((self.p_width - max_title_size - 29)/2)

        if (self.p_width != self.p_ex_width
                or self.p_height != self.p_ex_height
                or self.scenePos() != self.p_ex_scene_pos):
            canvas.scene.resize_the_scene()

        self.p_ex_width = self.p_width
        self.p_ex_height = self.p_height
        self.p_ex_scene_pos = self.scenePos()

        self.repaintLines(forced=True)
        self.update()

    def repaintLines(self, forced=False):
        if forced or self.pos() != self.m_last_pos:
            for connection in self.m_connection_lines:
                connection.line.updateLinePos()

        self.m_last_pos = self.pos()

    def resetLinesZValue(self):
        for connection in canvas.connection_list:
            if (connection.port_out_id in self.m_port_list_ids
                    and connection.port_in_id in self.m_port_list_ids):
                z_value = canvas.last_z_value
            else:
                z_value = canvas.last_z_value - 1

            connection.widget.setZValue(z_value)

    def _get_adjacent_boxes(self):
        #rect = self.boundingRect()
        #rect.translate(self.pos())
        #rect.adjust(-25, -7, 25, 7)
        
        #item_list = []
        
        #for item in canvas.scene.items(rect):
            #if item is not self and item.type() == CanvasBoxType:
                #item_list.append(item)
        
        item_list = [self]
        
        for item in item_list:
            rect = item.boundingRect()
            rect.translate(item.pos())
            rect.adjust(-25, -7, 25, 7)
            
            for litem in canvas.scene.items(rect):
                if (litem.type() == CanvasBoxType
                        and litem not in item_list):
                    item_list.append(litem)
        print(item_list)
        print([i.m_group_name for i in item_list])
        return item_list

    def _deplace_other_boxes(self):
        def rect_with_mergin(rect):
            return rect.adjusted(-24, -6, 24, 6)
        
        def get_default_direction(fixed_rect, moving_rect)->int:
            if (moving_rect.top() <= fixed_rect.center().y() <= moving_rect.bottom()
                    or fixed_rect.top() <= moving_rect.center().y() <= fixed_rect.bottom()):
                if (fixed_rect.right() < moving_rect.center().x()
                        and fixed_rect.center().x() < moving_rect.left()):
                    return DIRECTION_RIGHT
                
                if (fixed_rect.left() > moving_rect.center().x()
                        and fixed_rect.center().x() > moving_rect.right()):
                    return DIRECTION_LEFT
            
            if fixed_rect.center().y() <= moving_rect.center().y():
                return DIRECTION_DOWN
            
            return DIRECTION_UP
        
        def repulse(direction: int, fixed, moving):
            ''' returns a qrect to be placed at side of fixed_rect
                where fixed_rect is an already determinated futur place
                for a box '''
                
            if isinstance(fixed, CanvasBox):
                fixed_rect = fixed.boundingRect().translated(fixed.pos())
            else:
                fixed_rect = fixed
            
            if isinstance(moving, CanvasBox):
                rect = moving.boundingRect().translated(moving.pos())
            else:
                rect = moving

            assert direction in (DIRECTION_DOWN, DIRECTION_LEFT,
                                 DIRECTION_UP, DIRECTION_RIGHT)
            
            x = rect.left()
            y = rect.top()
            
            if direction in (DIRECTION_LEFT, DIRECTION_RIGHT):
                if direction == DIRECTION_LEFT:
                    x = fixed_rect.left() - 4 * box_spacing - rect.width()
                else:
                    x = fixed_rect.right() + 4 * box_spacing

                top_diff = abs(fixed_rect.top() - rect.top())
                bottom_diff = abs(fixed_rect.bottom() - rect.bottom())

                if bottom_diff > top_diff and top_diff <= 12:
                    y = fixed_rect.top()
                elif bottom_diff <= 12:
                    y = fixed_rect.bottom() - rect.height()
                    
                #y -= pos_offset.y()
            
            elif direction in (DIRECTION_UP, DIRECTION_DOWN):
                if direction == DIRECTION_UP:
                    y = fixed_rect.top() - box_spacing - rect.height()
                else:
                    y = fixed_rect.bottom() + box_spacing
                
                left_diff = abs(fixed_rect.left() - rect.left())
                right_diff = abs(fixed_rect.right() - rect.right())
                
                if right_diff > left_diff and left_diff <= 12:
                    x = fixed_rect.left()
                elif right_diff <= 12:
                    x = fixed_rect.right() - rect.width()
                
                #x -= pos_offset.x()
            return QRectF(x, y, rect.width(), rect.height())
            #return rect.translated(QPointF(x, y))

        box_spacing = 6
        magnet = 12

        srect = self.boundingRect()
        srect.translate(self.pos())

        impacted_rect = rect_with_mergin(srect)

        items_to_move = []

        for item in canvas.scene.items(impacted_rect):
            if item.type() == CanvasBoxType and item is not self:
                items_to_move.append(item)
                
        if not items_to_move:
            return
        
        # here we are sure the box area with margins contains other boxes.
        # Check if box area without margins contains others boxes,
        # if not, then we will move this box at regular margin
        # from the other boxes
        for item in canvas.scene.items(srect):
            if item.type() == CanvasBoxType and item is not self:
                break
        else:
            print('on passe par la self repulsion')
            
            left_item = None
            top_item = None
            right_item = None
            bottom_item = None
            left_item_right = 0
            top_item_bottom = 0
            right_item_left = 0
            bottom_item_top = 0
            
            for item in items_to_move:
                irect = item.boundingRect()
                irect.translate(item.pos())
                
                if irect.right() <= srect.left():
                    if left_item is None or irect.right() > left_item_right:
                        left_item = item
                        left_item_right = irect.right()
                    
                if irect.bottom() <= srect.top():
                    if top_item is None or irect.bottom() > top_item_bottom:
                        top_item = item
                        top_item_bottom = irect.bottom()
                    
                if irect.left() >= srect.right():
                    if right_item is None or irect.left() < right_item_left:
                        right_item = item
                        right_item_left = irect.left()
                    
                if irect.top() >= srect.bottom():
                    if bottom_item is None or irect.top() < bottom_item_top:
                        bottom_item = item
                        bottom_item_top = irect.top()
            
            if not ((left_item and right_item) or (top_item and bottom_item)):
                rect = None

                if left_item is not None:
                    rect = repulse(
                        DIRECTION_RIGHT,
                        left_item.boundingRect().translated(left_item.pos()),
                        self)
                if top_item is not None:
                    rect = repulse(
                        DIRECTION_DOWN,
                        top_item.boundingRect().translated(top_item.pos()),
                        self)
                if right_item is not None:
                    rect = repulse(
                        DIRECTION_LEFT,
                        right_item.boundingRect().translated(right_item.pos()),
                        self)
                if bottom_item is not None:
                    rect = repulse(
                        DIRECTION_UP,
                        bottom_item.boundingRect().translated(bottom_item.pos()),
                        self)
                
                pos_point = rect.topLeft()
                pos_point -= self.boundingRect().topLeft()
                
                canvas.scene.add_box_to_animation(self, pos_point.x(), pos_point.y())
                return

        items_to_move_dicts = []

        for item in items_to_move:
            # get item qrect
            irect = item.boundingRect()
            irect.translate(item.pos())
            
            direction = get_default_direction(srect, irect)
            pos_item_dict = {
                'direction': direction,
                'pos': 0,
                'item': item,
                'repulser': self}
            
            # stock a position only for sorting reason
            if direction == DIRECTION_RIGHT:
                pos_item_dict['pos'] = irect.left()
            elif direction == DIRECTION_LEFT:
                pos_item_dict['pos'] = - irect.right()
            elif direction == DIRECTION_DOWN:
                pos_item_dict['pos'] = irect.top()
            elif direction == DIRECTION_UP:
                pos_item_dict['pos'] = - irect.bottom()
            
            print('ji', item.m_group_name, direction)
            
            items_to_move_dicts.append(pos_item_dict)
                
        # sort the list of dicts
        items_to_move_dicts = sorted(
            items_to_move_dicts, key = lambda d: d['pos'])
        items_to_move_dicts = sorted(
            items_to_move_dicts, key = lambda d: d['direction'])

        print('eorkg')
        print(items_to_move_dicts)

        # here we stock only the rects of the definitely placed boxes
        definitive_list = [self.boundingRect().translated(self.pos())]
        #definitive_list = []
            
        for pos_item_dict in items_to_move_dicts:
            direction = pos_item_dict['direction']
            item = pos_item_dict['item']
            repulser_item = pos_item_dict['repulser']
            
            ref_rect = repulser_item.boundingRect().translated(repulser_item.pos())
            
            new_rect = repulse(direction, ref_rect, item)
            print('replsi1', direction, item.m_group_name, item.boundingRect().translated(item.pos()), new_rect)
            
            for defi_rect in definitive_list:
                imp_rect = rect_with_mergin(defi_rect)
                if imp_rect.intersects(new_rect):
                    ref_rect = defi_rect
                    
                    default_direction = get_default_direction(ref_rect, new_rect)
                    if direction == DIRECTION_LEFT:
                        if default_direction != DIRECTION_RIGHT:
                            direction = default_direction
                    elif direction == DIRECTION_UP:
                        if default_direction != DIRECTION_DOWN:
                            direction = default_direction
                    elif direction == DIRECTION_RIGHT:
                        if default_direction != DIRECTION_LEFT:
                            direction = default_direction
                    elif direction == DIRECTION_DOWN:
                        if default_direction != DIRECTION_UP:
                            direction = default_direction
                    
                    print('reppluse', direction, item.m_group_name, new_rect)
                    new_rect = repulse(direction, ref_rect, new_rect)
                    print('r+', new_rect)

            definitive_list.append(new_rect)
            
            adding_list = []
            
            for mitem in canvas.scene.items(rect_with_mergin(new_rect)):
                if (mitem.type() == CanvasBoxType
                        and mitem is not self
                        and mitem not in [d['item'] for d in items_to_move_dicts]):
                    mirect = mitem.boundingRect().translated(mitem.pos())
                    adding_list.append(
                        {'direction': direction,
                         'pos': mirect.right(),
                         'item': mitem,
                         'repulser': item})
            
            adding_list = sorted(adding_list, key = lambda d: d['pos'])
            for adding in adding_list:
                items_to_move_dicts.append(adding)

            # now we decide where the box is moved
            pos_offset = item.boundingRect().topLeft()
            to_send_rect = new_rect.translated(- pos_offset)
            canvas.scene.add_box_to_animation(
                item, to_send_rect.left(), to_send_rect.top())

    def type(self):
        return CanvasBoxType

    def contextMenuEvent(self, event):
        if canvas.is_line_mov:
            return

        event.accept()
        menu = QMenu()

        dark = ''
        if is_dark_theme(menu):
            dark = '-dark'

        # Disconnect menu stuff
        discMenu = QMenu(_translate('patchbay', "Disconnect"), menu)
        discMenu.setIcon(
            QIcon(QPixmap(':scalable/breeze%s/lines-disconnector' % dark)))

        conn_list_ids = []
        disconnect_list = [] # will contains disconnect_element dicts

        for connection in canvas.connection_list:
            if CanvasConnectionConcerns(
                    connection, self.m_group_id, self.m_port_list_ids):
                conn_list_ids.append(connection.connection_id)
                other_group_id = connection.group_in_id
                group_port_mode = PORT_MODE_INPUT

                if self.m_splitted:
                    if self.m_splitted_mode == PORT_MODE_INPUT:
                        other_group_id = connection.group_out_id
                        group_port_mode = PORT_MODE_OUTPUT
                else:
                    if other_group_id == self.m_group_id:
                        other_group_id = connection.group_out_id
                        group_port_mode = PORT_MODE_OUTPUT

                for disconnect_element in disconnect_list:
                    if disconnect_element['group_id'] == other_group_id:
                        if group_port_mode == PORT_MODE_INPUT:
                            disconnect_element['connection_in_ids'].append(
                                connection.connection_id)
                        else:
                            disconnect_element['connection_out_ids'].append(
                                connection.connection_id)
                        break
                else:
                    disconnect_element = {'group_id': other_group_id,
                                          'connection_in_ids': [],
                                          'connection_out_ids': []}

                    if group_port_mode == PORT_MODE_INPUT:
                        disconnect_element['connection_in_ids'].append(
                            connection.connection_id)
                    else:
                        disconnect_element['connection_out_ids'].append(
                            connection.connection_id)

                    disconnect_list.append(disconnect_element)

        if disconnect_list:
            for disconnect_element in disconnect_list:
                for group in canvas.group_list:
                    if group.group_id == disconnect_element['group_id']:
                        if (group.split
                                and disconnect_element['connection_in_ids']
                                and disconnect_element['connection_out_ids']):
                            ins_label = " (inputs)"
                            outs_label = " (outputs)"

                            if group.icon_type == ICON_HARDWARE:
                                ins_label = " (playbacks)"
                                outs_label = " (captures)"

                            act_x_disc1 = discMenu.addAction(
                                group.group_name + outs_label)
                            act_x_disc1.setIcon(CanvasGetIcon(
                                group.icon_type, group.icon_name, PORT_MODE_OUTPUT))
                            act_x_disc1.setData(
                                disconnect_element['connection_out_ids'])
                            act_x_disc1.triggered.connect(
                                canvas.qobject.PortContextMenuDisconnect)

                            act_x_disc2 = discMenu.addAction(
                                group.group_name + ins_label)
                            act_x_disc2.setIcon(CanvasGetIcon(
                                group.icon_type, group.icon_name, PORT_MODE_INPUT))
                            act_x_disc2.setData(
                                disconnect_element['connection_in_ids'])
                            act_x_disc2.triggered.connect(
                                canvas.qobject.PortContextMenuDisconnect)
                        else:
                            port_mode = PORT_MODE_NULL
                            if not disconnect_element['connection_in_ids']:
                                port_mode = PORT_MODE_OUTPUT
                            elif not disconnect_element['connection_out_ids']:
                                port_mode = PORT_MODE_INPUT

                            act_x_disc = discMenu.addAction(group.group_name)
                            icon = CanvasGetIcon(
                                group.icon_type, group.icon_name, port_mode)
                            act_x_disc.setIcon(icon)
                            act_x_disc.setData(
                                disconnect_element['connection_out_ids']
                                + disconnect_element['connection_in_ids'])
                            act_x_disc.triggered.connect(
                                canvas.qobject.PortContextMenuDisconnect)
                        break
        else:
            act_x_disc = discMenu.addAction("No connections")
            act_x_disc.setEnabled(False)

        menu.addMenu(discMenu)
        act_x_disc_all = menu.addAction(
            _translate('patchbay', "Disconnect &All"))
        act_x_disc_all.setIcon(
            QIcon(QPixmap(':scalable/breeze%s/lines-disconnector' % dark)))
        act_x_sep1 = menu.addSeparator()
        act_x_info = menu.addAction(_translate('patchbay', "Info"))
        act_x_rename = menu.addAction(_translate('patchbay', "Rename"))
        act_x_sep2 = menu.addSeparator()
        split_join_name = _translate('patchbay', "Split")
        split_join_icon = QIcon.fromTheme('split')
        if self.m_splitted:
            split_join_name = _translate('patchbay', "Join")
            split_join_icon = QIcon.fromTheme('join')
        act_x_split_join = menu.addAction(split_join_name)
        act_x_split_join.setIcon(split_join_icon)

        wrap_title = _translate('patchbay', 'Wrap')
        wrap_icon = QIcon.fromTheme('pan-up-symbolic')
        if self._wrapped:
            wrap_title = _translate('patchbay', 'Unwrap')
            wrap_icon = QIcon.fromTheme('pan-down-symbolic')

        act_x_wrap = menu.addAction(wrap_title)
        act_x_wrap.setIcon(wrap_icon)

        act_x_sep3 = menu.addSeparator()

        if not features.group_info:
            act_x_info.setVisible(False)

        if not features.group_rename:
            act_x_rename.setVisible(False)

        if not (features.group_info and features.group_rename):
            act_x_sep1.setVisible(False)

        if self.m_plugin_id >= 0 and self.m_plugin_id <= MAX_PLUGIN_ID_ALLOWED:
            menu.addSeparator()
            act_p_edit = menu.addAction("Edit")
            act_p_ui = menu.addAction("Show Custom UI")
            menu.addSeparator()
            act_p_clone = menu.addAction("Clone")
            act_p_rename = menu.addAction("Rename...")
            act_p_replace = menu.addAction("Replace...")
            act_p_remove = menu.addAction("Remove")

            if not self.m_plugin_ui:
                act_p_ui.setVisible(False)

        else:
            act_p_edit = act_p_ui = None
            act_p_clone = act_p_rename = None
            act_p_replace = act_p_remove = None

        haveIns = haveOuts = False
        for port in canvas.port_list:
            if port.group_id == self.m_group_id and port.port_id in self.m_port_list_ids:
                if port.port_mode == PORT_MODE_INPUT:
                    haveIns = True
                elif port.port_mode == PORT_MODE_OUTPUT:
                    haveOuts = True

        if not (self.m_splitted or bool(haveIns and haveOuts)):
            act_x_sep2.setVisible(False)
            act_x_split_join.setVisible(False)

        act_selected = menu.exec_(event.screenPos())

        if act_selected is None:
            pass

        elif act_selected == act_x_disc_all:
            for conn_id in conn_list_ids:
                canvas.callback(ACTION_PORTS_DISCONNECT, conn_id, 0, "")

        elif act_selected == act_x_info:
            canvas.callback(ACTION_GROUP_INFO, self.m_group_id, 0, "")

        elif act_selected == act_x_rename:
            canvas.callback(ACTION_GROUP_RENAME, self.m_group_id, 0, "")

        elif act_selected == act_x_split_join:
            if self.m_splitted:
                canvas.callback(ACTION_GROUP_JOIN, self.m_group_id, 0, "")
            else:
                canvas.callback(ACTION_GROUP_SPLIT, self.m_group_id, 0, "")

        elif act_selected == act_p_edit:
            canvas.callback(ACTION_PLUGIN_EDIT, self.m_plugin_id, 0, "")

        elif act_selected == act_p_ui:
            canvas.callback(ACTION_PLUGIN_SHOW_UI, self.m_plugin_id, 0, "")

        elif act_selected == act_p_clone:
            canvas.callback(ACTION_PLUGIN_CLONE, self.m_plugin_id, 0, "")

        elif act_selected == act_p_rename:
            canvas.callback(ACTION_PLUGIN_RENAME, self.m_plugin_id, 0, "")

        elif act_selected == act_p_replace:
            canvas.callback(ACTION_PLUGIN_REPLACE, self.m_plugin_id, 0, "")

        elif act_selected == act_p_remove:
            canvas.callback(ACTION_PLUGIN_REMOVE, self.m_plugin_id, 0, "")

        elif act_selected == act_x_wrap:
            canvas.callback(ACTION_GROUP_WRAP, self.m_group_id,
                            self.m_splitted_mode, str(not self._wrapped))

    def keyPressEvent(self, event):
        if self.m_plugin_id >= 0 and event.key() == Qt.Key_Delete:
            event.accept()
            canvas.callback(ACTION_PLUGIN_REMOVE, self.m_plugin_id, 0, "")
            return
        QGraphicsItem.keyPressEvent(self, event)

    def hoverEnterEvent(self, event):
        if options.auto_select_items:
            if len(canvas.scene.selectedItems()) > 0:
                canvas.scene.clearSelection()
            self.setSelected(True)
        QGraphicsItem.hoverEnterEvent(self, event)

    def mouseDoubleClickEvent(self, event):
        if self.m_plugin_id >= 0:
            event.accept()
            canvas.callback(ACTION_PLUGIN_SHOW_UI if self.m_plugin_ui else ACTION_PLUGIN_EDIT, self.m_plugin_id, 0, "")
            return

        QGraphicsItem.mouseDoubleClickEvent(self, event)

    def mousePressEvent(self, event):
        print('erkoogkokllddl', event.button(), Qt.MidButton, Qt.MiddleButton, Qt.LeftButton)
        canvas.last_z_value += 1
        self.setZValue(canvas.last_z_value)
        self.resetLinesZValue()
        self.m_cursor_moving = False

        if event.button() == Qt.RightButton:
            event.accept()
            canvas.scene.clearSelection()
            self.setSelected(True)
            self.m_mouse_down = False
            return

        elif event.button() == Qt.LeftButton:
            if QApplication.keyboardModifiers() & Qt.ShiftModifier:
                boxes = self._get_adjacent_boxes()
                for box in boxes:
                    box.setSelected(True)
                return
            
            if self.sceneBoundingRect().contains(event.scenePos()):
                if self._wrapped:
                    # unwrap the box if event is one of the triangles zones
                    ypos = canvas.theme.box_header_height
                    if len(self._title_lines) >= 3:
                        ypos += 14

                    triangle_rect_out = QRectF(
                        0, ypos, 24, ypos + canvas.theme.port_spacing)
                    triangle_rect_in = QRectF(
                        self.p_width - 24, ypos,
                        24, ypos + canvas.theme.port_spacing)

                    mode = PORT_MODE_INPUT
                    wrap = False

                    for trirect in triangle_rect_out, triangle_rect_in:
                        trirect.translate(self.scenePos())
                        if (self.m_current_port_mode & mode
                                and trirect.contains(event.scenePos())):
                            wrap = True
                            break

                        mode = PORT_MODE_OUTPUT

                    if wrap:
                        CanvasCallback(
                            ACTION_GROUP_WRAP, self.m_group_id,
                            self.m_splitted_mode, 'False')
                        return

                self.m_mouse_down = True
            else:
                # FIXME: Check if still valid: Fix a weird Qt behaviour with right-click mouseMove
                self.m_mouse_down = False
                event.ignore()
                return

        else:
            self.m_mouse_down = False

        QGraphicsItem.mousePressEvent(self, event)

    def mouseMoveEvent(self, event):
        if canvas.scene.resizing_scene:
            # QGraphicsScene.setSceneRect calls this method
            # and resize_the_scene can be called from this method
            # So, here we avoid a RecursionError
            return

        if self.m_mouse_down:
            if not self.m_cursor_moving:
                self.setCursor(QCursor(Qt.SizeAllCursor))
                self.m_cursor_moving = True
                canvas.scene.fix_temporary_scroll_bars()

            QGraphicsItem.mouseMoveEvent(self, event)

            self.repaintLines()
            canvas.scene.resize_the_scene()
            return

        QGraphicsItem.mouseMoveEvent(self, event)

    def mouseReleaseEvent(self, event):
        if self.m_cursor_moving:
            self.unsetCursor()
            self.repaintLines(forced=True)
            canvas.scene.reset_scroll_bars()
            self.fixPosAfterMove()
            self._deplace_other_boxes()
            QTimer.singleShot(0, canvas.scene.update)

        self.m_mouse_down = False

        if (QApplication.keyboardModifiers() & Qt.ShiftModifier
                and not self.m_cursor_moving):
            return
        
        self.m_cursor_moving = False
        
        QGraphicsItem.mouseReleaseEvent(self, event)

    def fixPos(self):
        self.setX(round(self.x()))
        self.setY(round(self.y()))

    def send_move_callback(self):
        x_y_str = "%i:%i" % (round(self.x()), round(self.y()))
        CanvasCallback(ACTION_GROUP_MOVE, self.m_group_id,
                       self.m_splitted_mode, x_y_str)

        for group in canvas.group_list:
            if group.group_id == self.m_group_id:
                pos = QPoint(round(self.x()), round(self.y()))

                if self.m_splitted_mode == PORT_MODE_NULL:
                    group.null_pos = pos
                elif self.m_splitted_mode == PORT_MODE_INPUT:
                    group.in_pos = pos
                elif self.m_splitted_mode == PORT_MODE_OUTPUT:
                    group.out_pos = pos
                break

    def fixPosAfterMove(self):
        for item in canvas.scene.selectedItems():
            if item.type() == CanvasBoxType:
                item.fixPos()
                item.send_move_callback()

    def boundingRect(self):
        if self._is_hardware:
            return QRectF(-6, -6, self.p_width + 12, self.p_height + 12)
        return QRectF(0, 0, self.p_width, self.p_height)

    def paint(self, painter, option, widget):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing,
                              bool(options.antialiasing == ANTIALIASING_FULL))

        # Draw rectangle
        pen = QPen(canvas.theme.box_pen_sel if self.isSelected() else canvas.theme.box_pen)
        pen.setWidthF(pen.widthF() + 0.00001)
        painter.setPen(pen)
        brush = painter.brush()
        lineHinting = pen.widthF() / 2

        if self._is_hardware:
            d = 6
            hw_gradient = QLinearGradient(-d, -d, self.p_width +d, self.p_height +d)
            hw_gradient.setColorAt(0, QColor(70, 70, 50))
            hw_gradient.setColorAt(1, QColor(50, 50, 30))
            painter.setBrush(hw_gradient)
            painter.setPen(QPen(QColor(30, 30, 30), 1))
            if self.m_splitted:
                hardware_poly = QPolygonF()

                if self.m_splitted_mode == PORT_MODE_INPUT:
                    hardware_poly += QPointF(- lineHinting, - lineHinting)
                    hardware_poly += QPointF(- lineHinting, 34)
                    hardware_poly += QPointF(-d /2.0, 34)
                    hardware_poly += QPointF(-d, 34 - d / 2.0)
                    hardware_poly += QPointF(-d, -d / 2.0)
                    hardware_poly += QPointF(-d / 2.0, -d)
                    hardware_poly += QPointF(self.p_width + d/2.0, -d)
                    hardware_poly += QPointF(self.p_width + d, -d / 2.0)
                    hardware_poly += QPointF(self.p_width + d, self.p_height + d/2.0)
                    hardware_poly += QPointF(self.p_width + d/2.0, self.p_height + d)
                    hardware_poly += QPointF(-d/2.0, self.p_height +d)
                    hardware_poly += QPointF(-d, self.p_height +d/2.0)
                    hardware_poly += QPointF(-d, self.p_height -3 + d/2.0)
                    hardware_poly += QPointF(-d/2.0, self.p_height -3)
                    hardware_poly += QPointF(- lineHinting, self.p_height -3)
                    hardware_poly += QPointF(- lineHinting, self.p_height + lineHinting)
                    hardware_poly += QPointF(self.p_width + lineHinting,
                                             self.p_height + lineHinting)
                    hardware_poly += QPointF(self.p_width + lineHinting, - lineHinting)
                else:
                    hardware_poly += QPointF(self.p_width + lineHinting, - lineHinting)
                    hardware_poly += QPointF(self.p_width + lineHinting, 34)
                    hardware_poly += QPointF(self.p_width + d/2.0, 34)
                    hardware_poly += QPointF(self.p_width + d, 34 - d/2.0)
                    hardware_poly += QPointF(self.p_width +d, -d / 2.0)
                    hardware_poly += QPointF(self.p_width + d/2.0, -d)
                    hardware_poly += QPointF(-d / 2.0, -d)
                    hardware_poly += QPointF(-d, -d/2.0)
                    hardware_poly += QPointF(-d, self.p_height + d/2.0)
                    hardware_poly += QPointF(-d/2.0, self.p_height + d)
                    hardware_poly += QPointF(self.p_width + d/2.0, self.p_height + d)
                    hardware_poly += QPointF(self.p_width + d, self.p_height + d/2.0)
                    hardware_poly += QPointF(self.p_width +d, self.p_height -3 + d/2.0)
                    hardware_poly += QPointF(self.p_width + d/2, self.p_height -3)
                    hardware_poly += QPointF(self.p_width + lineHinting, self.p_height -3)
                    hardware_poly += QPointF(self.p_width + lineHinting,
                                             self.p_height + lineHinting)
                    hardware_poly += QPointF(-lineHinting, self.p_height + lineHinting)
                    hardware_poly += QPointF(-lineHinting, -lineHinting)

                painter.drawPolygon(hardware_poly)
            else:
                hw_poly_top = QPolygonF()
                hw_poly_top += QPointF(-lineHinting, -lineHinting)
                hw_poly_top += QPointF(-lineHinting, 34)
                hw_poly_top += QPointF(-d /2.0, 34)
                hw_poly_top += QPointF(-d, 34 - d / 2.0)
                hw_poly_top += QPointF(-d, -d / 2.0)
                hw_poly_top += QPointF(-d / 2.0, -d)
                hw_poly_top += QPointF(self.p_width + d/2.0, -d)
                hw_poly_top += QPointF(self.p_width + d, -d / 2.0)
                hw_poly_top += QPointF(self.p_width + d, 34 - d/2)
                hw_poly_top += QPointF(self.p_width+ d/2, 34)
                hw_poly_top += QPointF(self.p_width + lineHinting, 34)
                hw_poly_top += QPointF(self.p_width + lineHinting, -lineHinting)
                painter.drawPolygon(hw_poly_top)

                hw_poly_bt = QPolygonF()
                hw_poly_bt += QPointF(-lineHinting, self.p_height + lineHinting)
                hw_poly_bt += QPointF(-lineHinting, self.p_height -3)
                hw_poly_bt += QPointF(-d/2, self.p_height -3)
                hw_poly_bt += QPointF(-d, self.p_height -3 + d/2)
                hw_poly_bt += QPointF(-d, self.p_height + d/2)
                hw_poly_bt += QPointF(-d/2, self.p_height + d)
                hw_poly_bt += QPointF(self.p_width + d/2, self.p_height + d)
                hw_poly_bt += QPointF(self.p_width +d, self.p_height + d/2)
                hw_poly_bt += QPointF(self.p_width +d, self.p_height -3 + d/2)
                hw_poly_bt += QPointF(self.p_width +d/2, self.p_height -3)
                hw_poly_bt += QPointF(self.p_width + lineHinting, self.p_height -3)
                hw_poly_bt += QPointF(self.p_width + lineHinting, self.p_height + lineHinting)
                painter.drawPolygon(hw_poly_bt)

            pen = QPen(canvas.theme.box_pen_sel if self.isSelected() else canvas.theme.box_pen)
            pen.setWidthF(pen.widthF() + 0.00001)
            painter.setPen(pen)
            painter.setBrush(brush)

        rect = QRectF(0, 0, self.p_width, self.p_height)

        if canvas.theme.box_bg_type == Theme.THEME_BG_GRADIENT:
            box_gradient = QLinearGradient(0, 0, 0, self.p_height)
            box_gradient.setColorAt(0, canvas.theme.box_bg_1)
            box_gradient.setColorAt(1, canvas.theme.box_bg_2)
            painter.setBrush(box_gradient)

        else:
            painter.setBrush(canvas.theme.box_bg_1)

        rect.adjust(lineHinting, lineHinting, -lineHinting, -lineHinting)
        painter.drawRect(rect)

        # Draw plugin inline display if supported
        self.paintInlineDisplay(painter)

        # Draw pixmap header
        rect.setHeight(canvas.theme.box_header_height)
        if canvas.theme.box_header_pixmap:
            painter.setPen(Qt.NoPen)
            painter.setBrush(canvas.theme.box_bg_2)

            # outline
            rect.adjust(lineHinting, lineHinting, -lineHinting, -lineHinting)
            painter.drawRect(rect)

            rect.adjust(1, 1, -1, 0)
            painter.drawTiledPixmap(rect, canvas.theme.box_header_pixmap, rect.topLeft())

        # Draw text
        title_x_pos = 8
        if self.has_top_icon():
            title_x_pos += 25

        for title_line in self._title_lines:
            title_line.x = title_x_pos
            title_line.y = canvas.theme.box_text_ypos

        if len(self._title_lines) >= 2:
            if self._title_lines[0].is_little:
                self._title_lines[0].y -= 7
                self._title_lines[1].y += 9
                if len(self._title_lines) >= 3:
                    self._title_lines[2].y += 24
            else:
                if len(self._title_lines) == 4:
                    self._title_lines[0].y -= 9
                    self._title_lines[1].y += 2
                    self._title_lines[2].y += 13
                    self._title_lines[3].y += 24
                else:
                    self._title_lines[0].y -= 6
                    self._title_lines[1].y += 9
                    if len(self._title_lines) >= 3:
                        self._title_lines[2].y += 24


        max_title_size = 0
        for title_line in self._title_lines:
            max_title_size = max(max_title_size, title_line.size)

        # may draw horizontal lines around title
        # and set x on title lines
        painter.setPen(QPen(QColor(255, 192, 0, 80), 1))

        if self.has_top_icon():
            title_x_pos = 29 + (self.p_width - 29 - max_title_size) / 2

            if title_x_pos > 43:
                painter.drawLine(5, 16, title_x_pos -29 -5, 16)
                painter.drawLine(
                    title_x_pos + max_title_size + 5, 16,
                    self.p_width -5, 16)

            for title_line in self._title_lines:
                title_line.x = title_x_pos
        else:
            left_xpos = self.p_width
            right_xpos = 0

            for title_line in self._title_lines:
                title_line.x = (self.p_width - title_line.size) / 2
                left_xpos = min(left_xpos, title_line.x)
                right_xpos = max(right_xpos, title_line.x + title_line.size)

            if left_xpos > 10:
                painter.drawLine(5, 16, left_xpos - 5, 16)
                painter.drawLine(right_xpos + 5, 16,
                                 self.p_width - 5, 16)

        if self.isSelected():
            painter.setPen(canvas.theme.box_text_sel)
        else:
            painter.setPen(canvas.theme.box_text)

        # draw title lines
        for title_line in self._title_lines:
            painter.setFont(title_line.font)
            painter.setOpacity(1.0)
            if title_line.is_little:
                painter.setOpacity(0.5)

            painter.drawText(title_line.x, title_line.y, title_line.text)

        if self._wrapped:
            painter.setPen(canvas.theme.box_pen)
            painter.setBrush(QColor(255, 192, 0, 80))

            for port_mode in PORT_MODE_INPUT, PORT_MODE_OUTPUT:
                if self.m_current_port_mode & port_mode:
                    side = 6
                    x = 6

                    ypos = canvas.theme.box_header_height
                    if len(self._title_lines) == 3:
                        ypos += 14

                    if port_mode == PORT_MODE_OUTPUT:
                        x = self.p_width - (x + 2 * side)

                    triangle = QPolygonF()
                    triangle += QPointF(x, ypos + 2)
                    triangle += QPointF(x + 2 * side, ypos + 2)
                    triangle += QPointF(x + side, ypos + side + 2)
                    painter.drawPolygon(triangle)

        self.repaintLines()

        painter.restore()

    def paintInlineDisplay(self, painter):
        if self.m_plugin_inline == self.INLINE_DISPLAY_DISABLED:
            return
        if not options.inline_displays:
            return

        inwidth  = self.p_width - self.p_width_in - self.p_width_out - 16
        inheight = self.p_height - canvas.theme.box_header_height - canvas.theme.box_header_spacing - canvas.theme.port_spacing - 3
        scaling  = canvas.scene.getScaleFactor() * canvas.scene.getDevicePixelRatioF()

        if self.m_plugin_id >= 0 and self.m_plugin_id <= MAX_PLUGIN_ID_ALLOWED and (
           self.m_plugin_inline == self.INLINE_DISPLAY_ENABLED or self.m_inline_scaling != scaling):
            size = "%i:%i" % (int(inwidth*scaling), int(inheight*scaling))
            data = canvas.callback(ACTION_INLINE_DISPLAY, self.m_plugin_id, 0, size)
            if data is None:
                return

            # invalidate old image first
            del self.m_inline_image

            self.m_inline_data = pack("%iB" % (data['height'] * data['stride']), *data['data'])
            self.m_inline_image = QImage(voidptr(self.m_inline_data), data['width'], data['height'], data['stride'], QImage.Format_ARGB32)
            self.m_inline_scaling = scaling
            self.m_plugin_inline = self.INLINE_DISPLAY_CACHED

        if self.m_inline_image is None:
            sys.stderr.write("ERROR: inline display image is None for\n",
                             self.m_plugin_id, self.m_group_name)
            return

        swidth = self.m_inline_image.width() / scaling
        sheight = self.m_inline_image.height() / scaling

        srcx = int(self.p_width_in + (self.p_width - self.p_width_in - self.p_width_out) / 2 - swidth / 2)
        srcy = int(canvas.theme.box_header_height + canvas.theme.box_header_spacing + 1 + (inheight - sheight) / 2)

        painter.drawImage(QRectF(srcx, srcy, swidth, sheight), self.m_inline_image)

# ------------------------------------------------------------------------------------------------------------
