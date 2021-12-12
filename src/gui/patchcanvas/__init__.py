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

from PyQt5.QtCore import QPointF, QRectF
from PyQt5.QtWidgets import QGraphicsItem

# ------------------------------------------------------------------------------------------------------------
# Imports (Theme)

from .theme import get_default_theme_name

# ------------------------------------------------------------------------------------------------------------

# Maximum Id for a plugin, treated as invalid/zero if above this value
MAX_PLUGIN_ID_ALLOWED = 0x7FF

# Port Mode
PORT_MODE_NULL   = 0
PORT_MODE_INPUT  = 1
PORT_MODE_OUTPUT = 2

# Port Type
PORT_TYPE_NULL       = 0
PORT_TYPE_AUDIO_JACK = 1
PORT_TYPE_MIDI_JACK  = 2
PORT_TYPE_MIDI_ALSA  = 3
PORT_TYPE_PARAMETER  = 4

# Callback Action
ACTION_GROUP_INFO = 0 # group_id, N, N
ACTION_GROUP_RENAME = 1 # group_id, N, N
ACTION_GROUP_SPLIT = 2 # group_id, N, N
ACTION_GROUP_JOIN = 3 # group_id, N, N
ACTION_GROUP_JOINED = 4 # group_id, N, N
ACTION_GROUP_MOVE = 5 # group_id, in_or_out, "x:y"
ACTION_GROUP_WRAP = 6 # group_id, folded, N
ACTION_PORTGROUP_ADD = 7 # N, N, "gId:pgId:pMode:pType:portId1:portId2"
ACTION_PORTGROUP_REMOVE = 8 # group_id, portgrp_id, N
ACTION_PORT_INFO = 9 # group_id, port_id, N
ACTION_PORT_RENAME = 10 # group_id, port_id, N
ACTION_PORTS_CONNECT = 11 # N, N, "outG:outP:inG:inP"
ACTION_PORTS_DISCONNECT = 12 # conn_id, N, N
ACTION_PLUGIN_CLONE = 13 # plugin_id, N, N
ACTION_PLUGIN_EDIT = 14 # plugin_id, N, N
ACTION_PLUGIN_RENAME = 15 # plugin_id, N, N
ACTION_PLUGIN_REPLACE = 16 # plugin_id, N, N
ACTION_PLUGIN_REMOVE = 17 # plugin_id, N, N
ACTION_PLUGIN_SHOW_UI = 18 # plugin_id, N, N
ACTION_BG_RIGHT_CLICK = 19 # N, N, N
ACTION_DOUBLE_CLICK = 20 # N, N, N
ACTION_INLINE_DISPLAY = 21 # plugin_id, N, N
ACTION_CLIENT_SHOW_GUI = 22 # group_id, visible, N

# Icon
ICON_APPLICATION = 0
ICON_HARDWARE = 1
ICON_DISTRHO = 2
ICON_FILE = 3
ICON_PLUGIN = 4
ICON_LADISH_ROOM = 5
ICON_CLIENT = 6
ICON_INTERNAL = 7

# Split Option
SPLIT_UNDEF = 0
SPLIT_NO = 1
SPLIT_YES = 2

# Antialiasing Option
ANTIALIASING_NONE = 0
ANTIALIASING_SMALL = 1
ANTIALIASING_FULL = 2

# Eye-Candy Option
EYECANDY_NONE = 0
EYECANDY_SMALL = 1
EYECANDY_FULL = 2

# For Repulsive boxes
DIRECTION_NONE = 0
DIRECTION_LEFT = 1
DIRECTION_RIGHT = 2
DIRECTION_UP = 3
DIRECTION_DOWN = 4

# ------------------------------------------------------------------------------------------------------------



# object types
CanvasBoxType = QGraphicsItem.UserType + 1
CanvasIconType = QGraphicsItem.UserType + 2
CanvasPortType = QGraphicsItem.UserType + 3
CanvasPortGroupType = QGraphicsItem.UserType + 4
CanvasLineType = QGraphicsItem.UserType + 5
CanvasBezierLineType = QGraphicsItem.UserType + 6
CanvasLineMovType = QGraphicsItem.UserType + 7
CanvasBezierLineMovType = QGraphicsItem.UserType + 8
CanvasRubberbandType = QGraphicsItem.UserType + 9

# ------------------------------------------------------------------------------------------------------------

# Canvas options
class options_t(object):
    __slots__ = [
        'theme_name',
        'auto_hide_groups',
        'auto_select_items',
        'use_bezier_lines',
        'antialiasing',
        'eyecandy',
        'inline_displays',
        'elastic',
        'prevent_overlap',
        'max_port_width']

# Canvas features
class features_t(object):
    __slots__ = [
        'group_info',
        'group_rename',
        'port_info',
        'port_rename',
        'handle_group_pos']


