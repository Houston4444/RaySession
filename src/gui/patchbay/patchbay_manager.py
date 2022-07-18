
from dataclasses import dataclass
import sys
import time
from typing import Callable, Union
from PyQt5.QtGui import QCursor, QGuiApplication
from PyQt5.QtWidgets import QMessageBox, QWidget
from PyQt5.QtCore import QTimer, QSettings

from .patchcanvas import patchcanvas, PortType, EyeCandy
from .patchcanvas.utils import get_new_group_positions
from .patchbay_signals import SignalsObject
from .tools_widgets import (PORT_TYPE_AUDIO, PORT_TYPE_MIDI,
                            PatchbayToolsWidget, CanvasMenu)
from .options_dialog import CanvasOptionsDialog
from .base_elements import (Connection, GroupPos, Port, Portgroup, Group,
                            JackPortFlag, PortgroupMem)
from .calbacker import Callbacker


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

@dataclass
class DelayedOrder:
    func: Callable
    args: tuple
    kwargs: dict
    draw_group: bool
    sort_group: bool
    clear_conns: bool

    
def later_by_batch(draw_group=False, sort_group=False, clear_conns=False):
    def decorator(func: Callable):
        def wrapper(*args, **kwargs):
            mng = args[0]
            assert isinstance(mng, PatchbayManager)
            if mng.very_fast_operation:
                return func(*args, **kwargs)
            
            mng.delayed_orders.append(
                DelayedOrder(func, args, kwargs,
                             draw_group or sort_group,
                             sort_group,
                             clear_conns))
            
            mng._delayed_orders_timer.start()
            return
        return wrapper
    return decorator


