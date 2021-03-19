
import sys
import time

from liblo import Server, Address, make_method

import jacklib


class OscJackPatch(Server):
    slow_wait_time = 0.020
    slow_wait_num = 50
    
    def __init__(self, main_object):
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
                        self._ray_patchbay_disconnect)
        self.add_method('/ray/patchbay/set_buffer_size', 'i',
                        self._ray_patchbay_set_buffersize)
        self.add_method('/ray/patchbay/refresh', '',
                        self._ray_patchbay_refresh)
        
        self.main_object = main_object
        self.jack_client = main_object.jack_client
        self.port_list = main_object.port_list
        self.connection_list = main_object.connection_list
        self.gui_list = []
        self._tmp_gui_url = ''
        self._terminate = False

    def set_tmp_gui_url(self, gui_url):
        self._tmp_gui_url = gui_url

    def set_jack_client(self, jack_client):
        self.jack_client = jack_client
    
    def _ray_patchbay_add_gui(self, path, args, types, src_addr):
        self.add_gui(args[0])

    def _ray_patchbay_gui_disannounce(self, path, args, types, src_addr):
        for gui_addr in self.gui_list:
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

    def _ray_patchbay_set_buffersize(self, path, args):
        buffer_size = args[0]
        self.main_object.set_buffer_size(buffer_size)

    def _ray_patchbay_refresh(self, path, args):
        self.main_object.refresh()

    def sendGui(self, *args):
        for gui_addr in self.gui_list:
            self.send(gui_addr, *args)

    def add_gui(self, gui_url):
        gui_addr = Address(gui_url)
        if gui_addr is None:
            return
        
        self.send(gui_addr, '/ray/gui/patchbay/announce',
                  int(self.main_object.jack_running),
                  self.main_object.samplerate,
                  self.main_object.buffer_size)

        #self.send(gui_addr, '/ray/gui/patchbay/big_packets', 0)
        n = 0

        for port in self.port_list:
            self.send(gui_addr, '/ray/gui/patchbay/port_added',
                      port.name, port.alias_1, port.alias_2,
                      port.type, port.flags, '')
            
            n += 1
            if n % self.slow_wait_num == 0:
                #self.send(gui_addr, '/ray/gui/patchbay/big_packets', 1)
                time.sleep(self.slow_wait_time)
                #self.send(gui_addr, '/ray/gui/patchbay/big_packets', 0)

        for connection in self.connection_list:
            self.send(gui_addr, '/ray/gui/patchbay/connection_added',
                      connection[0], connection[1])
            
            n += 1
            if n % self.slow_wait_num == 0:
                #self.send(gui_addr, '/ray/gui/patchbay/big_packets', 1)
                time.sleep(self.slow_wait_time)
                #self.send(gui_addr, '/ray/gui/patchbay/big_packets', 0)

        #self.send(gui_addr, '/ray/gui/patchbay/big_packets', 1)
        
        self.gui_list.append(gui_addr)

    def server_restarted(self):
        self.sendGui('/ray/gui/patchbay/server_started')
        self.send_samplerate()
        self.send_buffersize()
        
        self.sendGui('/ray/gui/patchbay/big_packets', 0)
        # we need to slow the long process of messages sends
        # to prevent loss packets
        
        n = 0
        
        for port in self.port_list:
            self.sendGui('/ray/gui/patchbay/port_added',
                        port.name, port.alias_1, port.alias_2,
                        port.type, port.flags, '')
            
            n += 1
            
            if n % self.slow_wait_num == 0:
                self.sendGui('/ray/gui/patchbay/big_packets', 1)
                time.sleep(self.slow_wait_time)
                self.sendGui('/ray/gui/patchbay/big_packets', 0)

        for connection in self.connection_list:
            self.sendGui('/ray/gui/patchbay/connection_added',
                         connection[0], connection[1])
            
            n += 1
            
            if n % self.slow_wait_num == 0:
                self.sendGui('/ray/gui/patchbay/big_packets', 1)
                time.sleep(self.slow_wait_time)
                self.sendGui('/ray/gui/patchbay/big_packets', 0)
        
        self.sendGui('/ray/gui/patchbay/big_packets', 1)

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
    
    def send_dsp_load(self, dsp_load: int):
        self.sendGui('/ray/gui/patchbay/dsp_load', dsp_load)
    
    def send_one_xrun(self):
        self.sendGui('/ray/gui/patchbay/add_xrun')
    
    def send_buffersize(self):
        self.sendGui('/ray/gui/patchbay/buffer_size',
                     self.main_object.buffer_size)
    
    def send_samplerate(self):
        self.sendGui('/ray/gui/patchbay/sample_rate',
                     self.main_object.samplerate)
    
    def is_terminate(self):
        return self._terminate
    
    def send_server_lose(self):
        self.sendGui('/ray/gui/patchbay/server_lose')
        
        # In the case server is not responding
        # and gui has not yet been added to gui_list
        # but gui url stocked in self._tmp_gui_url
        if not self.gui_list and self._tmp_gui_url:
            try:
                addr = Address(self._tmp_gui_url)
            except:
                return
        
        self.send(addr, '/ray/gui/patchbay/server_lose')
