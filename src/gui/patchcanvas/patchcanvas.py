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

import sys
import time
from pathlib import Path
from PyQt5.QtCore import (pyqtSlot, qCritical, qFatal, qWarning, QObject,
                          QPoint, QPointF, QRectF, QSettings, QTimer, pyqtSignal)
from PyQt5.QtGui import QFontMetricsF, QFont

from .init_values import (
    CanvasItemType,
    PortType,
    canvas,
    options,
    features,
    CanvasOptionsObject,
    CanvasFeaturesObject,
    CallbackAct,
    MAX_PLUGIN_ID_ALLOWED,
    GroupObject,
    PortObject,
    PortgrpObject,
    ConnectionObject,
    PortMode,
    BoxSplitMode,
    BoxLayoutMode,
    IconType,
    EyeCandy, # not used here, but can be taken from parent
)

import patchcanvas.utils as utils

from .canvasbox import CanvasBox
from .canvasbezierline import CanvasBezierLine
from .theme_manager import ThemeManager
from .scene import PatchScene

# ------------------------------------------------------------------------------------------------------------

def warning_print(string: str):
    sys.stderr.write('patchcanvas::%s\n' % string)


class CanvasObject(QObject):
    port_added = pyqtSignal(int, int)
    port_removed = pyqtSignal(int, int)
    connection_added = pyqtSignal(int)
    connection_removed = pyqtSignal(int)
    move_boxes_finished = pyqtSignal()
    zoom_changed = pyqtSignal(int)

    def __init__(self, parent=None):
        QObject.__init__(self, parent)
        self.groups_to_join = []
        self.move_boxes_finished.connect(self.join_after_move)

    @pyqtSlot()
    def port_context_menu_disconnect(self):
        try:
            con_ids_list = list(self.sender().data())
        except:
            return

        for connection_id in con_ids_list:
            if type(connection_id) != int:
                continue

            utils.canvas_callback(CallbackAct.PORTS_DISCONNECT, connection_id)

    @pyqtSlot()
    def set_as_stereo_with(self):
        try:
            all_data = self.sender().data()
        except:
            return

        port_widget = all_data[0]
        port_id = all_data[1]
        port_widget.set_as_stereo(port_id)

    def join_after_move(self):
        for group_id in self.groups_to_join:
            join_group(group_id)

        self.groups_to_join.clear()

# ------------------------------------------------------------------------------------------------------------

def _get_stored_canvas_position(key, fallback_pos):
    try:
        return canvas.settings.value(
            "CanvasPositions/" + key, fallback_pos, type=QPointF)
    except:
        return fallback_pos

# -----------------------------------

def init(app_name: str, scene: PatchScene, callback,
         theme_paths: tuple[Path], debug=False):
    if debug:
        warning_print("init(\"%s\", %s, %s, %s)"
                      % (app_name, scene, callback, str(debug)))

    if canvas.initiated:
        warning_print("init() - already initiated")
        return

    if not callback:
        warning_print("init() - fatal error: callback not set")
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

    # TODO settings from falktx    
    if not canvas.settings:
        canvas.settings = QSettings("falkTX", app_name)

    if canvas.theme_manager is None:
        canvas.theme_manager = ThemeManager(theme_paths)
        if not canvas.theme_manager.set_theme(options.theme_name):
            canvas.theme_manager.set_theme('Black Gold')

        canvas.theme.load_cache()

    canvas.initiated = True

def clear():
    if canvas.debug:
        warning_print("clear()")

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
        disconnect_ports(idx)

    for group_id, port_id in port_list_ids:
        remove_port(group_id, port_id)

    for idx in group_list_ids:
        remove_group(idx)

    canvas.last_z_value = 0
    canvas.last_connection_id = 0

    canvas.group_list.clear()
    canvas.port_list.clear()
    canvas.portgrp_list.clear()
    canvas.connection_list.clear()
    canvas.group_plugin_map = {}

    canvas.scene.clearSelection()

    for item in canvas.scene.items():
        if item.type() in (CanvasItemType.ICON, CanvasItemType.RUBBERBAND):
            continue
        canvas.scene.removeItem(item)
        del item

    canvas.initiated = False

    QTimer.singleShot(0, canvas.scene.update)

# ------------------------------------------------------------------------------------------------------------

def set_initial_pos(x: int, y: int):
    if canvas.debug:
        warning_print("set_initial_pos(%i, %i)" % (x, y))

    canvas.initial_pos.setX(x)
    canvas.initial_pos.setY(y)

def set_canvas_size(x: int, y: int, width: int, height: int):
    if canvas.debug:
        warning_print("set_canvas_size(%i, %i, %i, %i)" % (x, y, width, height))

    canvas.size_rect.setX(x)
    canvas.size_rect.setY(y)
    canvas.size_rect.setWidth(width)
    canvas.size_rect.setHeight(height)
    canvas.scene.update_limits()
    canvas.scene.fix_scale_factor()

