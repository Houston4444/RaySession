
from typing import TYPE_CHECKING


import ray
from patchbay.patchbay_manager import PatchbayManager
from patchbay.patchbay_elements import Group
from patchbay.canvas_options import CanvasOptionsDialog
from patchbay.patchbay_tools import PatchbayToolsWidget, CanvasMenu
from patchbay.patchbay_calbacker import Callbacker

from gui_server_thread import GuiServerThread
from gui_tools import RS, is_dark_theme, RayIcon

if TYPE_CHECKING:
    from gui_session import Session


class PatchbayMainCallbacker(Callbacker):
    def __init__(self, manager: 'PatchbayMainManager'):
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
        group = self.mng._groups_by_id.get(group_id)
        if group is None:
            return

        for client in self.mng.session.client_list:
            if client.can_be_own_jack_client(group.name):
                show = 'show' if visible else 'hide'
                self.mng.send_to_daemon(
                    '/ray/client/%s_optional_gui' % show,
                    client.client_id)
                break


class PatchbayMainManager(PatchbayManager):
    def __init__(self, session: 'Session'):
        super().__init__(RS.settings)
        self.callbacker = PatchbayMainCallbacker(self)
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
    
    #### reimplemented functions ###
    
    def refresh(self):
        super().refresh()
        self.send_to_patchbay_daemon('/ray/patchbay/refresh')
    
    def disannounce(self):
        self.send_to_patchbay_daemon('/ray/patchbay/gui_disannounce')
        super().disannounce()
    
    def save_group_position(self, gpos: ray.GroupPosition):
        super().save_group_position(gpos)
        self.send_to_daemon(
            '/ray/server/patchbay/save_group_position', *gpos.spread())
    
    def save_portgroup_memory(self, portgrp_mem: ray.PortGroupMemory):
        super().save_portgroup_memory(portgrp_mem)
        self.send_to_daemon(
            '/ray/server/patchbay/save_portgroup',
            *portgrp_mem.spread())
    
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
                return group_name.replace(' ', '.' , 1)
        
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