
import ray

from daemon_tools import RS
from server_sender import ServerSender


class CanvasSaver(ServerSender):
    def __init__(self):
        ServerSender.__init__(self)
        self.group_positions_session = []
        self.group_positions_config = []
        self.portgroups_session = []
        self.portgroups_config = []
        tuple_config_list = RS.settings.value(
            'Canvas/GroupPositions', type=list)
        
        for gt in tuple_config_list:
            group_pos = ray.GroupPosition()
            group_pos.write_from_dict(gt)
            self.group_positions_config.append(group_pos)
        
    def get_all_group_positions(self)->list:
        group_positions_config_exclu = []
        
        for gpos_cf in self.group_positions_config:
            for gpos_ss in self.group_positions_session:
                if gpos_ss.group_name == gpos_cg.group_name:
                    break
            else:
                group_positions_config_exclu.append(gpos_cf)

        return self.group_positions_session + group_positions_config_exclu
    
    def send_session_group_positions(self):
        for gpos in self.group_positions_session:
            self.sendGui('/ray/gui/patchbay/group_position_info',
                         *gpos.spread())
    
    def send_all_group_positions(self, src_addr):
        print('chaminiiia')
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
                if gpos.group_name == gp.group_name:
                    gpos.update(*args)
                    break
            else:
                group_positions.append(gp)

        RS.settings.setValue('Canvas/GroupPositions',
                             [gp.to_dict() for gp in group_positions])
    
    def load_session_canvas(self, xml_element):
        nodes = xml_element.childNodes()
        for i in range(nodes.count()):
            node = nodes.at(i)
            tag_name = node.toElement().tagName()
            if tag_name == 'GroupPositions':
                self.update_group_session_positions(node)
            elif tag_name == 'Portgroups':
                self.update_session_portgroups(node)
    
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
    
    def update_group_session_positions(self, xml_element):
        print('zlkjfdkkkdsks')
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

            #in_or_out_str = el.attribute('in_or_out')
            #group = el.attribute('group')
            #x_str = el.attribute('x')
            #y_str = el.attribute('y')
            
            ## verify that values are digits
            #int_ok = True
            #for digit_str in (in_or_out_str, x_str, y_str):
                #if digit_str.startswith('-'):
                    #digit_str = digit_str.replace('-', '', 1)

                #if not digit_str.isdigit():
                    #int_ok = False
                    #break
            
            #if not int_ok:
                #continue

            #gpos = GroupPosition(int(in_or_out_str), group,
                                 #int(x_str), int(y_str))
            gpos = ray.GroupPosition.newFrom(*args)

            self.group_positions_session.append(gpos)
            
    def update_session_portgroups(self, xml_element):
        pass
