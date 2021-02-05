
import liblo

PORT_MODE_OUTPUT = 0
PORT_MODE_INPUT = 1
PORT_MODE_NULL = 2

PORT_TYPE_AUDIO = 0
PORT_TYPE_MIDI = 1
PORT_TYPE_NULL = 2


class OscJackPatch(liblo.ServerThread):
    def __init__(self, port_list, connection_list):
        liblo.ServerThread.__init__(self)
        
        self.port_list = port_list
        self.connection_list = connection_list
        self.gui_list = []

    def get_port_name(self, port_type: int, port_id: int)->str:
        for port in self.port_list:
            if port.id == port_id:
                if port.type != port_type:
                    return ''
                return port.name
        
        return ''

    @liblo.make_method('/ray/patchbay/gui_announce', '')
    def gui_announce(self, path, args, types, src_addr):
        for port in self.port_list:
            self.send(src_addr, '/ray/gui/patchbay/add_port',
                      port.id, port.name, port.mode, port.type)

        for connection in self.connection_list:
            self.send(src_addr, '/ray/gui/patchbay/add_connection',
                      connection[0], connection[1])

        self.gui_list.append(src_addr)

    @liblo.make_method('/ray/patchbay/connect', 'iii')
    def connect_ports(self, path, args):
        port_type, port_out_id, port_in_id = args
        port_out_name = self.get_port_name(port_out_id)
        port_in_name = self.get_port_name(port_in_id)

        if not (port_out_name and port_in_name):
            return
            
        #connect here
    
    @liblo.make_method('/ray/patchbay/disconnect', 'iii')
    def remove_connection(self, path, args):
        port_type, port_out_id, port_in_id = args
        port_out_name = self.get_port_name(port_out_id)
        port_in_name = self.get_port_name(port_in_id)

        if not (port_out_name and port_in_name):
            return
        
        #disconnect here

    def sendGui(self, *args):
        for gui_addr in self.gui_list:
            self.send(gui_addr, *args)

    def port_added(self, port):
        self.sendGui('/ray/gui/patchbay/add_port',
                     port.id, port.name, port.mode, port.type)
    
    def port_renamed(self, port):
        self.sendGui('/ray/gui/patchbay/port_renamed',
                     port.id, port.name)
    
    def port_removed(self, port):
        self.sendGui('/ray/gui/patchbay/port_removed', port.id)
    
    def connection_added(self, connection):
        self.sendGui('/ray/gui/patchbay/connection_added',
                     connection[0], connection[1])    

    def connection_removed(self, connection):
        self.sendGui('/ray/gui/patchbay/connection_removed',
                     connection[0], connection[1])
    