def set_loading_items(yesno: bool):
    '''while canvas is loading items (groups or ports, connections...)
    then, items will be added, but no redraw.
    This is an optimization that prevents a lot of redraws.
    Think to set loading items at False and use redraw_all_groups
    or redraw_group once the long operation is finished'''
    canvas.loading_items = yesno

def add_group(group_id: int, group_name: str, split=BoxSplitMode.UNDEF,
              icon_type=IconType.APPLICATION, icon_name='', layout_modes={},
              null_xy=(0, 0), in_xy=(0, 0), out_xy=(0, 0),
              split_animated=False):
    if canvas.debug:
        warning_print("add_group(%i, %s, %s, %s)" % (
              group_id, group_name, split.name, icon_type.name))

    for group in canvas.group_list:
        if group.group_id == group_id:
            warning_print(
                "add_group(%i, %s, %s, %s) - group already exists"
                % (group_id, group_name, split.name, icon_type.name))
            return

    if split is BoxSplitMode.UNDEF and icon_type is IconType.HARDWARE:
        split = BoxSplitMode.YES

    group_box = CanvasBox(group_id, group_name, icon_type, icon_name)
    
    group = GroupObject()
    group.group_id = group_id
    group.group_name = group_name
    group.split = bool(split == BoxSplitMode.YES)
    group.icon_type = icon_type
    group.icon_name = icon_name
    group.layout_modes = layout_modes
    group.plugin_id = -1
    group.plugin_ui = False
    group.plugin_inline = False
    group.handle_client_gui = False
    group.gui_visible = False
    group.null_pos = QPoint(*null_xy)
    group.in_pos = QPoint(*in_xy)
    group.out_pos = QPoint(*out_xy)
    # group_dict.widgets = [group_box, None]
    group.widgets = list[CanvasBox]()
    group.widgets.append(group_box)
    group.widgets.append(None)

    if split == BoxSplitMode.YES:
        group_box.set_split(True, PortMode.OUTPUT)

        if features.handle_group_pos:
            new_pos = _get_stored_canvas_position(
                group_name + "_OUTPUT", utils.get_new_group_pos(False))
            canvas.scene.add_box_to_animation(group_box, new_pos.x(), new_pos.y())
        else:
            if split_animated:
                group_box.setPos(group.null_pos)
            else:
                group_box.setPos(group.out_pos)

        group_sbox = CanvasBox(group_id, group_name, icon_type, icon_name)
        group_sbox.set_split(True, PortMode.INPUT)

        group.widgets[1] = group_sbox

        if features.handle_group_pos:
            new_pos = _get_stored_canvas_position(
                group_name + "_INPUT", utils.get_new_group_pos(True))
            canvas.scene.add_box_to_animation(group_sbox, new_pos.x(), new_pos.y())
        else:
            if split_animated:
                group_sbox.setPos(group.null_pos)
            else:
                group_sbox.setPos(group.in_pos)

        canvas.last_z_value += 1
        group_sbox.setZValue(canvas.last_z_value)

    else:
        group_box.set_split(False)

        if features.handle_group_pos:
            group_box.setPos(_get_stored_canvas_position(
                group_name, utils.get_new_group_pos(False)))
        else:
            # Special ladish fake-split groups
            #horizontal = bool(icon_type in (IconType.HARDWARE, IconType.LADISH_ROOM))
            group_box.setPos(group.null_pos)


    canvas.last_z_value += 1
    group_box.setZValue(canvas.last_z_value)    
    canvas.group_list.append(group)
    
    if canvas.loading_items:
        return

    if split_animated:
        for box in group.widgets:
            if box is not None:
                if box.get_splitted_mode() is PortMode.OUTPUT:
                    canvas.scene.add_box_to_animation(
                        box, group.out_pos.x(), group.out_pos.y())
                elif box.get_splitted_mode() is PortMode.INPUT:
                    canvas.scene.add_box_to_animation(
                        box, group.in_pos.x(), group.in_pos.y())

    QTimer.singleShot(0, canvas.scene.update)

def remove_group(group_id: int, save_positions=True):
    if canvas.debug:
        warning_print("remove_group(%i)" % group_id)

    for group in canvas.group_list:
        if group.group_id == group_id:            
            item = group.widgets[0]
            group_name = group.group_name

            if group.split:
                s_item = group.widgets[1]

                if features.handle_group_pos and save_positions:
                    canvas.settings.setValue(
                        "CanvasPositions/%s_OUTPUT" % group_name, item.pos())
                    canvas.settings.setValue(
                        "CanvasPositions/%s_INPUT" % group_name, s_item.pos())
                    canvas.settings.setValue(
                        "CanvasPositions/%s_SPLIT" % group_name, BoxSplitMode.YES)

                s_item.remove_icon_from_scene()
                canvas.scene.removeItem(s_item)
                del s_item

            else:
                if features.handle_group_pos and save_positions:
                    canvas.settings.setValue(
                        "CanvasPositions/%s" % group_name, item.pos())
                    canvas.settings.setValue(
                        "CanvasPositions/%s_SPLIT" % group_name, BoxSplitMode.NO)

            item.remove_icon_from_scene()
            canvas.scene.removeItem(item)
            del item

            canvas.group_list.remove(group)
            canvas.group_plugin_map.pop(group.plugin_id, None)

            if canvas.loading_items:
                return

            QTimer.singleShot(0, canvas.scene.update)
            QTimer.singleShot(0, canvas.scene.resize_the_scene)
            return

    qCritical("PatchCanvas::remove_group(%i) - unable to find group to remove" % group_id)

