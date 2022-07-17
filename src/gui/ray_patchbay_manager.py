
import json
from typing import TYPE_CHECKING
import time
import os
import sys

from gui.patchbay.patchcanvas.init_values import PortType

from .patchbay.patchbay_manager import PatchbayManager
from .patchbay.base_elements import (Group, GroupPos, PortgroupMem,
                                     PortMode, BoxLayoutMode)
from .patchbay.options_dialog import CanvasOptionsDialog
from .patchbay.tools_widgets import PatchbayToolsWidget, CanvasMenu
from .patchbay.calbacker import Callbacker

from . import ray
from .gui_server_thread import GuiServerThread
from .gui_tools import RS, is_dark_theme, RayIcon

if TYPE_CHECKING:
    from .gui_session import Session
    from .main_window import MainWindow


def convert_group_pos_from_ray_to_patchbay(
        ray_gpos: ray.GroupPosition) -> GroupPos:
    gpos = GroupPos()
    gpos.port_types_view = ray_gpos.port_types_view
    gpos.group_name = ray_gpos.group_name
    gpos.null_zone = ray_gpos.null_zone
    gpos.in_zone = ray_gpos.in_zone
    gpos.out_zone = ray_gpos.out_zone
    gpos.null_xy = ray_gpos.null_xy
    gpos.in_xy = ray_gpos.in_xy
    gpos.out_xy = ray_gpos.out_xy
    gpos.flags = ray_gpos.flags
    
    for port_mode in PortMode:
        layout_mode = ray_gpos.get_layout_mode(port_mode.value)
        gpos.set_layout_mode(port_mode, BoxLayoutMode(layout_mode))
    
    gpos.fully_set = ray_gpos.fully_set
    return gpos

def convert_group_pos_from_patchbay_to_ray(
        gpos: GroupPos) -> ray.GroupPosition:
    ray_gpos = ray.GroupPosition.new_from(
        int(gpos.port_types_view), gpos.group_name,
        gpos.null_zone, gpos.in_zone, gpos.out_zone,
        *gpos.null_xy, *gpos.in_xy, *gpos.out_xy,
        int(gpos.flags), 0)
    
    for port_mode, box_layout_mode in gpos.layout_modes.items():
        ray_gpos.set_layout_mode(port_mode.value, box_layout_mode.value)
    ray_gpos.fully_set = gpos.fully_set

    return ray_gpos

def convert_portgrp_mem_from_ray_to_patchbay(
        ray_pgmem: ray.PortGroupMemory) -> PortgroupMem:
    pgmem = PortgroupMem()
    pgmem.group_name = ray_pgmem.group_name
    try:
        pgmem.port_mode = PortMode(ray_pgmem.port_mode)
    except ValueError:
        pgmem.port_mode = PortMode.NULL

    try:
        pgmem.port_type = PortType(ray_pgmem.port_type)
    except ValueError:
        pgmem.port_type = PortType.NULL
    
    pgmem.above_metadatas = bool(ray_pgmem.above_metadatas) 
    # TODO, see if copy is required, probably not
    pgmem.port_names = ray_pgmem.port_names
    return pgmem

def convert_portgrp_mem_from_patchbay_to_ray(
        pgmem: PortgroupMem) -> ray.PortGroupMemory:
    return ray.PortGroupMemory.new_from(
        pgmem.group_name, pgmem.port_type.value, pgmem.port_mode.value,
        int(pgmem.above_metadatas), *pgmem.port_names)


