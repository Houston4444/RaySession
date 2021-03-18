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

from PyQt5.QtCore import (pyqtSlot, qCritical, qFatal, qWarning, QObject,
                          QPointF, QRectF, QSettings, QTimer, pyqtSignal)

# ------------------------------------------------------------------------------------------------------------
# Imports (Custom)

from . import (
    canvas,
    features,
    options,
    group_dict_t,
    port_dict_t,
    portgrp_dict_t,
    connection_dict_t,
    bool2str,
    icon2str,
    split2str,
    port_mode2str,
    port_type2str,
    CanvasIconType,
    CanvasRubberbandType,
    ACTION_PORTS_DISCONNECT,
    EYECANDY_FULL,
    ICON_APPLICATION,
    ICON_HARDWARE,
    ICON_LADISH_ROOM,
    PORT_MODE_INPUT,
    PORT_MODE_OUTPUT,
    SPLIT_YES,
    SPLIT_NO,
    SPLIT_UNDEF,
    MAX_PLUGIN_ID_ALLOWED,
)

from .canvasbox import CanvasBox
from .canvasbezierline import CanvasBezierLine
from .canvasline import CanvasLine
from .theme import Theme, getDefaultTheme, getThemeName
from .utils import (CanvasCallback, CanvasGetNewGroupPos, CanvasItemFX, 
    CanvasRemoveItemFX, CanvasGetPortGroupPosition)

# FIXME
from . import *
from .scene import PatchScene

# ------------------------------------------------------------------------------------------------------------

class CanvasObject(QObject):
    port_added = pyqtSignal(int, int)
    port_removed = pyqtSignal(int, int)
    connection_added = pyqtSignal(int)
    connection_removed = pyqtSignal(int)
    move_boxes_finished = pyqtSignal()
    
    def __init__(self, parent=None):
        QObject.__init__(self, parent)

    @pyqtSlot()
    def AnimationFinishedShow(self):
        animation = self.sender()
        if animation:
            animation.forceStop()
            canvas.animation_list.remove(animation)

    @pyqtSlot()
    def AnimationFinishedHide(self):
        animation = self.sender()
        if animation:
            animation.forceStop()
            canvas.animation_list.remove(animation)
            item = animation.item()
            if item:
                item.hide()

    @pyqtSlot()
    def AnimationFinishedDestroy(self):
        animation = self.sender()
        if animation:
            animation.forceStop()
            canvas.animation_list.remove(animation)
            item = animation.item()
            if item:
                CanvasRemoveItemFX(item)

    #@pyqtSlot()
    #def PortContextMenuConnect(self):
        #try:
            #sources, targets = self.sender().data()
        #except:
            #return

        #for port_type in (PORT_TYPE_AUDIO_JACK, PORT_TYPE_MIDI_JACK,
                          #PORT_TYPE_MIDI_ALSA):
            #source_ports = sources[port_type]
            #target_ports = targets[port_type]

            #source_ports_len = len(source_ports)
            #target_ports_len = len(target_ports)

            #if source_ports_len == 0 or target_ports_len == 0:
                #continue

            #for i in range(min(source_ports_len, target_ports_len)):
                #data = "%i:%i:%i:%i" % (source_ports[i][0],
                                        #source_ports[i][1],
                                        #target_ports[i][0],
                                        #target_ports[i][1])
                #CanvasCallback(ACTION_PORTS_CONNECT, 0, 0, data)

            #if source_ports_len == 1 and target_ports_len > 1:
                #for i in range(1, target_ports_len):
                    #data = "%i:%i:%i:%i" % (source_ports[0][0],
                                            #source_ports[0][1],
                                            #target_ports[i][0],
                                            #target_ports[i][1])
                    #CanvasCallback(ACTION_PORTS_CONNECT, 0, 0, data)

    @pyqtSlot()
    def port_context_menu_connect(self):
        try:
            all_ids = list(self.sender().data())
        except:
            return
        
        if len(all_ids) != 4:
            return
        
        group_out_id, port_out_id, group_in_id, port_in_id = all_ids
        CanvasCallback(ACTION_PORTS_CONNECT, '', '', ':'.join(all_ids))

    @pyqtSlot()
    def PortContextMenuDisconnect(self):
        try:
            con_ids_list = list(self.sender().data())
        except:
            return
        
        for connectionId in con_ids_list:
            if type(connectionId) != int:
                continue
            
            CanvasCallback(ACTION_PORTS_DISCONNECT, connectionId, 0, "")
    
    @pyqtSlot()
    def SetasStereoWith(self):
        try:
            all_data = self.sender().data()
        except:
            return
        
        port_widget = all_data[0]
        port_id = all_data[1]
        port_widget.SetAsStereo(port_id)

# ------------------------------------------------------------------------------------------------------------

def getStoredCanvasPosition(key, fallback_pos):
    try:
        return canvas.settings.value("CanvasPositions/" + key, fallback_pos, type=QPointF)
    except:
        return fallback_pos

def getStoredCanvasSplit(group_name, fallback_split_mode):
    try:
        return canvas.settings.value("CanvasPositions/%s_SPLIT" % group_name, fallback_split_mode, type=int)
    except:
        return fallback_split_mode

# ------------------------------------------------------------------------------------------------------------

