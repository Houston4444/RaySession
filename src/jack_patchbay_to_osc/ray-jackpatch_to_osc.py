#!/usr/bin/python3 -u

import os
import signal
import sys
import warnings

import jacklib
import osc_server
import threading
import time

PORT_TYPE_NULL = 0
PORT_TYPE_AUDIO = 1
PORT_TYPE_MIDI = 2

EXISTENCE_PATH = '/tmp/RaySession/patchbay_infos'





# Define a context manager to suppress stdout and stderr.
class suppress_stdout_stderr(object):
    '''
    A context manager for doing a "deep suppression" of stdout and stderr in 
    Python, i.e. will suppress all print, even if the print originates in a 
    compiled C/Fortran sub-function.
       This will not suppress raised exceptions, since exceptions are printed
    to stderr just before a script exits, and after the context manager has
    exited (at least, I think that is why it lets exceptions through).      

    '''
    def __init__(self):
        # Open a pair of null files
        self.null_fds =  [os.open(os.devnull,os.O_RDWR) for x in range(2)]
        # Save the actual stdout (1) and stderr (2) file descriptors.
        self.save_fds = [os.dup(1), os.dup(2)]

    def __enter__(self):
        # Assign the null pointers to stdout and stderr.
        os.dup2(self.null_fds[0],1)
        os.dup2(self.null_fds[1],2)

    def __exit__(self, *_):
        # Re-assign the real stdout/stderr back to (1) and (2)
        os.dup2(self.save_fds[0],1)
        os.dup2(self.save_fds[1],2)
        # Close all file descriptors
        for fd in self.null_fds + self.save_fds:
            os.close(fd)
            

class JackPort:
    id = 0
    name = ''
    type = PORT_TYPE_NULL
    flags = 0
    alias_1 = ''
    alias_2 = ''
    
    def __init__(self, port_name:str, jack_client):
        self.name = port_name
        port_ptr = jacklib.port_by_name(jack_client, port_name)
        self.flags = jacklib.port_flags(port_ptr)

        port_type_str = str(jacklib.port_type(port_ptr), encoding="utf-8")
        if port_type_str == jacklib.JACK_DEFAULT_AUDIO_TYPE:
            self.type = PORT_TYPE_AUDIO
        elif port_type_str == jacklib.JACK_DEFAULT_MIDI_TYPE:
            self.type = PORT_TYPE_MIDI
        
        ret, alias_1, alias_2 = jacklib.port_get_aliases(port_ptr)
        if ret:
            self.alias_1 = alias_1
            self.alias_2 = alias_2