class PatchbayManager:
    use_graceful_names = True
    port_types_view = (enum_to_flag(PortType.AUDIO_JACK)
                       | enum_to_flag(PortType.MIDI_JACK))
    
    # when True, items can be added to patchcanvas but they won't be drawn
    optimized_operation = False
    
    # when True, items are not added/removed from patchcanvas
    # useful to win time at startup or refresh
    very_fast_operation = False

    groups = list[Group]()
    connections = list[Connection]()
    _groups_by_name = dict[str, Group]()
    _groups_by_id = dict[int, Group]()
    _ports_by_name = dict[str, Port]()

    group_positions = list[GroupPos]()
    portgroups_memory = list[PortgroupMem]()
    delayed_orders = list[DelayedOrder]()

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
        # when a lot of ports are added/removed/renamed simultaneously.
        self._delayed_orders_timer = QTimer()
        self._delayed_orders_timer.setInterval(50)
        self._delayed_orders_timer.setSingleShot(True)
        self._delayed_orders_timer.timeout.connect(
            self._delayed_orders_timeout)

    # --- widgets related methods --- #

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

    def show_options_dialog(self):
        if self.options_dialog is None:
            return
        
        self.options_dialog.move(QCursor.pos())
        self.options_dialog.show()

    # --- manager methods --- #

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

    def get_group_from_name(self, group_name: str) -> Union[Group, None]:
        return self._groups_by_name.get(group_name)

    def get_group_from_id(self, group_id: int) -> Union[Group, None]:
        return self._groups_by_id.get(group_id)

    def get_port_from_name(self, port_name: str) -> Port:
        return self._ports_by_name.get(port_name)

    def get_port_from_uuid(self, uuid:int) -> Port:
        for group in self.groups:
            for port in group.ports:
                if port.uuid == uuid:
                    return port

    def get_port_from_id(self, group_id: int, port_id: int) -> Port:
        group = self.get_group_from_id(group_id)
        if group is not None:        
            for port in group.ports:
                if port.port_id == port_id:
                    return port

    def save_group_position(self, gpos: GroupPos):
        # reimplement this to save a group position elsewhere
        pass

    def save_portgroup_memory(self, portgrp_mem: PortgroupMem):
        # reimplement this to save a portgroup memory elsewhere
        pass

    def get_corrected_a2j_group_name(self, group_name: str) -> str:
        # a2j replace points with spaces in the group name
        # we do nothing here, but in some conditions we can 
        # assume we know it.
        return group_name

    def set_group_as_nsm_client(self, group: Group):
        pass

    def get_group_position(self, group_name: str) -> GroupPos:
        for gpos in self.group_positions:
            if (gpos.port_types_view == self.port_types_view
                    and gpos.group_name == group_name):
                return gpos

        # prevent move to a new position in case of port_types_view change
        # if there is no remembered position for this group in new view
        group = self.get_group_from_name(group_name)
        if group is not None:
            # copy the group_position
            gpos = group.current_position.copy()
            gpos.port_types_view = self.port_types_view
            return gpos

        # group position doesn't already exists, create one
        gpos = GroupPos()
        gpos.fully_set = False
        gpos.port_types_view = self.port_types_view
        gpos.group_name = group_name
        gpos.null_xy, gpos.in_xy, gpos.out_xy = get_new_group_positions()
        self.group_positions.append(gpos)
        self.save_group_position(gpos)
        return gpos

    def add_portgroup_memory(self, portgroup_mem: PortgroupMem):
        remove_list = list[PortgroupMem]()

        for pg_mem in self.portgroups_memory:
            if pg_mem.has_a_common_port_with(portgroup_mem):
                remove_list.append(pg_mem)

        for pg_mem in remove_list:
            self.portgroups_memory.remove(pg_mem)

        self.portgroups_memory.append(portgroup_mem)
        
        group = self.get_group_from_name(portgroup_mem.group_name)
        if group is not None:
            group.portgroup_memory_added(portgroup_mem)

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

        groups_and_pos = dict[Group, GroupPos]()

        for group in self.groups:
            group.change_port_types_view()
            groups_and_pos[group] = self.get_group_position(group.name)

        for connection in self.connections:
            connection.add_to_canvas()

        self.optimize_operation(False)
        
        patchcanvas.redraw_all_groups()
        
        for group, gpos in groups_and_pos.items():
            group.set_group_position(gpos)
        
        self.sg.port_types_view_changed.emit(self.port_types_view)

    # --- options triggers ---

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

    @later_by_batch()
    def set_group_uuid_from_name(self, client_name: str, uuid: int):
        group = self.get_group_from_name(client_name)
        if group is not None:
            group.uuid = uuid

    @later_by_batch(draw_group=True)
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
        
        group = self.get_group_from_name(group_name)
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

    @later_by_batch(draw_group=True, clear_conns=True)
    def remove_port(self, name: str) -> Union[int, None]:
        ''' removes a port from name and return its group_id '''
        port = self.get_port_from_name(name)
        if port is None:
            return None

        group = self.get_group_from_id(port.group_id)
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

    @later_by_batch(draw_group=True)
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
            group = self.get_group_from_name(group_name)
            if group is not None:
                group.remove_port(port)
                if not group.ports:
                    self._remove_group(group)

            port.remove_from_canvas()
            port.full_name = new_name

            group = self.get_group_from_name(new_group_name)
            if group is None:
                # copy the group_position to not move the group
                # because group has been renamed
                orig_gpos = self.get_group_position(group_name)
                gpos = orig_gpos.copy()
                gpos.group_name = new_group_name

                group = Group(self, self._next_group_id, new_group_name, gpos)
                self._next_group_id += 1
                group.add_port(port)
                group.add_to_canvas()
            else:
                group.add_port(port)

            port.add_to_canvas()
            return group.group_id

        group = self.get_group_from_id(port.group_id)
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

    @later_by_batch(sort_group=True)
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

    @later_by_batch()
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

    @later_by_batch()
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

    def _delayed_orders_timeout(self):
        self.optimize_operation(True)
        
        group_ids_to_update = set()
        group_ids_to_sort = set()
        some_groups_removed = False
        clear_conns = False
        
        for oq in self.delayed_orders:
            group_id = oq.func(*oq.args, **oq.kwargs)
            if oq.sort_group and group_id:
                group_ids_to_sort.add(group_id)
            if oq.draw_group:
                if group_id:
                    group_ids_to_update.add(group_id)
                else:
                    some_groups_removed = True
            if oq.clear_conns:
                clear_conns = True
        
        for group in self.groups:
            if group.group_id in group_ids_to_sort:
                group.sort_ports_in_canvas()

        if clear_conns:
            # sometimes connections are still in canvas without ports
            # probably because the message for their destruction
            # has not been received.
            # here we can assume to clear all of them
            conns_to_clean = list[Connection]()

            for conn in self.connections:
                for port in (conn.port_out, conn.port_in):
                    fport = self.get_port_from_name(port.full_name)
                    if fport is None:
                        conn.remove_from_canvas()
                        conns_to_clean.append(conn)
                        break
                    
                    if not fport.in_canvas:
                        conn.remove_from_canvas()
                    
            for conn in conns_to_clean:
                self.connections.remove(conn)
        
        self.optimize_operation(False)
        self.delayed_orders.clear()

        for group in self.groups:
            if group.group_id in group_ids_to_update:
                group.redraw_in_canvas()

        if some_groups_removed:
            patchcanvas.canvas.scene.resize_the_scene()
