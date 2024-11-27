
# Imports from standard library
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any
import os
import sys
import logging

# Imports from HoustonPatchbay
from patchbay.patchcanvas.patshared import (
    GroupPos, PortgroupMem, PortMode, PortTypesViewFlag)
from patchbay.base_elements import ToolDisplayed
from patchbay.base_group import Group
from patchbay import (
    PatchbayManager,
    Callbacker,
    PatchbayToolsWidget,
    CanvasOptionsDialog,
    CanvasMenu,
    patchcanvas
)

# Imports from src/shared
import ray
import xdg
from jack_renaming_tools import group_belongs_to_client

# Local imports
from gui_server_thread import GuiServerThread
from gui_tools import RS, get_code_root

if TYPE_CHECKING:
    from gui_session import Session
    from main_window import MainWindow


_logger = logging.getLogger(__name__)


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
            if group_belongs_to_client(group.name, client.jack_client_name):
                show = 'show' if visible else 'hide'
                self.mng.send_to_daemon(
                    f'/ray/client/{show}_optional_gui',
                    client.client_id)
                break
            
    def _group_selected(self, group_id: int, splitted_mode: PortMode):
        # select client widget matching with the selected box
        group = self.mng.get_group_from_id(group_id)
        if group is None:
            return
        
        for client in self.mng.session.client_list:
            if group_belongs_to_client(group.name, client.jack_client_name):
                item = client.widget.list_widget_item
                item.setSelected(True)
                client.widget.list_widget.scrollToItem(item)
                break                


