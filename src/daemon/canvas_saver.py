
import json
import logging
from pathlib import Path
import tempfile
import time
from typing import TYPE_CHECKING, Any, Union

from liblo import Address

import ray
from daemon_tools import RS, Terminal
from server_sender import ServerSender
from jack_renaming_tools import group_belongs_to_client
from patchcanvas_enums import (
    from_json_to_str, PortTypesViewFlag, GroupPos, ViewData,
    portgroups_mem_from_json, portgroups_memory_to_json,
    PortType, PortMode, PortgroupMem)

if TYPE_CHECKING:
    from session_signaled import SignaledSession


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

        self.views_session = dict[
            int, dict[PortTypesViewFlag, dict[str, GroupPos]]]()
        self.views_config = dict[
            int, dict[PortTypesViewFlag, dict[str, GroupPos]]]()
        self.view_datas_session = dict[int, ViewData]()
        self.view_datas_config = dict[int, ViewData]()

        self.portgroups = dict[
            PortType, dict[str, dict[PortMode, list[PortgroupMem]]]]()
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
                    self.write_view_from_json(
                        json_contents['views'], config=True)

                elif 'group_positions' in json_contents.keys():
                    # config file older than 0.15.0
                    gpos_list: list[GroupPos] = \
                        json_contents['group_positions']
                    gpos_version = _get_version_tuple_json_dict(json_contents)
                    self.views_config[1] = \
                        dict[PortTypesViewFlag, dict[str, GroupPos]]()
                    self.view_datas_config[1] = ViewData(PortTypesViewFlag.ALL)

                    for gpos_dict in gpos_list:
                        gpos = GroupPos.from_serialized_dict(
                            gpos_dict, version=gpos_version)
                        ptv = gpos.port_types_view
                        ptv_dict = self.views_config[1].get(ptv)
                        if ptv_dict is None:
                            ptv_dict = self.views_config[1][ptv] = \
                                dict[str, GroupPos]()

                        ptv_dict[gpos.group_name] = gpos

                if 'portgroups' in json_contents.keys():
                    self.portgroups = portgroups_mem_from_json(
                        json_contents['portgroups'])

    def write_view_from_json(self, json_list: list, config=False):
        if not isinstance(json_list, list):
            return {}

        if config:
            views_dict = self.views_config
            data_dict = self.view_datas_config
        else:
            views_dict = self.views_session
            data_dict = self.view_datas_session
        
        views_dict.clear()
        data_dict.clear()
        
        for view_dict in json_list:
            if not isinstance(view_dict, dict):
                continue

            view_num = view_dict.get('index')
            if not isinstance(view_num, int):
                continue
            
            views_dict[view_num] = dict[
                PortTypesViewFlag, dict[str, GroupPos]]()
            data_dict[view_num] = ViewData(PortTypesViewFlag.ALL)

            view_name = view_dict.get('name')
            if not isinstance(view_name, str):
                view_name = ''
            default_ptv = PortTypesViewFlag.from_config_str(
                view_dict.get('default_port_types', 'ALL'))
            is_white_list = view_dict.get('is_white_list')
            if not isinstance(is_white_list, bool):
                is_white_list = False
            
            data_dict[view_num].name = view_name
            data_dict[view_num].default_port_types_view = default_ptv
            data_dict[view_num].is_white_list = is_white_list
            
            ptv_str: str

            for ptv_str, ptv_dict in view_dict.items():
                ptv = PortTypesViewFlag.from_config_str(ptv_str)
                if ptv is PortTypesViewFlag.NONE:
                    continue
                
                views_dict[view_num][ptv] = dict[str, GroupPos]()
                
                group_name: str
                ptv_dict: dict
                for group_name, gpos_dict in ptv_dict.items():
                    if not isinstance(gpos_dict, dict):
                        continue
                    
                    gpos = GroupPos.from_new_dict(ptv, group_name, gpos_dict)
                    views_dict[view_num][ptv][group_name] = gpos

    def send_session_group_positions(self):
        server = self.get_server()
        if not server:
            return

        local_guis = list['Address']()
        distant_guis = list['Address']()
        for gui_addr in server.gui_list:
            if ray.are_on_same_machine(server.url, gui_addr.url):
                local_guis.append(gui_addr)
            else:
                distant_guis.append(gui_addr)

        if local_guis:
            views_dict = {'views': self.get_json_view_list()}

            for gui_addr in local_guis:
                with (tempfile.NamedTemporaryFile(delete=False, mode='w+') as f):
                    json.dump(views_dict, f)
                    self.send(gui_addr,
                             '/ray/gui/patchbay/fast_temp_file_memory',
                             f.name)

        if distant_guis:
            for gui_addr in distant_guis:
                for view_number, view_dict in self.views_session.items():
                    for ptv, gps_dict in view_dict.items():
                        for group_name, group_pos in gps_dict.items():
                            self.send(
                                gui_addr,
                                '/ray/gui/patchbay/update_group_position',
                                view_number, *group_pos.to_arg_list())

    def get_json_view_list(self, config=False) -> list[dict]:
        if config:
            views_dict = self.views_config
            data_dict = self.view_datas_config            
        else:
            views_dict = self.views_session
            data_dict = self.view_datas_session
        
        out_list = list[dict]()
        
        for view_index, view_dict in views_dict.items():
            view = {}
            view['index'] = view_index
            view_data = data_dict.get(view_index)
            if view_data is not None:
                view['default_port_types_view'] = \
                    view_data.default_port_types_view.name
                view['is_white_list'] = view_data.is_white_list
                view['name'] = view_data.name
            
            for ptv, ptv_dict in view_dict.items():
                view[ptv.name] = {}
                for group_name, group_pos in ptv_dict.items():
                    view[ptv.name][group_name] = group_pos.as_new_dict()
            
            out_list.append(view)
        
        return out_list

    def _views_data_as_json_list(self, views_data: dict[int, ViewData]):
        out_list = list[dict[str, Union[str, int]]]()
        for index, view_data in views_data.items():
            vd_dict = {'index': index}        
            if view_data.default_port_types_view is not PortTypesViewFlag.ALL:
                vd_dict['default_ptv'] = view_data.default_port_types_view
            if view_data.name:
                vd_dict['name'] = view_data.name
            if view_data.is_white_list:
                vd_dict['is_white_list'] = True
            out_list.append(vd_dict)
        return out_list

    def send_all_group_positions(self, src_addr: Address):
        '''Used when a GUI is connected to the daemon.'''
        if ray.are_on_same_machine(self.get_server_url(), src_addr.url):
            canvas_dict = dict[str, list]()
            canvas_dict['portgroups'] = portgroups_memory_to_json(
                self.portgroups)

            config_list = self.get_json_view_list(config=True)
            session_list = self.get_json_view_list(config=False)
            
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

        # send view datas
        view_data_mixed = self.view_datas_config.copy()
        view_data_mixed |= self.view_datas_session
        self.send(src_addr,
                  '/ray/gui/patchbay/views_changed',
                  json.dumps(self._views_data_as_json_list(view_data_mixed)))

        i = 0

        for view_index, ptvs_dict in self.views_session.items():
            for ptv, gps_dict in ptvs_dict.items():
                for group_name, gpos in gps_dict.items():
                    self.send(
                        src_addr, '/ray/gui/patchbay/update_group_position',
                        view_index, *gpos.to_arg_list())
                    
                    i += 1
                    if i == 50:
                        # we need to slow big process of canvas memory
                        # to prevent loss OSC packets
                        time.sleep(0.020)
                        i = 0

        for view_index, ptvs_dict in self.views_config.items():
            ptvs_dict_sess = self.views_session.get(view_index)
            for ptv, gps_dict in ptvs_dict.items():
                gps_dict_sess = None
                if ptvs_dict_sess is not None:
                    gps_dict_sess = ptvs_dict_sess.get(ptv)
                
                for group_name, gpos in gps_dict.items():
                    if (gps_dict_sess is not None
                            and gps_dict_sess.get(group_name) is not None):
                        continue
                    
                    self.send(
                        src_addr, '/ray/gui/patchbay/update_group_position',
                        view_index, *gpos.to_arg_list())
                    
                    i += 1
                    if i == 50:
                        # we need to slow big process of canvas memory
                        # to prevent loss OSC packets
                        time.sleep(0.020)
                        i = 0

        for ptype_dict in self.portgroups.values():
            for gp_dict in ptype_dict.values():
                for pmode_list in gp_dict.values():
                    for pg_mem in pmode_list:
                        self.send(
                            src_addr, '/ray/gui/patchbay/update_portgroup',
                            *pg_mem.to_arg_list())

            i += 1
            if i == 50:
                time.sleep(0.020)

    def save_group_position(self, *args):
        '''Save a group position sent by GUI'''
        view_num, ptv_int, group_name, *rest = args
        ptv = PortTypesViewFlag(ptv_int)
        
        ptvs_dict = self.views_session.get(view_num)
        if ptvs_dict is None:
            ptvs_dict = self.views_session[view_num] = \
                dict[PortTypesViewFlag, dict[str, GroupPos]]()
        
        ptv_dict = ptvs_dict.get(ptv)
        if ptv_dict is None:
            ptv_dict = ptvs_dict[ptv] = dict[str, GroupPos]()
            
        ptv_dict[group_name] = GroupPos.from_arg_list(args[1:])
        
        ptvs_dict_cf = self.views_config.get(view_num)
        if ptvs_dict_cf is None:
            ptvs_dict_cf = self.views_config[view_num] = \
                dict[PortTypesViewFlag, dict[str, GroupPos]]()
        
        ptv_dict_cf = ptvs_dict_cf.get(ptv)
        if ptv_dict_cf is None:
            ptv_dict_cf = ptvs_dict_cf[ptv] = dict[str, GroupPos]()
            
        ptv_dict_cf[group_name] = GroupPos.from_arg_list(args[1:])

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
        
        view_cf = self.views_config.get(view_num)
        if view_cf is not None:    
            ptv_dict_cf = view_cf.get(ptv)
            if ptv_dict_cf is not None:
                ptv_dict_cf_keys = [k for k in ptv_dict_cf.keys()]
                for group_name in ptv_dict_cf_keys:
                    if group_name not in presents:
                        ptv_dict_cf.pop(group_name)
                
        view_ss = self.views_session.get(view_num)
        if view_ss is not None:
            ptv_dict_ss = view_ss.get(ptv)
            if ptv_dict_ss is not None:
                ptv_dict_ss_keys = [k for k in ptv_dict_ss.keys()]
                for group_name in ptv_dict_ss_keys:
                    if group_name not in presents:
                        ptv_dict_ss.pop(group_name)

    def load_json_session_canvas(self, session_path: Path):
        self.views_session.clear()
        self.view_datas_session.clear()

        session_canvas_file = session_path / f'.{JSON_PATH}'
        if not session_canvas_file.exists():
            return

        with open(session_canvas_file, 'r') as f:
            json_contents = {}
            gpos_list = list[dict]()

            try:
                json_contents = json.load(f)
            except json.JSONDecodeError:
                Terminal.message("Failed to load session canvas file %s" % f)

        session_version = (0, 15, 0)

        if isinstance(json_contents, dict):
            if 'views' in json_contents.keys():
                self.write_view_from_json(json_contents['views'])
            
            elif 'group_positions' in json_contents.keys():
                gpos_list : list[dict] = json_contents['group_positions']
                session_version = _get_version_tuple_json_dict(
                    json_contents)

                # affect all existing group positions to view 1
                self.views_session[1] = \
                    dict[PortTypesViewFlag, dict[str, GroupPos]]()
                self.view_datas_session[1] = ViewData(PortTypesViewFlag.ALL)

                for gpos_dict in gpos_list:
                    gpos = GroupPos.from_serialized_dict(
                        gpos_dict, version=session_version)
                    gpos_list.append(gpos)
                    
                    self.views_session[1]
                    ptv_dict = self.views_session[1].get(gpos.port_types_view)
                    if ptv_dict is None:
                        ptv_dict = self.views_session[1][gpos.port_types_view] = \
                            dict[str, GroupPos]()
                    ptv_dict[gpos.group_name] = gpos

    def save_json_session_canvas(self, session_path: Path):
        session_json_path = session_path / f'.{JSON_PATH}'

        json_contents = {}
        json_contents['views'] = self.get_json_view_list()
        json_contents['version'] = ray.VERSION

        with open(session_json_path, 'w+') as f:
            f.write(from_json_to_str(json_contents))

    def unload_session(self):
        self.view_datas_session.clear()
        self.views_session.clear()
        
        self.send_gui(
            '/ray/gui/patchbay/views_changed',
            json.dumps(self._views_data_as_json_list(self.view_datas_config)))

    def save_config_file(self):
        json_contents = {}
        json_contents['views'] = self.get_json_view_list(config=True)
        json_contents['portgroups'] = portgroups_memory_to_json(
            self.portgroups)
        json_contents['version'] = ray.VERSION

        with open(self._config_json_path, 'w+') as f:
            f.write(from_json_to_str(json_contents))

    def save_portgroup(self, *args):
        nw_pg_mem = PortgroupMem.from_arg_list(args)

        ptype_dict = self.portgroups.get(nw_pg_mem.port_type)
        if ptype_dict is None:
            ptype_dict = self.portgroups[nw_pg_mem.port_type] = \
                dict[str, dict[PortMode, list[PortgroupMem]]]()
        
        gp_dict = ptype_dict.get(nw_pg_mem.group_name)
        if gp_dict is None:
            gp_dict = ptype_dict[nw_pg_mem.group_name] = \
                dict[PortMode, list[PortgroupMem]]()
                
        pg_list = gp_dict.get(nw_pg_mem.port_mode)
        if pg_list is None:
            pg_list = gp_dict[nw_pg_mem.port_mode] = list[PortgroupMem]()        

        # remove any portgroup with a commmon port with the new one
        rm_pg = list[PortgroupMem]()

        for pg_mem in pg_list:
            for port_name in pg_mem.port_names:
                if port_name in nw_pg_mem.port_names:
                    rm_pg.append(pg_mem)
                    break
                    
        for pg_mem in rm_pg:
            pg_list.remove(pg_mem)
        
        pg_list.append(nw_pg_mem)

    def views_changed(self, *args):
        json_views_list = args[0]
        views_list: list[dict] = json.loads(json_views_list)
        
        # remove from all dicts removed views
        indexes = [v.get('index') for v in views_list
                   if v.get('index') is not None]
        
        rm_indexes = set[int]()
        all_keys = set([k for k in self.views_session.keys()]
                       + [k for k in self.views_config.keys()]) 
        for view_num in all_keys:
            if view_num not in indexes:
                rm_indexes.add(view_num)
        
        for rm_index in rm_indexes:
            for vdict in (self.views_config, self.views_session,
                          self.view_datas_config, self.view_datas_session):
                if vdict.get(rm_index) is not None:
                    vdict.pop(rm_index)
        
        # update views datas 
        for view_dict in views_list:
            index = view_dict.get('index')
            name = view_dict.get('name')
            default_ptv = view_dict.get('default_ptv')
            is_white_list = view_dict.get('is_white_list')
            vds = [vd for vd in [self.view_datas_config.get(index),
                                 self.view_datas_session.get(index)]
                   if vd is not None]
            
            for vd in vds:
                if name is not None:
                    vd.name = name
                
                if default_ptv is not None:
                    vd.default_port_types_view = \
                        PortTypesViewFlag.from_config_str(default_ptv)
                        
                if is_white_list is not None:
                    vd.is_white_list = is_white_list

    def client_jack_name_changed(
            self, old_jack_name: str, new_jack_name: str):
        server = self.session.get_server()
        
        for view_num, view_dict in self.views_session.items():
            for ptv_dict in view_dict.values():
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