def init(appName, scene, callback, debug=False):
    if debug:
        print("PatchCanvas::init(\"%s\", %s, %s, %s)" % (appName, scene, callback, bool2str(debug)))

    if canvas.initiated:
        qCritical("PatchCanvas::init() - already initiated")
        return

    if not callback:
        qFatal("PatchCanvas::init() - fatal error: callback not set")
        return

    canvas.callback = callback
    canvas.debug = debug
    canvas.scene = scene

    canvas.last_z_value = 0
    canvas.last_connection_id = 0
    canvas.initial_pos = QPointF(0, 0)
    canvas.size_rect = QRectF()

    if not canvas.qobject:
        canvas.qobject = CanvasObject()
    if not canvas.settings:
        canvas.settings = QSettings("falkTX", appName)

    if canvas.theme:
        del canvas.theme
        canvas.theme = None

    for i in range(Theme.THEME_MAX):
        this_theme_name = getThemeName(i)
        if this_theme_name == options.theme_name:
            canvas.theme = Theme(i)
            break

    if not canvas.theme:
        canvas.theme = Theme(getDefaultTheme())

    canvas.scene.updateTheme()

    canvas.initiated = True

def clear():
    if canvas.debug:
        print("PatchCanvas::clear()")

    group_list_ids = []
    port_list_ids = []
    connection_list_ids = []

    for group in canvas.group_list:
        group_list_ids.append(group.group_id)

    for port in canvas.port_list:
        port_list_ids.append((port.group_id, port.port_id))

    for connection in canvas.connection_list:
        connection_list_ids.append(connection.connection_id)

    for idx in connection_list_ids:
        disconnectPorts(idx)

    for group_id, port_id in port_list_ids:
        removePort(group_id, port_id)

    for idx in group_list_ids:
        removeGroup(idx)

    canvas.last_z_value = 0
    canvas.last_connection_id = 0

    canvas.group_list = []
    canvas.port_list = []
    canvas.portgrp_list = []
    canvas.connection_list = []
    canvas.group_plugin_map = {}

    canvas.scene.clearSelection()

    animatedItems = []
    for animation in canvas.animation_list:
        animatedItems.append(animation.item())

    for item in canvas.scene.items():
        if item.type() in (CanvasIconType, CanvasRubberbandType) or item in animatedItems:
            continue
        canvas.scene.removeItem(item)
        del item

    canvas.initiated = False

    QTimer.singleShot(0, canvas.scene.update)

# ------------------------------------------------------------------------------------------------------------

def setInitialPos(x, y):
    if canvas.debug:
        print("PatchCanvas::setInitialPos(%i, %i)" % (x, y))

    canvas.initial_pos.setX(x)
    canvas.initial_pos.setY(y)

def setCanvasSize(x, y, width, height):
    if canvas.debug:
        print("PatchCanvas::setCanvasSize(%i, %i, %i, %i)" % (x, y, width, height))

    canvas.size_rect.setX(x)
    canvas.size_rect.setY(y)
    canvas.size_rect.setWidth(width)
    canvas.size_rect.setHeight(height)
    canvas.scene.updateLimits()
    canvas.scene.fixScaleFactor()

def addGroup(group_id, group_name, split=SPLIT_UNDEF, icon_type=ICON_APPLICATION,
             icon_name='', orig_pos=None):
    if canvas.debug:
        print("PatchCanvas::addGroup(%i, %s, %s, %s)" % (
              group_id, group_name.encode(), split2str(split), icon2str(icon_type)))

    for group in canvas.group_list:
        if group.group_id == group_id:
            qWarning("PatchCanvas::addGroup(%i, %s, %s, %s) - group already exists" % (
                     group_id, group_name.encode(), split2str(split), icon2str(icon_type)))
            return

    if split == SPLIT_UNDEF:
        isHardware = bool(icon_type == ICON_HARDWARE)
        #if features.handle_group_pos:
            #split = getStoredCanvasSplit(group_name, SPLIT_YES if isHardware else split)
        #elif isHardware:
            #split = SPLIT_YES
        if isHardware:
            split = SPLIT_YES

    group_box = CanvasBox(group_id, group_name, icon_type, icon_name)

    group_dict = group_dict_t()
    group_dict.group_id = group_id
    group_dict.group_name = group_name
    group_dict.split = bool(split == SPLIT_YES)
    group_dict.icon_type = icon_type
    group_dict.icon_name = icon_name
    group_dict.plugin_id = -1
    group_dict.plugin_ui = False
    group_dict.plugin_inline = False
    group_dict.widgets = [group_box, None]

    if split == SPLIT_YES:
        group_box.setSplit(True, PORT_MODE_OUTPUT)

        if features.handle_group_pos:
            #group_box.setPos(getStoredCanvasPosition(group_name + "_OUTPUT", CanvasGetNewGroupPos(False)))
            new_pos = getStoredCanvasPosition(group_name + "_OUTPUT", CanvasGetNewGroupPos(False))
            
            if orig_pos is None:
                group_box.setPos(new_pos)
            else:
                print('kladdd', orig_pos, new_pos)
                group_box.setPos(orig_pos)
                canvas.scene.add_box_to_animation(group_box, new_pos.x(), new_pos.y())
        else:
            #group_box.setPos(CanvasGetNewGroupPos(False))
            new_pos = CanvasGetNewGroupPos(False)
            canvas.scene.add_box_to_animation(group_box, new_pos.x(), new_pos.y())

        group_sbox = CanvasBox(group_id, group_name, icon_type, icon_name)
        group_sbox.setSplit(True, PORT_MODE_INPUT)

        group_dict.widgets[1] = group_sbox

        if features.handle_group_pos:
            
            new_pos = getStoredCanvasPosition(group_name + "_INPUT", CanvasGetNewGroupPos(True))
            
            if orig_pos is None:
                group_sbox.setPos(new_pos)
            else:
                group_sbox.setPos(orig_pos)
                canvas.scene.add_box_to_animation(group_sbox, new_pos.x(), new_pos.y())
            #group_sbox.setPos(getStoredCanvasPosition(group_name + "_INPUT", CanvasGetNewGroupPos(True)))
        else:
            #group_sbox.setPos(CanvasGetNewGroupPos(True))
            new_pos = CanvasGetNewGroupPos(True)
            canvas.scene.add_box_to_animation(group_sbox, new_pos.x(), new_pos.y())

        canvas.last_z_value += 1
        group_sbox.setZValue(canvas.last_z_value)

        if options.eyecandy == EYECANDY_FULL and not options.auto_hide_groups:
            CanvasItemFX(group_sbox, True, False)

        group_sbox.checkItemPos()

    else:
        group_box.setSplit(False)

        if features.handle_group_pos:
            group_box.setPos(getStoredCanvasPosition(group_name, CanvasGetNewGroupPos(False)))
        else:
            # Special ladish fake-split groups
            horizontal = bool(icon_type in (ICON_HARDWARE, ICON_LADISH_ROOM))
            group_box.setPos(CanvasGetNewGroupPos(horizontal))

    group_box.checkItemPos()

    canvas.last_z_value += 1
    group_box.setZValue(canvas.last_z_value)

    canvas.group_list.append(group_dict)

    if options.eyecandy == EYECANDY_FULL and not options.auto_hide_groups:
        CanvasItemFX(group_box, True, False)
        return

    QTimer.singleShot(0, canvas.scene.update)

