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

import sys

from PyQt5.QtCore import qCritical, QPointF, QTimer, QFile
from PyQt5.QtGui import QIcon

# ------------------------------------------------------------------------------------------------------------
# Imports (Custom)

from . import (bool2str, canvas, CanvasBoxType,
               ICON_APPLICATION, ICON_CLIENT, ICON_HARDWARE, ICON_INTERNAL,
               PORT_MODE_NULL, PORT_MODE_INPUT, PORT_MODE_OUTPUT,
               ACTION_PORTS_CONNECT, ACTION_PORTS_DISCONNECT)
from .canvasfadeanimation import CanvasFadeAnimation

# ------------------------------------------------------------------------------------------------------------

def CanvasGetNewGroupPositions()->tuple:
    rect = canvas.scene.get_new_scene_rect()
    if rect.isNull():
        return ((200, 0), (400, 0), (0, 0))

    y = rect.bottom() + 20

    return ((rect.left() + rect.width() / 2, y),
            (rect.right() - 50, y),
            (rect.left(), y))

def CanvasGetNewGroupPos(horizontal):
    if canvas.debug:
        print("PatchCanvas::CanvasGetNewGroupPos(%s)" % bool2str(horizontal))

    new_pos = QPointF(canvas.initial_pos)
    items = canvas.scene.items()

    break_loop = False
    while not break_loop:
        break_for = False
        for i, item in enumerate(items):
            if item and item.type() == CanvasBoxType:
                if item.sceneBoundingRect().contains(new_pos):
                    if horizontal:
                        new_pos += QPointF(item.boundingRect().width() + 15, 0)
                    else:
                        new_pos += QPointF(0, item.boundingRect().height() + 15)
                    break_for = True
                    break

            if i >= len(items) - 1 and not break_for:
                break_loop = True

    return new_pos

def CanvasGetFullPortName(group_id, port_id):
    if canvas.debug:
        print("PatchCanvas::CanvasGetFullPortName(%i, %i)" % (group_id, port_id))

    for port in canvas.port_list:
        if port.group_id == group_id and port.port_id == port_id:
            group_id = port.group_id
            for group in canvas.group_list:
                if group.group_id == group_id:
                    return group.group_name + ":" + port.port_name
            break

    qCritical("PatchCanvas::CanvasGetFullPortName(%i, %i) - unable to find port" % (group_id, port_id))
    return ""

def CanvasGetPortConnectionList(group_id, port_id):
    if canvas.debug:
        print("PatchCanvas::CanvasGetPortConnectionList(%i, %i)"
              % (group_id, port_id))

    conn_list = []

    for connection in canvas.connection_list:
        if (connection.group_out_id == group_id
                and connection.port_out_id == port_id):
            conn_list.append((connection.connection_id,
                              connection.group_in_id,
                              connection.port_in_id))
        elif (connection.group_in_id == group_id
                and connection.port_in_id == port_id):
            conn_list.append((connection.connection_id,
                              connection.group_out_id,
                              connection.port_out_id))

    return conn_list

def CanvasGetPortGroupPosition(group_id: int, port_id: int,
                               portgrp_id: int)->tuple:
    if portgrp_id <= 0:
        return (0, 1)
    
    for portgrp in canvas.portgrp_list:
        if (portgrp.group_id == group_id
                and portgrp.portgrp_id == portgrp_id):
            for i in range(len(portgrp.port_id_list)):
                if port_id == portgrp.port_id_list[i]:
                    return (i, len(portgrp.port_id_list))
    return (0, 1)