def rename_group(group_id: int, new_group_name: str):
    if canvas.debug:
        warning_print("rename_group(%i, %s)" % (group_id, new_group_name))

    for group in canvas.group_list:
        if group.group_id == group_id:
            group.group_name = new_group_name
            group.widgets[0].set_group_name(new_group_name)

            if group.split and group.widgets[1]:
                group.widgets[1].set_group_name(new_group_name)

            QTimer.singleShot(0, canvas.scene.update)
            return

    qCritical("PatchCanvas::rename_group(%i, %s) - unable to find group to rename"
              % (group_id, new_group_name.encode()))

def split_group(group_id: int, on_place=False):
    if canvas.debug:
        warning_print("split_group(%i)" % group_id)

    item = None

    # Step 1 - Store all Item data
    for group in canvas.group_list:
        if group.group_id == group_id:
            if group.split:
                qCritical("PatchCanvas::split_group(%i) - group is already split" % group_id)
                return

            item = group.widgets[0]
            tmp_group = group.copy_no_widget()
            
            if on_place and item is not None:
                pos = item.pos()
                rect = item.boundingRect()
                y = int(pos.y())
                x = int(pos.x())
                tmp_group.in_pos = QPoint(x - int(rect.width() / 2), y)
                tmp_group.out_pos = QPoint(x + int(rect.width() / 2), y)
            break

    if not item:
        qCritical("PatchCanvas::split_group(%i) - unable to find group to split" % group_id)
        return

    wrap = item.is_wrapped()

    portgrps_data = [pg.copy_no_widget() for pg in canvas.portgrp_list
                     if pg.group_id == group_id]
    ports_data = [p.copy_no_widget() for p in canvas.port_list
                  if p.group_id == group_id]
    conns_data = [c.copy_no_widget() for c in canvas.connection_list
                  if group_id in (c.group_out_id, c.group_in_id)]

    canvas.loading_items = True

    # Step 2 - Remove Item and Children
    for conn in conns_data:
        disconnect_ports(conn.connection_id)

    for portgrp in portgrps_data:
        if portgrp.group_id == group_id:
            remove_portgroup(group_id, portgrp.portgrp_id)

    for port in ports_data:
        if port.group_id == group_id:
            remove_port(group_id, port.port_id)

    remove_group(group_id)

    g = tmp_group

    # Step 3 - Re-create Item, now split
    add_group(group_id, g.group_name, BoxSplitMode.YES,
              g.icon_type, g.icon_name, g.layout_modes,
              null_xy=(g.null_pos.x(), g.null_pos.y()),
              in_xy=(g.in_pos.x(), g.in_pos.y()),
              out_xy=(g.out_pos.x(), g.out_pos.y()),
              split_animated=True)

    if g.handle_client_gui:
        set_optional_gui_state(group_id, g.gui_visible)

    if g.plugin_id >= 0:
        set_group_as_plugin(group_id, g.plugin_id, g.plugin_ui, g.plugin_inline)

    for port in ports_data:
        add_port(group_id, port.port_id, port.port_name, port.port_mode,
                 port.port_type, port.is_alternate)

    for portgrp in portgrps_data:
        add_portgroup(group_id, portgrp.portgrp_id, portgrp.port_mode,
                      portgrp.port_type, portgrp.port_id_list)

    for conn in conns_data:
        connect_ports(conn.connection_id, conn.group_out_id, conn.port_out_id,
                      conn.group_in_id, conn.port_in_id)

    canvas.loading_items = False

    for group in canvas.group_list:
        if group.group_id == group_id:
            for box in group.widgets:
                if box is not None:
                    box.set_wrapped(wrap, animate=False)
                    box.update_positions(even_animated=True)

    QTimer.singleShot(0, canvas.scene.update)