def removeGroup(group_id, save_positions=True):
    if canvas.debug:
        print("PatchCanvas::removeGroup(%i)" % group_id)

    for group in canvas.group_list:
        if group.group_id == group_id:
            item = group.widgets[0]
            group_name = group.group_name

            if group.split:
                s_item = group.widgets[1]

                if features.handle_group_pos and save_positions:
                    canvas.settings.setValue("CanvasPositions/%s_OUTPUT" % group_name, item.pos())
                    canvas.settings.setValue("CanvasPositions/%s_INPUT" % group_name, s_item.pos())
                    canvas.settings.setValue("CanvasPositions/%s_SPLIT" % group_name, SPLIT_YES)

                if options.eyecandy == EYECANDY_FULL:
                    CanvasItemFX(s_item, False, True)
                else:
                    s_item.removeIconFromScene()
                    canvas.scene.removeItem(s_item)
                    del s_item

            else:
                if features.handle_group_pos and save_positions:
                    canvas.settings.setValue("CanvasPositions/%s" % group_name, item.pos())
                    canvas.settings.setValue("CanvasPositions/%s_SPLIT" % group_name, SPLIT_NO)

            if options.eyecandy == EYECANDY_FULL:
                CanvasItemFX(item, False, True)
            else:
                item.removeIconFromScene()
                canvas.scene.removeItem(item)
                del item

            canvas.group_list.remove(group)
            canvas.group_plugin_map.pop(group.plugin_id, None)

            QTimer.singleShot(0, canvas.scene.update)
            return

    qCritical("PatchCanvas::removeGroup(%i) - unable to find group to remove" % group_id)

def renameGroup(group_id, new_group_name):
    if canvas.debug:
        print("PatchCanvas::renameGroup(%i, %s)" % (group_id, new_group_name.encode()))

    for group in canvas.group_list:
        if group.group_id == group_id:
            group.group_name = new_group_name
            group.widgets[0].setGroupName(new_group_name)

            if group.split and group.widgets[1]:
                group.widgets[1].setGroupName(new_group_name)

            QTimer.singleShot(0, canvas.scene.update)
            return

    qCritical("PatchCanvas::renameGroup(%i, %s) - unable to find group to rename" % (group_id, new_group_name.encode()))

