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

from typing import TYPE_CHECKING
from enum import IntEnum, IntFlag

from PyQt5.QtCore import QPointF, QRectF, QSettings
from PyQt5.QtWidgets import QGraphicsItem

if TYPE_CHECKING:
    # all these classes are not importable normally because
    # it would make a circular import
    # they are imported only from IDE to get types
    from .theme import Theme
    from .theme_manager import ThemeManager
    from .scene import PatchScene
    from .box_widget import BoxWidget
    from .port_widget import PortWidget
    from .portgroup_widget import PortgroupWidget
    from .line_widget import LineWidget
    from .patchcanvas import CanvasObject


# Maximum Id for a plugin, treated as invalid/zero if above this value
MAX_PLUGIN_ID_ALLOWED = 0x7FF


class PortMode(IntFlag):
    NULL = 0x00
    INPUT = 0x01
    OUTPUT = 0x02
    BOTH = INPUT | OUTPUT


class PortType(IntFlag):
    NULL = 0x00
    AUDIO_JACK = 0x01
    MIDI_JACK = 0x02
    MIDI_ALSA = 0x04
    PARAMETER = 0x08


# Callback Actions
class CallbackAct(IntEnum):
    GROUP_INFO = 0          # group_id: int
    GROUP_RENAME = 1        # group_id: int
    GROUP_SPLIT = 2         # group_id: int
    GROUP_JOIN = 3          # group_id: int
    GROUP_JOINED = 4        # group_id: int
    GROUP_MOVE = 5          # group_id: int, splitted_mode: PortMode, x: int, y: int
    GROUP_WRAP = 6          # group_id: int, folded: bool
    GROUP_LAYOUT_CHANGE = 7 # group_id: int, layout_mode: BoxLayoutMode, splitted_mode: PortMode
    PORTGROUP_ADD = 8       # group_id: int, portgrp_id: int, port_mode: PortMode,
                            #      port_type: PortType, port_ids: tuple[int]
    PORTGROUP_REMOVE = 9    # group_id: int, portgrp_id: int
    PORT_INFO = 10          # group_id: int, port_id: int
    PORT_RENAME = 11        # group_id: int, port_id: int
    PORTS_CONNECT = 12      # group_out_id: int, port_out_id: int,
                            #      group_in_id: int, port_in_id: int
    PORTS_DISCONNECT = 13   # conn_id: int
    PLUGIN_CLONE = 14       # plugin_id: int
    PLUGIN_EDIT = 15        # plugin_id: int
    PLUGIN_RENAME = 16      # plugin_id: int
    PLUGIN_REPLACE = 17     # plugin_id: int
    PLUGIN_REMOVE = 18      # plugin_id: int
    PLUGIN_SHOW_UI = 19     # plugin_id: int
    INLINE_DISPLAY = 20     # plugin_id: int
    BG_RIGHT_CLICK = 21     # 
    DOUBLE_CLICK = 22       # 
    CLIENT_SHOW_GUI = 23    # group_id: int, visible: bool
    THEME_CHANGED = 24      # theme_name: str


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
class BoxSplitMode(IntEnum):
    UNDEF = 0
    NO = 1
    YES = 2


# define the way ports are put in a box
class BoxLayoutMode(IntEnum):
    AUTO = 0
    HIGH = 1
    LARGE = 2


class EyeCandy(IntEnum):
    NONE = 0
    SMALL = 1 # Use boxes shadows


# For Repulsive boxes
class Direction(IntEnum):
    NONE = 0
    LEFT = 1
    RIGHT = 2
    UP = 3
    DOWN = 4


class CanvasItemType(IntEnum):
    # this enum is still here if really needed
    # but never really used.
    # Prefer use isinstance(item, type) if possible
    # because IDE will know easier with which class
    # we are dealing. 
    BOX = QGraphicsItem.UserType + 1
    ICON = QGraphicsItem.UserType + 2
    PORT = QGraphicsItem.UserType + 3
    PORTGROUP = QGraphicsItem.UserType + 4
    BEZIER_LINE = QGraphicsItem.UserType + 5
    BEZIER_LINE_MOV = QGraphicsItem.UserType + 6
    RUBBERBAND = QGraphicsItem.UserType + 7


