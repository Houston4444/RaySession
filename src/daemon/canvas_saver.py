
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


class CanvasSaver(ServerSender):
    def __init__(self):
        ServerSender.__init__(self)
        self.group_positions_session = []
        self.group_positions_config = []
        self.portgroups_session = []
        self.portgroups_config = []
        
    def get_all_group_positions(self)->list:
        group_positions_config_exclu = []
        
        for gpos_cf in self.group_positions_config:
            for gpos_ss in self.group_positions_session:
                if gpos_ss.same_group(gpos_cf):
                    break
            else:
                group_positions_config_exclu.append(gpos_cf)

        return self.group_positions_session + group_positions_config_exclu
    
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
                
    def update_group_session_positions(self, xml_element):
        self.group_positions_session.clear()
        
        nodes = xml_element.childNodes()

        for i in range(nodes.count()):
            node = nodes.at(i)
            el = node.toElement()
            if el.tagName() != "group":
                continue

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
                    
            gpos = GroupPosition(int(in_or_out_str), group,
                                 int(x_str), int(y_str))

            self.group_positions_session.append(gpos)