def splitGroup(group_id):
    if canvas.debug:
        print("PatchCanvas::splitGroup(%i)" % group_id)

    item = None
    group_name = ""
    group_icon_type = ICON_APPLICATION
    group_icon_name = ""
    plugin_id = -1
    plugin_ui = False
    plugin_inline = False
    portgrps_data = []
    ports_data = []
    conns_data = []

    # Step 1 - Store all Item data
    for group in canvas.group_list:
        if group.group_id == group_id:
            if group.split:
                qCritical("PatchCanvas::splitGroup(%i) - group is already split" % group_id)
                return

            item = group.widgets[0]
            group_name = group.group_name
            group_icon_type = group.icon_type
            group_icon_name = group.icon_name
            plugin_id = group.plugin_id
            plugin_ui = group.plugin_ui
            plugin_inline = group.plugin_inline
            break

    if not item:
        qCritical("PatchCanvas::splitGroup(%i) - unable to find group to split" % group_id)
        return

    for portgrp in canvas.portgrp_list:
        if portgrp.group_id == group_id:
            portgrp_dict = portgrp_dict_t()
            portgrp_dict.group_id = portgrp.group_id
            portgrp_dict.portgrp_id = portgrp.portgrp_id
            portgrp_dict.port_type = portgrp.port_type
            portgrp_dict.port_mode = portgrp.port_mode
            portgrp_dict.port_id_list = portgrp.port_id_list.copy()
            portgrp_dict.widget = None
            portgrps_data.append(portgrp_dict)

    for port in canvas.port_list:
        if port.group_id == group_id:
            port_dict = port_dict_t()
            port_dict.group_id = port.group_id
            port_dict.port_id = port.port_id
            port_dict.port_name = port.port_name
            port_dict.port_mode = port.port_mode
            port_dict.port_type = port.port_type
            port_dict.portgrp_id = 0
            port_dict.is_alternate = port.is_alternate
            port_dict.widget = None
            ports_data.append(port_dict)

    for connection in canvas.connection_list:
        if (connection.group_out_id == group_id
                or connection.group_in_id == group_id):
            connection_dict = connection_dict_t()
            connection_dict.connection_id = connection.connection_id
            connection_dict.group_in_id = connection.group_in_id
            connection_dict.port_in_id = connection.port_in_id
            connection_dict.group_out_id = connection.group_out_id
            connection_dict.port_out_id = connection.port_out_id
            connection_dict.widget = None
            conns_data.append(connection_dict)

    # Step 2 - Remove Item and Children
    for conn in conns_data:
        disconnectPorts(conn.connection_id)
    
    for portgrp in portgrps_data:
        if portgrp.group_id == group_id:
            removePortGroup(group_id, portgrp.portgrp_id, fast=True)
    
    for port in ports_data:
        if port.group_id == group_id:
            removePort(group_id, port.port_id, fast=True)

    ex_pos = item.pos()

    removeGroup(group_id)

    # Step 3 - Re-create Item, now split
    addGroup(group_id, group_name, SPLIT_YES,
             group_icon_type, group_icon_name, orig_pos=ex_pos)

    if plugin_id >= 0:
        setGroupAsPlugin(group_id, plugin_id, plugin_ui, plugin_inline)
    
    for port in ports_data:
        addPort(group_id, port.port_id, port.port_name, port.port_mode,
                port.port_type, port.is_alternate, fast=True)
        
    for portgrp in portgrps_data:
        addPortGroup(group_id, portgrp.portgrp_id, portgrp.port_mode,
                     portgrp.port_type, portgrp.port_id_list, fast=True)

    for conn in conns_data:
        connectPorts(conn.connection_id, conn.group_out_id, conn.port_out_id,
                     conn.group_in_id, conn.port_in_id)
    
    for group in canvas.group_list:
        if group.group_id == group_id:
            for box in group.widgets:
                if box is not None:
                    box.updatePositions()

    QTimer.singleShot(0, canvas.scene.update)

def joinGroup(group_id):
    if canvas.debug:
        print("PatchCanvas::joinGroup(%i)" % group_id)

    item = None
    s_item = None
    group_name = ""
    group_icon_type = ICON_APPLICATION
    group_icon_name = ""
    plugin_id = -1
    plugin_ui = False
    plugin_inline = False
    portgrps_data = []
    ports_data = []
    conns_data = []

    # Step 1 - Store all Item data
    for group in canvas.group_list:
        if group.group_id == group_id:
            if not group.split:
                qCritical("PatchCanvas::joinGroup(%i) - group is not split" % group_id)
                return

            item = group.widgets[0]
            s_item = group.widgets[1]
            group_name = group.group_name
            group_icon_type = group.icon_type
            group_icon_name = group.icon_name
            plugin_id = group.plugin_id
            plugin_ui = group.plugin_ui
            plugin_inline = group.plugin_inline
            break

    # FIXME
    if not (item and s_item):
        qCritical("PatchCanvas::joinGroup(%i) - unable to find groups to join" % group_id)
        return
    
    for portgrp in canvas.portgrp_list:
        if portgrp.group_id == group_id:
            portgrp_dict = portgrp_dict_t()
            portgrp_dict.group_id = portgrp.group_id
            portgrp_dict.portgrp_id = portgrp.portgrp_id
            portgrp_dict.port_type = portgrp.port_type
            portgrp_dict.port_mode = portgrp.port_mode
            portgrp_dict.port_id_list = portgrp.port_id_list.copy()
            portgrp_dict.widget = None
            portgrps_data.append(portgrp_dict)
    
    for port in canvas.port_list:
        if port.group_id == group_id:
            port_dict = port_dict_t()
            port_dict.group_id = port.group_id
            port_dict.port_id = port.port_id
            port_dict.port_name = port.port_name
            port_dict.port_mode = port.port_mode
            port_dict.port_type = port.port_type
            port_dict.portgrp_id = port.portgrp_id
            port_dict.is_alternate = port.is_alternate
            port_dict.widget = None
            ports_data.append(port_dict)

    for connection in canvas.connection_list:
        if (connection.group_out_id == group_id
                or connection.group_in_id == group_id):
            connection_dict = connection_dict_t()
            connection_dict.connection_id = connection.connection_id
            connection_dict.group_in_id = connection.group_in_id
            connection_dict.port_in_id = connection.port_in_id
            connection_dict.group_out_id = connection.group_out_id
            connection_dict.port_out_id = connection.port_out_id
            connection_dict.widget = None
            conns_data.append(connection_dict)

    # Step 2 - Remove Item and Children
    for conn in conns_data:
        disconnectPorts(conn.connection_id)
    
    for portgrp in portgrps_data:
        removePortGroup(group_id, portgrp.portgrp_id, fast=True)
    
    for port in ports_data:
        removePort(group_id, port.port_id, fast=True)

    removeGroup(group_id, save_positions=False)

    # Step 3 - Re-create Item, now together
    addGroup(group_id, group_name, SPLIT_NO,
             group_icon_type, group_icon_name)

    if plugin_id >= 0:
        setGroupAsPlugin(group_id, plugin_id, plugin_ui, plugin_inline)
    
    for port in ports_data:
        addPort(group_id, port.port_id, port.port_name, port.port_mode,
                port.port_type, port.is_alternate, fast=True)
    
    for portgrp in portgrps_data:
        addPortGroup(group_id, portgrp.portgrp_id, portgrp.port_mode,
                     portgrp.port_type, portgrp.port_id_list, fast=True)
    
    for conn in conns_data:
        connectPorts(conn.connection_id, conn.group_out_id, conn.port_out_id,
                     conn.group_in_id, conn.port_in_id)

    for group in canvas.group_list:
        if group.group_id == group_id:
            for box in group.widgets:
                if box is not None:
                    box.updatePositions()

    QTimer.singleShot(0, canvas.scene.update)

