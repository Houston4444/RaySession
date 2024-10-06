
import json
from pathlib import Path
import tempfile
import time
from typing import TYPE_CHECKING, Optional

from liblo import Address

import ray
from daemon_tools import RS, Terminal
from server_sender import ServerSender
from jack_renaming_tools import group_belongs_to_client
from patchcanvas_enums import (
    from_json_to_str, PortTypesViewFlag, GroupPos, ViewData)

if TYPE_CHECKING:
    from session_signaled import SignaledSession


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

        self.group_positions_session = list[ray.GroupPosition]()
        self.group_positions_config = list[ray.GroupPosition]()
        self.portgroups = list[ray.PortGroupMemory]()
        self._config_json_path = \
            Path(RS.settings.fileName()).parent / JSON_PATH

        if not self._config_json_path.exists():
            return

        with open(self._config_json_path, 'r') as f:
            json_contents = {}
            gpos_list = list[ray.GroupPosition]()
            pg_list = list[ray.PortGroupMemory]()

            try:
                json_contents = json.load(f)
            except json.JSONDecodeError:
                Terminal.message(
                    f"Failed to load patchcanvas config file {f}")

            # Old group_position port_types_view norm was
            # full_view = AUDIO | MIDI (1|2 = 3)
            # now this is:
            # full_view = AUDIO | MIDI | CV | VIDEO (1|2|4|8 = 15)
            # (even if VIDEO is not implemented in the pachbay daemon yet)
            
            # so we need to consider that a full view is a full view
            # and convert in old sessions port_types_view = 3 -> 15 
            needs_port_types_view_convert = False

            if isinstance(json_contents, dict):
                if 'views' in json_contents.keys():
                    self.write_view_from_json(
                        json_contents['views'], config=True)

                elif 'group_positions' in json_contents.keys():
                    gpos_list = json_contents['group_positions']

                if 'portgroups' in json_contents.keys():
                    pg_list = json_contents['portgroups']
                    
                if _get_version_tuple_json_dict(json_contents) < (0, 13, 0):
                    needs_port_types_view_convert = True

            for gpos_dict in gpos_list:
                gpos = ray.GroupPosition()
                gpos.write_from_dict(gpos_dict)
                if needs_port_types_view_convert and gpos.port_types_view == 3:
                    gpos.port_types_view = 15
                
                if not [g for g in self.group_positions_config if g.is_same(gpos)]:
                    self.group_positions_config.append(gpos)

            for pg_dict in pg_list:
                portgroup = ray.PortGroupMemory()
                portgroup.write_from_dict(pg_dict)
                self.portgroups.append(portgroup)

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
            data_dict[view_num] = ViewData('', PortTypesViewFlag.NONE, False)

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
            views_dict = self.get_json_view_list()

            for gui_addr in local_guis:
                with (tempfile.NamedTemporaryFile(delete=False, mode='w+')
                        as f):
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

    # def send_session_group_positions(self):
    #     server = self.get_server()
    #     if not server:
    #         return

    #     local_guis = list['Address']()
    #     distant_guis = list['Address']()
    #     for gui_addr in server.gui_list:
    #         if ray.are_on_same_machine(server.url, gui_addr.url):
    #             local_guis.append(gui_addr)
    #         else:
    #             distant_guis.append(gui_addr)

    #     if local_guis:
    #         session_gpos_dict = {'group_positions': list[dict]()}
    #         for gpos in self.group_positions_session:
    #             session_gpos_dict['group_positions'].append(gpos.to_dict())

    #         for gui_addr in local_guis:
    #             file = tempfile.NamedTemporaryFile(delete=False, mode='w+')
    #             json.dump(session_gpos_dict, file)

    #             self.send(gui_addr,
    #                       '/ray/gui/patchbay/fast_temp_file_memory',
    #                       file.name)

    #     if distant_guis:
    #         for gui_addr in distant_guis:
    #             for gpos in self.group_positions_session:
    #                 self.send(gui_addr,
    #                           '/ray/gui/patchbay/update_group_position',
    #                           *gpos.spread())

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
            view_data = data_dict.get('index')
            if view_data is not None:
                view['default_port_types_view'] = \
                    view_data.default_port_types_view.name
                view['is_white_list'] = view_data.is_white_list
            
            for ptv, ptv_dict in view_dict.items():
                view[ptv.name] = {}
                for group_name, group_pos in ptv_dict.items():
                    view[ptv.name][group_name] = group_pos.as_new_dict()
            
            out_list.append(view)
        
        return out_list

    def send_all_group_positions(self, src_addr: Address):
        if ray.are_on_same_machine(self.get_server_url(), src_addr.url):
            canvas_dict = dict[str, list]()
            canvas_dict['portgroups'] = list[dict]()

            config_list = self.get_json_view_list(config=True)
            session_list = self.get_json_view_list(config=False)

            for view_dict in session_list:
                for cf_view_dict in config_list:
                    if cf_view_dict['index'] == view_dict['index']:
                        config_list.remove(cf_view_dict)
                        break
                config_list.append(view_dict)
            
            canvas_dict['views'] = config_list
            
            for portgroup in self.portgroups:
                canvas_dict['portgroups'].append(portgroup.to_dict())
            
            with tempfile.NamedTemporaryFile(delete=False, mode='w+') as f:
                json.dump(canvas_dict, f)
                self.send(src_addr,
                          '/ray/gui/patchbay/fast_temp_file_memory',
                          f.name)
            return
        
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

        for portgroup in self.portgroups:
            self.send(src_addr, '/ray/gui/patchbay/update_portgroup',
                      *portgroup.spread())

            i += 1
            if i == 50:
                time.sleep(0.020)

    # def send_all_group_positions(self, src_addr: Address):
    #     if ray.are_on_same_machine(self.get_server_url(), src_addr.url):
    #         # GUI is on the same machine than the daemon
    #         # send group positions via a tmp file because they can be many
    #         # it can be faster, it also prevents to lose packets
    #         canvas_dict = {'group_positions': [], 'portgroups': []}
    #         for gpos in self.group_positions_session:
    #             canvas_dict['group_positions'].append(gpos.to_dict())

    #         for gpos_cf in self.group_positions_config:
    #             for gpos_ss in self.group_positions_session:
    #                 if (gpos_ss.port_types_view == gpos_cf.port_types_view
    #                         and gpos_ss.group_name == gpos_cf.group_name):
    #                     break
    #             else:
    #                 canvas_dict['group_positions'].append(gpos_cf.to_dict())

    #         for portgroup in self.portgroups:
    #             canvas_dict['portgroups'].append(portgroup.to_dict())

    #         file = tempfile.NamedTemporaryFile(delete=False, mode='w+')
    #         json.dump(canvas_dict, file)
    #         file.close()
    #         self.send(src_addr,
    #                   '/ray/gui/patchbay/fast_temp_file_memory',
    #                   file.name)
    #         return

    #     i = 0

    #     for gpos in self.group_positions_session:
    #         self.send(src_addr, '/ray/gui/patchbay/update_group_position',
    #                   *gpos.spread())
    #         i += 1
    #         if i == 50:
    #             # we need to slow big process of canvas memory
    #             # to prevent loss OSC packets
    #             time.sleep(0.020)
    #             i = 0

    #     for gpos_cf in self.group_positions_config:
    #         for gpos_ss in self.group_positions_session:
    #             if (gpos_ss.port_types_view == gpos_cf.port_types_view
    #                     and gpos_ss.group_name == gpos_cf.group_name):
    #                 break
    #         else:
    #             self.send(src_addr, '/ray/gui/patchbay/update_group_position',
    #                       *gpos_cf.spread())

    #             i += 1
    #             if i == 50:
    #                 time.sleep(0.020)
    #                 i = 0

    #     for portgroup in self.portgroups:
    #         self.send(src_addr, '/ray/gui/patchbay/update_portgroup',
    #                   *portgroup.spread())

    #         i += 1
    #         if i == 50:
    #             time.sleep(0.020)

    def save_group_position(self, *args):
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

    # def save_group_position(self, *args):
    #     gp = ray.GroupPosition.new_from(*args)
    #     for group_positions in (self.group_positions_session,
    #                             self.group_positions_config):
    #         for gpos in group_positions:
    #             if gpos.is_same(gp):
    #                 gpos.update(*args)
    #                 break
    #         else:
    #             group_positions.append(gp)

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
                    self.view_datas_session[1] = ViewData(
                        '', PortTypesViewFlag.ALL, False)

                    for gpos_dict in gpos_list:
                        gpos = GroupPos.from_serialized_dict(gpos_dict)
                        gpos_list.append(gpos)
                        
                        if session_version < (0, 13, 0):
                            if (gpos.port_types_view
                                    is PortTypesViewFlag.AUDIO
                                    | PortTypesViewFlag.MIDI):
                                gpos.port_types_view = PortTypesViewFlag.ALL
                        
                        elif session_version < (0, 14, 0):
                            if (gpos.port_types_view
                                    is (PortTypesViewFlag.AUDIO
                                        | PortTypesViewFlag.MIDI
                                        | PortTypesViewFlag.CV
                                        | PortTypesViewFlag.VIDEO)):
                                gpos.port_types_view = PortTypesViewFlag.ALL
                        
                        self.views_session[1]
                        ptv_dict = self.views_session[1].get(gpos.port_types_view)
                        if ptv_dict is None:
                            ptv_dict = self.views_session[1][gpos.port_types_view] = \
                                dict[str, GroupPos]()
                        ptv_dict[gpos.group_name] = gpos

    # def load_json_session_canvas(self, session_path: Path):
    #     self.group_positions_session.clear()

    #     session_canvas_file = session_path / f'.{JSON_PATH}'
    #     if not session_canvas_file.exists():
    #         return

    #     with open(session_canvas_file, 'r') as f:
    #         json_contents = {}
    #         gpos_list = list[dict]()

    #         try:
    #             json_contents = json.load(f)
    #         except json.JSONDecodeError:
    #             Terminal.message("Failed to load session canvas file %s" % f)

    #         session_version = (0, 14, 0)

    #         if isinstance(json_contents, dict):
    #             if 'group_positions' in json_contents.keys():
    #                 gpos_list : list[dict]() = json_contents['group_positions']
    #             session_version = _get_version_tuple_json_dict(json_contents)

    #         for gpos_dict in gpos_list:
    #             gpos = ray.GroupPosition()
    #             gpos.write_from_dict(gpos_dict)
    #             if session_version < (0, 13, 0):
    #                 if gpos.port_types_view == 3:
    #                     gpos.port_types_view = 15
                
    #             elif session_version < (0, 14, 0):
    #                 if gpos.port_types_view == 15:
    #                     gpos.port_types_view = 31
                
    #             if not [g for g in self.group_positions_session
    #                     if g.is_same(gpos)]:
    #                 self.group_positions_session.append(gpos)

    def save_json_session_canvas(self, session_path: Path):
        session_json_path = session_path / f'.{JSON_PATH}'

        json_contents = {}
        json_contents['views'] = self.get_json_view_list()        
        json_contents['version'] = ray.VERSION

        with open(session_json_path, 'w+') as f:
            f.write(from_json_to_str(json_contents))

    # def save_json_session_canvas(self, session_path: Path):
    #     session_json_path = session_path / f'.{JSON_PATH}'

    #     if not self.group_positions_session:
    #         return

    #     json_contents = {}
    #     json_contents['group_positions'] = [
    #         gpos.to_dict() for gpos in self.group_positions_session]
    #     json_contents['version'] = ray.VERSION

    #     with open(session_json_path, 'w+') as f:
    #         json.dump(json_contents, f, indent=2)

    def save_config_file(self):
        json_contents = {}
        json_contents['views'] = self.get_json_view_list(config=True)
        json_contents['portgroups'] = [
            portgroup.to_dict() for portgroup in self.portgroups]
        json_contents['version'] = ray.VERSION

        with open(self._config_json_path, 'w+') as f:
            f.write(from_json_to_str(json_contents))

    # def save_config_file(self):
    #     if not self.group_positions_config:
    #         return

    #     json_contents = {}
    #     json_contents['group_positions'] = [
    #         gpos.to_dict() for gpos in self.group_positions_config]
    #     json_contents['portgroups'] = [
    #         portgroup.to_dict() for portgroup in self.portgroups]
    #     json_contents['version'] = ray.VERSION

    #     with open(self._config_json_path, 'w+') as f:
    #         json.dump(json_contents, f, indent=2)

    def save_portgroup(self, *args):
        new_portgroup = ray.PortGroupMemory.new_from(*args)

        remove_list = []

        # remove any portgroup with a commmon port with the new one
        for portgroup in self.portgroups:
            if portgroup.has_a_common_port_with(new_portgroup):
                remove_list.append(portgroup)

        for portgroup in remove_list:
            self.portgroups.remove(portgroup)

        self.portgroups.append(new_portgroup)

    def client_jack_name_changed(
            self, old_jack_name: str, new_jack_name: str):
        server = self.session.get_server()
        
        for view_num, view_dict in self.views_session.items():
            for ptv, ptv_dict in view_dict.items():
                group_name_change_list = list[tuple(str, str)]()
                
                for group_name, group_pos in ptv_dict.items():
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

    # def client_jack_name_changed(
    #         self, old_jack_name: str, new_jack_name: str):
    #     server = self.session.get_server()
        
    #     for gpos in self.group_positions_session:
    #         if group_belongs_to_client(gpos.group_name, old_jack_name):
    #             gpos.group_name = gpos.group_name.replace(
    #                 old_jack_name, new_jack_name, 1)

    #             if server is not None:
    #                 server.send_gui(
    #                     '/ray/gui/patchbay/update_group_position',
    #                     *gpos.spread())