def join_group(group_id: int):
    if canvas.debug:
        warning_print("join_group(%i)" % group_id)

    item = None
    s_item = None

    # Step 1 - Store all Item data
    for group in canvas.group_list:
        if group.group_id == group_id:
            if not group.split:
                warning_print("join_group(%i) - group is not split" % group_id)
                return

            item, s_item = group.widgets
            tmp_group = group.copy_no_widget()
            break

    if not (item and s_item):
        warning_print("join_group(%i) - unable to find groups to join" % group_id)
        return

    wrap = item.is_wrapped() and s_item.is_wrapped()

    portgrps_data = [pg.copy_no_widget() for pg in canvas.portgrp_list
                     if pg.group_id == group_id]
    ports_data = [p.copy_no_widget() for p in canvas.port_list
                  if p.group_id == group_id]
    conns_data = [c.copy_no_widget() for c in canvas.connection_list
                  if group_id in (c.group_out_id, c.group_in_id)]

    canvas.loading_items = True

    # Step 2 - Remove Item and Children
    for conn in conns_data:
        disconnect_ports(conn.connection_id)

    for portgrp in portgrps_data:
        remove_portgroup(group_id, portgrp.portgrp_id)

    for port in ports_data:
        remove_port(group_id, port.port_id)

    remove_group(group_id, save_positions=False)

    g = tmp_group
    # Step 3 - Re-create Item, now together
    add_group(group_id, g.group_name, BoxSplitMode.NO,
              g.icon_type, g.icon_name, g.layout_modes,
              null_xy=(g.null_pos.x(), g.null_pos.y()),
              in_xy=(g.in_pos.x(), g.in_pos.y()),
              out_xy=(g.out_pos.x(), g.out_pos.y()))

    if g.handle_client_gui:
        set_optional_gui_state(group_id, g.gui_visible)

    if g.plugin_id >= 0:
        set_group_as_plugin(group_id, g.plugin_id, g.plugin_ui, g.plugin_inline)

    for port in ports_data:
        add_port(group_id, port.port_id, port.port_name, port.port_mode,
                 port.port_type, port.is_alternate)

    for portgrp in portgrps_data:
        add_portgroup(group_id, portgrp.portgrp_id, portgrp.port_mode,
                      portgrp.port_type, portgrp.port_id_list)

    for conn in conns_data:
        connect_ports(conn.connection_id, conn.group_out_id, conn.port_out_id,
                      conn.group_in_id, conn.port_in_id)

    for group in canvas.group_list:
        if group.group_id == group_id:
            for box in group.widgets:
                if box is not None:
                    box.set_wrapped(wrap, animate=False)

    canvas.loading_items = False
    redraw_group(group_id)

    canvas.callback(CallbackAct.GROUP_JOINED, group_id)

    QTimer.singleShot(0, canvas.scene.update)

def redraw_all_groups():
    start_time = time.time()
    last_time = start_time
    time_dicts = []
    i = 0
    
    # We are redrawing all groups.
    # For optimization reason we prevent here to resize the scene
    # at each group draw, we'll do it once all is done,
    # same for prevent_overlap.
    elastic = options.elastic
    options.elastic = False
    prevent_overlap = options.prevent_overlap
    options.prevent_overlap = False
        
    for group in canvas.group_list:
        for box in group.widgets:
            if box is not None:
                i += 1
                box.update_positions(without_connections=True)
        now = time.time()
        
        time_dicts.append({'group': group.group_name, 'time': now - last_time})
        
        last_time = now
    
    for connection in canvas.connection_list:
        if connection.widget is not None:
            connection.widget.update_line_pos()
    
    if canvas.scene is None:
        options.elastic = elastic
        options.prevent_overlap = prevent_overlap
        return
    
    if elastic:
        canvas.scene.set_elastic(True)
    
    box_count = 0
    if prevent_overlap:
        canvas.scene.set_prevent_overlap(True)
        for group in canvas.group_list:
            for box in group.widgets:
                if box is not None:
                    box_count += 1
                    canvas.scene.deplace_boxes_from_repulsers([box])
    
    if not elastic or prevent_overlap:
        QTimer.singleShot(0, canvas.scene.update)

def redraw_group(group_id: int):
    for group in canvas.group_list:
        if group.group_id == group_id:            
            for box in group.widgets:
                if box is not None:
                    box.update_positions()
            break

    QTimer.singleShot(0, canvas.scene.update)

def animate_before_join(group_id: int):
    canvas.qobject.groups_to_join.append(group_id)

    for group in canvas.group_list:
        if group.group_id == group_id:
            for widget in group.widgets:
                canvas.scene.add_box_to_animation(
                    widget, group.null_pos.x(), group.null_pos.y())
            break

def move_group_boxes(group_id: int, null_xy: tuple,
                     in_xy: tuple, out_xy: tuple, animate=True):
    for group in canvas.group_list:
        if group.group_id == group_id:
            break
    else:
        return

    group.null_pos = QPoint(*null_xy)
    group.in_pos = QPoint(*in_xy)
    group.out_pos = QPoint(*out_xy)

    if group.split:
        for port_mode in (PortMode.OUTPUT, PortMode.INPUT):
            box = group.widgets[0]
            xy = out_xy
            pos = group.out_pos

            if port_mode is PortMode.INPUT:
                box = group.widgets[1]
                xy = in_xy
                pos = group.in_pos

            if box is None:
                continue

            box_pos = box.pos()

            if int(box_pos.x()) == xy[0] and int(box_pos.y()) == xy[1]:
                continue

            canvas.scene.add_box_to_animation(
                box, xy[0], xy[1], force_anim=animate)
    else:
        box = group.widgets[0]
        if box is None:
            return

        box_pos = box.pos()
        if int(box_pos.x()) == null_xy[0] and int(box_pos.y()) == null_xy[1]:
            return

        canvas.scene.add_box_to_animation(box, null_xy[0], null_xy[1],
                                          force_anim=animate)

