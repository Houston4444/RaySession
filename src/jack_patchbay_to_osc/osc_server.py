
#import liblo
from liblo import ServerThread, Address, make_method

import jacklib

PORT_MODE_OUTPUT = 0
PORT_MODE_INPUT = 1
PORT_MODE_NULL = 2

PORT_TYPE_AUDIO = 0
PORT_TYPE_MIDI = 1
PORT_TYPE_NULL = 2


class OscJackPatch(ServerThread):
    def __init__(self, jack_client, port_list, connection_list):
        ServerThread.__init__(self)
        
        self.jack_client = jack_client
        self.port_list = port_list
        self.connection_list = connection_list
        self.gui_list = []
        print('port:', self.port)
        
        for port in port_list:
            print('pp', port.name) 

    def get_port_name(self, port_type: int, port_id: int)->str:
        for port in self.port_list:
            if port.id == port_id:
                if port.type != port_type:
                    return ''
                return port.name
        
        return ''

    def add_gui(self, gui_url):
        gui_addr = Address(gui_url)
        if gui_addr is None:
            return

        self.send(gui_addr, '/ray/gui/patchbay_announce')

        for port in self.port_list:
            self.send(gui_addr, '/ray/gui/patchbay/add_port',
                      port.id, port.name, port.mode, port.type)

        for connection in self.connection_list:
            self.send(gui_addr, '/ray/gui/patchbay/add_connection',
                      connection[0], connection[1])

        self.gui_list.append(gui_addr)

    @make_method('/ray/patchbay/add_gui', 's')
    def add_gui_from_daemon(self, path, args, types, src_addr):
        self.add_gui(args[0])

    @make_method('/ray/patchbay/connect', 'ss')
    def connect_ports(self, path, args):
        port_out_name, port_in_name = args
        print('eofkefoef', args)
        #connect here
        jacklib.connect(self.jack_client, port_out_name, port_in_name)
    
    @make_method('/ray/patchbay/disconnect', 'ss')
    def remove_connection(self, path, args):
        port_out_name, port_in_name = args

        #disconnect here
        jacklib.disconnect(self.jack_client, port_out_name, port_in_name)

    @make_method(None, None)
    def unknown_message(self, path, args, types, src_addr):
        print('bahzde', args, types)

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
    
    def server_stopped(self):
        # here server is JACK (in future maybe pipewire)
        self.sendGui('/ray/gui/patchbay/server_stopped')
    
