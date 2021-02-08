
from patchcanvas import patchcanvas

# Port Type
PORT_TYPE_NULL = 0
PORT_TYPE_AUDIO = 1
PORT_TYPE_MIDI = 2

# Port Mode
PORT_MODE_NULL = 0
PORT_MODE_INPUT = 1
PORT_MODE_OUTPUT = 2

# Port Flags
PORT_IS_INPUT = 0x01
PORT_IS_OUTPUT = 0x02
PORT_IS_PHYSICAL = 0x04
PORT_CAN_MONITOR = 0x08
PORT_IS_TERMINAL = 0x10
PORT_IS_CONTROL_VOLTAGE = 0x100

USE_ALIAS_NONE = 0
USE_ALIAS_1 = 1
USE_ALIAS_2 = 2


class Connection:
    def __init__(self, connection_id: int, port_out, port_in):
        self.connection_id = connection_id
        self.port_out = port_out
        self.port_in = port_in
    
    def add_to_canvas(self):
        patchcanvas.connectPorts(
            self.connection_id,
            self.port_out.group_id, self.port_out.port_id,
            self.port_in.group_id, self.port_in.port_id)
        
    def remove_from_canvas(self):
        patchcanvas.disconnectPorts(self.connection_id)


class Port:
    short_name = ''
    group_id = -1
    portgroup_id = 0

    def __init__(self, port_id: int, name: str, alias_1: str, alias_2: str,
                 port_type: int, flags: int, metadata: str):
        self.port_id = port_id
        self.full_name = name
        self.alias_1 = alias_1
        self.alias_2 = alias_2
        self.type = port_type
        self.flags = flags
        self.metadata = metadata

    def add_to_canvas(self):
        port_mode = PORT_MODE_NULL
        if self.flags & PORT_IS_INPUT:
            port_mode = PORT_MODE_INPUT
        elif self.flags & PORT_IS_OUTPUT:
            port_mode = PORT_MODE_OUTPUT
        else:
            return

        patchcanvas.addPort(self.group_id, self.port_id, self.short_name,
                            port_mode, self.type, self.portgroup_id)
    
    def remove_from_canvas(self):
        patchcanvas.removePort(self.group_id, self.port_id)
    
    def change_canvas_properties(self):
        patchcanvas.changePortProperties(self.group_id, self.port_id,
                                         self.portgroup_id, self.short_name)

class Group:
    def __init__(self, group_id: int, name: str):
        self.group_id = group_id
        self.name = name
        self.ports = []
        self._is_hardware = False

    def add_to_canvas(self):
        icon = patchcanvas.ICON_APPLICATION
        if self._is_hardware:
            icon = patchcanvas.ICON_HARDWARE

        patchcanvas.addGroup(self.group_id, self.name,
                             patchcanvas.SPLIT_UNDEF, icon)
    
    def remove_from_canvas(self):
        patchcanvas.removeGroup(self.group_id)

    def add_port(self, port, use_alias: int):
        port_full_name = port.full_name
        if use_alias == USE_ALIAS_1:
            port_full_name = port.alias_1
        elif use_alias == USE_ALIAS_2:
            port_full_name = port.alias_2
        
        port.group_id = self.group_id
        port.short_name = port_full_name.partition(':')[2]
        
        if not self.ports:
            # we are adding the first port of the group
            if port.flags & PORT_IS_TERMINAL:
                print('gigigical')
                self._is_hardware = True
        
        self.ports.append(port)
    
    def remove_port(self, port):
        if port in self.ports:
            self.ports.remove(port)
            
    def rename_port(self, port):
        if self.use_alias == USE_ALIAS_NONE:
            port.short_name = port.full_name.partition(':')[2]

class PatchbayManager:
    def __init__(self):
        self.groups = []
        self.connections = []
        self._next_group_id = 0
        self._next_port_id = 0
        self._next_portgroup_id = 0
        self._next_connection_id = 0
        
        self.use_alias = USE_ALIAS_NONE
    
    def get_port_from_name(self, port_name: str):
        for group in self.groups:
            for port in group.ports:
                if port.full_name == port_name:
                    return port
    
    def add_port(self, name: str, alias_1: str, alias_2: str,
                 port_type: int, flags: int, metadata: str):
        port = Port(self._next_port_id, name, alias_1, alias_2,
                    port_type, flags, metadata)
        self._next_port_id += 1

        full_port_name = name
        if self.use_alias == USE_ALIAS_1:
            full_port_name = alias_1
        elif self.use_alias == USE_ALIAS_2:
            full_port_name = alias_2
            
        group_name, colon, port_name = full_port_name.partition(':')
        print('yallla', group_name)
        print('yoolle', port_name)
        group_is_new = False
        
        for group in self.groups:
            if group.name == group_name:
                break
        else:
            # port is an non existing group, create the group
            group = Group(self._next_group_id, group_name)
            self._next_group_id += 1
            self.groups.append(group)
            group_is_new = True
        
        group.add_port(port, self.use_alias)
        if group_is_new:
            group.add_to_canvas()
        port.add_to_canvas()
    
    def remove_port(self, name: str):
        port = self.get_port_from_name(name)
        if port is None:
            return
        
        for group in self.groups:
            if group.group_id == port.group_id:
                group.remove_port(port)
                port.remove_from_canvas()
                if not group.ports:
                    group.remove_from_canvas()
                    self.groups.remove(group)
                break
            
        #self.all_ports.remove(port)
    
    def rename_port(self, name: str, new_name: str):
        port = self.get_port_from_name(name)
        if port is None:
            return
        
        group_name = name.partition(':')[0]
        new_group_name = new_name.partition(':')[0]
        
        # In case a port rename implies another group port
        if (self.use_alias == USE_ALIAS_NONE
                and group_name != new_group_name):
            for group in self.groups:
                if group.name == group_name:
                    group.remove_port(port)
                    if not group.ports:
                        self.groups.remove(group)
                    break
            
            port.remove_from_canvas()
            port.full_name = new_name

            for group in self.groups:
                if group.name == new_group_name:
                    group.add_port(port)
                    break
            else:
                group = Group(self._next_group_id, new_group_name)
                self._next_group_id += 1
                group.add_port(port)
                group.add_to_canvas()
            
            port.add_to_canvas()
            return
        
        for group in self.groups:
            if group.group_id == port.group_id:
                group.rename_port(port)
                port.change_canvas_properties()
                break
    
    def add_connection(self, port_out_name: str, port_in_name: str):
        port_out = self.get_port_from_name(port_out_name)
        port_in = self.get_port_from_name(port_in_name)
        
        if port_out is None or port_in is None:
            return
        
        for connection in self.connections:
            if (connection.port_out == port_out
                    and connection.port_in == port_in):
                return
        
        connection = Connection(self._next_connection_id, port_out, port_in)
        self._next_connection_id += 1
        self.connections.append(connection)
        connection.add_to_canvas()
    
    def remove_connection(self, port_out_name: str, port_in_name: str):
        port_out = self.get_port_from_name(port_out_name)
        port_in = self.get_port_from_name(port_in_name)
        
        if port_out is None or port_in is None:
            return
        
        for connection in self.connections:
            if (connection.port_out == port_out
                    and connection.port_in == port_in):
                self.connections.remove(connection)
                connection.remove_from_canvas()
                break
