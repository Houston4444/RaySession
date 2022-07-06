
import json
import os
import sys
import time
from typing import TYPE_CHECKING, Union
from PyQt5.QtGui import QCursor, QGuiApplication
from PyQt5.QtWidgets import QMessageBox, QWidget
from PyQt5.QtCore import QTimer, QSettings

import ray

from .patchcanvas import patchcanvas
from .patchcanvas import PortType, EyeCandy
from .patchbay_signals import SignalsObject
from .patchbay_tools import (PORT_TYPE_AUDIO, PORT_TYPE_MIDI,
                            PatchbayToolsWidget, CanvasMenu)
from .canvas_options import CanvasOptionsDialog

from .patchbay_elements import Connection, Port, Portgroup, Group, JackPortFlag
from .patchbay_calbacker import Callbacker


# Group Position Flags
GROUP_CONTEXT_AUDIO = 0x01
GROUP_CONTEXT_MIDI = 0x02
GROUP_SPLITTED = 0x04
GROUP_WRAPPED_INPUT = 0x10
GROUP_WRAPPED_OUTPUT = 0x20
GROUP_HAS_BEEN_SPLITTED = 0x40

# Meta data (taken from pyjacklib)
_JACK_METADATA_PREFIX = "http://jackaudio.org/metadata/"
JACK_METADATA_CONNECTED = _JACK_METADATA_PREFIX + "connected"
JACK_METADATA_EVENT_TYPES = _JACK_METADATA_PREFIX + "event-types"
JACK_METADATA_HARDWARE = _JACK_METADATA_PREFIX + "hardware"
JACK_METADATA_ICON_LARGE = _JACK_METADATA_PREFIX + "icon-large"
JACK_METADATA_ICON_NAME = _JACK_METADATA_PREFIX + "icon-name"
JACK_METADATA_ICON_SMALL = _JACK_METADATA_PREFIX + "icon-small"
JACK_METADATA_ORDER = _JACK_METADATA_PREFIX + "order"
JACK_METADATA_PORT_GROUP = _JACK_METADATA_PREFIX + "port-group"
JACK_METADATA_PRETTY_NAME = _JACK_METADATA_PREFIX + "pretty-name"
JACK_METADATA_SIGNAL_TYPE = _JACK_METADATA_PREFIX + "signal-type"

_translate = QGuiApplication.translate

def enum_to_flag(enum_int: int) -> int:
    if enum_int <= 0:
        return 0
    return 2 ** (enum_int - 1)


