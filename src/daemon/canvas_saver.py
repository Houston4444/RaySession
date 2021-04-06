
import json
import os

import ray

from daemon_tools import RS
from server_sender import ServerSender

JSON_PATH = 'ray_canvas.json'

class CanvasSaver(ServerSender):
    def __init__(self):
        ServerSender.__init__(self)
        self.group_positions_session = []
        self.group_positions_config = []
        self.portgroups = []
        self._config_json_path = "%s/%s" % (
            os.path.dirname(RS.settings.fileName()), JSON_PATH)

        if not os.path.exists(self._config_json_path):
            return

        with open(self._config_json_path, 'r') as f:
            json_contents = json.load(f)
            gpos_list = []
            pg_list = []
            if type(json_contents) == dict:
                if 'group_positions' in json_contents.keys():
                    gpos_list = json_contents['group_positions']
                if 'portgroups' in json_contents.keys():
                    pg_list = json_contents['portgroups']

            for gpos_dict in gpos_list:
                gpos = ray.GroupPosition()
                gpos.write_from_dict(gpos_dict)
                self.group_positions_config.append(gpos)

            for pg_dict in pg_list:
                portgroup = ray.PortGroupMemory()
                portgroup.write_from_dict(pg_dict)
                self.portgroups.append(portgroup)

    def get_all_group_positions(self)->list:
        group_positions_config_exclu = []
        
        for gpos_cf in self.group_positions_config:
            for gpos_ss in self.group_positions_session:
                if (gpos_ss.port_types_view == gpos_cf.port_types_view
                        and gpos_ss.group_name == gpos_cf.group_name):
                    break
            else:
                group_positions_config_exclu.append(gpos_cf)

        return self.group_positions_session + group_positions_config_exclu
    
    def send_session_group_positions(self):
        for gpos in self.group_positions_session:
            self.sendGui('/ray/gui/patchbay/update_group_position',
                         *gpos.spread())
    
    def send_all_group_positions(self, src_addr):
        for gpos in self.group_positions_session:
            self.send(src_addr, '/ray/gui/patchbay/update_group_position',
                      *gpos.spread())

        for gpos_cf in self.group_positions_config:
            for gpos_ss in self.group_positions_session:
                if (gpos_ss.port_types_view == gpos_cf.port_types_view
                        and gpos_ss.group_name == gpos_cf.group_name):
                    break
            else:
                self.send(src_addr, '/ray/gui/patchbay/update_group_position',
                          *gpos_cf.spread())
        
        self.send_portgroups(src_addr)

    def save_group_position(self, *args):
        gp = ray.GroupPosition.newFrom(*args)
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
            json_contents = json.load(f)
            gpos_list = []
            if (type(json_contents) == dict
                    and 'group_positions' in json_contents.keys()):
                gpos_list = json_contents['group_positions']

            for gpos_dict in gpos_list:
                gpos = ray.GroupPosition()
                gpos.write_from_dict(gpos_dict)
                self.group_positions_session.append(gpos)
    
    def load_session_canvas(self, xml_element):
        nodes = xml_element.childNodes()
        for i in range(nodes.count()):
            node = nodes.at(i)
            tag_name = node.toElement().tagName()
            if tag_name == 'GroupPositions':
                self.update_group_session_positions(node)
            elif tag_name == 'Portgroups':
                self.update_session_portgroups(node)
    
    def save_json_session_canvas(self, session_path: str):
        session_json_path = "%s/.%s" % (session_path, JSON_PATH)
        
        if not self.group_positions_session:
            return
        
        json_contents = {}
        json_contents['group_positions'] = [
            gpos.to_dict() for gpos in self.group_positions_session]
        
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

        with open(self._config_json_path, 'w+') as f:
            json.dump(json_contents, f, indent=2)
            
    def save_portgroup(self, *args):
        new_portgroup = ray.PortGroupMemory.newFrom(*args)
        
        remove_list = []
        
        # remove any portgroup with a commmon port with the new one
        for portgroup in self.portgroups:
            if portgroup.has_a_common_port_with(new_portgroup):
                remove_list.append(portgroup)
        
        for portgroup in remove_list:
            self.portgroups.remove(portgroup)
        
        self.portgroups.append(new_portgroup)
        
    def send_portgroups(self, src_addr):
        for portgroup in self.portgroups:
            print('fkjj', portgroup.spread())
            self.send(src_addr, '/ray/gui/patchbay/update_portgroup',
                      *portgroup.spread())

