
import sys
import time
#import pickle
import tempfile
import socket
import json
import subprocess

from liblo import Server, Address, make_method

import jacklib


### Code copied from shared/ray.py
### we don't import ray.py here, because this executable is Qt free
### TODO : make a miniray.py with only Qt free code

class Machine192:
    ip = ''
    read_done = False
    
    @staticmethod
    def read()->str:
        try:
            ips = subprocess.check_output(
                ['ip', 'route', 'get', '1']).decode()
            ip_line = ips.partition('\n')[0]
            ip_end = ip_line.rpartition('src ')[2]
            ip = ip_end.partition(' ')[0]

        except BaseException:
            try:
                ips = subprocess.check_output(['hostname', '-I']).decode()
                ip = ips.split(' ')[0]
            except BaseException:
                return ''

        if ip.count('.') != 3:
            return ''
        
        return ip
    
    @classmethod
    def get(cls)->str:
        if cls.read_done:
            return cls.ip
        
        cls.ip = cls.read()
        cls.read_done = True

        return cls.ip

def areOnSameMachine(url1, url2):
    if url1 == url2:
        return True

    try:
        address1 = Address(url1)
        address2 = Address(url2)
    except BaseException:
        return False

    if address1.hostname == address2.hostname:
        return True

    try:
        if (socket.gethostbyname(address1.hostname)
                    in ('127.0.0.1', '127.0.1.1')
                and socket.gethostbyname(address2.hostname)
                    in ('127.0.0.1', '127.0.1.1')):
            return True

        if socket.gethostbyaddr(
                address1.hostname) == socket.gethostbyaddr(
                address2.hostname):
            return True

    except BaseException:
        try:
            ip = Machine192.get()

            if ip not in (address1.hostname, address2.hostname):
                return False

            try:
                if socket.gethostbyname(
                        address1.hostname) in (
                        '127.0.0.1',
                        '127.0.1.1'):
                    if address2.hostname == ip:
                        return True
            except BaseException:
                if socket.gethostbyname(
                        address2.hostname) in (
                        '127.0.0.1',
                        '127.0.1.1'):
                    if address1.hostname == ip:
                        return True

        except BaseException:
            return False

        return False

    return False


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
        self.add_method('/ray/patchbay/set_metadata', 'hss',
                        self._ray_patchbay_set_metadata)
        
        self.main_object = main_object
        self.jack_client = main_object.jack_client
        self.port_list = main_object.port_list
        self.connection_list = main_object.connection_list
        self.metadata_list = main_object.metadata_list
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

    def _ray_patchbay_set_metadata(self, path, args):
        uuid, key, value = args
        self.main_object.set_metadata(uuid, key, value)

    def send_gui(self, *args):
        for gui_addr in self.gui_list:
            self.send(gui_addr, *args)

    def multi_send(self, src_addr_list, *args):
        for src_addr in src_addr_list:
            self.send(src_addr, *args)

    def send_local_data(self, src_addr_list):
        # at invitation, if gui is on the same machine
        # it's prefferable to save all data in /tmp
        # Indeed, to prevent OSC packet loses
        # this daemon will send a lot of OSC messages not too fast
        # so here, it is faster, and prevent OSC saturation.
        # json format (and not binary with pickle) is choosen
        # this way, code language of the GUI is not a blocker
        patchbay_data = {'ports': [], 'connections': [], 'metadatas': []}
        for port in self.port_list:
            port_dict = {'name': port.name, 'type': port.type,
                         'flags': port.flags, 'uuid': port.uuid}
            patchbay_data['ports'].append(port_dict)
        
        for connection in self.connection_list:
            conn_dict = {'port_out_name': connection[0],
                         'port_in_name': connection[1]}
            patchbay_data['connections'].append(conn_dict)

        for metadata in self.metadata_list:
            patchbay_data['metadatas'].append(metadata)

        for src_addr in src_addr_list:
            # tmp file is deleted by the gui itself once read
            # so there is one tmp file per local GUI
            file = tempfile.NamedTemporaryFile(delete=False, mode='w+')
            json.dump(patchbay_data, file)
            file.close()

            self.send(src_addr, '/ray/gui/patchbay/fast_temp_file_running',
                    file.name)

    def send_distant_data(self, src_addr_list):
        # we need to slow the long process of messages sends
        # to prevent loss packets
        self.multi_send(src_addr_list, '/ray/gui/patchbay/big_packets', 0)
        n = 0
        increment = len(src_addr_list)

        for port in self.port_list:
            self.multi_send(src_addr_list, '/ray/gui/patchbay/port_added',
                            port.name, port.type, port.flags, port.uuid)
            
            n += increment
            if n % self.slow_wait_num < increment:
                self.multi_send(src_addr_list,
                                '/ray/gui/patchbay/big_packets', 1)
                time.sleep(self.slow_wait_time)
                self.multi_send(src_addr_list,
                                '/ray/gui/patchbay/big_packets', 0)

        for connection in self.connection_list:
            self.multi_send(src_addr_list,
                            '/ray/gui/patchbay/connection_added',
                            connection[0], connection[1])
            
            n += increment
            if n % self.slow_wait_num < increment:
                self.multi_send(src_addr_list,
                                '/ray/gui/patchbay/big_packets', 1)
                time.sleep(self.slow_wait_time)
                self.multi_send(src_addr_list,
                                '/ray/gui/patchbay/big_packets', 0)
                
        for metadata in self.metadata_list:
            self.multi_send(src_addr_list,
                            '/ray/gui/patchbay/metadata_updated',
                            metadata['uuid'], metadata['key'],
                            metadata['value'])
            
            n += increment
            if n % self.slow_wait_num < increment:
                self.multi_send(src_addr_list,
                                '/ray/gui/patchbay/big_packets', 1)
                time.sleep(self.slow_wait_time)
                self.multi_send(src_addr_list,
                                '/ray/gui/patchbay/big_packets', 0)

        self.multi_send(src_addr_list, '/ray/gui/patchbay/big_packets', 1)

    def add_gui(self, gui_url):
        gui_addr = Address(gui_url)
        if gui_addr is None:
            return
        
        self.send(gui_addr, '/ray/gui/patchbay/announce',
                  int(self.main_object.jack_running),
                  self.main_object.samplerate,
                  self.main_object.buffer_size)

        if areOnSameMachine(gui_url, self.url):
            self.send_local_data([gui_addr])
        else:
            self.send_distant_data([gui_addr])
        
        self.gui_list.append(gui_addr)

    def server_restarted(self):
        self.send_gui('/ray/gui/patchbay/server_started')
        self.send_samplerate()
        self.send_buffersize()
        
        local_guis = []
        distant_guis = []
        
        for gui_addr in self.gui_list:
            if areOnSameMachine(self.url, gui_addr.url):
                local_guis.append(gui_addr)
            else:
                distant_guis.append(gui_addr)
                
        if local_guis:
            self.send_local_data(local_guis)
        if distant_guis:
            self.send_distant_data(distant_guis)

    def port_added(self, port):
        self.send_gui('/ray/gui/patchbay/port_added',
                      port.name, port.type, port.flags, port.uuid) 

    def port_renamed(self, port, ex_name):
        self.send_gui('/ray/gui/patchbay/port_renamed', ex_name, port.name)
    
    def port_removed(self, port):
        self.send_gui('/ray/gui/patchbay/port_removed', port.name)
    
    def metadata_updated(self, uuid: int, key: str, value: str):
        self.send_gui('/ray/gui/patchbay/metadata_updated', uuid, key, value)
    
    def port_order_changed(self, port):
        if port.order is None:
            return

        self.send_gui('/ray/gui/patchbay/port_order_changed',
                      port.name, port.order)
    
    def connection_added(self, connection):
        self.send_gui('/ray/gui/patchbay/connection_added',
                     connection[0], connection[1])    

    def connection_removed(self, connection):
        self.send_gui('/ray/gui/patchbay/connection_removed',
                     connection[0], connection[1])
    
    def server_stopped(self):
        # here server is JACK (in future maybe pipewire)
        self.send_gui('/ray/gui/patchbay/server_stopped')
    
    def send_dsp_load(self, dsp_load: int):
        self.send_gui('/ray/gui/patchbay/dsp_load', dsp_load)
    
    def send_one_xrun(self):
        self.send_gui('/ray/gui/patchbay/add_xrun')
    
    def send_buffersize(self):
        self.send_gui('/ray/gui/patchbay/buffer_size',
                     self.main_object.buffer_size)
    
    def send_samplerate(self):
        self.send_gui('/ray/gui/patchbay/sample_rate',
                     self.main_object.samplerate)
    
    def is_terminate(self):
        return self._terminate
    
    def send_server_lose(self):
        self.send_gui('/ray/gui/patchbay/server_lose')
        
        # In the case server is not responding
        # and gui has not yet been added to gui_list
        # but gui url stocked in self._tmp_gui_url
        if not self.gui_list and self._tmp_gui_url:
            try:
                addr = Address(self._tmp_gui_url)
            except:
                return
        
        self.send(addr, '/ray/gui/patchbay/server_lose')
