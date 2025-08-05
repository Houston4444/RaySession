
# Imports from standard library
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Union

# Imports from HoustonPatchbay
from patshared import (
    PortgroupsDict, from_json_to_str, PortTypesViewFlag, GroupPos,
    PortgroupMem, ViewsDict, CustomNames)

# Imports from src/shared
import ray
from jack_renaming_tools import group_belongs_to_client
from osclib import MegaSend, OscPack
import osc_paths.ray as r
import osc_paths.ray.patchbay.monitor as rpm

# Local imports
from daemon_tools import RS
from server_sender import ServerSender

if TYPE_CHECKING:
    from session_signaled import SignaledSession
    from osc_server_thread import Gui


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
        self.custom_names_config = CustomNames()
        self.custom_names_session = CustomNames()

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
                self.session.message(
                    f"Failed to load patchcanvas config file {f}")

            if isinstance(json_contents, dict):
                if 'views' in json_contents.keys():
                    self.views_config.eat_json_list(json_contents['views'])

                elif 'group_positions' in json_contents.keys():
                    # config file older than 0.15.0
                    gpos_list: list[dict[str, Any]] = \
                        json_contents['group_positions']
                    gpos_version = _get_version_tuple_json_dict(json_contents)
                    
                    for gpos_dict in gpos_list:
                        self.views_config.add_old_json_gpos(
                            gpos_dict, gpos_version)

                if 'portgroups' in json_contents.keys():
                    self.portgroups.eat_json(json_contents['portgroups'])
                    
                if 'pretty_names' in json_contents.keys():
                    self.custom_names_config.eat_json(
                        json_contents['pretty_names'])
            
            self.views_config_at_load = self.views_config.copy()
        
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
        
        mixed_views = (self.views_config.short_data_states()
                       | self.views_session.short_data_states())
        mixed_views_str = json.dumps(mixed_views)

        ms_gui = MegaSend('session_group_pos')
        ms_pbay = MegaSend('session_pretty_names')

        for view_number in self.views_session.keys():
            for gpos in self.views_session.iter_group_poses(
                    view_num=view_number):
                ms_gui.add(
                    rpm.UPDATE_GROUP_POSITION,
                    view_number, *gpos.to_arg_list())

        # we send config pretty names, for the case we are switching session
        # to be sure to clear pretty-names coming from previous session
        for gp_name, ptov in self.custom_names_config.groups.items():
            ms_gui.add(rpm.UPDATE_GROUP_PRETTY_NAME,
                       gp_name, ptov.custom)
            ms_pbay.add(r.patchbay.GROUP_CUSTOM_NAME,
                        gp_name, ptov.custom, ptov.above_pretty)

        for pt_name, ptov in self.custom_names_config.ports.items():
            ms_gui.add(rpm.UPDATE_PORT_PRETTY_NAME,
                       pt_name, ptov.custom)
            ms_pbay.add(r.patchbay.PORT_CUSTOM_NAME,
                        pt_name, ptov.custom, ptov.above_pretty)

        for gp_name, ptov in self.custom_names_session.groups.items():
            ms_gui.add(rpm.UPDATE_GROUP_PRETTY_NAME,
                       gp_name, ptov.custom)
            ms_pbay.add(r.patchbay.GROUP_CUSTOM_NAME,
                        gp_name, ptov.custom, ptov.above_pretty)
        
        ms_pbay.add(r.patchbay.GROUP_CUSTOM_NAME, '', '', '')

        for port_name, ptov in self.custom_names_session.ports.items():
            ms_gui.add(rpm.UPDATE_PORT_PRETTY_NAME,
                       port_name, ptov.custom)
            ms_pbay.add(r.patchbay.PORT_CUSTOM_NAME,
                        port_name, ptov.custom, ptov.above_pretty)

        ms_pbay.add(r.patchbay.PORT_CUSTOM_NAME, '', '', '')
        ms_gui.add(rpm.VIEWS_CHANGED, mixed_views_str)

        self.mega_send_patchbay(ms_pbay)
        self.mega_send_gui(ms_gui)

    def send_all_group_positions(self, gui: 'Gui'):
        '''Used when a new GUI is connected to the daemon.'''

        ms = MegaSend('all_group_positions')

        # views (containing GroupPos)
        for view_index in self.views_config.keys():
            for gpos in self.views_config.iter_group_poses(
                    view_num=view_index):
                ms.add(rpm.UPDATE_GROUP_POSITION,
                       view_index, *gpos.to_arg_list())

        for view_index in self.views_session.keys():
            for gpos in self.views_session.iter_group_poses(
                    view_num=view_index):
                ms.add(rpm.UPDATE_GROUP_POSITION,
                       view_index, *gpos.to_arg_list())

        # portgroups
        for pg_mem in self.portgroups.iter_all_portgroups():
            ms.add(rpm.UPDATE_PORTGROUP,
                   *pg_mem.to_arg_list())

        # pretty names       
        for gp_name, pretty_group in self.custom_names_config.groups.items():
            ms.add(rpm.UPDATE_GROUP_PRETTY_NAME,
                   gp_name, pretty_group.custom)
            
        for gp_name, pretty_group in self.custom_names_session.groups.items():
            ms.add(rpm.UPDATE_GROUP_PRETTY_NAME,
                   gp_name, pretty_group.custom)

        for pt_name, pretty_port in self.custom_names_config.ports.items():
            ms.add(rpm.UPDATE_PORT_PRETTY_NAME,
                   pt_name, pretty_port.custom)

        for pt_name, pretty_port in self.custom_names_session.ports.items():
            ms.add(rpm.UPDATE_PORT_PRETTY_NAME,
                   pt_name, pretty_port.custom)

        # send view datas
        view_data_mixed = (self.views_config.short_data_states()
                           | self.views_session.short_data_states())

        ms.add(rpm.VIEWS_CHANGED,
               json.dumps(view_data_mixed))
        
        self.mega_send(gui.addr, ms)

    def save_group_position(self, *args):
        '''Save a group position sent by GUI'''
        view_num = args[0]
        gpos = GroupPos.from_arg_list(args[1:])
        pv_gpos_ss = self.views_session.get_group_pos(
            view_num, gpos.port_types_view, gpos.group_name)
        gpos_cf = self.views_config.get_group_pos(
            view_num, gpos.port_types_view, gpos.group_name)
        if gpos_cf is not None:
            gpos_cf.apply_only_diffs(pv_gpos_ss, gpos)
        else:
            self.views_config.add_group_pos(view_num, gpos)

        self.views_session.add_group_pos(view_num, gpos)

    def clear_absents_in_view(self, *args):
        try:
            json_dict: dict[str, Union[int, str, list[str]]] = \
                json.loads(args[0])
            view_num: int = json_dict['view_num']
            ptv = PortTypesViewFlag.from_config_str(json_dict['ptv'])
            presents = set(json_dict['presents'])
        except BaseException as e:
            _logger.warning(
                f'failed to clear absents in canvas view\n{str(e)}')
            return

        self.views_config.clear_absents(view_num, ptv, presents)
        self.views_session.clear_absents(view_num, ptv, presents)

    def change_view_number(self, ex_view_num: int, new_view_num: int):        
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
                self.session.message(
                    f"Failed to load session canvas file {f}")

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
                    
            if 'pretty_names' in json_contents.keys():
                self.custom_names_session.eat_json(
                    json_contents['pretty_names'])
                
                # add empty pretty name in config in case a key 
                # existing in session does not exists in config.
                # It avoids to have them still active
                # when the session is closed. The patchbay daemon
                # could remove them.
                # It happens only if session json file has been
                # written manually, or if session has been cleared.
                for gp_name in self.custom_names_session.groups.keys():
                    if self.custom_names_config.groups.get(gp_name) is None:
                        self.custom_names_config.save_group(gp_name, '')
                
                for port_name in self.custom_names_session.ports.keys():
                    if self.custom_names_config.ports.get(port_name) is None:
                        self.custom_names_config.save_port(port_name, '')

        self.views_session_at_load = self.views_session.copy()
        self.views_config_at_load = self.views_config.copy()
                    
    def save_json_session_canvas(self, session_path: Path):
        session_json_path = session_path / f'.{JSON_PATH}'

        json_contents = {}
        json_contents['views'] = self.views_session.to_json_list()
        json_contents['pretty_names'] = self.custom_names_session.to_json()
        json_contents['version'] = ray.VERSION

        with open(session_json_path, 'w+') as f:
            f.write(from_json_to_str(json_contents))

    def unload_session(self):
        self._clear_config_from_unused_views()

        # send to GUI the config poses to overwrite the session poses 
        ms_gui = MegaSend('cfg group poss and pretty names after unload')

        for view_number in self.views_config.keys():
            for gpos in self.views_config.iter_group_poses(
                    view_num=view_number):
                ms_gui.add(
                    rpm.UPDATE_GROUP_POSITION,
                    view_number, *gpos.to_arg_list())
        
        self.mega_send_gui(ms_gui)
        self.views_session.clear()
        self.custom_names_session.clear()
        
        self.send_session_group_positions()

    def save_config_file(self):
        json_contents = {
            'views': self.views_config.to_json_list(),
            'portgroups': self.portgroups.to_json(),
            'pretty_names': self.custom_names_config.to_json(),
            'version': ray.VERSION
        }

        with open(self._config_json_path, 'w+') as f:
            f.write(from_json_to_str(json_contents))

    def save_portgroup(self, *args):
        self.portgroups.save_portgroup(PortgroupMem.from_arg_list(args))

    def save_group_pretty_name(
            self, group_name: str, pretty_name: str, over_pretty: str):
        self.custom_names_config.save_group(
            group_name, pretty_name, over_pretty)
        self.custom_names_session.save_group(
            group_name, pretty_name, over_pretty)
        
    def save_port_pretty_name(
            self, port_name: str, pretty_name: str, over_pretty: str):
        self.custom_names_config.save_port(
            port_name, pretty_name, over_pretty)
        self.custom_names_session.save_port(
            port_name, pretty_name, over_pretty)

    def views_changed(self, *args):
        json_views_list = args[0]
        try:
            views_list: dict[str, dict] = json.loads(json_views_list)
        except:
            return
        
        self.views_config.update_from_short_data_states(views_list)
        self.views_session.update_from_short_data_states(views_list)

    def view_ptv_changed(self, view_num: int, ptv_int: int):
        ptv = PortTypesViewFlag(ptv_int)
        
        for views in (self.views_config, self.views_session):
            view = views.get(view_num)
            if view is None:
                views.add_view(
                    view_num=view_num, default_ptv=ptv)
            else:
                view.default_port_types_view = ptv

    def client_jack_name_changed(
            self, old_jack_name: str, new_jack_name: str):
        for view_num, view_data in self.views_session.items():
            for ptv_dict in view_data.ptvs.values():
                group_name_change_list = list[tuple[str, str]]()
                
                for group_name in ptv_dict.keys():
                    if group_belongs_to_client(group_name, old_jack_name):
                        new_group_name = group_name.replace(
                            old_jack_name, new_jack_name, 1)
                        group_name_change_list.append(
                            (group_name, new_group_name))
                        
                for old, new in group_name_change_list:
                    ptv_dict[new] = ptv_dict.pop(old)
                    ptv_dict[new].group_name = new
                    self.send_gui(
                        rpm.UPDATE_GROUP_POSITION,
                        view_num, *ptv_dict[new].to_arg_list()) 

    def send_pretty_names_to_patchbay_daemon(self, osp: OscPack):
        pretty_names = self.custom_names_config | self.custom_names_session
        ms = MegaSend('pretty_names_to_patchbaydmn')
        
        for group_name, ptov in pretty_names.groups.items():
            ms.add(r.patchbay.GROUP_CUSTOM_NAME,
                   group_name, ptov.custom, ptov.above_pretty)
        
        ms.add(r.patchbay.GROUP_CUSTOM_NAME, '', '', '')

        for port_name, ptov in pretty_names.ports.items():
            ms.add(r.patchbay.PORT_CUSTOM_NAME,
                   port_name, ptov.custom, ptov.above_pretty)
        
        ms.add(r.patchbay.PORT_CUSTOM_NAME, '', '', '')
        
        self.mega_send(osp.src_addr, ms)
        
    def has_pretty_names(self) -> bool:
        return bool(self.custom_names_config | self.custom_names_session)