def wrap_group_box(group_id: int, port_mode: int, yesno: bool, animate=True):
    for group in canvas.group_list:
        if group.group_id == group_id:
            for box in group.widgets:
                if (box is not None
                        and box.get_splitted_mode() == port_mode):
                    box.set_wrapped(yesno, animate=animate)
            break

def set_group_layout_mode(group_id: int, port_mode: PortMode, layout_mode: BoxLayoutMode):
    for group in canvas.group_list:
        if group.group_id == group_id:
            group.layout_modes[port_mode] = layout_mode

            for box in group.widgets:
                if box is not None:
                    if not canvas.loading_items:
                        box.update_positions()
            break
                        

# ------------------------------------------------------------------------------------------------------------

def get_group_pos(group_id, port_mode=PortMode.OUTPUT):
    # Not used now
    if canvas.debug:
        warning_print(
            "get_group_pos(%i, %s)"
            % (group_id, port_mode.name))

    for group in canvas.group_list:
        if group.group_id == group_id:
            return group.widgets[1 if (group.split and port_mode is PortMode.INPUT) else 0].pos()

    warning_print(
        "get_group_pos(%i, %s) - unable to find group"
        % (group_id, port_mode.name))
    return QPointF(0, 0)

def restore_group_positions(dataList):
    # Not used now
    if canvas.debug:
        warning_print("restore_group_positions(...)")

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

def set_group_pos(group_id, group_pos_x, group_pos_y):
    # Not used now
    set_group_pos_full(group_id, group_pos_x, group_pos_y, group_pos_x, group_pos_y)

def set_group_pos_full(group_id, group_pos_x_o, group_pos_y_o,
                       group_pos_x_i, group_pos_y_i):
    # Not used now
    if canvas.debug:
        print("PatchCanvas::set_group_pos(%i, %i, %i, %i, %i)" % (
              group_id, group_pos_x_o, group_pos_y_o, group_pos_x_i, group_pos_y_i))

    for group in canvas.group_list:
        if group.group_id == group_id:
            group.widgets[0].setPos(group_pos_x_o, group_pos_y_o)

            if group.split and group.widgets[1]:
                group.widgets[1].setPos(group_pos_x_i, group_pos_y_i)

            QTimer.singleShot(0, canvas.scene.update)
            return

    qCritical(
        "PatchCanvas::set_group_pos(%i, %i, %i, %i, %i) - unable to find group to reposition"
        % (group_id, group_pos_x_o, group_pos_y_o, group_pos_x_i, group_pos_y_i))

# ------------------------------------------------------------------------------------------------------------

def set_group_icon(group_id: int, icon_type: IconType, icon_name: str):
    if canvas.debug:
        print("PatchCanvas::set_group_icon(%i, %s)" % (group_id, icon_type.name))

    for group in canvas.group_list:
        if group.group_id == group_id:
            group.icon_type = icon_type
            for widget in group.widgets:
                if widget is not None:
                    widget.set_icon(icon_type, icon_name)

            QTimer.singleShot(0, canvas.scene.update)
            return

    qCritical(
        "PatchCanvas::set_group_icon(%i, %s) - unable to find group to change icon"
        % (group_id, icon_type.name))

def set_group_as_plugin(group_id: int, plugin_id: int,
                        has_ui: bool, has_inline_display: bool):
    if canvas.debug:
        print("PatchCanvas::set_group_as_plugin(%i, %i, %s, %s)"
              % (group_id, plugin_id, str(has_ui), str(has_inline_display)))

    for group in canvas.group_list:
        if group.group_id == group_id:
            group.plugin_id = plugin_id
            group.plugin_ui = has_ui
            group.plugin_inline = has_inline_display
            group.widgets[0].set_as_plugin(plugin_id, has_ui, has_inline_display)

            if group.split and group.widgets[1]:
                group.widgets[1].set_as_plugin(plugin_id, has_ui, has_inline_display)

            canvas.group_plugin_map[plugin_id] = group
            return

    qCritical(
        "PatchCanvas::set_group_as_plugin(%i, %i, %s, %s) - unable to find group to set as plugin"
        % (group_id, plugin_id, str(has_ui), str(has_inline_display)))

# ------------------------------------------------------------------------------------------------------------