# Main Canvas object
class Canvas(object):
    def __init__(self):
        self.qobject = None
        self.settings = None
        self.theme = None
        self.initiated = False

        self.group_list = []
        self.port_list = []
        self.portgrp_list = []
        self.connection_list = []
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

    def callback(self, action, value1, value2, value_str):
        print("Canvas::callback({}, {}, {}, {})".format(
            action, value1, value2, value_str))

# ------------------------------------------------------------------------------------------------------------

# object lists
class group_dict_t(object):
    __slots__ = [
        'group_id',
        'group_name',
        'split',
        'icon_type',
        'icon_name',
        'plugin_id',
        'plugin_ui',
        'plugin_inline',
        'null_pos',
        'in_pos',
        'out_pos',
        'handle_client_gui',
        'gui_visible',
        'widgets']

class port_dict_t(object):
    __slots__ = [
        'group_id',
        'port_id',
        'port_name',
        'port_mode',
        'port_type',
        'portgrp_id',
        'is_alternate',
        'widget']

    def is_connectable_to(self, other)->bool:
        if self.port_type != other.port_type:
            return False

        if self.port_mode == other.port_mode:
            return False


class portgrp_dict_t(object):
    __slots__ = [
        'portgrp_id',
        'group_id',
        'port_mode',
        'port_type',
        'port_id_list',
        'widget'
    ]

class connection_dict_t(object):
    __slots__ = [
        'connection_id',
        'group_in_id',
        'port_in_id',
        'group_out_id',
        'port_out_id',
        'widget'
    ]

class clipboard_element_dict_t:
    __slots__ = [
        'port_type',
        'port_mode',
        'group_id',
        'port_id',
        'group_port_ids']


class animation_dict_t(object):
    __slots__ = [
        'animation',
        'item'
    ]

# ------------------------------------------------------------------------------------------------------------

# Internal functions
def bool2str(check):
    return "True" if check else "False"

def port_mode2str(port_mode):
    if port_mode == PORT_MODE_NULL:
        return "PORT_MODE_NULL"
    elif port_mode == PORT_MODE_INPUT:
        return "PORT_MODE_INPUT"
    elif port_mode == PORT_MODE_OUTPUT:
        return "PORT_MODE_OUTPUT"
    else:
        return "PORT_MODE_???"

def port_type2str(port_type):
    if port_type == PORT_TYPE_NULL:
        return "PORT_TYPE_NULL"
    elif port_type == PORT_TYPE_AUDIO_JACK:
        return "PORT_TYPE_AUDIO_JACK"
    elif port_type == PORT_TYPE_MIDI_JACK:
        return "PORT_TYPE_MIDI_JACK"
    elif port_type == PORT_TYPE_MIDI_ALSA:
        return "PORT_TYPE_MIDI_ALSA"
    elif port_type == PORT_TYPE_PARAMETER:
        return "PORT_TYPE_MIDI_PARAMETER"
    else:
        return "PORT_TYPE_???"

def icon2str(icon):
    if icon == ICON_APPLICATION:
        return "ICON_APPLICATION"
    elif icon == ICON_HARDWARE:
        return "ICON_HARDWARE"
    elif icon == ICON_DISTRHO:
        return "ICON_DISTRHO"
    elif icon == ICON_FILE:
        return "ICON_FILE"
    elif icon == ICON_PLUGIN:
        return "ICON_PLUGIN"
    elif icon == ICON_LADISH_ROOM:
        return "ICON_LADISH_ROOM"
    else:
        return "ICON_???"

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

options = options_t()
options.theme_name = get_default_theme_name()
options.auto_hide_groups = False
options.auto_select_items = False
options.use_bezier_lines = True
options.antialiasing = ANTIALIASING_SMALL
options.eyecandy = EYECANDY_SMALL
options.inline_displays = False
options.elastic = True
options.prevent_overlap = True
options.max_port_width = 160

features = features_t()
features.group_info = False
features.group_rename = False
features.port_info = False
features.port_rename = False
features.handle_group_pos = False

# PatchCanvas API
def get_options_t():
    return options_t()

def get_features_t():
    return features_t()

def set_options(new_options):
    if canvas.initiated: return
    options.theme_name = new_options.theme_name
    options.auto_hide_groups = new_options.auto_hide_groups
    options.auto_select_items = new_options.auto_select_items
    options.use_bezier_lines = new_options.use_bezier_lines
    options.antialiasing = new_options.antialiasing
    options.eyecandy = new_options.eyecandy
    options.inline_displays = new_options.inline_displays
    options.elastic = new_options.elastic
    options.prevent_overlap = new_options.prevent_overlap
    options.max_port_width = new_options.max_port_width

def set_features(new_features):
    if canvas.initiated: return
    features.group_info   = new_features.group_info
    features.group_rename = new_features.group_rename
    features.port_info    = new_features.port_info
    features.port_rename  = new_features.port_rename
    features.handle_group_pos = new_features.handle_group_pos
