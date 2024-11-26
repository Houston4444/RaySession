
import json
import logging
from pathlib import Path
import tempfile
import time
from typing import TYPE_CHECKING, Union

import ray
from osclib import Address, are_on_same_machine
from jack_renaming_tools import group_belongs_to_client
from daemon_tools import RS, Terminal
from server_sender import ServerSender
from patshared import (
    PortgroupsDict, from_json_to_str, PortTypesViewFlag, GroupPos,
    PortgroupMem, ViewsDict)

if TYPE_CHECKING:
    from .session_signaled import SignaledSession


_logger = logging.getLogger(__name__)


JSON_PATH = 'ray_canvas.json'

def _get_version_tuple_json_dict(json_contents: dict) -> tuple[int, int, int]:
    if 'version' in json_contents.keys():
        version_str: str = json_contents['version']
        try:
            version_list = [int(v) for v in version_str.split('.')]
        except:
            version_list = [int(v) for v in ray.VERSION.split('.')]
    else:
        version_list = [0, 12, 0]
    
    return tuple(version_list)


class CanvasSaver(ServerSender):
    def __init__(self, session: 'SignaledSession'):
        ServerSender.__init__(self)
        self.session = session

        self.views_session = ViewsDict(ensure_one_view=False)
        self.views_config = ViewsDict(ensure_one_view=False)
        self.views_session_at_load = ViewsDict(ensure_one_view=False)
        self.views_config_at_load = ViewsDict(ensure_one_view=False)

        self.portgroups = PortgroupsDict()
        self._config_json_path = \
            Path(RS.settings.fileName()).parent / JSON_PATH

        if not self._config_json_path.exists():
            return

        with open(self._config_json_path, 'r') as f:
            json_contents = {}

            try:
                json_contents = json.load(f)
            except json.JSONDecodeError:
                Terminal.message(
                    f"Failed to load patchcanvas config file {f}")

            if isinstance(json_contents, dict):
                if 'views' in json_contents.keys():
                    self.views_config.eat_json_list(json_contents['views'])

                elif 'group_positions' in json_contents.keys():
                    # config file older than 0.15.0
                    gpos_list: list[GroupPos] = \
                        json_contents['group_positions']
                    gpos_version = _get_version_tuple_json_dict(json_contents)
                    
                    for gpos_dict in gpos_list:
                        self.views_config.add_old_json_gpos(
                            gpos_dict, gpos_version)

                if 'portgroups' in json_contents.keys():
                    self.portgroups.eat_json(json_contents['portgroups'])
            
            self.views_config_at_load = self.views_config.copy()
        
        self.current_view_num = 1
        self.current_ptv = PortTypesViewFlag.ALL

    def _clear_config_from_unused_views(self):
        no_change_indexes = set[int]()
        
        for ls_index, ls_view_data in self.views_session_at_load.items():
            s_view_data = self.views_session.get(ls_index)
            if s_view_data is None:
                continue
            
            if ls_view_data == s_view_data:
                no_change_indexes.add(ls_index)
        
        rm_indexes = set[int]()
        replace_indexes = set[int]()
            
        for c_index, c_view_data in self.views_config.items():
            if c_index not in no_change_indexes:
                continue
            
            lc_view_data = self.views_config_at_load.get(c_index)
            if lc_view_data is None:
                rm_indexes.add(c_index)
                continue
            
            if lc_view_data != c_view_data:
                replace_indexes.add(c_index)
                
        for rm_index in rm_indexes:
            self.views_config.pop(rm_index)
            
        for replace_index in replace_indexes:
            self.views_config[replace_index] = \
                self.views_config_at_load[replace_index]

    def send_session_group_positions(self):
        if self.is_dummy:
            return
        
        server = self.get_server()
        if not server:
            return

        local_guis = list['Address']()
        distant_guis = list['Address']()
        
        mixed_views = (self.views_config.short_data_states()
                       | self.views_session.short_data_states())
        mixed_views_str = json.dumps(mixed_views)
        
        for gui_addr in server.gui_list:
            if are_on_same_machine(server.url, gui_addr.url):
                local_guis.append(gui_addr)
            else:
                distant_guis.append(gui_addr)

        if local_guis:
            views_dict = {'views': self.views_session.to_json_list()}

            for gui_addr in local_guis:
                with (tempfile.NamedTemporaryFile(delete=False, mode='w+') as f):
                    json.dump(views_dict, f)
                    self.send(gui_addr,
                              '/ray/gui/patchbay/fast_temp_file_memory',
                              f.name)
                
                self.send(gui_addr,
                          '/ray/gui/patchbay/views_changed',
                          mixed_views_str)

        if distant_guis:
            for gui_addr in distant_guis:
                i = 0
                
                for view_number in self.views_session.keys():
                    for gpos in self.views_session.iter_group_poses(
                            view_num=view_number):
                        self.send(
                            gui_addr,
                            '/ray/gui/patchbay/update_group_position',
                            view_number, *gpos.to_arg_list())
                        i += 1
                        
                        if i == 50:
                            time.sleep(0.020)
                            i = 0
            
                self.send(gui_addr,
                          '/ray/gui/patchbay/views_changed',
                          mixed_views_str)

    def send_all_group_positions(self, src_addr: Address):
        '''Used when a GUI is connected to the daemon.'''
        if are_on_same_machine(self.get_server_url(), src_addr.url):
            canvas_dict = dict[str, list]()
            canvas_dict['portgroups'] = self.portgroups.to_json()

            config_list = self.views_config.to_json_list()
            session_list = self.views_session.to_json_list()
            
            mixed_dict = dict[int, dict]()
            
            for cf_view_dict in config_list:
                cf_index = cf_view_dict.get('index')
                if cf_index is None:
                    continue
                
                mixed_dict[cf_index] = cf_view_dict
                
            for ss_view_dict in session_list:
                ss_index = ss_view_dict.get('index')
                if ss_index is None:
                    continue
                
                mixed_view_dict = mixed_dict.get(ss_index)
                
                if mixed_view_dict is None:
                    mixed_dict[ss_index] = ss_view_dict
                    continue
                
                mixed_view_dict |= ss_view_dict
            
            canvas_dict['views'] = [d for d in mixed_dict.values()]
            
            with tempfile.NamedTemporaryFile(delete=False, mode='w+') as f:
                json.dump(canvas_dict, f)
                self.send(src_addr,
                          '/ray/gui/patchbay/fast_temp_file_memory',
                          f.name)
            return

        i = 0

        for view_index in self.views_config.keys():
            for gpos in self.views_config.iter_group_poses(
                    view_num=view_index):
                self.send(
                    src_addr, '/ray/gui/patchbay/update_group_position',
                    view_index, *gpos.to_arg_list())
                
                i += 1
                if i == 50:
                    # we need to slow big process of canvas memory
                    # to prevent loss OSC packets
                    time.sleep(0.020)
                    i = 0

        for view_index in self.views_session.keys():
            for gpos in self.views_session.iter_group_poses(
                    view_num=view_index):
                self.send(
                    src_addr, '/ray/gui/patchbay/update_group_position',
                    view_index, *gpos.to_arg_list())
                
                i += 1
                if i == 50:
                    # we need to slow big process of canvas memory
                    # to prevent loss OSC packets
                    time.sleep(0.020)
                    i = 0

        for pg_mem in self.portgroups.iter_all_portgroups():
            self.send(src_addr, '/ray/gui/patchbay/update_portgroup',
                      *pg_mem.to_arg_list())

            i += 1
            if i == 50:
                time.sleep(0.020)
                i = 0
                
        # send view datas
        view_data_mixed = (self.views_config.short_data_states()
                           |self.views_session.short_data_states())

        self.send(src_addr,
                  '/ray/gui/patchbay/views_changed',
                  json.dumps(view_data_mixed))

    def save_group_position(self, *args):
        '''Save a group position sent by GUI'''
        view_num = args[0]

        self.views_session.add_group_pos(
            view_num, GroupPos.from_arg_list(args[1:]))
        self.views_config.add_group_pos(
            view_num, GroupPos.from_arg_list(args[1:]))

    def clear_absents_in_view(self, *args):
        try:
            json_dict: dict[str, Union[int, str, list[str]]] = \
                json.loads(args[0])
            view_num = json_dict['view_num']
            ptv = PortTypesViewFlag.from_config_str(json_dict['ptv'])
            presents = set(json_dict['presents'])
        except BaseException as e:
            _logger.warning(
                f'failed to clear absents in canvas view\n{str(e)}')
            return

        self.views_config.clear_absents(view_num, ptv, presents)
        self.views_session.clear_absents(view_num, ptv, presents)

    def change_view_number(self, *args):
        ex_view_num, new_view_num = args
        
        for vdict in (self.views_config, self.views_session):
            if vdict.get(ex_view_num) is None:
                _logger.warning(
                    f'Changing view number for a non '
                    f'existing view n°{ex_view_num}')
                continue
            
            if vdict.get(new_view_num) is not None:
                vdict[ex_view_num], vdict[new_view_num] = \
                    vdict[new_view_num], vdict[ex_view_num]
            
            else:
                vdict[new_view_num] = vdict.pop(ex_view_num)

    def load_json_session_canvas(self, session_path: Path):
        session_canvas_file = session_path / f'.{JSON_PATH}'
        if not session_canvas_file.exists():
            return

        with open(session_canvas_file, 'r') as f:
            json_contents = {}

            try:
                json_contents = json.load(f)
            except json.JSONDecodeError:
                Terminal.message("Failed to load session canvas file %s" % f)

        session_version = (0, 15, 0)
        self.views_session.clear()

        if isinstance(json_contents, dict):
            if 'views' in json_contents.keys():
                self.views_session.eat_json_list(json_contents['views'])
            
            elif 'group_positions' in json_contents.keys():
                gpos_list : list[dict] = json_contents['group_positions']
                session_version = _get_version_tuple_json_dict(
                    json_contents)

                for gpos_dict in gpos_list:
                    self.views_session.add_old_json_gpos(
                        gpos_dict, session_version)
        
        self.views_session_at_load = self.views_session.copy()
        self.views_config_at_load = self.views_config.copy()
                    
    def save_json_session_canvas(self, session_path: Path):
        session_json_path = session_path / f'.{JSON_PATH}'

        json_contents = {}
        json_contents['views'] = self.views_session.to_json_list()
        json_contents['version'] = ray.VERSION

        with open(session_json_path, 'w+') as f:
            f.write(from_json_to_str(json_contents))

    def unload_session(self):
        self._clear_config_from_unused_views()
        self.views_session.clear()        
        self.send_session_group_positions()

    def save_config_file(self):
        json_contents = {
            'views': self.views_config.to_json_list(),
            'portgroups': self.portgroups.to_json(),
            'version': ray.VERSION
        }

        with open(self._config_json_path, 'w+') as f:
            f.write(from_json_to_str(json_contents))

    def save_portgroup(self, *args):
        self.portgroups.save_portgroup(PortgroupMem.from_arg_list(args))

    def views_changed(self, *args):
        json_views_list = args[0]
        try:
            views_list: dict[str, dict] = json.loads(json_views_list)
        except:
            return
        
        self.views_config.update_from_short_data_states(views_list)
        self.views_session.update_from_short_data_states(views_list)

    def view_ptv_changed(self, view_num: int, ptv_int: int):
        self.current_view_num = view_num
        self.current_ptv = PortTypesViewFlag(ptv_int)
        
        for views in (self.views_config, self.views_session):
            view = views.get(view_num)
            if view is None:
                views.add_view(
                    view_num=view_num, default_ptv=self.current_ptv)
            else:
                view.default_port_types_view = self.current_ptv

    def client_jack_name_changed(
            self, old_jack_name: str, new_jack_name: str):
        server = self.session.get_server()
        
        for view_num, view_data in self.views_session.items():
            for ptv_dict in view_data.ptvs.values():
                group_name_change_list = list[tuple(str, str)]()
                
                for group_name in ptv_dict.keys():
                    if group_belongs_to_client(group_name, old_jack_name):
                        new_group_name = group_name.replace(
                            old_jack_name, new_jack_name, 1)
                        group_name_change_list.append(
                            (group_name, new_group_name))
                        
                for old, new in group_name_change_list:
                    ptv_dict[new] = ptv_dict.pop(old)
                    ptv_dict[new].group_name = new
                    server.send_gui(
                        '/ray/gui/patchbay/update_group_position',
                        view_num, *ptv_dict[new].to_arg_list())                    