class RayPatchbayManager(PatchbayManager):
    main_win: 'MainWindow'
    
    def __init__(self, session: 'Session'):
        super().__init__(RS.settings)
        self.session = session
        self.set_tools_widget(PatchbayToolsWidget())
        
        self._last_selected_client_name = ''
        self._last_selected_box_n = 1

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
            with open(file_path, 'r') as file:
                new_dict = json.load(file)
                assert isinstance(new_dict, dict)
        except IOError:
            return {}
        except ImportError:
            return {}

        return new_dict
    
    def _setup_canvas(self):
        SUBMODULE = 'HoustonPatchbay'
        source_theme_path = get_code_root() / SUBMODULE / 'themes'
        manual_path = get_code_root() / SUBMODULE / 'manual'
        theme_paths = list[Path]()
        
        app_title = ray.APP_TITLE.lower()
        
        theme_paths.append(
            xdg.xdg_data_home() / app_title / SUBMODULE / 'themes')

        if source_theme_path.exists():
            theme_paths.append(source_theme_path)

        for p in xdg.xdg_data_dirs():
            path = p / app_title / SUBMODULE / 'themes'
            if path not in theme_paths:
                theme_paths.append(path)

        if TYPE_CHECKING:
            assert isinstance(self.main_win, MainWindow)

        self.app_init(self.main_win.ui.graphicsView,
                      theme_paths,
                      callbacker=RayPatchbayCallbacker(self),
                      manual_path=manual_path,
                      default_theme_name='Yellow Boards')
    
    #### reimplemented functions ###
    
    def refresh(self):
        super().refresh()
        self.send_to_patchbay_daemon('/ray/patchbay/refresh')
    
    def disannounce(self):
        self.send_to_patchbay_daemon('/ray/patchbay/gui_disannounce')
        super().disannounce()
    
    def set_views_changed(self):
        super().set_views_changed()
        self.send_to_daemon('/ray/server/patchbay/views_changed',
                            json.dumps(self.views.short_data_states()))
    
    def save_view_and_port_types_view(self):
        self.send_to_daemon(
            '/ray/server/patchbay/view_ptv_changed',
            self.view_number,
            self.port_types_view.value)
    
    def save_group_position(self, gpos: GroupPos):
        super().save_group_position(gpos)
        self.send_to_daemon(
            '/ray/server/patchbay/save_group_position',
            self.view_number, *gpos.to_arg_list())

    def save_portgroup_memory(self, pg_mem: PortgroupMem):
        super().save_portgroup_memory(pg_mem)
        self.send_to_daemon(
            '/ray/server/patchbay/save_portgroup',
            *pg_mem.to_arg_list())

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
                if (client.status is not ray.ClientStatus.STOPPED
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

        else:
            for group in self.groups:
                opac = bool(text.lower() not in group.name.lower()
                            and text.lower() not in group.display_name.lower())
                if opac:
                    opac_grp_ids.add(group.group_id)
        
        patchcanvas.semi_hide_groups(opac_grp_ids)
        
        n_boxes = 0
        
        for group in self.groups:
            if group.group_id not in opac_grp_ids:
                n_grp_boxes = group.get_number_of_boxes()

                if n_select > n_boxes and n_select <= n_boxes + n_grp_boxes:
                    group.select_filtered_box(n_select - n_boxes)
                n_boxes += n_grp_boxes

        return n_boxes

    def clear_absents_in_view(self, only_current_ptv=False):
        if only_current_ptv:
            presents = set[str]()

            for group in self.groups:
                if group.is_in_port_types_view(self.port_types_view):
                    presents.add(group.current_position.group_name)

            self.views.clear_absents(
                self.view_number, self.port_types_view, presents)

            out_dict = {'view_num': self.view_number,
                        'ptv': self.port_types_view.name,
                        'presents': [g for g in presents]}

            self.send_to_daemon(
                '/ray/server/patchbay/clear_absents_in_view',
                json.dumps(out_dict))
            return
        
        for ptv in self.views[self.view_number].ptvs.keys():
            presents = set[str]()

            for group in self.groups:
                if group.is_in_port_types_view(ptv):
                    presents.add(group.current_position.group_name)

            self.views.clear_absents(self.view_number, ptv, presents)

            out_dict = {'view_num': self.view_number,
                        'ptv': ptv.name,
                        'presents': [g for g in presents]}

            self.send_to_daemon(
                '/ray/server/patchbay/clear_absents_in_view',
                json.dumps(out_dict))

    def change_view_number(self, new_num: int):
        ex_view_num = self.view_number
        super().change_view_number(new_num)
        self.send_to_daemon(
            '/ray/server/patchbay/view_number_changed', ex_view_num, new_num)

    def get_corrected_a2j_group_name(self, group_name: str) -> str:
        # fix a2j wrongly substitute '.' with space
        for client in self.session.client_list:
            if (client.status is not ray.ClientStatus.STOPPED
                    and '.' in client.jack_client_name
                    and (client.jack_client_name.replace('.', ' ', 1)
                            == group_name)):
                return client.jack_client_name
        
        return group_name

    def set_group_as_nsm_client(self, group: Group):
        for client in self.session.client_list:
            if group_belongs_to_client(group.name, client.jack_client_name):
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

    def transport_play_pause(self, play: bool):
        self.send_to_patchbay_daemon('/ray/patchbay/transport_play', int(play))
    
    def transport_stop(self):
        self.send_to_patchbay_daemon('/ray/patchbay/transport_stop')
    
    def transport_relocate(self, frame: int):
        self.send_to_patchbay_daemon('/ray/patchbay/transport_relocate', frame)

    def change_tools_displayed(self, tools_displayed: ToolDisplayed):
        ex_tool_displayed = self._tools_displayed
        super().change_tools_displayed(tools_displayed)
        ex_transport_disp = ex_tool_displayed & (ToolDisplayed.TRANSPORT_CLOCK
                                                 | ToolDisplayed.TRANSPORT_PLAY_STOP)
        transport_disp = tools_displayed & (ToolDisplayed.TRANSPORT_CLOCK
                                           | ToolDisplayed.TRANSPORT_PLAY_STOP)

        if transport_disp != ex_transport_disp:
            if transport_disp & ToolDisplayed.TRANSPORT_CLOCK:
                int_transp = 2
            elif transport_disp & ToolDisplayed.TRANSPORT_PLAY_STOP:
                int_transp = 1
            else:
                int_transp = 0

            self.send_to_patchbay_daemon('/ray/patchbay/activate_transport',
                                          int_transp)
             
        if (ex_tool_displayed & ToolDisplayed.DSP_LOAD
                != tools_displayed & ToolDisplayed.DSP_LOAD):
            self.send_to_patchbay_daemon(
                '/ray/patchbay/activate_dsp_load',
                int(bool(tools_displayed & ToolDisplayed.DSP_LOAD)))

        #### added functions ####
    
    def select_client_box(self, jack_client_name: str, previous=False):
        if not jack_client_name:
            self._last_selected_client_name = ''
            self._last_selected_box_n = 0
            patchcanvas.canvas.scene.clearSelection()
            return
        
        box_n = 0
        if jack_client_name == self._last_selected_client_name:            
            n_max = 0
            for group in self.groups:
                if group_belongs_to_client(group.name, jack_client_name):
                    n_max += group.get_number_of_boxes()
            
            if previous:
                if self._last_selected_box_n == 0:
                    self._last_selected_box_n = n_max -1
                else:
                    self._last_selected_box_n -= 1
            else:
                self._last_selected_box_n += 1

            if n_max:
                box_n = self._last_selected_box_n % n_max
            
        n = 0
        box_found = False
        for group in self.groups:
            if group_belongs_to_client(group.name, jack_client_name):
                if group.get_number_of_boxes() + n <= box_n:
                    n += group.get_number_of_boxes()
                    continue
                
                group.select_filtered_box(1 + box_n -n)
                box_found = True
                break
        
        if box_found:
            self._last_selected_client_name = jack_client_name
            self._last_selected_box_n = box_n
        else:
            patchcanvas.canvas.scene.clearSelection()
            self._last_selected_client_name = ''
            self._last_selected_box_n = 0

    def update_group_position(self, *args):
        view_number = args[0]        
        gpos = GroupPos.from_arg_list(*args[1:])
        view_dict = self.views.get(view_number)
        if view_dict is None:
            view_dict = self.views[view_number] = \
                dict[PortTypesViewFlag, dict[str, GroupPos]]()
        
        ptv_dict = view_dict.get(gpos.port_types_view)
        if ptv_dict is None:
            ptv_dict = view_dict[gpos.port_types_view] = \
                dict[str, GroupPos]()
                
        ptv_dict[gpos.group_name] = gpos

        if (view_number is self.view_number
                and gpos.port_types_view is self.port_types_view):
            group = self.get_group_from_name(gpos.group_name)
            if group is not None:
                group.set_group_position(gpos)

    def update_portgroup(self, *args):
        pg_mem = PortgroupMem.from_arg_list(args)
        self.add_portgroup_memory(pg_mem)

        group = self.get_group_from_name(pg_mem.group_name)
        if group is not None:
            group.portgroup_memory_added(pg_mem)
    
    def views_changed(self, *args):
        views_data_json = args[0]
        self.views.update_from_short_data_states(json.loads(views_data_json))

        if not self.views:
            self.views.add_view(1)

        if self.view_number not in self.views.keys():
            self.view_number = self.views.first_view_num()

        self.sg.views_changed.emit()
        
        # in the case the port types view or is_white_list is not the same
        self.change_view(self.view_number)
    
    def optional_gui_state_changed(self, client_id: str, visible: bool):
        for client in self.session.client_list:
            if client.client_id == client_id:
                for group in self.groups:
                    if group_belongs_to_client(group.name, client.jack_client_name):
                        group.set_optional_gui_state(visible)
                break
    
    def receive_big_packets(self, state: int):
        self.optimize_operation(not bool(state))
        if state:
            self.redraw_all_groups()
            
    def finish_init(self):
        self.set_main_win(self.session.main_win)
        self._setup_canvas()
        self.set_canvas_menu(CanvasMenu(self))
        if self.main_win._patchbay_tools is not None:
            self.set_tools_widget(self.main_win._patchbay_tools)
        self.set_options_dialog(
            CanvasOptionsDialog(self.main_win, self, RS.settings))

    def fast_temp_file_memory(self, temp_path: str):
        '''receive a .json file path from daemon with groups positions
        and portgroups remembered from user.'''

        canvas_data = self._get_json_contents_from_path(temp_path)
        if not canvas_data:
            _logger.error(
                f"Failed to load tmp file {temp_path} to get canvas positions")
            return


        pg_memory = canvas_data.get('portgroups')
        starting = pg_memory is not None

        if pg_memory is not None:
            self.portgroups_memory.eat_json(pg_memory)

        self.views.eat_json_list(canvas_data.get('views'), clear=starting)

        try:
            os.remove(temp_path)
        except:
            pass
        
        # do not use self.set_views_changed(), we don't need to send
        # views to daemon, just update widgets
        self.sg.views_changed.emit()
    
        if starting or self.view_number not in self.views.keys():
            self.view_number = self.views.first_view_num()
        self.change_view(self.view_number)

    def fast_temp_file_running(self, temp_path: str):
        '''receives a .json file path from patchbay daemon with all ports,
        connections and jack metadatas'''
            
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
        has_group_positions = False
        for gpos in self.views.iter_group_poses():
            has_group_positions = True
            break
        
        if has_group_positions:
            self.optimize_operation(True)
            self._set_very_fast_operation(True)

        for key in patchbay_data.keys():
            if key == 'ports':
                p: dict[str, Any]
                for p in patchbay_data[key]:
                    self.add_port(p.get('name'), p.get('type'),
                                  p.get('flags'), p.get('uuid'))

            elif key == 'connections':
                c: dict[str, Any]
                for c in patchbay_data[key]:
                    self.add_connection(c.get('port_out_name'),
                                        c.get('port_in_name'))

        for key in patchbay_data.keys():
            if key == 'clients':
                cnu: dict[str, Any]
                for cnu in patchbay_data[key]:
                    self.set_group_uuid_from_name(cnu.get('name'), cnu.get('uuid'))
                break

        for key in patchbay_data.keys():
            if key == 'metadatas':
                m: dict[str, Any]
                for m in patchbay_data[key]:
                    self.metadata_update(
                        m.get('uuid'), m.get('key'), m.get('value'))
                break

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
        
        if self.main_win is not None:
            self.main_win.add_patchbay_tools(
                self._tools_widget, self.canvas_menu)

        self._tools_widget.set_samplerate(samplerate)
        self._tools_widget.set_buffer_size(buffer_size)
        self._tools_widget.set_jack_running(jack_running)
        self._tools_widget.set_patchbay_manager(self)