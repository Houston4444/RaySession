
import json
import os
import tempfile
import time
from typing import TYPE_CHECKING
from liblo import Address

import ray

from daemon_tools import RS, dirname, Terminal
from server_sender import ServerSender
from jack_renaming_tools import group_belongs_to_client

if TYPE_CHECKING:
    from session_signaled import SignaledSession

JSON_PATH = 'ray_canvas.json'

def _get_version_tuple_json_dict(json_contents: dict) -> tuple[int, int, int]:
    if 'version' in json_contents.keys():
        version_str = json_contents['version']
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

        self.group_positions_session = list[ray.GroupPosition]()
        self.group_positions_config = list[ray.GroupPosition]()
        self.portgroups = list[ray.PortGroupMemory]()
        self._config_json_path = "%s/%s" % (
            dirname(RS.settings.fileName()), JSON_PATH)

        if not os.path.exists(self._config_json_path):
            return

        with open(self._config_json_path, 'r') as f:
            json_contents = {}
            gpos_list = list[ray.GroupPosition]()
            pg_list = list[ray.PortGroupMemory]()

            try:
                json_contents = json.load(f)
            except json.JSONDecodeError:
                Terminal.message(f"Failed to load patchcanvas config file {f}")

            # Old group_position port_types_view norm was
            # full_view = AUDIO | MIDI (1|2 = 3)
            # now this is:
            # full_view = AUDIO | MIDI | CV | VIDEO (1|2|4|8 = 15)
            # (even if VIDEO is not implemented in patchbay yet)
            
            # so we need to consider that a full view is a full view
            # and convert in old sessions port_types_view = 3 -> 15 
            needs_port_types_view_convert = False

            if isinstance(json_contents, dict):
                if 'group_positions' in json_contents.keys():
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

        local_guis = []
        distant_guis = []
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

    def load_json_session_canvas(self, session_path: str):
        self.group_positions_session.clear()

        session_canvas_file = "%s/.%s" % (session_path, JSON_PATH)

        if not os.path.exists(session_canvas_file):
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
                
                if not [g for g in self.group_positions_session if g.is_same(gpos)]:
                    self.group_positions_session.append(gpos)

    def save_json_session_canvas(self, session_path: str):
        session_json_path = "%s/.%s" % (session_path, JSON_PATH)

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