def animateBeforeJoin(group_id: int):
    for group in canvas.group_list:
        if group.group_id == group_id:
            canvas.settings.setValue(
                "CanvasPositions/%s_OUTPUT" % group.group_name, group.widgets[0].pos())
            canvas.settings.setValue(
                "CanvasPositions/%s_INPUT" % group.group_name, group.widgets[1].pos())
            canvas.settings.setValue(
                "CanvasPositions/%s_SPLIT" % group.group_name, SPLIT_YES)
            
            new_pos = getStoredCanvasPosition(
                group.group_name, CanvasGetNewGroupPos(False))
            for widget in group.widgets:
                canvas.scene.add_box_to_animation(
                    widget, new_pos.x(), new_pos.y())
            break

def moveGroupBox(group_id: int, port_mode: int, x: int, y: int, animate=True):
    for group in canvas.group_list:
        if group.group_id == group_id:
            box = None
            if group.split:
                if port_mode == PORT_MODE_OUTPUT:
                    box = group.widgets[0]
                elif port_mode == PORT_MODE_INPUT:
                    box = group.widgets[1]
                else:
                    return
            else:
                if port_mode == PORT_MODE_INPUT + PORT_MODE_OUTPUT:
                    box = group.widgets[0]
                else:
                    return
            
            if box is None:
                return
            
            if animate:
                canvas.scene.add_box_to_animation(box, x, y)
            else:
                box.setPos(x, y)
            #canvas.scene.move_boxes.append(
                #{'widget': box, 'from_x': box.pos().x(), 'from_y': box.pos().y(),
                 #'to_x': x, 'to_y': y})
            #canvas.scene.move_box_timer.start()
            break
                
                

# ------------------------------------------------------------------------------------------------------------

def getGroupPos(group_id, port_mode=PORT_MODE_OUTPUT):
    if canvas.debug:
        print("PatchCanvas::getGroupPos(%i, %s)" % (group_id, port_mode2str(port_mode)))

    for group in canvas.group_list:
        if group.group_id == group_id:
            return group.widgets[1 if (group.split and port_mode == PORT_MODE_INPUT) else 0].pos()

    qCritical("PatchCanvas::getGroupPos(%i, %s) - unable to find group" % (group_id, port_mode2str(port_mode)))
    return QPointF(0, 0)

def saveGroupPositions():
    if canvas.debug:
        print("PatchCanvas::getGroupPositions()")

    ret = []

    for group in canvas.group_list:
        if group.split:
            pos1 = group.widgets[0].pos()
            pos2 = group.widgets[1].pos()
        else:
            pos1 = group.widgets[0].pos()
            pos2 = QPointF(0, 0)

        ret.append({
            "name" : group.group_name,
            "pos1x": pos1.x(),
            "pos1y": pos1.y(),
            "pos2x": pos2.x(),
            "pos2y": pos2.y(),
            "split": group.split,
        })

    return ret

def restoreGroupPositions(dataList):
    if canvas.debug:
        print("PatchCanvas::restoreGroupPositions(...)")

    mapping = {}

    for group in canvas.group_list:
        mapping[group.group_name] = group

    for data in dataList:
        name = data['name']
        group = mapping.get(name, None)

        if group is None:
            continue

        group.widgets[0].setPos(data['pos1x'], data['pos1y'])

        if group.split and group.widgets[1]:
            group.widgets[1].setPos(data['pos2x'], data['pos2y'])

def setGroupPos(group_id, group_pos_x, group_pos_y):
    setGroupPosFull(group_id, group_pos_x, group_pos_y, group_pos_x, group_pos_y)