def CanvasGetPortGroupName(group_id: int, ports_ids_list: list)->str:
    ports_names = []
    
    for port in canvas.port_list:
        if port.group_id == group_id and port.port_id in ports_ids_list:
            ports_names.append(port.port_name)
    
    if len(ports_names) < 2:
        return ''
    
    portgrp_name_ends = (' ', '_', '.', '-', '#', ':', 'out', 'in', 'Out',
                         'In', 'Output', 'Input', 'output', 'input' )
    
    # set portgrp name
    portgrp_name = ''
    check_character = True
    
    for c in ports_names[0]:        
        for eachname in ports_names:
            if not eachname.startswith(portgrp_name + c):
                check_character = False
                break
        if not check_character:
            break
        portgrp_name += c
    
    # reduce portgrp name until it ends with one of the characters
    # in portgrp_name_ends
    check = False
    while not check:
        for x in portgrp_name_ends:
            if portgrp_name.endswith(x):
                check = True
                break
        
        if len(portgrp_name) == 0 or portgrp_name in ports_names:
            check = True
            
        if not check:
            portgrp_name = portgrp_name[:-1]
    
    return portgrp_name

def CanvasGetPortPrintName(group_id, port_id, portgrp_id):
    for portgrp in canvas.portgrp_list:
        if (portgrp.group_id == group_id
                and portgrp.portgrp_id == portgrp_id):
            portgrp_name = CanvasGetPortGroupName(group_id,
                                                     portgrp.port_id_list)
            for port in canvas.port_list:
                if port.group_id == group_id and port.port_id == port_id:
                    return port.port_name.replace(portgrp_name, '', 1)

def CanvasGetPortGroupPortList(group_id: int, portgrp_id: int)->list:
    for portgrp in canvas.portgrp_list:
        if (portgrp.group_id == group_id
                and portgrp.portgrp_id == portgrp_id):
            return portgrp.port_id_list
    return []

def CanvasGetPortGroupFullName(group_id, portgrp_id):
    for portgrp in canvas.portgrp_list:
        if (portgrp.group_id == group_id
                and portgrp.portgrp_id == portgrp_id):
            group_name = ""
            for group in canvas.group_list:
                if group.group_id == group_id:
                    group_name = group.group_name
                    break
            else:
                return ""
            
            endofname = ''
            for port_id in portgrp.port_id_list:
                endofname += "%s/" % CanvasGetPortPrintName(group_id, port_id,
                                                     portgrp.portgrp_id)
            portgrp_name = CanvasGetPortGroupName(group_id, 
                                                     portgrp.port_id_list)
            
            return "%s:%s %s" % (group_name, portgrp_name, endofname[:-1])
    
    return ""

def CanvasConnectionMatches(connection, group_id_1: int, port_ids_list_1: list,
                            group_id_2: int, port_ids_list_2: list)->bool:
    if (connection.group_in_id == group_id_1
        and connection.port_in_id in port_ids_list_1
        and connection.group_out_id == group_id_2
        and connection.port_out_id in port_ids_list_2):
            return True
    elif (connection.group_in_id == group_id_2
          and connection.port_in_id in port_ids_list_2
          and connection.group_out_id == group_id_1
          and connection.port_out_id in port_ids_list_1):
            return True
    else:
        return False

def CanvasConnectionConcerns(connection, group_id: int, port_ids_list: list)->bool:
    if (connection.group_in_id == group_id
        and connection.port_in_id in port_ids_list):
            return True
    elif (connection.group_out_id == group_id
          and connection.port_out_id in port_ids_list):
              return True
    else:
        return False

def CanvasGetGroupIcon(group_id: int, port_mode: int):
    # port_mode is here reversed
    group_port_mode = PORT_MODE_INPUT
    if port_mode == PORT_MODE_INPUT:
        group_port_mode = PORT_MODE_OUTPUT
    
    for group in canvas.group_list:
        if group.group_id == group_id:
            if not group.split:
                group_port_mode = PORT_MODE_NULL
            
            return CanvasGetIcon(
                group.icon_type, group.icon_name, group_port_mode)
    
    return QIcon()