class RayPatchbayCallbacker(Callbacker):
    def __init__(self, manager: 'RayPatchbayManager'):
        super().__init__(manager)
        self.mng = manager
        
    def _ports_connect(self, group_out_id: int, port_out_id: int,
                       group_in_id: int, port_in_id: int):
        port_out = self.mng.get_port_from_id(group_out_id, port_out_id)
        port_in = self.mng.get_port_from_id(group_in_id, port_in_id)

        if port_out is None or port_in is None:
            return

        self.mng.send_to_patchbay_daemon(
            '/ray/patchbay/connect',
            port_out.full_name, port_in.full_name)

    def _ports_disconnect(self, connection_id: int):
        for connection in self.mng.connections:
            if connection.connection_id == connection_id:
                self.mng.send_to_patchbay_daemon(
                    '/ray/patchbay/disconnect',
                    connection.port_out.full_name,
                    connection.port_in.full_name)
                break

    def _client_show_gui(self, group_id: int, visible: int):
        group = self.mng.get_group_from_id(group_id)
        if group is None:
            return

        for client in self.mng.session.client_list:
            if client.can_be_own_jack_client(group.name):
                show = 'show' if visible else 'hide'
                self.mng.send_to_daemon(
                    '/ray/client/%s_optional_gui' % show,
                    client.client_id)
                break