def setGroupPosFull(group_id, group_pos_x_o, group_pos_y_o, group_pos_x_i, group_pos_y_i):
    if canvas.debug:
        print("PatchCanvas::setGroupPos(%i, %i, %i, %i, %i)" % (
              group_id, group_pos_x_o, group_pos_y_o, group_pos_x_i, group_pos_y_i))

    for group in canvas.group_list:
        if group.group_id == group_id:
            group.widgets[0].setPos(group_pos_x_o, group_pos_y_o)

            if group.split and group.widgets[1]:
                group.widgets[1].setPos(group_pos_x_i, group_pos_y_i)

            QTimer.singleShot(0, canvas.scene.update)
            return

    qCritical("PatchCanvas::setGroupPos(%i, %i, %i, %i, %i) - unable to find group to reposition" % (
              group_id, group_pos_x_o, group_pos_y_o, group_pos_x_i, group_pos_y_i))

# ------------------------------------------------------------------------------------------------------------

def setGroupIcon(group_id, icon_type):
    if canvas.debug:
        print("PatchCanvas::setGroupIcon(%i, %s)" % (group_id, icon2str(icon_type)))

    for group in canvas.group_list:
        if group.group_id == group_id:
            group.icon_type = icon_type
            group.widgets[0].setIcon(icon_type)

            if group.split and group.widgets[1]:
                group.widgets[1].setIcon(icon_type)

            QTimer.singleShot(0, canvas.scene.update)
            return

    qCritical("PatchCanvas::setGroupIcon(%i, %s) - unable to find group to change icon" % (group_id, icon2str(icon_type)))

def setGroupAsPlugin(group_id, plugin_id, hasUI, hasInlineDisplay):
    if canvas.debug:
        print("PatchCanvas::setGroupAsPlugin(%i, %i, %s, %s)" % (
              group_id, plugin_id, bool2str(hasUI), bool2str(hasInlineDisplay)))

    for group in canvas.group_list:
        if group.group_id == group_id:
            group.plugin_id = plugin_id
            group.plugin_ui = hasUI
            group.plugin_inline = hasInlineDisplay
            group.widgets[0].setAsPlugin(plugin_id, hasUI, hasInlineDisplay)

            if group.split and group.widgets[1]:
                group.widgets[1].setAsPlugin(plugin_id, hasUI, hasInlineDisplay)

            canvas.group_plugin_map[plugin_id] = group
            return

    qCritical("PatchCanvas::setGroupAsPlugin(%i, %i, %s, %s) - unable to find group to set as plugin" % (
              group_id, plugin_id, bool2str(hasUI), bool2str(hasInlineDisplay)))

# ------------------------------------------------------------------------------------------------------------

def addPort(group_id, port_id, port_name, port_mode, port_type, is_alternate=False, fast=False):
    if canvas.debug:
        print("PatchCanvas::addPort(%i, %i, %s, %s, %s, %s)" % (
              group_id, port_id, port_name.encode(),
              port_mode2str(port_mode), port_type2str(port_type), bool2str(is_alternate)))

    for port in canvas.port_list:
        if port.group_id == group_id and port.port_id == port_id:
            qWarning("PatchCanvas::addPort(%i, %i, %s, %s, %s) - port already exists" % (
                     group_id, port_id, port_name.encode(), port_mode2str(port_mode), port_type2str(port_type)))
            return

    box_widget = None
    port_widget = None

    for group in canvas.group_list:
        if group.group_id == group_id:
            if group.split and group.widgets[0].getSplittedMode() != port_mode and group.widgets[1]:
                n = 1
            else:
                n = 0
            box_widget = group.widgets[n]
            port_widget = box_widget.addPortFromGroup(
                port_id, port_mode, port_type,
                port_name, is_alternate)
            break

    if not (box_widget and port_widget):
        qCritical("PatchCanvas::addPort(%i, %i, %s, %s, %s) - Unable to find parent group" % (
                  group_id, port_id, port_name.encode(), port_mode2str(port_mode), port_type2str(port_type)))
        return

    port_dict = port_dict_t()
    port_dict.group_id = group_id
    port_dict.port_id = port_id
    port_dict.port_name = port_name
    port_dict.port_mode = port_mode
    port_dict.port_type = port_type
    port_dict.portgrp_id = 0
    port_dict.is_alternate = is_alternate
    port_dict.widget = port_widget
    canvas.port_list.append(port_dict)
    
    canvas.last_z_value += 1
    port_widget.setZValue(canvas.last_z_value)
    
    canvas.qobject.port_added.emit(port_dict.group_id, port_dict.port_id)
    
    if fast:
        return

    box_widget.updatePositions()
    
    if options.eyecandy == EYECANDY_FULL:
        CanvasItemFX(port_widget, True, False)
        return

    QTimer.singleShot(0, canvas.scene.update)

def removePort(group_id, port_id, fast=False):
    if canvas.debug:
        print("PatchCanvas::removePort(%i, %i)" % (group_id, port_id))

    for port in canvas.port_list:
        if port.group_id == group_id and port.port_id == port_id:
            if port.portgrp_id:
                qCritical("PatchCanvas::removePort(%i, %i) - Port is in portgroup %i, remove it before !" % (
                    group_id, port_id, port.portgrp_id))
                return
            
            item = port.widget
            if item is not None:
                item.parentItem().removePortFromGroup(port_id)
                canvas.scene.removeItem(item)
                
            del item
            canvas.port_list.remove(port)
            
            canvas.qobject.port_removed.emit(group_id, port_id)
            if fast:
                return
            
            QTimer.singleShot(0, canvas.scene.update)
            return

    qCritical("PatchCanvas::removePort(%i, %i) - Unable to find port to remove" % (group_id, port_id))