def add_port(group_id: int, port_id: int, port_name: str,
             port_mode: PortMode, port_type: PortType, is_alternate=False):
    if canvas.debug:
        print("PatchCanvas::add_port(%i, %i, %s, %s, %s, %s)"
              % (group_id, port_id, port_name.encode(),
                 port_mode.name,
                 port_type.name, str(is_alternate)))

    for port in canvas.port_list:
        if port.group_id == group_id and port.port_id == port_id:
            sys.stderr.write(
                "PatchCanvas::add_port(%i, %i, %s, %s, %s) - port already exists\n"
                % (group_id, port_id, port_name,
                   port_mode.name, port_type.name))
            return
    
    box_widget = None
    port_widget = None

    for group in canvas.group_list:
        if group.group_id == group_id:
            n = 0
            if (group.split
                    and group.widgets[0].get_splitted_mode() != port_mode
                    and group.widgets[1] is not None):
                n = 1

            box_widget = group.widgets[n]
            port_widget = box_widget.add_port_from_group(
                port_id, port_mode, port_type,
                port_name, is_alternate)
            break
    
    if not (box_widget and port_widget):
        qCritical(
            "PatchCanvas::add_port(%i, %i, %s, %s, %s) - Unable to find parent group"
            % (group_id, port_id, port_name.encode(),
               port_mode.name, port_type.name))
        return

    port = PortObject()
    port.group_id = group_id
    port.port_id = port_id
    port.port_name = port_name
    port.port_mode = port_mode
    port.port_type = port_type
    port.portgrp_id = 0
    port.is_alternate = is_alternate
    port.widget = port_widget
    canvas.port_list.append(port)

    canvas.last_z_value += 1
    port_widget.setZValue(canvas.last_z_value)

    #canvas.qobject.port_added.emit(port_dict.group_id, port_dict.port_id)
    
    if canvas.loading_items:
        return

    box_widget.update_positions()

    QTimer.singleShot(0, canvas.scene.update)

def remove_port(group_id: int, port_id: int):
    if canvas.debug:
        print("PatchCanvas::remove_port(%i, %i)" % (group_id, port_id))

    for port in canvas.port_list:
        if port.group_id == group_id and port.port_id == port_id:
            if port.portgrp_id:
                qCritical(
                    "PatchCanvas::remove_port(%i, %i) - Port is in portgroup %i, remove it before !"
                    % (group_id, port_id, port.portgrp_id))
                return

            item = port.widget
            if item is not None:
                item.parentItem().remove_port_from_group(port_id)
                canvas.scene.removeItem(item)

            del item
            canvas.port_list.remove(port)

            canvas.qobject.port_removed.emit(group_id, port_id)
            if canvas.loading_items:
                return

            QTimer.singleShot(0, canvas.scene.update)
            return

    qCritical(
        "PatchCanvas::remove_port(%i, %i) - Unable to find port to remove"
        % (group_id, port_id))

def rename_port(group_id: int, port_id: int, new_port_name: str):
    if canvas.debug:
        print("PatchCanvas::rename_port(%i, %i, %s)" % (group_id, port_id, new_port_name))

    for port in canvas.port_list:
        if port.group_id == group_id and port.port_id == port_id:
            if new_port_name != port.port_name:
                port.port_name = new_port_name
                
                port.widget.set_port_name(new_port_name)

            if canvas.loading_items:
                return

            port.widget.parentItem().update_positions()

            QTimer.singleShot(0, canvas.scene.update)
            return

    qCritical("PatchCanvas::rename_port(%i, %i, %s) - Unable to find port to rename"
              % (group_id, port_id, new_port_name.encode()))

def add_portgroup(group_id: int, portgrp_id: int, port_mode: PortMode,
                  port_type: PortType, port_id_list: list):
    if canvas.debug:
        print("PatchCanvas::add_portgroup(%i, %i)" % (group_id, portgrp_id))

    for portgrp in canvas.portgrp_list:
        if portgrp.group_id == group_id and portgrp.portgrp_id == portgrp_id:
            qWarning("PatchCanvas::add_portgroup(%i, %i) - portgroup already exists"
                     % (group_id, portgrp_id))
            return
    
    portgrp_dict = PortgrpObject()
    portgrp_dict.group_id = group_id
    portgrp_dict.portgrp_id = portgrp_id
    portgrp_dict.port_mode = port_mode
    portgrp_dict.port_type = port_type
    portgrp_dict.port_id_list = tuple(port_id_list)
    portgrp_dict.widget = None

    i = 0
    # check that port ids are present and groupable in this group
    for port in canvas.port_list:
        if (port.group_id == group_id
                and port.port_type == port_type
                and port.port_mode == port_mode):
            if port.port_id == port_id_list[i]:
                if port.portgrp_id:
                    qWarning(
                        "PatchCanvas::add_portgroup(%i, %i, %s) - port id %i is already in portgroup %i"
                        % (group_id, portgrp_id, str(port_id_list), port.port_id, port.portgrp_id))
                    return

                i += 1

                if i == len(port_id_list):
                    # everything seems ok for this portgroup, stop the check
                    break

            elif i > 0:
                qWarning(
                    "PatchCanvas::add_portgroup(%i, %i, %s) - port ids are not consecutive"
                    % (group_id, portgrp_id, str(port_id_list)))
                return
    else:
        qWarning(
            "PatchCanvas::add_portgroup(%i, %i, %s) - not enought ports with port_id_list"
            % (group_id, portgrp_id, str(port_id_list)))
        return

    # modify ports impacted by portgroup
    for port in canvas.port_list:
        if (port.group_id == group_id
                and port.port_id in port_id_list):
            port.portgrp_id = portgrp_id
            if port.widget is not None:
                port.widget.set_portgroup_id(
                    portgrp_id,
                    port_id_list.index(port.port_id),
                    len(port_id_list))

    canvas.portgrp_list.append(portgrp_dict)
    
    # add portgroup widget and refresh the view
    for group in canvas.group_list:
        if group.group_id == group_id:
            for box in group.widgets:
                if box is None:
                    continue

                if (not box.is_splitted()
                        or box.get_splitted_mode() == port_mode):
                    portgrp_dict.widget = box.add_portgroup_from_group(
                        portgrp_id, port_mode, port_type, port_id_list)

                    if not canvas.loading_items:
                        box.update_positions()
            break