class RayPatchbayManager(PatchbayManager):
    def __init__(self, session: 'Session'):
        super().__init__(RS.settings)
        self.callbacker = RayPatchbayCallbacker(self)
        self.session = session
        self.set_tools_widget(PatchbayToolsWidget())

    @staticmethod
    def send_to_patchbay_daemon(*args):
        server = GuiServerThread.instance()
        if not server:
            return

        if server.patchbay_addr is None:
            return

        server.send(server.patchbay_addr, *args)

    @staticmethod
    def send_to_daemon(*args):
        server = GuiServerThread.instance()
        if not server:
            return
        server.to_daemon(*args)
    
    def _get_json_contents_from_path(self, file_path: str) -> dict:
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
    
    #### reimplemented functions ###
    
    def refresh(self):
        super().refresh()
        print('snened')
        self.send_to_patchbay_daemon('/ray/patchbay/refresh')
    
    def disannounce(self):
        self.send_to_patchbay_daemon('/ray/patchbay/gui_disannounce')
        super().disannounce()
    
    def save_group_position(self, gpos: GroupPos):
        super().save_group_position(gpos)
        ray_gpos = convert_group_pos_from_patchbay_to_ray(gpos)
        self.send_to_daemon(
            '/ray/server/patchbay/save_group_position', *ray_gpos.spread())

    def save_portgroup_memory(self, portgrp_mem: PortgroupMem):
        super().save_portgroup_memory(portgrp_mem)
        ray_pgmem = convert_portgrp_mem_from_patchbay_to_ray(portgrp_mem)
        self.send_to_daemon(
            '/ray/server/patchbay/save_portgroup',
            *ray_pgmem.spread())

    def change_buffersize(self, buffer_size: int):
        super().change_buffersize(buffer_size)
        self.send_to_patchbay_daemon('/ray/patchbay/set_buffer_size',
                                     buffer_size)

    def filter_groups(self, text: str, n_select=0) -> int:
        ''' semi hides groups not matching with text
            and returns number of matching boxes '''
        opac_grp_ids = set()
        opac_conn_ids = set()
        
        if text.startswith(('cl:', 'client:')):
            client_ids = text.rpartition(':')[2].split(' ')
            jack_client_names = list[str]()
            
            for client in self.session.client_list:
                if (client.status != ray.ClientStatus.STOPPED
                        and client.client_id in client_ids):
                    jack_client_names.append(client.jack_client_name)
                    if not client.jack_client_name.endswith('.' + client.client_id):
                        jack_client_names.append(client.jack_client_name + '.0')
            
            for group in self.groups:
                opac = False
                for jack_client_name in jack_client_names:
                    if (group.name == jack_client_name
                            or group.name.startswith(jack_client_name + '/')
                            or (group.name.startswith(jack_client_name + ' (')
                                    and ')' in group.name)):
                        break
                else:
                    opac = True
                    opac_grp_ids.add(group.group_id)
                
                group.semi_hide(opac)

        else:
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

    def get_corrected_a2j_group_name(self, group_name: str) -> str:
        # fix a2j wrongly substitute '.' with space
        for client in self.session.client_list:
            if (client.status != ray.ClientStatus.STOPPED
                    and '.' in client.jack_client_name
                    and (client.jack_client_name.replace('.', ' ', 1)
                            == group_name)):
                return client.jack_client_name
        
        return group_name
    
    def set_group_as_nsm_client(self, group: Group):
        for client in self.session.client_list:
            if client.can_be_own_jack_client(group.name):
                group.set_client_icon(client.icon)
                
                # in case of long jack naming (ClientName.ClientId)
                # do not display ClientName if we have the icon
                if (client.icon
                        and client.jack_client_name.endswith('.' + client.client_id)
                        and group.name.startswith(client.jack_client_name)):
                    group.display_name = group.display_name.partition('.')[2]
                
                if client.has_gui:
                    group.set_optional_gui_state(client.gui_state)
                break
    
    #### added functions ####
    
    def update_group_position(self, *args):
        # arguments are these ones delivered from ray.GroupPosition.spread()
        # Not define them allows easier code modifications.
        gpos = convert_group_pos_from_ray_to_patchbay(
            ray.GroupPosition.new_from(*args))
        
        for gposition in self.group_positions:
            if (gposition.group_name == gpos.group_name
                    and gposition.port_types_view == gpos.port_types_view):
                gposition.eat(gpos)
                break
        else:
            self.group_positions.append(gpos)
        
        if gpos.port_types_view == self.port_types_view:
            group = self.get_group_from_name(gpos.group_name)
            if group is not None:
                group.set_group_position(gpos)

    def update_portgroup(self, *args):
        ray_pgmem = ray.PortGroupMemory.new_from(*args)
        pg_mem = convert_portgrp_mem_from_ray_to_patchbay(ray_pgmem)
        self.add_portgroup_memory(pg_mem)

        group = self.get_group_from_name(pg_mem.group_name)
        if group is not None:
            group.portgroup_memory_added(pg_mem)
    
    def optional_gui_state_changed(self, client_id: str, visible: bool):
        for client in self.session.client_list:
            if client.client_id == client_id:
                for group in self.groups:
                    if client.can_be_own_jack_client(group.name):
                        group.set_optional_gui_state(visible)
                break
    
    def receive_big_packets(self, state: int):
        self.optimize_operation(not bool(state))
        if state:
            self.redraw_all_groups()
            
    def finish_init(self):
        self.set_main_win(self.session.main_win)
        self.set_canvas_menu(CanvasMenu(self))
        
        options_dialog = CanvasOptionsDialog(self.main_win, RS.settings)
        options_dialog.set_user_theme_icon(
            RayIcon('im-user', is_dark_theme(options_dialog)))
        self.set_options_dialog(options_dialog)
        
    def fast_temp_file_memory(self, temp_path):
        ''' receives a .json file path from daemon with groups positions
            and portgroups remembered from user. '''
        canvas_data = self._get_json_contents_from_path(temp_path)
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

        try:
            os.remove(temp_path)
        except:
            pass

    def fast_temp_file_running(self, temp_path: str):
        ''' receives a .json file path from patchbay daemon with all ports, connections
            and jack metadatas'''
            
        patchbay_data = self._get_json_contents_from_path(temp_path)
        if not patchbay_data:
            sys.stderr.write(
                "RaySession::Failed to load tmp file %s to get JACK ports\n"
                % temp_path)
            return

        self.clear_all()

        # optimize_operation allow to not redraw group at each port added.
        # however, if there is no group position
        # (i.e. if there is no config at all), it is prefferable to
        # know where finish the group boxes before to add another one.
        
        # very fast operation means that nothing is done in the patchcanvas
        # everything stays here in this file.
        if self.group_positions:
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

        for group in self.groups:
            group.sort_ports_in_canvas()

        self._set_very_fast_operation(False)
                
        for group in self.groups:
            group.add_all_ports_to_canvas()
        
        for conn in self.connections:
            conn.add_to_canvas()

        self.optimize_operation(False)
        self.redraw_all_groups()

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
            if TYPE_CHECKING and not isinstance(self.main_win, MainWindow):
                return
            self.main_win.add_patchbay_tools(
                self._tools_widget, self.canvas_menu)