# Canvas options
class CanvasOptionsObject:
    theme_name = ""
    auto_hide_groups = True
    auto_select_items = False
    eyecandy = EyeCandy.NONE
    inline_displays = 0
    elastic = True
    borders_navigation = True
    prevent_overlap = True
    max_port_width = 180
    
    # def __init__(self):
    #     self.theme_name = ""
    #     self.auto_hide_groups = True
    #     self.auto_select_items = False
    #     self.eyecandy = EyeCandy.SMALL
    #     self.inline_displays = 0
    #     self.elastic = True
    #     self.borders_navigation = True
    #     self.prevent_overlap = True
    #     self.max_port_width = 180


# Canvas features
class CanvasFeaturesObject:
    group_info = False
    group_rename = False
    port_info = True
    port_rename = False
    handle_group_pos = False
    
    # def __init__(self):
    #     self.group_info = False
    #     self.group_rename = False
    #     self.port_info = True
    #     self.port_rename = False
    #     self.handle_group_pos = False


# Main Canvas object
class Canvas:
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
        self.clipboard = list[ClipboardElement]()
        self.clipboard_cut = True
        self.group_plugin_map = {}

        self.scene = None
        self.last_z_value = 0
        self.last_connection_id = 0
        self.initial_pos = QPointF(0, 0)
        self.size_rect = QRectF()

        self.is_line_mov = False
        self.semi_hide_opacity = 0.17
        self.loading_items = False
        
        # This is only to get object methods in IDE everywhere.
        if TYPE_CHECKING:
            self.qobject = CanvasObject()
            self.theme = Theme()
            self.theme_manager = ThemeManager()
            self.scene = PatchScene()
            self.settings = QSettings()
            self.options = CanvasOptionsObject()
            self.features = CanvasFeaturesObject()

    def callback(self, action: CallbackAct, value1: int,
                 value2: int, value_str: str):
        print("Canvas::callback({}, {}, {}, {})".format(
            action.name, value1, value2, value_str))

# ------------------------
        
        

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
        widgets: list[BoxWidget]

    def copy_no_widget(self):
        group_copy = GroupObject()
        group_copy.__dict__ = self.__dict__.copy()
        group_copy.widgets = [None, None]
        return group_copy


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
        widget: PortWidget

    def copy_no_widget(self):
        port_copy = PortObject()
        port_copy.__dict__ = self.__dict__.copy()
        port_copy.widget = None
        return port_copy


class PortgrpObject:
    portgrp_id: int
    group_id: int
    port_mode: PortMode
    port_type: PortType
    port_id_list: list[int]
    widget: object
    if TYPE_CHECKING:
        widget: PortgroupWidget

    def copy_no_widget(self):
        portgrp_copy = PortgrpObject()
        portgrp_copy.__dict__ = self.__dict__.copy()
        portgrp_copy.widget = None
        return portgrp_copy


class ConnectionObject:
    connection_id: int
    group_in_id: int
    port_in_id: int
    group_out_id: int
    port_out_id: int
    widget: object
    if TYPE_CHECKING:
        widget: LineWidget

    def copy_no_widget(self):
        conn_copy = ConnectionObject()
        conn_copy.__dict__ = self.__dict__.copy()
        conn_copy.widget = None
        return conn_copy

    def matches(self, group_id_1: int, port_ids_list_1: list[int],
                group_id_2: int, port_ids_list_2: list[int]) -> bool:
        if (self.group_in_id == group_id_1
            and self.port_in_id in port_ids_list_1
            and self.group_out_id == group_id_2
            and self.port_out_id in port_ids_list_2):
                return True
        elif (self.group_in_id == group_id_2
            and self.port_in_id in port_ids_list_2
            and self.group_out_id == group_id_1
            and self.port_out_id in port_ids_list_1):
                return True
        else:
            return False

    def concerns(self, group_id: int, port_ids_list: list[int]) -> bool:
        if (self.group_in_id == group_id
                and self.port_in_id in port_ids_list):
            return True
        elif (self.group_out_id == group_id
            and self.port_out_id in port_ids_list):
            return True
        else:
            return False


class ClipboardElement:
    port_type: PortType
    port_mode: PortMode
    group_id: int
    port_id: int
    group_port_ids: list[int]


# -----------------------------

# Global objects
canvas = Canvas()

options = CanvasOptionsObject()
options.theme_name = ''
options.auto_hide_groups = False
options.auto_select_items = False
options.eyecandy = EyeCandy.NONE
options.inline_displays = False
options.elastic = True
options.prevent_overlap = True
options.borders_navigation = True
options.max_port_width = 160

features = CanvasFeaturesObject()
features.group_info = False
features.group_rename = False
features.port_info = False
features.port_rename = False
features.handle_group_pos = False