def remove_portgroup(group_id: int, portgrp_id: int):
    if canvas.debug:
        print("PatchCanvas::remove_portgroup(%i, %i)" % (group_id, portgrp_id))

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
                        port.widget.set_portgroup_id(0, 0, 1)
                        box_widget = port.widget.parentItem()

            if portgrp.widget is not None:
                item = portgrp.widget
                canvas.scene.removeItem(item)
                del item
                portgrp.widget = None
            break
    else:
        qCritical(
            "PatchCanvas::remove_portgroup(%i, %i) - Unable to find portgrp to remove"
            % (group_id, portgrp_id))
        return

    canvas.portgrp_list.remove(portgrp)

    if canvas.loading_items:
        return

    if box_widget is not None:
        box_widget._layout_may_have_change = True
        box_widget.update_positions()

    QTimer.singleShot(0, canvas.scene.update)

def connect_ports(connection_id: int, group_out_id: int, port_out_id: int,
                  group_in_id: int, port_in_id: int):
    if canvas.debug:
        print("PatchCanvas::connect_ports(%i, %i, %i, %i, %i)"
              % (connection_id, group_out_id, port_out_id, group_in_id, port_in_id))

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
        qCritical(
            "PatchCanvas::connect_ports(%i, %i, %i, %i, %i) - unable to find ports to connect"
            % (connection_id, group_out_id, port_out_id, group_in_id, port_in_id))
        return

    connection = ConnectionObject()
    connection.connection_id = connection_id
    connection.group_in_id = group_in_id
    connection.port_in_id = port_in_id
    connection.group_out_id = group_out_id
    connection.port_out_id = port_out_id
    connection.widget = CanvasBezierLine(port_out, port_in, None)

    canvas.scene.addItem(connection.widget)

    port_out_parent.add_line_from_group(connection.widget, connection_id)
    port_in_parent.add_line_from_group(connection.widget, connection_id)

    canvas.last_z_value += 1
    port_out_parent.setZValue(canvas.last_z_value)
    port_in_parent.setZValue(canvas.last_z_value)

    canvas.last_z_value += 1
    connection.widget.setZValue(canvas.last_z_value)

    canvas.connection_list.append(connection)

    canvas.qobject.connection_added.emit(connection_id)
    
    if canvas.loading_items:
        return

    QTimer.singleShot(0, canvas.scene.update)

def disconnect_ports(connection_id: int):
    if canvas.debug:
        print("PatchCanvas::disconnect_ports(%i)" % connection_id)

    for connection in canvas.connection_list:
        if connection.connection_id == connection_id:
            tmp_conn = connection.copy_no_widget()
            line = connection.widget
            canvas.connection_list.remove(connection)
            break
    else:
        qCritical("PatchCanvas::disconnect_ports(%i) - unable to find connection ports"
                  % connection_id)
        return

    canvas.qobject.connection_removed.emit(connection_id)

    for port in canvas.port_list:
        if (port.group_id == tmp_conn.group_out_id
                and port.port_id == tmp_conn.port_out_id):
            item1 = port.widget
            break
    else:
        qCritical("PatchCanvas::disconnect_ports(%i) - unable to find output port"
                  % connection_id)
        return

    for port in canvas.port_list:
        if (port.group_id == tmp_conn.group_in_id 
                and port.port_id == tmp_conn.port_in_id):
            item2 = port.widget
            break
    else:
        qCritical("PatchCanvas::disconnect_ports(%i) - unable to find input port"
                  % connection_id)
        return

    item1.parentItem().remove_line_from_group(connection_id)
    item2.parentItem().remove_line_from_group(connection_id)

    canvas.scene.removeItem(line)
    del line

    if canvas.loading_items:
        return

    QTimer.singleShot(0, canvas.scene.update)

# ----------------------------------------------------------------------------

def get_theme() -> str:
    return canvas.theme_manager.get_theme()

def list_themes() -> list:
    return canvas.theme_manager.list_themes()

def change_theme(theme_name='') -> bool:
    return canvas.theme_manager.set_theme(theme_name)

def copy_and_load_current_theme(new_theme_name: str) -> int:
    return canvas.theme_manager.copy_and_load_current_theme(new_theme_name)

# ----------------------------------------------------------------------------