def changePortProperties(group_id, port_id, portgrp_id, new_port_name):
    if canvas.debug:
        print("PatchCanvas::renamePort(%i, %i, %s)" % (group_id, port_id, new_port_name.encode()))

    for port in canvas.port_list:
        if port.group_id == group_id and port.port_id == port_id:
            if new_port_name != port.port_name:
                port.port_name = new_port_name
                port.widget.setPortName(new_port_name)
            
            port.widget.parentItem().updatePositions()

            QTimer.singleShot(0, canvas.scene.update)
            return

    qCritical("PatchCanvas::renamePort(%i, %i, %s) - Unable to find port to rename" % (
              group_id, port_id, new_port_name.encode()))            

def addPortGroup(group_id, portgrp_id, port_mode, port_type, port_id_list, fast=False):
    if canvas.debug:
        print("PatchCanvas::addPortGroup(%i, %i)" % (group_id, portgrp_id))
        
    for portgrp in canvas.portgrp_list:
        if portgrp.group_id == group_id and portgrp.portgrp_id == portgrp_id:
            qWarning("PatchCanvas::addPortGroup(%i, %i) - port group already exists" % (
                     group_id, portgrp_id))
            return
        
    portgrp_dict = portgrp_dict_t()
    portgrp_dict.group_id = group_id
    portgrp_dict.portgrp_id = portgrp_id
    portgrp_dict.port_mode = port_mode
    portgrp_dict.port_type = port_type
    portgrp_dict.port_id_list = port_id_list.copy()
    portgrp_dict.widget = None
    
    # check that port ids are present in canvas in this group
    i = 0
    for port in canvas.port_list:
        if (port.group_id == group_id
                and port.port_type == port_type
                and port.port_mode == port_mode
                and port.port_id in port_id_list):
            i += 1
    
    if len(port_id_list) != i:
        qWarning("PatchCanvas::addPortGroup(%i, %i) - not enought ports with port_id_list" % (
            group_id, portgrp_id))
        return
    
    # modify ports impacted by portgroup
    for port in canvas.port_list:
        if (port.group_id == group_id
                 and port.port_id in port_id_list):
            port.portgrp_id = portgrp_id
            if port.widget is not None:
                port.widget.setPortGroupId(portgrp_id)

    canvas.portgrp_list.append(portgrp_dict)
    
    # add portgroup widget and refresh the view
    for group in canvas.group_list:
        if group.group_id == group_id:
            for box in group.widgets:
                if box is None:
                    continue
                
                if (not box.isSplitted()
                        or box.getSplittedMode() == port_mode):
                    portgrp_dict.widget = box.addPortGroupFromGroup(
                        portgrp_id, port_mode, port_type, port_id_list)
                    
                    if not fast:
                        box.updatePositions()
            break

def removePortGroup(group_id, portgrp_id, fast=False):
    if canvas.debug:
        print("PatchCanvas::removePortGroup(%i, %i)" % (group_id, portgrp_id))

    box_widget = None
    
    for portgrp in canvas.portgrp_list:
        if (portgrp.group_id == group_id
                and portgrp.portgrp_id == portgrp_id):
            # set portgrp_id to the concerned ports
            for port in canvas.port_list:
                if (port.group_id == group_id
                        and port.portgrp_id == portgrp_id):
                    port.portgrp_id = 0
    
                    if port.widget is not None:
                        port.widget.setPortGroupId(0)
                        box_widget = port.widget.parentItem()
                        
            portgrp.port_id_list.clear()
            
            if portgrp.widget is not None:
                item = portgrp.widget
                canvas.scene.removeItem(item)
                del item
                portgrp.widget = None
            break
    else:
        qCritical("PatchCanvas::removePortGroup(%i, %i) - Unable to find portgrp to remove" % (
              group_id, portgrp_id))
        return
    
    canvas.portgrp_list.remove(portgrp)
    
    if fast:
        return
    
    if box_widget is not None:
        box_widget.updatePositions()
    
    QTimer.singleShot(0, canvas.scene.update)

def connectPorts(connection_id, group_out_id, port_out_id, group_in_id, port_in_id):
    if canvas.debug:
        print("PatchCanvas::connectPorts(%i, %i, %i, %i, %i)" % (
              connection_id, group_out_id, port_out_id, group_in_id, port_in_id))

    port_out = None
    port_in = None
    port_out_parent = None
    port_in_parent = None

    for port in canvas.port_list:
        if port.group_id == group_out_id and port.port_id == port_out_id:
            port_out = port.widget
            if port_out is not None:
                port_out_parent = port_out.parentItem()
        elif port.group_id == group_in_id and port.port_id == port_in_id:
            port_in = port.widget
            if port_in is not None:
                port_in_parent = port_in.parentItem()

    # FIXME
    if not (port_out and port_in and port_out_parent and port_in_parent):
        qCritical("PatchCanvas::connectPorts(%i, %i, %i, %i, %i) - unable to find ports to connect" % (
                  connection_id, group_out_id, port_out_id, group_in_id, port_in_id))
        return

    connection_dict = connection_dict_t()
    connection_dict.connection_id = connection_id
    connection_dict.group_in_id = group_in_id
    connection_dict.port_in_id = port_in_id
    connection_dict.group_out_id = group_out_id
    connection_dict.port_out_id = port_out_id
    
    if options.use_bezier_lines:
        connection_dict.widget = CanvasBezierLine(port_out, port_in, None)
    else:
        connection_dict.widget = CanvasLine(port_out, port_in, None)

    canvas.scene.addItem(connection_dict.widget)

    port_out_parent.addLineFromGroup(connection_dict.widget, connection_id)
    port_in_parent.addLineFromGroup(connection_dict.widget, connection_id)

    canvas.last_z_value += 1
    port_out_parent.setZValue(canvas.last_z_value)
    port_in_parent.setZValue(canvas.last_z_value)

    canvas.last_z_value += 1
    connection_dict.widget.setZValue(canvas.last_z_value)

    canvas.connection_list.append(connection_dict)
    
    canvas.qobject.connection_added.emit(connection_id)
    
    if options.eyecandy == EYECANDY_FULL:
        item = connection_dict.widget
        CanvasItemFX(item, True, False)
        return

    QTimer.singleShot(0, canvas.scene.update)

