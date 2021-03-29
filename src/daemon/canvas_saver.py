
import json
import os

import ray

from daemon_tools import RS
from server_sender import ServerSender

JSON_PATH = 'ray_canvas_positions.json'

class CanvasSaver(ServerSender):
    def __init__(self):
        ServerSender.__init__(self)
        self.group_positions_session = []
        self.group_positions_config = []
        self.portgroups_session = []
        self.portgroups_config = []
        self._config_json_path = "%s/%s" % (
            os.path.dirname(RS.settings.fileName()), JSON_PATH)

        if os.path.exists(self._config_json_path):
            with open(self._config_json_path, 'r') as f:
                gpos_list = json.load(f)
                for gpos_dict in gpos_list:
                    gpos = ray.GroupPosition()
                    gpos.write_from_dict(gpos_dict)
                    self.group_positions_config.append(gpos)
        
    def get_all_group_positions(self)->list:
        group_positions_config_exclu = []
        
        for gpos_cf in self.group_positions_config:
            for gpos_ss in self.group_positions_session:
                if gpos_ss.group_name == gpos_cf.group_name:
                    break
            else:
                group_positions_config_exclu.append(gpos_cf)

        return self.group_positions_session + group_positions_config_exclu
    
    def send_session_group_positions(self):
        print('ilrzrillrifzrli')
        for gpos in self.group_positions_session:
            print('eijrjijif', gpos.group_name)
            self.sendGui('/ray/gui/patchbay/group_position_info',
                         *gpos.spread())
    
    def send_all_group_positions(self, src_addr):
        for gpos in self.group_positions_session:
            self.send(src_addr, '/ray/gui/patchbay/group_position_info',
                      *gpos.spread())

        for gpos_cf in self.group_positions_config:
            for gpos_ss in self.group_positions_session:
                if gpos_ss.group_name == gpos_cf.group_name:
                    break
            else:
                self.send(src_addr, '/ray/gui/patchbay/group_position_info',
                          *gpos_cf.spread())

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

        #RS.settings.setValue('Canvas/GroupPositions',
                             #[gp.to_dict() for gp in group_positions])
    
    def load_json_session_canvas(self, session_path: str):
        self.group_positions_session.clear()
        
        session_canvas_file = "%s/.%s" % (session_path, JSON_PATH)
        
        if not os.path.exists(session_canvas_file):
            return
            
        with open(session_canvas_file, 'r') as f:
            gpos_list = json.load(f)
            for gpos_dict in gpos_list:
                gpos = ray.GroupPosition()
                gpos.write_from_dict(gpos_dict)
                print('zouga', gpos_dict)
                print('kdlfjdfkjl', gpos.group_name)
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
        
        #audio_midi_gpos = []
        #audio_gpos = []
        #midi_gpos = []
        
        #save_dict = {'audio+midi': audio_midi_gpos,
                     #'audio': audio_gpos,
                     #'midi': midi_gpos}
        
        #for gpos in self.group_positions_session:
            #if gpos.context == ray.GROUP_CONTEXT_AUDIO:
                #audio_gpos.append(gpos.to_dict())
            #elif gpos.context == ray.GROUP_CONTEXT_MIDI:
                #midi_gpos.append(gpos.to_dict())
            #else:
                #audio_midi_gpos.append(gpos.to_dict())
        
        with open(session_json_path, 'w+') as f:
            json.dump(
                [gpos.to_dict() for gpos in self.group_positions_session],
                f, indent=2)
    
    def save_session_canvas(self, xml, xml_element):
        xml_group_positions = xml.createElement('GroupPositions')
        xml_portgroups = xml.createElement('Portgroups')
        
        # save patchbay group positions
        for gpos in self.group_positions_session:
            xml_gpos = xml.createElement('group_position')
            for attr in gpos.get_attributes():
                xml_gpos.setAttribute(attr, gpos.get_str_value(attr))
            
            xml_group_positions.appendChild(xml_gpos)
        
        ## save patchbay portgroups (stereo/mono)
        #for portgroup in self.portgroups_session:
            #xml_pgs = xml.createElement('portgroup')
            #xml_pgs.setAttribute('
                
                
        #for portgroup in self.canvas_portgroups:
            #xml_pgrp = xml.createElement('portgroup')
            #for atttribute in portgroup.keys():
                #xml.pgrp.setAttribute(attribute, portgroup[attribute])
            #xml_portgroups.appendChild(xml_pgrp)
        
        xml_element.appendChild(xml_group_positions)
        xml_element.appendChild(xml_portgroups)
    
    def save_config_file(self):
        if not self.group_positions_config:
            return

        with open(self._config_json_path, 'w+') as f:
            json.dump(
                [gpos.to_dict() for gpos in self.group_positions_config],
                f, indent=2)
    
    def update_group_session_positions(self, xml_element):
        self.group_positions_session.clear()
        nodes = xml_element.childNodes()

        for i in range(nodes.count()):
            node = nodes.at(i)
            el = node.toElement()
            if el.tagName() != "group_position":
                continue

            args = []
            for attr in ray.GroupPosition.get_attributes():
                args.append(el.attribute(attr))

            gpos = ray.GroupPosition.newFrom(*args)
            self.group_positions_session.append(gpos)
            
    def update_session_portgroups(self, xml_element):
        pass
