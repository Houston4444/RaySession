
# Imports from standard library
import json
from pathlib import Path
from typing import TYPE_CHECKING
import os
import logging

# Imports from HoustonPatchbay
from patshared import (
    GroupPos, PortgroupMem, PortMode, ViewData, Naming)
from patchbay.bases.elements import ToolDisplayed
from patchbay.bases.group import Group
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
import osc_paths.ray as r

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
    
    def _group_rename(
            self, group_id: int, pretty_name: str, save_in_jack: bool):
        group = self.mng.get_group_from_id(group_id)
        if group is None:
            return

        if not group.uuid:
            save_in_jack = False

        self.mng.send_to_daemon(
            r.server.patchbay.SAVE_GROUP_PRETTY_NAME,
            group.name, pretty_name, group.mdata_pretty_name,
            int(save_in_jack))
        
    def _port_rename(self, group_id: int, port_id: int,
                     pretty_name: str, save_in_jack: bool):
        port = self.mng.get_port_from_id(group_id, port_id)
        if port is None:
            return
        
        if not port.type.is_jack:
            save_in_jack = False
        
        self.mng.send_to_daemon(
            r.server.patchbay.SAVE_PORT_PRETTY_NAME,
            port.full_name_id_free, pretty_name,
            port.mdata_pretty_name, int(save_in_jack))

    def _ports_connect(self, group_out_id: int, port_out_id: int,
                       group_in_id: int, port_in_id: int):
        port_out = self.mng.get_port_from_id(group_out_id, port_out_id)
        port_in = self.mng.get_port_from_id(group_in_id, port_in_id)

        if port_out is None or port_in is None:
            return

        self.mng.send_to_patchbay_daemon(
            r.patchbay.CONNECT,
            port_out.full_name, port_in.full_name)

    def _ports_disconnect(self, connection_id: int):
        for connection in self.mng.connections:
            if connection.connection_id == connection_id:
                self.mng.send_to_patchbay_daemon(
                    r.patchbay.DISCONNECT,
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

        server.send_patchbay_daemon(*args)

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
        self.send_to_patchbay_daemon(r.patchbay.REFRESH)
    
    def disannounce(self):
        self.send_to_patchbay_daemon(
            r.patchbay.GUI_DISANNOUNCE, '')
        super().disannounce()
    
    def set_views_changed(self):
        super().set_views_changed()
        self.send_to_daemon(r.server.patchbay.VIEWS_CHANGED,
                            json.dumps(self.views.short_data_states()))
    
    def save_view_and_port_types_view(self):
        self.send_to_daemon(
            r.server.patchbay.VIEW_PTV_CHANGED,
            self.view_number,
            self.port_types_view.value)
    
    def save_group_position(self, gpos: GroupPos):
        super().save_group_position(gpos)
        self.send_to_daemon(
            r.server.patchbay.SAVE_GROUP_POSITION,
            self.view_number, *gpos.to_arg_list())

    def save_portgroup_memory(self, pg_mem: PortgroupMem):
        super().save_portgroup_memory(pg_mem)
        self.send_to_daemon(
            r.server.patchbay.SAVE_PORTGROUP,
            *pg_mem.to_arg_list())

    def change_buffersize(self, buffer_size: int):
        super().change_buffersize(buffer_size)
        self.send_to_patchbay_daemon(
            r.patchbay.SET_BUFFER_SIZE, buffer_size)

    def filter_groups(self, text: str, n_select=0) -> int:
        '''semi hides groups not matching with text
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
                opac = bool(
                    text.lower() not in group.name.lower()
                    and text.lower() not in group.graceful_name.lower())
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
                r.server.patchbay.CLEAR_ABSENTS_IN_VIEW,
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
                r.server.patchbay.CLEAR_ABSENTS_IN_VIEW,
                json.dumps(out_dict))

    def change_view_number(self, new_num: int):
        ex_view_num = self.view_number
        super().change_view_number(new_num)
        self.send_to_daemon(
            r.server.patchbay.VIEW_NUMBER_CHANGED, ex_view_num, new_num)

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
                    group.graceful_name = group.graceful_name.partition('.')[2]
                
                if client.has_gui:
                    group.set_optional_gui_state(client.gui_state)
                break

    def transport_play_pause(self, play: bool):
        self.send_to_patchbay_daemon(r.patchbay.TRANSPORT_PLAY, int(play))
    
    def transport_stop(self):
        self.send_to_patchbay_daemon(r.patchbay.TRANSPORT_STOP)
    
    def transport_relocate(self, frame: int):
        self.send_to_patchbay_daemon(r.patchbay.TRANSPORT_RELOCATE, frame)

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

            self.send_to_patchbay_daemon(r.patchbay.ACTIVATE_TRANSPORT,
                                          int_transp)
             
        if (ex_tool_displayed & ToolDisplayed.DSP_LOAD
                != tools_displayed & ToolDisplayed.DSP_LOAD):
            self.send_to_patchbay_daemon(
                r.patchbay.ACTIVATE_DSP_LOAD,
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
        gpos = GroupPos.from_arg_list(args[1:])
        view_data = self.views.get(view_number)
        
        if view_data is None:
            view_data = self.views[view_number] = ViewData(
                gpos.port_types_view)
        
        ptv_dict = view_data.ptvs.get(gpos.port_types_view)
        if ptv_dict is None:
            ptv_dict = view_data.ptvs[gpos.port_types_view] = \
                dict[str, GroupPos]()
                
        ptv_dict[gpos.group_name] = gpos

        # In the past, move a box in a GUI was moving this box in others GUIs.
        # It takes finally no sense, because the theme can make very different
        # boxes sizes. We should probably choose that position saver
        # is the first GUI launched.
        # Out of this case, if this code is executed, we can assume the view
        # will be changed very soon and it will update the canvas.

        # if (view_number is self.view_number
        #         and gpos.port_types_view is self.port_types_view):
        #     group = self.get_group_from_name(gpos.group_name)
        #     if group is not None:
        #         group.set_group_position(
        #             gpos, redraw=PortMode.NULL, restore=PortMode.BOTH, move_now=False)

    def update_portgroup(self, *args):
        pg_mem = PortgroupMem.from_arg_list(args)
        self.add_portgroup_memory(pg_mem)

        group = self.get_group_from_name(pg_mem.group_name)
        if group is not None:
            group.portgroup_memory_added(pg_mem)
    
    def views_changed(self, json_dict: str):
        views_data_json = json_dict
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
    
    def update_group_pretty_name(self, group_name: str, pretty_name: str):
        self.pretty_names.save_group(group_name, pretty_name, '')
        group = self.get_group_from_name(group_name)
        if group is not None:
            group.rename_in_canvas()
    
    def update_port_pretty_name(self, port_name: str, pretty_name: str):
        self.pretty_names.save_port(port_name, pretty_name, '')
        port = self.get_port_from_name(port_name)
        if port is not None:
            port.rename_in_canvas()
    
    def change_jack_export_naming(self, naming: Naming):
        super().change_jack_export_naming(naming)
        
        pretty_enable = Naming.INTERNAL_PRETTY in naming
        self.send_to_daemon(r.server.EXPORT_PRETTY_NAMES, str(pretty_enable))
    
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
            CanvasOptionsDialog(self.main_win, self))

    def patchbay_announce(self, jack_running: int, samplerate: int,
                          buffer_size: int, tcp_url: str):
        if self._tools_widget is None:
            return
        
        if self.main_win is not None:
            self.main_win.add_patchbay_tools(
                self._tools_widget, self.canvas_menu)

        self._tools_widget.set_samplerate(samplerate)
        self._tools_widget.set_buffer_size(buffer_size)
        self._tools_widget.set_jack_running(jack_running)
        self._tools_widget.set_patchbay_manager(self)