class PatchbayManager:
    use_graceful_names = True
    port_types_view = (enum_to_flag(PortType.AUDIO_JACK)
                       | enum_to_flag(PortType.MIDI_JACK))
    optimized_operation = False
    very_fast_operation = False

    groups = list[Group]()
    connections = list[Connection]()
    _groups_by_name = dict[str, Group]()
    _groups_by_id = dict[int, Group]()
    _ports_by_name = dict[str, Port]()

    group_positions = list[ray.GroupPosition]()
    portgroups_memory = list[ray.PortGroupMemory]()
    orders_queue = list[dict]()

    def __init__(self, settings=None):
        self.callbacker = Callbacker(self)
        
        if settings is not None:
            assert isinstance(settings, QSettings)
        self._settings = settings

        self.main_win = None
        self._tools_widget = None
        self.options_dialog = None

        self.sg = SignalsObject()

        self._next_group_id = 0
        self._next_port_id = 0
        self._next_connection_id = 0
        self._next_portgroup_id = 1

        self.set_graceful_names(settings.value(
            'Canvas/use_graceful_names', True, type=bool))
        self.group_a2j_hw = settings.value(
            'Canvas/group_a2j_ports', True, type=bool)

        # all patchbay events are delayed
        # to reduce the patchbay comsumption.
        # Redraws in canvas are made once 50ms have passed without any event.
        # This prevent one group redraw per port added/removed
        # when a lot of ports are added/removed/renamed simultaneously
        self._orders_queue_timer = QTimer()
        self._orders_queue_timer.setInterval(50)
        self._orders_queue_timer.setSingleShot(True)
        self._orders_queue_timer.timeout.connect(
            self._order_queue_timeout)

    def set_main_win(self, main_win: QWidget):
        self.main_win = main_win

    def set_tools_widget(self, tools_widget: PatchbayToolsWidget):
        self._tools_widget = tools_widget
        self._tools_widget.buffer_size_change_order.connect(
            self.change_buffersize)

    def set_canvas_menu(self, canvas_menu: CanvasMenu):
        self.canvas_menu = canvas_menu

    def set_options_dialog(self, options_dialog: CanvasOptionsDialog):
        self.options_dialog = options_dialog
        self.options_dialog.gracious_names_checked.connect(
            self.set_graceful_names)
        self.options_dialog.a2j_grouped_checked.connect(
            self.set_a2j_grouped)
        self.options_dialog.group_shadows_checked.connect(
            self.set_group_shadows)
        self.options_dialog.theme_changed.connect(
            self.change_theme)
        self.options_dialog.elastic_checked.connect(
            self.set_elastic_canvas)
        self.options_dialog.borders_nav_checked.connect(
            self.set_borders_navigation)
        self.options_dialog.prevent_overlap_checked.connect(
            self.set_prevent_overlap)
        self.options_dialog.max_port_width_changed.connect(
            patchcanvas.set_max_port_width)

    @staticmethod
    def save_patchcanvas_cache():
        patchcanvas.save_cache()

    def set_use_graceful_names(self, yesno: bool):
        self.use_graceful_names = yesno

    def optimize_operation(self, yesno: bool):
        self.optimized_operation = yesno
        if patchcanvas.canvas is not None:
            patchcanvas.set_loading_items(yesno)

    def _set_very_fast_operation(self, yesno: bool):
        self.very_fast_operation = yesno

    def _add_group(self, group: Group):
        self.groups.append(group)
        self._groups_by_id[group.group_id] = group
        self._groups_by_name[group.name] = group

    def _remove_group(self, group: Group):
        if group in self.groups:
            self.groups.remove(group)
            self._groups_by_id.pop(group.group_id)
            self._groups_by_name.pop(group.name)

    def _clear_groups(self):
        self.groups.clear()
        self._groups_by_id.clear()
        self._groups_by_name.clear()

    def new_portgroup(self, group_id: int, port_mode: int,
                      ports: tuple[Port]) -> Portgroup:
        portgroup = Portgroup(self, group_id, self._next_portgroup_id,
                              port_mode, ports)
        self._next_portgroup_id += 1
        return portgroup

    def port_type_shown(self, port_type: int) -> bool:
        return bool(self.port_types_view & enum_to_flag(port_type))

    def show_options_dialog(self):
        if self.options_dialog is None:
            return
        
        self.options_dialog.move(QCursor.pos())
        self.options_dialog.show()

    def set_graceful_names(self, yesno: int):
        if self.use_graceful_names != yesno:
            self.toggle_graceful_names()

    def set_a2j_grouped(self, yesno: int):
        if self.group_a2j_hw != bool(yesno):
            self.group_a2j_hw = bool(yesno)
            self.refresh()

    def set_group_shadows(self, yesno: int):
        if yesno:
            patchcanvas.options.eyecandy = EyeCandy.SMALL
        else:
            patchcanvas.options.eyecandy = EyeCandy.NONE
        self.remove_and_add_all()

    def change_theme(self, theme_name: str):
        if not theme_name:
            return
        patchcanvas.change_theme(theme_name)

    def set_elastic_canvas(self, yesno: int):
        patchcanvas.set_elastic(yesno)

    def set_borders_navigation(self, yesno: int):
        patchcanvas.set_borders_navigation(yesno)

    def set_prevent_overlap(self, yesno: int):
        patchcanvas.set_prevent_overlap(yesno)

    def toggle_graceful_names(self):
        self.set_use_graceful_names(not self.use_graceful_names)
        self.optimize_operation(True)
        for group in self.groups:
            group.update_ports_in_canvas()
            group.update_name_in_canvas()
        self.optimize_operation(False)
        patchcanvas.redraw_all_groups()

    def refresh(self):
        self.clear_all()

    def get_port_from_name(self, port_name: str) -> Port:
        return self._ports_by_name.get(port_name)

    def get_port_from_uuid(self, uuid:int) -> Port:
        for group in self.groups:
            for port in group.ports:
                if port.uuid == uuid:
                    return port

    def get_port_from_id(self, group_id: int, port_id: int) -> Port:
        group = self._groups_by_id.get(group_id)
        if group is not None:        
            for port in group.ports:
                if port.port_id == port_id:
                    return port

    def save_group_position(self, gpos: ray.GroupPosition):
        pass

    def save_portgroup_memory(self, portgrp_mem: ray.PortGroupMemory):
        pass    

    def get_corrected_a2j_group_name(self, group_name: str) -> str:
        return group_name

    def set_group_as_nsm_client(self, group: Group):
        pass

    def get_group_position(self, group_name: str) -> ray.GroupPosition:
        for gpos in self.group_positions:
            if (gpos.port_types_view == self.port_types_view
                    and gpos.group_name == group_name):
                return gpos

        # prevent move to a new position in case of port_types_view change
        # if there is no remembered position for this group in new view
        group = self._groups_by_name.get(group_name)
        if group is not None:
            # copy the group_position
            gpos = ray.GroupPosition.new_from(
                *group.current_position.spread())
            gpos.port_types_view = self.port_types_view
            self.group_positions.append(gpos)
            return gpos

        # group position doesn't already exists, create one
        gpos = ray.GroupPosition()
        gpos.fully_set = False
        gpos.port_types_view = self.port_types_view
        gpos.group_name = group_name
        gpos.null_xy, gpos.in_xy, gpos.out_xy =  \
            patchcanvas.utils.get_new_group_positions()
        self.group_positions.append(gpos)
        self.save_group_position(gpos)
        return gpos

    def add_portgroup_memory(self, portgroup_mem):
        remove_list = []

        for pg_mem in self.portgroups_memory:
            if pg_mem.has_a_common_port_with(portgroup_mem):
                remove_list.append(pg_mem)

        for pg_mem in remove_list:
            self.portgroups_memory.remove(pg_mem)

        self.portgroups_memory.append(portgroup_mem)

    def remove_and_add_all(self):
        self.optimize_operation(True)
            
        for connection in self.connections:
            connection.remove_from_canvas()
        
        for group in self.groups:
            for portgroup in group.portgroups:
                portgroup.remove_from_canvas()
            
            for port in group.ports:
                port.remove_from_canvas()
            group.remove_from_canvas()
            
            group.add_to_canvas()
            for port in group.ports:
                port.add_to_canvas()
            for portgroup in group.portgroups:
                portgroup.add_to_canvas()
        
        for connection in self.connections:
            connection.add_to_canvas()
        
        self.optimize_operation(False)
        patchcanvas.redraw_all_groups()

    def clear_all(self):
        self.optimize_operation(True)
        for connection in self.connections:
            connection.remove_from_canvas()

        for group in self.groups:
            group.remove_all_ports()
            group.remove_from_canvas()

        self.optimize_operation(False)

        self.connections.clear()
        self._clear_groups()

        patchcanvas.clear()

        self._next_group_id = 0
        self._next_port_id = 0
        self._next_portgroup_id = 1
        self._next_connection_id = 0

    def change_port_types_view(self, port_types_view: int):
        if port_types_view == self.port_types_view:
            return

        self.port_types_view = port_types_view

        # Prevent visual update at each canvas item creation
        # because we may create a lot of ports here
        self.optimize_operation(True)

        for connection in self.connections:
            if (connection.in_canvas
                    and not port_types_view & connection.port_type()):
                connection.remove_from_canvas()

        for group in self.groups:
            group.change_port_types_view()
            gpos = self.get_group_position(group.name)
            group.set_group_position(gpos)

        for connection in self.connections:
            connection.add_to_canvas()

        self.optimize_operation(False)
        patchcanvas.redraw_all_groups()
        self.sg.port_types_view_changed.emit(
            self.port_types_view)

    def get_json_contents_from_path(self, file_path: str) -> dict:
        if not os.path.exists(file_path):
            return {}

        if not os.access(file_path, os.R_OK):
            return {}

        try:
            file = open(file_path, 'r')
        except IOError:
            return {}

        try:
            new_dict = json.load(file)
            assert isinstance(new_dict, dict)
        except ImportError:
            return {}

        file.close()
        return new_dict

    def set_group_uuid_from_name(self, client_name: str, uuid: int):
        group = self._groups_by_name.get(client_name)
        if group is not None:
            group.uuid = uuid

    def add_port(self, name: str, port_type_int: int, flags: int, uuid: int) -> int:
        ''' adds port and returns the group_id '''
        port_type = PortType.NULL

        if port_type_int == PORT_TYPE_AUDIO:
            port_type = PortType.AUDIO_JACK
        elif port_type_int == PORT_TYPE_MIDI:
            port_type = PortType.MIDI_JACK
        
        port = Port(self, self._next_port_id, name, port_type, flags, uuid)
        self._next_port_id += 1

        full_port_name = name
        group_name, colon, port_name = full_port_name.partition(':')

        is_a2j_group = False
        group_is_new = False

        if (full_port_name.startswith(('a2j:', 'Midi-Bridge:'))
                and (not self.group_a2j_hw
                     or not port.flags & JackPortFlag.IS_PHYSICAL)):
            group_name, colon, port_name = port_name.partition(':')
            if full_port_name.startswith('a2j:'):
                if ' [' in group_name:
                    group_name = group_name.rpartition(' [')[0]
                else:
                    if ' (capture)' in group_name:
                        group_name = group_name.partition(' (capture)')[0]
                    else:
                        group_name = group_name.partition(' (playback)')[0]

                # fix a2j wrongly substitute '.' with space
                group_name = self.get_corrected_a2j_group_name(group_name)

            if port.flags & JackPortFlag.IS_PHYSICAL:
                is_a2j_group = True
        
        group = self._groups_by_name.get(group_name)
        if group is None:
            # port is an non existing group, create the group
            gpos = self.get_group_position(group_name)
            group = Group(self, self._next_group_id, group_name, gpos)
            group.a2j_group = is_a2j_group
            self.set_group_as_nsm_client(group)

            self._next_group_id += 1
            self._add_group(group)
            group_is_new = True

        group.add_port(port)
        group.graceful_port(port)

        if group_is_new:
            gpos = self.get_group_position(group_name)
            group.set_group_position(gpos)

        group.add_to_canvas()
        port.add_to_canvas()
        group.check_for_portgroup_on_last_port()
        group.check_for_display_name_on_last_port()
        
        return group.group_id

    def remove_port(self, name: str) -> Union[int, None]:
        ''' removes a port from name and return the group_id'''
        port = self.get_port_from_name(name)
        if port is None:
            return None

        for connection in self.connections:
            if connection.port_out is port or connection.port_in is port:
                connection.remove_from_canvas()
                self.connections.remove(connection)
                break

        group = self._groups_by_id.get(port.group_id)
        if group is None:
            return None

        # remove portgroup first if port is in a portgroup
        if port.portgroup_id:
            for portgroup in group.portgroups:
                if portgroup.portgroup_id == port.portgroup_id:
                    group.portgroups.remove(portgroup)
                    portgroup.remove_from_canvas()
                    break

        port.remove_from_canvas()
        group.remove_port(port)

        if not group.ports:
            group.remove_from_canvas()
            self._remove_group(group)
            return None
        
        return group.group_id

    def rename_port(self, name: str, new_name: str) -> Union[int, None]:
        port = self.get_port_from_name(name)
        if port is None:
            sys.stderr.write(
                "RaySession:PatchbayManager::rename_port"
                + "\"%s\" to \"%s\", port doesn't exists\n"
                    % (name, new_name))
            return

        group_name = name.partition(':')[0]
        new_group_name = new_name.partition(':')[0]

        # In case a port rename implies another group for the port
        if group_name != new_group_name:
            group = self._groups_by_name.get(group_name)
            if group is not None:
                group.remove_port(port)
                if not group.ports:
                    self._remove_group(group)

            port.remove_from_canvas()
            port.full_name = new_name

            group = self._groups_by_name.get(new_group_name)
            if group is None:
                # copy the group_position to not move the group
                # because group has been renamed
                orig_gpos = self.get_group_position(group_name)
                gpos = ray.GroupPosition.new_from(*orig_gpos.spread())
                gpos.group_name = new_group_name

                group = Group(self, self._next_group_id, new_group_name, gpos)
                self._next_group_id += 1
                group.add_port(port)
                group.add_to_canvas()
            else:
                group.add_port(port)

            port.add_to_canvas()
            return group.group_id

        group = self._groups_by_id.get(port.group_id)
        if group is not None:
            # because many ports may be renamed quicky
            # It is prefferable to rename all theses ports together.
            # It prevents too much widget update in canvas,
            # renames now could also prevent to find stereo detected portgroups
            # if one of the two ports has been renamed and not the other one.
            port.full_name = new_name
            group.graceful_port(port)
            port.rename_in_canvas()

            return group.group_id

    def metadata_update(self, uuid: int, key: str, value: str) -> int:
        ''' remember metadata and returns the group_id'''
        if key == JACK_METADATA_ORDER:
            port = self.get_port_from_uuid(uuid)
            if port is None:
                return

            try:
                port_order = int(value)
            except:
                sys.stderr.write(
                    "RaySession:PatchbayManager::JACK_METADATA_ORDER "
                    + "value is not an int (%i,%s)\n" % (uuid, value))
                return

            port.order = port_order
            return port.group_id

        elif key == JACK_METADATA_PRETTY_NAME:
            port = self.get_port_from_uuid(uuid)
            if port is None:
                return

            port.pretty_name = value
            port.rename_in_canvas()
            return port.group_id

        elif key == JACK_METADATA_PORT_GROUP:
            port = self.get_port_from_uuid(uuid)
            if port is None:
                return

            port.mdata_portgroup = value
            return port.group_id

        elif key == JACK_METADATA_ICON_NAME:
            for group in self.groups:
                if group.uuid == uuid:
                    group.set_client_icon(value, from_metadata=True)
                    return group.group_id

    def add_connection(self, port_out_name: str, port_in_name: str):
        port_out = self.get_port_from_name(port_out_name)
        port_in = self.get_port_from_name(port_in_name)  

        if port_out is None or port_in is None:
            return

        for connection in self.connections:
            if (connection.port_out == port_out
                    and connection.port_in == port_in):
                return

        connection = Connection(self, self._next_connection_id, port_out, port_in)
        self._next_connection_id += 1
        self.connections.append(connection)
        connection.add_to_canvas()

    def remove_connection(self, port_out_name: str, port_in_name: str):
        port_out = self.get_port_from_name(port_out_name)
        port_in = self.get_port_from_name(port_in_name)

        if port_out is None or port_in is None:
            return

        for connection in self.connections:
            if (connection.port_out == port_out
                    and connection.port_in == port_in):
                self.connections.remove(connection)
                connection.remove_from_canvas()
                break

    def update_group_position(self, *args):
        # remember group position and move boxes if needed
        gpos = ray.GroupPosition.new_from(*args)

        for group_position in self.group_positions:
            if (group_position.group_name == gpos.group_name
                    and group_position.port_types_view == gpos.port_types_view):
                group_position.update(*args)
        else:
            self.group_positions.append(gpos)

        if gpos.port_types_view == PatchbayManager.port_types_view:
            group = self._groups_by_name.get(gpos.group_name)
            if group is not None:
                group.set_group_position(gpos)

    def update_portgroup(self, *args):
        portgroup_mem = ray.PortGroupMemory.new_from(*args)
        self.add_portgroup_memory(portgroup_mem)

        group = self._groups_by_name.get(portgroup_mem.group_name)
        if group is not None:
            group.portgroup_memory_added(portgroup_mem)

    def disannounce(self):
        self.clear_all()

    def server_started(self):
        if self._tools_widget is not None:
            self._tools_widget.set_jack_running(True)

    def server_stopped(self):
        if self._tools_widget is not None:
            self._tools_widget.set_jack_running(False)
        self.clear_all()

    def server_lose(self):
        if self._tools_widget is not None:
            self._tools_widget.set_jack_running(False)

        self.clear_all()

        if self.main_win is not None:
            ret = QMessageBox.critical(
                self.main_win,
                _translate('patchbay', "JACK server lose"),
                _translate('patchbay', "JACK server seems to be totally busy... ;("))

    def set_dsp_load(self, dsp_load: int):
        if self._tools_widget is not None:
            self._tools_widget.set_dsp_load(dsp_load)

    def add_xrun(self):
        if self._tools_widget is not None:
            self._tools_widget.add_xrun()

    def change_buffersize(self, buffer_size: int):
        pass

    def redraw_all_groups(self):
        patchcanvas.redraw_all_groups()

    def filter_groups(self, text: str, n_select=0) -> int:
        ''' semi hides groups not matching with text
            and returns number of matching boxes '''
        opac_grp_ids = set()
        opac_conn_ids = set()

        for group in self.groups:
            opac = bool(text.lower() not in group.name.lower()
                        and text.lower() not in group.display_name.lower())
            if opac:
                opac_grp_ids.add(group.group_id)

            group.semi_hide(opac)
        
        for conn in self.connections:
            opac_conn = bool(
                conn.port_out.group_id in opac_grp_ids
                and conn.port_in.group_id in opac_grp_ids)
            
            conn.semi_hide(opac_conn)
            if opac_conn:
                opac_conn_ids.add(conn.connection_id)
            
        for group in self.groups:
            if group.group_id in opac_grp_ids:
                group.set_in_front()
        
        for conn in self.connections:
            if conn.connection_id in opac_conn_ids:
                conn.set_in_front()
        
        for conn in self.connections:
            if conn.connection_id not in opac_conn_ids:
                conn.set_in_front()
        
        n_boxes = 0
        
        for group in self.groups:
            if group.group_id not in opac_grp_ids:
                group.set_in_front()
                n_grp_boxes = group.get_number_of_boxes()

                if n_select > n_boxes and n_select <= n_boxes + n_grp_boxes:
                    group.select_filtered_box(n_select - n_boxes)
                n_boxes += n_grp_boxes

        return n_boxes

    def set_semi_hide_opacity(self, opacity: float):
        patchcanvas.set_semi_hide_opacity(opacity)

    def buffer_size_changed(self, buffer_size: int):
        if self._tools_widget is not None:
            self._tools_widget.set_buffer_size(buffer_size)

    def sample_rate_changed(self, samplerate):
        if self._tools_widget is not None:
            self._tools_widget.set_samplerate(samplerate)

    def add_order_to_queue(self, order: str, *args):
        self.orders_queue.append({'order': order, 'args': args})
        self._orders_queue_timer.start()

    def _order_queue_timeout(self):
        self.optimize_operation(True)
        
        group_ids_to_update = set()
        group_ids_to_sort = set()
        some_groups_removed = False
        
        for order_dict in self.orders_queue:
            order = order_dict['order']
            args = order_dict['args']
            
            if order == 'add_port':
                group_id = self.add_port(*args)
                group_ids_to_update.add(group_id)
                
            elif order == 'remove_port':
                group_id = self.remove_port(*args)
                if group_id is None:
                    some_groups_removed = True
                else:
                    group_ids_to_update.add(group_id)
                    
            elif order == 'rename_port':
                group_id = self.rename_port(*args)
                group_ids_to_update.add(group_id)
                
            elif order == 'add_connection':
                self.add_connection(*args)
                
            elif order == 'remove_connection':
                self.remove_connection(*args)
                
            elif order == 'update_metadata':
                group_id = self.metadata_update(*args)
                if group_id is not None:
                    group_ids_to_update.add(group_id)
                    group_ids_to_sort.add(group_id)
            else:
                sys.stderr.write(
                    '_order_queue_timeout wrong order: %s\n' % order)
        
        for group in self.groups:
            if group.group_id in group_ids_to_sort:
                group.sort_ports_in_canvas()

        self.optimize_operation(False)
        self.orders_queue.clear()
        
        for group in self.groups:
            if group.group_id in group_ids_to_update:
                group.redraw_in_canvas()

        if some_groups_removed:
            patchcanvas.canvas.scene.resize_the_scene()

    def fast_temp_file_memory(self, temp_path):
        ''' receives a .json file path from daemon with groups positions
            and portgroups remembered from user. '''
        canvas_data = self.get_json_contents_from_path(temp_path)
        if not canvas_data:
            sys.stderr.write(
                "RaySession::Failed to load tmp file %s to get canvas positions\n"
                % temp_path)
            return

        for key in canvas_data.keys():
            if key == 'group_positions':
                for gpos_dict in canvas_data[key]:
                    gpos = ray.GroupPosition()
                    gpos.write_from_dict(gpos_dict)
                    self.update_group_position(*gpos.spread())

            elif key == 'portgroups':
                for pg_dict in canvas_data[key]:
                    portgroup_mem = ray.PortGroupMemory()
                    portgroup_mem.write_from_dict(pg_dict)
                    self.update_portgroup(*portgroup_mem.spread())

        os.remove(temp_path)

    def fast_temp_file_running(self, temp_path: str):
        ''' receives a .json file path from patchbay daemon with all ports, connections
            and jack metadatas'''
        patchbay_data = self.get_json_contents_from_path(temp_path)
        if not patchbay_data:
            sys.stderr.write(
                "RaySession::Failed to load tmp file %s to get JACK ports\n"
                % temp_path)
            return

        # optimize_operation allow to not redraw group at each port added.
        # however, if there is no group position
        # (i.e. if there is no config at all), it is prefferable to
        # know where finish the group boxes before to add another one.
        
        # very fast operation means that nothing is done in the patchcanvas
        # everything stays here in this file.
        print('fast tmp file running start', time.time())

        if self.group_positions:
            print('on a des group positions')
            self.optimize_operation(True)
            self._set_very_fast_operation(True)

        for key in patchbay_data.keys():
            if key == 'ports':
                for p in patchbay_data[key]:
                    if TYPE_CHECKING and not isinstance(p, dict):
                        continue
                    self.add_port(p.get('name'), p.get('type'),
                                  p.get('flags'), p.get('uuid'))

            elif key == 'connections':
                for c in patchbay_data[key]:
                    if TYPE_CHECKING and not isinstance(c, dict):
                        continue
                    self.add_connection(c.get('port_out_name'),
                                        c.get('port_in_name'))

        for key in patchbay_data.keys():
            if key == 'clients':
                for cnu in patchbay_data[key]:
                    if TYPE_CHECKING and not isinstance(cnu, dict):
                        continue
                    self.set_group_uuid_from_name(cnu.get('name'), cnu.get('uuid'))
                break

        for key in patchbay_data.keys():
            if key == 'metadatas':
                for m in patchbay_data[key]:
                    if TYPE_CHECKING and not isinstance(m, dict):
                        continue
                    self.metadata_update(
                        m.get('uuid'), m.get('key'), m.get('value'))

        print('tout est rentré', time.time())

        # print('ddk', patchcanvas.canvas.group_list)

        for group in self.groups:
            group.sort_ports_in_canvas()

        print('les ports sont dans lorde', time.time())

        self._set_very_fast_operation(False)
        
        print('tout va rentrer dans le canvas', time.time())
        
        for group in self.groups:
            group.add_all_ports_to_canvas()
        
        print('avant conns', time.time())
        
        for conn in self.connections:
            conn.add_to_canvas()

        print('sfkddf', time.time())
        self.optimize_operation(False)
        patchcanvas.redraw_all_groups()

        try:
            os.remove(temp_path)
        except:
            # if this tmp file can not be removed
            # this is really not strong.
            pass

    def patchbay_announce(self, jack_running: int, samplerate: int,
                          buffer_size: int):
        if self._tools_widget is None:
            return
        
        self._tools_widget.set_samplerate(samplerate)
        self._tools_widget.set_buffer_size(buffer_size)
        self._tools_widget.set_jack_running(jack_running)

        if self.main_win is not None:
            self.main_win.add_patchbay_tools(
                self._tools_widget, self.canvas_menu)
