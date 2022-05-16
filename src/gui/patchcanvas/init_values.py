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
from typing import TYPE_CHECKING
from enum import IntEnum, IntFlag

from PyQt5.QtCore import QPointF, QRectF
from PyQt5.QtWidgets import QGraphicsItem

# ------------------------------------------------------------------------------------------------------------
# Imports (Theme)
# ------------------------------------------------------------------------------------------------------------
if TYPE_CHECKING:
    # all these classes are not importable normally because
    # it would make a circular import
    # they are imported only to get types for IDE
    from .theme import Theme
    from .scene import PatchScene
    from .canvasbox import CanvasBox
    from .canvasport import CanvasPort
    from .canvasportgroup import CanvasPortGroup
    from .canvasbezierline import CanvasBezierLine
    from .patchcanvas import CanvasObject


# Maximum Id for a plugin, treated as invalid/zero if above this value
MAX_PLUGIN_ID_ALLOWED = 0x7FF

# Port Mode
class PortMode(IntFlag):
    NULL = 0x00
    INPUT = 0x01
    OUTPUT = 0x02

class PortType(IntEnum):
    NULL = 0
    AUDIO_JACK = 1
    MIDI_JACK = 2
    MIDI_ALSA = 3
    PARAMETER = 4
    
# Port Type
PORT_TYPE_NULL = 0
PORT_TYPE_AUDIO_JACK = 1
PORT_TYPE_MIDI_JACK = 2
PORT_TYPE_MIDI_ALSA = 3
PORT_TYPE_PARAMETER = 4

# Callback Action
class CallbackAct(IntEnum):
    GROUP_INFO = 0 # group_id, N, N
    GROUP_RENAME = 1 # group_id, N, N
    GROUP_SPLIT = 2 # group_id, N, N
    GROUP_JOIN = 3 # group_id, N, N
    GROUP_JOINED = 4 # group_id, N, N
    GROUP_MOVE = 5 # group_id, in_or_out, "x:y"
    GROUP_WRAP = 6 # group_id, folded, N
    GROUP_LAYOUT_CHANGE = 7 # group_id, layout_mode, in_or_out
    PORTGROUP_ADD = 8 # N, N, "gId:pgId:pMode:pType:portId1:portId2"
    PORTGROUP_REMOVE = 9 # group_id, portgrp_id, N
    PORT_INFO = 10 # group_id, port_id, N
    PORT_RENAME = 11 # group_id, port_id, N
    PORTS_CONNECT = 12 # N, N, "outG:outP:inG:inP"
    PORTS_DISCONNECT = 13 # conn_id, N, N
    PLUGIN_CLONE = 14 # plugin_id, N, N
    PLUGIN_EDIT = 15 # plugin_id, N, N
    PLUGIN_RENAME = 16 # plugin_id, N, N
    PLUGIN_REPLACE = 17 # plugin_id, N, N
    PLUGIN_REMOVE = 18 # plugin_id, N, N
    PLUGIN_SHOW_UI = 19 # plugin_id, N, N
    BG_RIGHT_CLICK = 20 # N, N, N
    DOUBLE_CLICK = 21 # N, N, N
    INLINE_DISPLAY = 22 # plugin_id, N, N
    CLIENT_SHOW_GUI = 23 # group_id, visible, N
    THEME_CHANGED = 24 # N, N, "theme_name"

# Icon
class IconType(IntEnum):
    APPLICATION = 0
    HARDWARE = 1
    DISTRHO = 2
    FILE = 3
    PLUGIN = 4
    LADISH_ROOM = 5
    CLIENT = 6
    INTERNAL = 7

# Split Option
SPLIT_UNDEF = 0
SPLIT_NO = 1
SPLIT_YES = 2

# Eye-Candy Option
EYECANDY_NONE = 0
EYECANDY_SMALL = 1 # Use boxes shadows

# For Repulsive boxes
DIRECTION_NONE = 0
DIRECTION_LEFT = 1
DIRECTION_RIGHT = 2
DIRECTION_UP = 3
DIRECTION_DOWN = 4

# -----------------------------------