class MainObject:
    port_list = []
    connection_list = []
    jack_running = False
    osc_server = None
    terminate = False
    jack_client = None
    samplerate = 48000
    buffer_size = 1024
    
    def __init__(self):
        self.last_sent_dsp_load = 0
        self.max_dsp_since_last_sent = 0.00
        self._waiting_jack_client_open = True
        
        print('sdgkjgj')
        self.osc_server = osc_server.OscJackPatch(self)
        print('sdlkfjjffjc')
        self.write_existence_file(self.osc_server.port)
        
        self.jack_waiter_thread = threading.Thread(
            target=self.check_jack_client_responding)
        self.jack_waiter_thread.start()
        self.start_jack_client()
        print('sldkxkxkxxkx')
    
    @staticmethod
    def c_char_p_p_to_list(c_char_p_p):
        i = 0
        return_list = []

        if not c_char_p_p:
            return return_list

        while True:
            new_char_p = c_char_p_p[i]
            if new_char_p:
                return_list.append(str(new_char_p, encoding="utf-8"))
                i += 1
            else:
                break

        jacklib.free(c_char_p_p)
        return return_list
    
    @staticmethod
    def write_existence_file(port: int):
        try:
            file = open(EXISTENCE_PATH, 'w')
        except PermissionError:
            sys.stderr.write(
                'ray-patchbay_to_osc: Error, no permission for existence file\n')
            sys.exit(1)

        contents = 'pid:%i\n' % os.getpid()
        contents += 'port:%i\n' % port

        file.write(contents)
        file.close()
    
    @staticmethod
    def remove_existence_file():
        if not os.path.exists(EXISTENCE_PATH):
            return 

        try:
            os.remove(EXISTENCE_PATH)
        except PermissionError:
            sys.stderr.write(
                'ray-patchbay_to_osc: Error, unable to remove %s\n'
                % EXISTENCE_PATH)
    
    @classmethod
    def signal_handler(cls, sig: int, frame):
        if sig in (signal.SIGINT, signal.SIGTERM):
            cls.terminate = True
    
    def add_gui(self, gui_url: str):
        self.osc_server.add_gui(gui_url)
    
    def check_jack_client_responding(self):
        print('decoaldlek')
        for i in range(10):
            print('dkfxjxkxkxk', i, self._waiting_jack_client_open)
            time.sleep(0.500)
            if not self._waiting_jack_client_open:
                break
        else:
            print('serveur perdu')
            self.osc_server.sendGui('/ray/gui/patchbay/server_lose')
            self.remove_existence_file()
            os.kill(os.getpid(), signal.SIGKILL)
    
    def refresh(self):
        if self.jack_running:
            self.get_all_ports_and_connections()
            self.osc_server.server_restarted()
    
    def remember_dsp_load(self):
        self.max_dsp_since_last_sent = max(
            self.max_dsp_since_last_sent,
            jacklib.cpu_load(self.jack_client))
        
    def send_dsp_load(self):
        current_dsp = int(self.max_dsp_since_last_sent + 0.5)
        if current_dsp != self.last_sent_dsp_load:
            self.osc_server.send_dsp_load(current_dsp)
            self.last_sent_dsp_load = current_dsp
        self.max_dsp_since_last_sent = 0.00
    
    def start_loop(self):
        n = 0

        while True:
            self.osc_server.recv(50)
            
            if self.is_terminate():
                break

            if self.jack_running:
                if n % 4 == 0:
                    self.remember_dsp_load()
                if n % 20 == 0:
                    self.send_dsp_load()

            else:
                if n % 10 == 0:
                    self.start_jack_client()
            n += 1
    
    def exit(self):
        if self.jack_running:
            jacklib.deactivate(self.jack_client)
            jacklib.client_close(self.jack_client)
        self.remove_existence_file()
        del self.osc_server
    
    def start_jack_client(self):
        self._waiting_jack_client_open = True
        
        #with suppress_stdout_stderr():
        self.jack_client = jacklib.client_open(
            "ray-patch_to_osc",
            jacklib.JackNoStartServer | jacklib.JackSessionID,
            None)

        if self.jack_client:
            self.jack_running = True
            self.set_registrations()
            self.get_all_ports_and_connections()
            self.osc_server.set_jack_client(self.jack_client)
            self.samplerate = jacklib.get_sample_rate(self.jack_client)
            self.buffer_size = jacklib.get_buffer_size(self.jack_client)
            self.osc_server.server_restarted()
        else:
            self.jack_running = False
        
        self._waiting_jack_client_open = False

    def is_terminate(self)->bool:
        if self.terminate or self.osc_server.is_terminate():
            return True
        
        return False
    
    def set_registrations(self):
        if not self.jack_client:
            return
        
        jacklib.set_port_registration_callback(
            self.jack_client, self.jack_port_registration_callback, None)
        jacklib.set_port_connect_callback(
            self.jack_client, self.jack_port_connect_callback, None)
        jacklib.set_port_rename_callback(
            self.jack_client, self.jack_port_rename_callback, None)
        jacklib.set_xrun_callback(
            self.jack_client, self.jack_xrun_callback, None)
        jacklib.set_buffer_size_callback(
            self.jack_client, self.jack_buffer_size_callback, None)
        jacklib.set_sample_rate_callback(
            self.jack_client, self.jack_sample_rate_callback, None)
        jacklib.on_shutdown(
            self.jack_client, self.jack_shutdown_callback, None)
        jacklib.activate(self.jack_client)
    
    def get_all_ports_and_connections(self):
        self.port_list.clear()
        self.connection_list.clear()

        #get all currents Jack ports and connections
        port_name_list = self.c_char_p_p_to_list(
            jacklib.get_ports(self.jack_client, "", "", 0))
        
        for port_name in port_name_list:
            jport = JackPort(port_name, self.jack_client)
            self.port_list.append(jport)

            if jport.flags & jacklib.JackPortIsInput:
                continue

            port_ptr = jacklib.port_by_name(self.jack_client, jport.name)
            
            # this port is output, list its connections
            port_connection_names = self.c_char_p_p_to_list(
                jacklib.port_get_all_connections(self.jack_client, port_ptr))

            for port_con_name in port_connection_names:
                self.connection_list.append((jport.name, port_con_name))
    
    def jack_shutdown_callback(self, arg=None)->int:
        self.jack_running = False
        self.port_list.clear()
        self.connection_list.clear()
        self.osc_server.server_stopped()
        return 0

    def jack_xrun_callback(self, arg=None)->int:
        self.osc_server.send_one_xrun()
        return 0

    def jack_sample_rate_callback(self, samplerate, arg=None)->int:
        self.samplerate = samplerate
        self.osc_server.send_samplerate()
        return 0

    def jack_buffer_size_callback(self, buffer_size, arg=None)->int:
        self.buffer_size = buffer_size
        self.osc_server.send_buffersize()
        return 0

    def jack_port_registration_callback(self, port_id: int, register: bool,
                                        arg=None)->int:
        if not self.jack_client:
            return 0
        
        port_ptr = jacklib.port_by_id(self.jack_client, port_id)
        port_name = str(jacklib.port_name(port_ptr), encoding="utf-8")
        
        if register:
            jport = JackPort(port_name, self.jack_client)
            self.port_list.append(jport)
            self.osc_server.port_added(jport)
        else:
            for jport in self.port_list:
                if jport.name == port_name:
                    self.port_list.remove(jport)
                    self.osc_server.port_removed(jport)
                    break
        return 0
    
    def jack_port_rename_callback(self, port_id: int, old_name: str,
                                  new_name: str, arg=None)->int:
        for jport in self.port_list:
            if jport.name == str(old_name, encoding="utf-8"):
                ex_name = jport.name
                jport.name = str(new_name, encoding="utf-8")
                self.osc_server.port_renamed(jport, ex_name)
                break
        return 0

    def jack_port_connect_callback(self, port_id_A: int, port_id_B: int,
                                   connect_yesno: bool, arg=None)->int:
        #if not self.jack_client:
            #return 0
        
        port_ptr_A = jacklib.port_by_id(self.jack_client, port_id_A)
        port_ptr_B = jacklib.port_by_id(self.jack_client, port_id_B)

        port_str_A = str(jacklib.port_name(port_ptr_A), encoding="utf-8")
        port_str_B = str(jacklib.port_name(port_ptr_B), encoding="utf-8")

        connection = (port_str_A, port_str_B)

        if connect_yesno:
            self.connection_list.append(connection)
            self.osc_server.connection_added(connection)
        else:
            if connection in self.connection_list:
                self.connection_list.remove(connection)
                self.osc_server.connection_removed(connection)

        return 0
    
    def set_buffer_size(self, buffer_size: int):
        jacklib.set_buffer_size(self.jack_client, buffer_size)


def main_loop():
    print('ekfek')
    main_object = MainObject()
    print('mlsdfkdl')
    if len(sys.argv) > 1:
        for gui_url in sys.argv[1:]:
            main_object.add_gui(gui_url)
    
    main_object.start_loop()
    main_object.exit()

if __name__ == '__main__':
    # prevent deprecation warnings python messages
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    
    signal.signal(signal.SIGINT, MainObject.signal_handler)
    signal.signal(signal.SIGTERM, MainObject.signal_handler)
    
    main_loop()