def CanvasGetIcon(icon_type: int, icon_name: str, port_mode: int):
    if icon_type in (ICON_CLIENT, ICON_APPLICATION):
        icon = QIcon.fromTheme(icon_name)

        if icon.isNull():
            for ext in ('svg', 'svgz', 'png'):
                filename = ":app_icons/%s.%s" % (icon_name, ext)

                if QFile.exists(filename):
                    del icon
                    icon = QIcon()
                    icon.addFile(filename)
                    break
        return icon
    
    icon = QIcon()
    
    if icon_type == ICON_HARDWARE:
        icon_file = ":/scalable/pb_hardware.svg"
        
        if icon_name == "a2j":
            icon_file = ":/scalable/DIN-5.svg"
        elif port_mode == PORT_MODE_INPUT:
            icon_file = ":/scalable/audio-headphones.svg"
        elif port_mode == PORT_MODE_OUTPUT:
            icon_file = ":/scalable/microphone.svg"
        
        icon.addFile(icon_file)
    
    elif icon_type == ICON_INTERNAL:
        icon.addFile(":/scalable/%s" % icon_name)
    
    return icon

def CanvasConnectPorts(group_id_1: int, port_id_1: int,
                       group_id_2: int, port_id_2:int):
    one_is_out = True
    
    for port in canvas.port_list:
        if port.group_id == group_id_1 and port.port_id == port_id_1:
            if port.port_mode != PORT_MODE_OUTPUT:
                one_is_out = False
            break
        elif port.group_id == group_id_2 and port.port_id == port_id_2:
            if port.port_mode == PORT_MODE_OUTPUT:
                one_is_out = False
            break
    else:
        sys.stderr.write(
            "PatchCanvas::CanvasConnectPorts, port not found %i:%i and %i:%i\n"
            % (group_id_1, port_id_1, group_id_2, port_id_2))
        return
    
    string_to_send = "%i:%i:%i:%i" % (group_id_2, port_id_2,
                                      group_id_1, port_id_1)
    if one_is_out:
        string_to_send = "%i:%i:%i:%i" % (group_id_1, port_id_1,
                                          group_id_2, port_id_2)
    
    canvas.callback(ACTION_PORTS_CONNECT, 0, 0, string_to_send)


def CanvasPortGroupConnectionState(group_id_1: int, port_id_list_1: list,
                                   group_id_2: int, port_id_list_2: list)->int:
    # returns
    # 0 if no connection
    # 1 if connection is irregular
    # 2 if connection is correct
    
    group_out_id = 0
    group_in_id = 0
    out_port_id_list = []
    in_port_id_list = []
    
    for port in canvas.port_list:
        if (port.group_id == group_id_1
                and port.port_id in port_id_list_1):
            if port.port_mode == PORT_MODE_OUTPUT:
                out_port_id_list = port_id_list_1
                group_out_id = group_id_1
            else:
                in_port_id_list = port_id_list_1
                group_in_id = group_id_1
        elif (port.group_id == group_id_2
                and port.port_id in port_id_list_2):
            if port.port_mode == PORT_MODE_OUTPUT:
                out_port_id_list = port_id_list_2
                group_out_id = group_id_2
            else:
                in_port_id_list = port_id_list_2
                group_in_id = group_id_2

    if not (out_port_id_list and in_port_id_list):
        return 0
    
    has_connection = False
    miss_connection = False
    
    for out_index in range(len(out_port_id_list)):
        for in_index in range(len(in_port_id_list)):
            if (out_index % len(in_port_id_list)
                    == in_index % len(out_port_id_list)):
                for connection in canvas.connection_list:
                    if (connection.group_out_id == group_out_id
                            and connection.port_out_id == out_port_id_list[out_index]
                            and connection.group_in_id == group_in_id
                            and connection.port_in_id == in_port_id_list[in_index]):
                        has_connection = True
                        break
                else:
                    miss_connection = True
            else:
                for connection in canvas.connection_list:
                    if (connection.group_out_id == group_out_id
                            and connection.port_out_id == out_port_id_list[out_index]
                            and connection.group_in_id == group_in_id
                            and connection.port_in_id == in_port_id_list[in_index]):
                        # irregular connection exists
                        # we are sure connection is irregular
                        return 1
    
    if has_connection:
        if miss_connection:
            return 1
        else:
            return 2
    else:
        return 0
                    