# object types
CanvasBoxType = QGraphicsItem.UserType + 1
CanvasIconType = QGraphicsItem.UserType + 2
CanvasPortType = QGraphicsItem.UserType + 3
CanvasPortGroupType = QGraphicsItem.UserType + 4
CanvasBezierLineType = QGraphicsItem.UserType + 5
CanvasBezierLineMovType = QGraphicsItem.UserType + 6
CanvasRubberbandType = QGraphicsItem.UserType + 7

# -----------------------------------

# Canvas options
class CanvasOptionsObject:
    theme_name: str
    auto_hide_groups: bool
    auto_select_items: bool
    eyecandy: int
    inline_displays: int
    elastic: bool
    prevent_overlap: bool
    max_port_width: int

# Canvas features
class CanvasFeaturesObject:
    group_info: bool
    group_rename: bool
    port_info: bool
    port_rename: bool
    handle_group_pos: bool


# Main Canvas object
class Canvas(object):
    def __init__(self):
        self.qobject = None
        self.settings = None
        self.theme = None
        
        self.initiated = False
        self.theme_paths = ()
        self.theme_manager = None

        self.group_list = list[GroupObject]()
        self.port_list = list[PortObject]()
        self.portgrp_list = list[PortgrpObject]()
        self.connection_list = list[ConnectionObject]()
        self.animation_list = []
        self.clipboard = []
        self.clipboard_cut = True
        self.group_plugin_map = {}

        self.callback = self.callback
        self.debug = False
        self.scene = None
        self.last_z_value = 0
        self.last_connection_id = 0
        self.initial_pos = QPointF(0, 0)
        self.size_rect = QRectF()

        self.is_line_mov = False
        self.semi_hide_opacity = 0.17
        self.loading_items = False
        
        # This is only to get theme object methods in IDE
        # everywhere.
        if TYPE_CHECKING:
            self.qobject = CanvasObject()
            self.theme = Theme()
            self.scene = PatchScene()

    def callback(self, action, value1, value2, value_str):
        print("Canvas::callback({}, {}, {}, {})".format(
            action, value1, value2, value_str))

# ------------------------------------------------------------------------------------------------------------

# object lists            
class GroupObject:
    group_id: int
    group_name: str
    split: int
    icon_type: int
    icon_name: str
    layout_modes: int
    plugin_id: int
    plugin_ui: int # to verify
    plugin_inline: int # to verify
    null_pos: tuple
    in_pos: tuple
    out_pos: tuple
    handle_client_gui: bool
    gui_visible: bool
    widgets: list
    if TYPE_CHECKING:
        widgets: list[CanvasBox]


class PortObject:
    group_id: int
    port_id: int
    port_name: str
    port_mode: PortMode
    port_type: PortType
    portgrp_id: int
    is_alternate: bool
    widget: object
    if TYPE_CHECKING:
        widget: CanvasPort


class PortgrpObject:
    portgrp_id: int
    group_id: int
    port_mode: PortMode
    port_type: PortType
    port_id_list: list[int]
    widget: object
    if TYPE_CHECKING:
        widget: CanvasPortGroup


class ConnectionObject:
    connection_id: int
    group_in_id: int
    port_in_id: int
    group_out_id: int
    port_out_id: int
    widget: object
    if TYPE_CHECKING:
        widget: CanvasBezierLine


class ClipboardElement:
    port_type: PortType
    port_mode: PortMode
    group_id: int
    port_id: int
    group_port_ids: list[int]


# ------------------------------------------------------------------------------------------------------------

# Internal functions
def bool2str(check: bool) -> str:
    return str(bool(check))

def split2str(split):
    if split == SPLIT_UNDEF:
        return "SPLIT_UNDEF"
    elif split == SPLIT_NO:
        return "SPLIT_NO"
    elif split == SPLIT_YES:
        return "SPLIT_YES"
    else:
        return "SPLIT_???"

# ------------------------------------------------------------------------------------------------------------

# Global objects
canvas = Canvas()

options = CanvasOptionsObject()
options.theme_name = ''
options.auto_hide_groups = False
options.auto_select_items = False
options.eyecandy = EYECANDY_NONE
options.inline_displays = False
options.elastic = True
options.prevent_overlap = True
options.max_port_width = 160

features = CanvasFeaturesObject()
features.group_info = False
features.group_rename = False
features.port_info = False
features.port_rename = False
features.handle_group_pos = False


