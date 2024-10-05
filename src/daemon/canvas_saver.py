
import json
from pathlib import Path
import tempfile
import time
from typing import TYPE_CHECKING

from liblo import Address

import ray
from daemon_tools import RS, Terminal
from server_sender import ServerSender
from jack_renaming_tools import group_belongs_to_client
from patchcanvas_enums import (
    PortMode, BoxLayoutMode, BoxFlag,
    PortTypesViewFlag, GroupPosFlag, GroupPos)

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

        # dict[view_num, dict[group_name, ray.GroupPosition] 
        self.views_session = dict[
            int, dict[PortTypesViewFlag, dict[str, ray.GroupPosition]]]()
        self.views_config = dict[
            int, dict[PortTypesViewFlag, dict[str, ray.GroupPosition]]]()

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
            views_config = dict[int, dict[int, dict[str, dict]]]()

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
                    main_dict = json_contents['views']
                    
                    self.views_config = self.write_view_from_json(main_dict)
                    
                    
                    
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

    def write_view_from_json(
            self, json_list: list) -> dict[
                int, dict[int, dict[str, ray.GroupPosition]]]:
        if not isinstance(json_list, list):
            return {}
        
        main_dict = dict[
            int, dict[PortTypesViewFlag, dict[str, ray.GroupPosition]]]()
        
        for view_dict in json_list:
            if not isinstance(view_dict, dict):
                continue

            view_num = view_dict.get('index')
            if not isinstance(view_num, int):
                continue
            
            main_dict[view_num] = dict[
                PortTypesViewFlag, dict[str, ray.GroupPosition]]()

            ptv_str: str
            for ptv_str, ptv_dict in view_dict.items():
                if ptv_str in ('index', 'name', 'default_port_types'):
                    continue
                
                if not isinstance(ptv_dict, dict):
                    continue
                
                ptv = PortTypesViewFlag.from_config_str(ptv_str)
                if ptv is PortTypesViewFlag.NONE:
                    continue
                
                main_dict[view_num][ptv] = dict[str, ray.GroupPosition]()
                
                group_name: str
                for group_name, gpos_dict in ptv_dict.items():
                    if not isinstance(gpos_dict, dict):
                        continue
                    
                    gpos = ray.GroupPosition()
                    gpos.port_types_view = ptv.value
                    gpos.group_name = group_name
                    
                    flags = gpos_dict.get('flags')
                    if flags == 'SPLITTED':
                        gpos.flags = GroupPosFlag.SPLITTED.value
                        
                    boxes = gpos_dict.get('boxes')
                    if isinstance(boxes, dict):
                        box_mode_str: str
                        for box_mode_str, box_dict in boxes.items():
                            if not isinstance(box_dict, dict):
                                continue
                            
                            port_mode = PortMode.NULL
                            for box_mode in box_mode_str.split('|'):
                                try:
                                    port_mode |= PortMode[box_mode]
                                except:
                                    continue
                            
                            if port_mode is PortMode.NULL:
                                continue
                                
                            pos_list = box_dict.get('pos')
                            xy = (0, 0)
                            
                            if (isinstance(pos_list, list)
                                    and len(pos_list) == 2
                                    and isinstance(pos_list[0], int)
                                    and isinstance(pos_list[1], int)):
                                xy = tuple(pos_list)
                                    
                            if port_mode is PortMode.INPUT:
                                gpos.in_xy = xy
                            elif port_mode is PortMode.OUTPUT:
                                gpos.out_xy = xy
                            elif port_mode is PortMode.BOTH:
                                gpos.null_xy = xy
                            
                            layout_mode_str = box_dict.get('layout_mode')
                            if isinstance(layout_mode_str, str):
                                try:
                                    layout_mode = BoxLayoutMode[
                                        layout_mode_str.upper()]
                                    gpos.set_layout_mode(
                                        port_mode.value, layout_mode.value)
                                except ValueError:
                                    pass
                                
                            flags_str = box_dict.get('flags')
                            if isinstance(flags_str, str):
                                try:
                                    box_flags = BoxFlag.NONE
                                    for flag_str in flags_str.split('|'):
                                        box_flags |= BoxFlag[flag_str.upper()]
                                    gpos.flags = box_flags.value
                                except ValueError:
                                    pass
                    
                main_dict[view_num][ptv][group_name] = gpos
        return main_dict                        

    def get_all_group_positions(self) -> list[ray.GroupPosition]:
        group_positions_config_exclu = list[ray.GroupPosition]()

        for gpos_cf in self.group_positions_config:
            for gpos_ss in self.group_positions_session:
                if (gpos_ss.port_types_view == gpos_cf.port_types_view
                        and gpos_ss.group_name == gpos_cf.group_name):
                    break
            else:
                group_positions_config_exclu.append(gpos_cf)

        return self.group_positions_session + group_positions_config_exclu

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
            session_gpos_dict = {'group_positions': list[dict]()}
            for gpos in self.group_positions_session:
                session_gpos_dict['group_positions'].append(gpos.to_dict())

            for gui_addr in local_guis:
                file = tempfile.NamedTemporaryFile(delete=False, mode='w+')
                json.dump(session_gpos_dict, file)

                self.send(gui_addr,
                          '/ray/gui/patchbay/fast_temp_file_memory',
                          file.name)

        if distant_guis:
            for gui_addr in distant_guis:
                for gpos in self.group_positions_session:
                    self.send(gui_addr,
                              '/ray/gui/patchbay/update_group_position',
                              *gpos.spread())

    def send_all_group_positions(self, src_addr: Address):
        if ray.are_on_same_machine(self.get_server_url(), src_addr.url):
            # GUI is on the same machine than the daemon
            # send group positions via a tmp file because they can be many
            # it can be faster, it also prevents to lose packets
            canvas_dict = {'group_positions': [], 'portgroups': []}
            for gpos in self.group_positions_session:
                canvas_dict['group_positions'].append(gpos.to_dict())

            for gpos_cf in self.group_positions_config:
                for gpos_ss in self.group_positions_session:
                    if (gpos_ss.port_types_view == gpos_cf.port_types_view
                            and gpos_ss.group_name == gpos_cf.group_name):
                        break
                else:
                    canvas_dict['group_positions'].append(gpos_cf.to_dict())

            for portgroup in self.portgroups:
                canvas_dict['portgroups'].append(portgroup.to_dict())

            file = tempfile.NamedTemporaryFile(delete=False, mode='w+')
            json.dump(canvas_dict, file)
            file.close()
            self.send(src_addr,
                      '/ray/gui/patchbay/fast_temp_file_memory',
                      file.name)
            return

        i = 0

        for gpos in self.group_positions_session:
            self.send(src_addr, '/ray/gui/patchbay/update_group_position',
                      *gpos.spread())
            i += 1
            if i == 50:
                # we need to slow big process of canvas memory
                # to prevent loss OSC packets
                time.sleep(0.020)
                i = 0

        for gpos_cf in self.group_positions_config:
            for gpos_ss in self.group_positions_session:
                if (gpos_ss.port_types_view == gpos_cf.port_types_view
                        and gpos_ss.group_name == gpos_cf.group_name):
                    break
            else:
                self.send(src_addr, '/ray/gui/patchbay/update_group_position',
                          *gpos_cf.spread())

                i += 1
                if i == 50:
                    time.sleep(0.020)
                    i = 0

        for portgroup in self.portgroups:
            self.send(src_addr, '/ray/gui/patchbay/update_portgroup',
                      *portgroup.spread())

            i += 1
            if i == 50:
                time.sleep(0.020)

    def save_group_position(self, *args):
        gp = ray.GroupPosition.new_from(*args)
        for group_positions in (self.group_positions_session,
                                self.group_positions_config):
            for gpos in group_positions:
                if gpos.is_same(gp):
                    gpos.update(*args)
                    break
            else:
                group_positions.append(gp)

    def load_json_session_canvas(self, session_path: Path):
        self.group_positions_session.clear()

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

            session_version = (0, 14, 0)

            if isinstance(json_contents, dict):
                if 'group_positions' in json_contents.keys():
                    gpos_list : list[dict]() = json_contents['group_positions']
                session_version = _get_version_tuple_json_dict(json_contents)

            for gpos_dict in gpos_list:
                gpos = ray.GroupPosition()
                gpos.write_from_dict(gpos_dict)
                if session_version < (0, 13, 0):
                    if gpos.port_types_view == 3:
                        gpos.port_types_view = 15
                
                elif session_version < (0, 14, 0):
                    if gpos.port_types_view == 15:
                        gpos.port_types_view = 31
                
                if not [g for g in self.group_positions_session
                        if g.is_same(gpos)]:
                    self.group_positions_session.append(gpos)

    def save_json_session_canvas(self, session_path: Path):
        session_json_path = session_path / f'.{JSON_PATH}'

        if not self.group_positions_session:
            return

        json_contents = {}
        json_contents['group_positions'] = [
            gpos.to_dict() for gpos in self.group_positions_session]
        json_contents['version'] = ray.VERSION

        with open(session_json_path, 'w+') as f:
            json.dump(json_contents, f, indent=2)

    def save_config_file(self):
        if not self.group_positions_config:
            return

        json_contents = {}
        json_contents['group_positions'] = [
            gpos.to_dict() for gpos in self.group_positions_config]
        json_contents['portgroups'] = [
            portgroup.to_dict() for portgroup in self.portgroups]
        json_contents['version'] = ray.VERSION

        with open(self._config_json_path, 'w+') as f:
            json.dump(json_contents, f, indent=2)

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

    def client_jack_name_changed(self, old_jack_name: str, new_jack_name: str):
        server = self.session.get_server()
        
        for gpos in self.group_positions_session:
            if group_belongs_to_client(gpos.group_name, old_jack_name):
                gpos.group_name = gpos.group_name.replace(
                    old_jack_name, new_jack_name, 1)

                if server is not None:
                    server.send_gui(
                        '/ray/gui/patchbay/update_group_position',
                        *gpos.spread())
