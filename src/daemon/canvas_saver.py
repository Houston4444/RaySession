
from daemon_tools import RS
from server_sender import ServerSender


class GroupPosition:
    def __init__(self, in_or_out: int, group: str, x: int, y: int):
        self.in_or_out = in_or_out
        self.group = group
        self.x = x
        self.y = y
    
    def is_group(self, in_or_out: int, group: str):
        return bool (self.in_or_out == in_or_out
                     and self.group == group)
    
    def same_group(self, other)->bool:
        return bool(self.in_or_out == other.in_or_out
                    and self.group == other.group)
    
    def change_x_y(self, x: int, y: int):
        self.x = x
        self.y = y

    def to_tuple(self)->tuple:
        return {'group': self.group,
                'in_or_out': self.in_or_out,
                'x': self.x,
                'y': self.y}

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
            group_pos = GroupPosition(
                gt['in_or_out'], gt['group'], gt['x'], gt['y'])
            self.group_positions_config.append(group_pos)
        
    def get_all_group_positions(self)->list:
        group_positions_config_exclu = []
        
        for gpos_cf in self.group_positions_config:
            for gpos_ss in self.group_positions_session:
                if gpos_ss.same_group(gpos_cf):
                    break
            else:
                group_positions_config_exclu.append(gpos_cf)

        return self.group_positions_session + group_positions_config_exclu
    
    def send_session_group_positions(self):
        for gpos in self.group_positions_session:
            self.sendGui('/ray/gui/patchbay/group_position_info',
                         gpos.in_or_out, gpos.group, gpos.x, gpos.y)
    
    def send_all_group_positions(self, src_addr):
        for gpos in self.group_positions_session:
            self.send(src_addr, '/ray/gui/patchbay/group_position_info',
                      gpos.in_or_out, gpos.group, gpos.x, gpos.y)

        for gpos_cf in self.group_positions_config:
            for gpos_ss in self.group_positions_session:
                if gpos_ss.same_group(gpos_cf):
                    break
            else:
                self.send(src_addr, '/ray/gui/patchbay/group_position_info',
                          gpos_cf.in_or_out, gpos_cf.group,
                          gpos_cf.x, gpos_cf.y)

    def save_group_position(self, in_or_out: int, group: str,
                            x: int, y : int):
        for group_positions in (self.group_positions_session,
                                self.group_positions_config):
            for gpos in group_positions:
                if gpos.is_group(in_or_out, group):
                    gpos.change_x_y(x, y)
                    break
            else:
                gpos = GroupPosition(in_or_out, group, x, y)
                group_positions.append(gpos)
        
        print('yaloo')
        RS.settings.setValue('Canvas/GroupPositions',
                             [gp.to_tuple() for gp in group_positions])
        print('augooluaf')
    
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
            xml_gpos = xml.createElement('group')
            xml_gpos.setAttribute('in_or_out', gpos.in_or_out)
            xml_gpos.setAttribute('group', gpos.group)
            xml_gpos.setAttribute('x', gpos.x)
            xml_gpos.setAttribute('y', gpos.y)
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
        self.group_positions_session.clear()
        print('oodod')
        nodes = xml_element.childNodes()

        for i in range(nodes.count()):
            print('coommlld')
            node = nodes.at(i)
            el = node.toElement()
            if el.tagName() != "group":
                continue
            print('cllms')
            in_or_out_str = el.attribute('in_or_out')
            group = el.attribute('group')
            x_str = el.attribute('x')
            y_str = el.attribute('y')
            
            # verify that values are digits
            int_ok = True
            for digit_str in (in_or_out_str, x_str, y_str):
                if not digit_str.isdigit():
                    int_ok = False
                    break
            
            if not int_ok:
                continue
            print('ldllldkd', in_or_out_str, group, x_str, y_str)
            gpos = GroupPosition(int(in_or_out_str), group,
                                 int(x_str), int(y_str))

            self.group_positions_session.append(gpos)
            
    def update_session_portgroups(self, xml_element):
        pass