def CanvasConnectPortGroups(group_id_1: int, portgrp_id_1: int,
                            group_id_2: int, portgrp_id_2: int,
                            disconnect=False):
    group_out_id = 0
    group_in_id = 0
    out_port_id_list = []
    in_port_id_list = []
    
    for portgrp in canvas.portgrp_list:
        if (portgrp.group_id == group_id_1
                and portgrp.portgrp_id == portgrp_id_1):
            if portgrp.port_mode == PORT_MODE_OUTPUT:
                group_out_id = group_id_1
                out_port_id_list = portgrp.port_id_list
            else:
                group_in_id = group_id_1
                in_port_id_list = portgrp.port_id_list
                
        elif (portgrp.group_id == group_id_2
                and portgrp.portgrp_id == portgrp_id_2):
            if portgrp.port_mode == PORT_MODE_OUTPUT:
                group_out_id = group_id_2
                out_port_id_list = portgrp.port_id_list
            else:
                group_in_id = group_id_2
                in_port_id_list = portgrp.port_id_list
    
    if not (out_port_id_list and in_port_id_list):
        sys.stderr.write(
            "PatchCanvas::CanvasConnectPortGroups, empty port id list\n")
        return
    
    connected_indexes = []
    
    # disconnect irregular connections
    for connection in canvas.connection_list:
        if (connection.group_out_id == group_out_id
                and connection.port_out_id in out_port_id_list
                and connection.group_in_id == group_in_id
                and connection.port_in_id in in_port_id_list):
            out_index = out_port_id_list.index(connection.port_out_id)
            in_index = in_port_id_list.index(connection.port_in_id)

            if (out_index % len(in_port_id_list)
                    == in_index % len(out_port_id_list)
                    and not disconnect):
                # remember this connection already exists
                # and has not to be remade
                connected_indexes.append((out_index, in_index))
            else:
                canvas.callback(ACTION_PORTS_DISCONNECT,
                                connection.connection_id, 0, '')
    
    if disconnect:
        return
    
    # finally connect the ports
    for out_index in range(len(out_port_id_list)):
        for in_index in range(len(in_port_id_list)):
            if (out_index % len(in_port_id_list)
                        == in_index % len(out_port_id_list)
                    and (out_index, in_index) not in connected_indexes):
                canvas.callback(
                    ACTION_PORTS_CONNECT, 0, 0,
                    "%i:%i:%i:%i" % (
                        group_out_id, out_port_id_list[out_index],
                        group_in_id, in_port_id_list[in_index]))
            

def CanvasCallback(action, value1, value2, value_str):
    if canvas.debug:
        sys.stderr.write("PatchCanvas::CanvasCallback(%i, %i, %i, %s)\n"
                         % (action, value1, value2, value_str.encode()))

    canvas.callback(action, value1, value2, value_str)

def CanvasItemFX(item, show, destroy):
    if canvas.debug:
        print("PatchCanvas::CanvasItemFX(%s, %s, %s)" % (item, bool2str(show), bool2str(destroy)))

    # Check if the item already has an animation
    for animation in canvas.animation_list:
        if animation.item() == item:
            animation.forceStop()
            canvas.animation_list.remove(animation)
            del animation
            break

    animation = CanvasFadeAnimation(item, show)
    animation.setDuration(750 if show else 500)

    if show:
        animation.finished.connect(canvas.qobject.AnimationFinishedShow)
    else:
        if destroy:
            animation.finished.connect(canvas.qobject.AnimationFinishedDestroy)
        else:
            animation.finished.connect(canvas.qobject.AnimationFinishedHide)

    canvas.animation_list.append(animation)

    animation.start()

def CanvasRemoveItemFX(item):
    if canvas.debug:
        print("PatchCanvas::CanvasRemoveItemFX(%s)" % item)

    if item.type() == CanvasBoxType:
        item.removeIconFromScene()

    canvas.scene.removeItem(item)
    del item

    QTimer.singleShot(0, canvas.scene.update)

# ------------------------------------------------------------------------------------------------------------