def redraw_plugin_group(plugin_id):
    group = canvas.group_plugin_map.get(plugin_id, None)

    if group is None:
        #qCritical("PatchCanvas::redraw_plugin_group(%i) - unable to find group" % plugin_id)
        return

    group.widgets[0].redraw_inline_display()

    if group.split and group.widgets[1]:
        group.widgets[1].redraw_inline_display()

def handle_plugin_removed(plugin_id):
    if canvas.debug:
        print("PatchCanvas::handle_plugin_removed(%i)" % plugin_id)

    group = canvas.group_plugin_map.pop(plugin_id, None)

    if group is not None:
        group.plugin_id = -1
        group.plugin_ui = False
        group.plugin_inline = False
        group.widgets[0].remove_as_plugin()

        if group.split and group.widgets[1]:
            group.widgets[1].remove_as_plugin()

    for group in canvas.group_list:
        if group.plugin_id < plugin_id or group.plugin_id > MAX_PLUGIN_ID_ALLOWED:
            continue

        group.plugin_id -= 1
        group.widgets[0]._plugin_id -= 1

        if group.split and group.widgets[1]:
            group.widgets[1]._plugin_id -= 1

        canvas.group_plugin_map[plugin_id] = group

def handle_all_plugins_removed():
    if canvas.debug:
        print("PatchCanvas::handle_all_plugins_removed()")

    canvas.group_plugin_map = {}

    for group in canvas.group_list:
        if group.plugin_id < 0:
            continue
        if group.plugin_id > MAX_PLUGIN_ID_ALLOWED:
            continue

        group.plugin_id = -1
        group.plugin_ui = False
        group.plugin_inline = False
        group.widgets[0].remove_as_plugin()

        if group.split and group.widgets[1]:
            group.widgets[1].remove_as_plugin()

def set_elastic(yesno: bool):
    canvas.scene.set_elastic(yesno)

def set_prevent_overlap(yesno: bool):
    canvas.scene.set_prevent_overlap(yesno)
    
    if yesno:
        redraw_all_groups()

def full_prevent_overlap():
    box_tuples = []
    for group in canvas.group_list:
        for box in group.widgets:
            if box is not None:
                box_tuples.append(box.sceneBoundingRect(), box)
    

def set_max_port_width(width: int):
    options.max_port_width = width
    redraw_all_groups()

def semi_hide_group(group_id: int, yesno: bool):
    for group in canvas.group_list:
        if group.group_id == group_id:
            for widget in group.widgets:
                if widget is not None:
                    widget.semi_hide(yesno)
            break

def semi_hide_connection(connection_id: int, yesno: bool):
    for connection in canvas.connection_list:
        if connection.connection_id == connection_id:
            if connection.widget is not None:
                connection.widget.semi_hide(yesno)
            break

def set_group_in_front(group_id: int):
    canvas.last_z_value += 1
    
    for group in canvas.group_list:
        if group.group_id == group_id:
            for widget in group.widgets:
                if widget is not None:
                    widget.setZValue(canvas.last_z_value)
            break

def set_connection_in_front(connection_id: int):
    canvas.last_z_value += 1
    
    for conn in canvas.connection_list:
        if conn.connection_id == connection_id:
            if conn.widget is not None:
                conn.widget.setZValue(canvas.last_z_value)
            break

def select_filtered_group_box(group_id: int, n_select=1):
    for group in canvas.group_list:
        if group.group_id == group_id:
            n_widget = 1

            for widget in group.widgets:
                if widget is not None and widget.isVisible():
                    if n_select == n_widget:
                        canvas.scene.clearSelection()
                        widget.setSelected(True)
                        canvas.scene.center_view_on(widget)
                        break

                    n_widget += 1
            break

def get_number_of_boxes(group_id: int)->int:
    n = 0
    
    for group in canvas.group_list:
        if group.group_id == group_id:
            for widget in group.widgets:
                if widget is not None and widget.isVisible():
                    n += 1
            break
    
    return n
    
def set_semi_hide_opacity(opacity: float):
    canvas.semi_hide_opacity = opacity

    for group in canvas.group_list:
        for widget in group.widgets:
            if widget is not None:
                widget.update_opacity()
                
    for conn in canvas.connection_list:
        if conn.widget is not None:
            conn.widget.update_line_gradient()

def set_optional_gui_state(group_id: int, visible: bool):
    for group in canvas.group_list:
        if group.group_id == group_id:
            group.handle_client_gui = True
            group.gui_visible = visible

            for widget in group.widgets:
                if widget is not None:
                    widget.set_optional_gui_state(visible)
            break
        
    canvas.scene.update()

def save_cache():
    canvas.theme.save_cache()
    
# PatchCanvas API
def get_options_object():
    return CanvasOptionsObject()

def get_features_object():
    return CanvasFeaturesObject()

def set_options(new_options: CanvasOptionsObject):
    if not canvas.initiated:
        options.__dict__ = new_options.__dict__.copy()

def set_features(new_features: CanvasFeaturesObject):
    if not canvas.initiated:
        features.__dict__ = new_features.__dict__.copy()
# ----------------------------------------------------------------------------
