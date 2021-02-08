
import sys
from liblo import Server, Address, make_method

import jacklib


class OscJackPatch(Server):
    def __init__(self, jack_client, port_list, connection_list):
        Server.__init__(self)
        self.add_method('/ray/patchbay/add_gui', 's',
                        self._ray_patchbay_add_gui)
        self.add_method('/ray/patchbay/gui_disannounce', '',
                        self._ray_patchbay_gui_disannounce)
        self.add_method('ray/patchbay/port/set_alias', 'sis',
                        self._ray_patchbay_port_set_alias)
        self.add_method('/ray/patchbay/connect', 'ss',
                        self._ray_patchbay_connect)
        self.add_method('/ray/patchbay/disconnect', 'ss',
                        self._ray_patchbay_connect)
        
        self.jack_client = jack_client
        self.port_list = port_list
        self.connection_list = connection_list
        self.gui_list = []
        self._terminate = False

    def _ray_patchbay_add_gui(self, path, args, types, src_addr):
        self.add_gui(args[0])

    def _ray_patchbay_gui_disannounce(self, path, args, types, src_addr):
        print('guiii diss')
        for gui_addr in self.gui_list:
            print('didi', gui_addr.url, src_addr.url)
            if gui_addr.url == src_addr.url:
                # possible because we break the loop
                self.gui_list.remove(gui_addr)
                break
        
        if not self.gui_list:
            # no more GUI connected, no reason to exists anymore
            self._terminate = True

    def _ray_patchbay_port_set_alias(self, path, args, types, src_addr):
        port_name, alias_num, alias = args
        for port in self.port_list:
            if port.name == port_name:
                # TODO
                # better would be to use jacklib.port_set_alias(port, alias)
                # but this is very confuse
                # 2 aliases possibles, but only one arg to this method (after port).
                if alias_num == 1:
                    port.alias_1 = alias
                elif alias_num == 2:
                    port.alias_2 = alias
                break

    def _ray_patchbay_connect(self, path, args):
        port_out_name, port_in_name = args
        #connect here
        jacklib.connect(self.jack_client, port_out_name, port_in_name)
    
    def _ray_patchbay_disconnect(self, path, args):
        port_out_name, port_in_name = args

        #disconnect here
        jacklib.disconnect(self.jack_client, port_out_name, port_in_name)

    def sendGui(self, *args):
        for gui_addr in self.gui_list:
            self.send(gui_addr, *args)

    def add_gui(self, gui_url):
        gui_addr = Address(gui_url)
        if gui_addr is None:
            return

        self.send(gui_addr, '/ray/gui/patchbay/announce')

        for port in self.port_list:
            self.send(gui_addr, '/ray/gui/patchbay/port_added',
                      port.name, port.alias_1, port.alias_2,
                      port.type, port.flags, '')

        for connection in self.connection_list:
            self.send(gui_addr, '/ray/gui/patchbay/connection_added',
                      connection[0], connection[1])

        self.gui_list.append(gui_addr)

    def port_added(self, port):
        self.sendGui('/ray/gui/patchbay/port_added',
                     port.name, port.alias_1, port.alias_2,
                     port.type, port.flags, '') 

    def port_renamed(self, port, ex_name):
        self.sendGui('/ray/gui/patchbay/port_renamed',
                     ex_name, port.name)
    
    def port_removed(self, port):
        self.sendGui('/ray/gui/patchbay/port_removed', port.name)
    
    def connection_added(self, connection):
        self.sendGui('/ray/gui/patchbay/connection_added',
                     connection[0], connection[1])    

    def connection_removed(self, connection):
        self.sendGui('/ray/gui/patchbay/connection_removed',
                     connection[0], connection[1])
    
    def server_stopped(self):
        # here server is JACK (in future maybe pipewire)
        self.sendGui('/ray/gui/patchbay/server_stopped')
        self._terminate = True
        
    def is_terminate(self):
        return self._terminate
    