def disconnectPorts(connection_id):
    if canvas.debug:
        print("PatchCanvas::disconnectPorts(%i)" % connection_id)

    line = None
    item1 = None
    item2 = None
    group1id = port1id = 0
    group2id = port2id = 0

    for connection in canvas.connection_list:
        if connection.connection_id == connection_id:
            group1id = connection.group_out_id
            group2id = connection.group_in_id
            port1id = connection.port_out_id
            port2id = connection.port_in_id
            line = connection.widget
            canvas.connection_list.remove(connection)
            break

    canvas.qobject.connection_removed.emit(connection_id)

    if not line:
        qCritical("PatchCanvas::disconnectPorts(%i) - unable to find connection ports" % connection_id)
        return

    for port in canvas.port_list:
        if port.group_id == group1id and port.port_id == port1id:
            item1 = port.widget
            break

    if not item1:
        qCritical("PatchCanvas::disconnectPorts(%i) - unable to find output port" % connection_id)
        return

    for port in canvas.port_list:
        if port.group_id == group2id and port.port_id == port2id:
            item2 = port.widget
            break

    if not item2:
        qCritical("PatchCanvas::disconnectPorts(%i) - unable to find input port" % connection_id)
        return

    item1.parentItem().removeLineFromGroup(connection_id)
    item2.parentItem().removeLineFromGroup(connection_id)

    if options.eyecandy == EYECANDY_FULL:
        CanvasItemFX(line, False, True)
        return

    canvas.scene.removeItem(line)
    del line

    QTimer.singleShot(0, canvas.scene.update)

# ------------------------------------------------------------------------------------------------------------

def arrange():
    if canvas.debug:
        print("PatchCanvas::arrange()")

def changeTheme(idx: int):
    canvas.theme.setTheme(idx)
    canvas.scene.updateTheme()
    
    for group in canvas.group_list:
        for widget in group.widgets:
            if widget is not None:
                widget.repaintLines(forced=True)
                widget.update()

    QTimer.singleShot(0, canvas.scene.update)

# ------------------------------------------------------------------------------------------------------------

def updateZValues():
    if canvas.debug:
        print("PatchCanvas::updateZValues()")

    for group in canvas.group_list:
        group.widgets[0].resetLinesZValue()

        if group.split and group.widgets[1]:
            group.widgets[1].resetLinesZValue()

# ------------------------------------------------------------------------------------------------------------

def redrawPluginGroup(plugin_id):
    group = canvas.group_plugin_map.get(plugin_id, None)

    if group is None:
        #qCritical("PatchCanvas::redrawPluginGroup(%i) - unable to find group" % plugin_id)
        return

    group.widgets[0].redrawInlineDisplay()

    if group.split and group.widgets[1]:
        group.widgets[1].redrawInlineDisplay()

def handlePluginRemoved(plugin_id):
    if canvas.debug:
        print("PatchCanvas::handlePluginRemoved(%i)" % plugin_id)

    group = canvas.group_plugin_map.pop(plugin_id, None)

    if group is not None:
        group.plugin_id = -1
        group.plugin_ui = False
        group.plugin_inline = False
        group.widgets[0].removeAsPlugin()

        if group.split and group.widgets[1]:
            group.widgets[1].removeAsPlugin()

    for group in canvas.group_list:
        if group.plugin_id < plugin_id or group.plugin_id > MAX_PLUGIN_ID_ALLOWED:
            continue

        group.plugin_id -= 1
        group.widgets[0].m_plugin_id -= 1

        if group.split and group.widgets[1]:
            group.widgets[1].m_plugin_id -= 1

        canvas.group_plugin_map[plugin_id] = group

def handleAllPluginsRemoved():
    if canvas.debug:
        print("PatchCanvas::handleAllPluginsRemoved()")

    canvas.group_plugin_map = {}

    for group in canvas.group_list:
        if group.plugin_id < 0:
            continue
        if group.plugin_id > MAX_PLUGIN_ID_ALLOWED:
            continue

        group.plugin_id = -1
        group.plugin_ui = False
        group.plugin_inline = False
        group.widgets[0].removeAsPlugin()

        if group.split and group.widgets[1]:
            group.widgets[1].removeAsPlugin()

def setElastic(yesno: bool):
    canvas.scene.set_elastic(yesno)

# ------------------------------------------------------------------------------------------------------------
