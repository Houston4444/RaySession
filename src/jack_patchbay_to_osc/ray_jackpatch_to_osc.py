#!/usr/bin/python3 -u

from dataclasses import dataclass
from enum import IntEnum
import os
import signal
import sys
import warnings

import osc_server
import threading
import time

import jacklib
from jacklib.helpers import c_char_p_p_to_list, voidptr2str

PORT_TYPE_NULL = 0
PORT_TYPE_AUDIO = 1
PORT_TYPE_MIDI = 2

EXISTENCE_PATH = '/tmp/RaySession/patchbay_daemons/'




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
            

@dataclass
class TransportPosition:
    frame: int
    rolling: bool
    valid_bbt: bool
    bar: int
    beat: int
    tick: int
    beats_per_minutes: float


class TransportWanted(IntEnum):
    NO = 0         # do not send any transport info
    STATE_ONLY = 1 # send info only when play/pause changed
    FULL = 2       # send all Transport infos


class JackPort:
    id = 0
    name = ''
    type = PORT_TYPE_NULL
    flags = 0
    alias_1 = ''
    alias_2 = ''
    order = None
    uuid = 0
    
    def __init__(self, port_name:str, jack_client, port_ptr=None):
        # In some cases, port could has just been renamed
        # then, jacklib.port_by_name() fail.
        # that is why, port_ptr can be sent as argument here
        self.name = port_name
        if port_ptr is None:
            port_ptr = jacklib.port_by_name(jack_client, port_name)
        self.flags = jacklib.port_flags(port_ptr)
        self.uuid = jacklib.port_uuid(port_ptr)

        port_type_str = jacklib.port_type(port_ptr)
        if port_type_str == jacklib.JACK_DEFAULT_AUDIO_TYPE:
            self.type = PORT_TYPE_AUDIO
        elif port_type_str == jacklib.JACK_DEFAULT_MIDI_TYPE:
            self.type = PORT_TYPE_MIDI
            
        order_prop = jacklib.get_property(self.uuid,
                                          jacklib.JACK_METADATA_ORDER)

        ret, alias_1, alias_2 = jacklib.port_get_aliases(port_ptr)
        if ret:
            self.alias_1 = alias_1
            self.alias_2 = alias_2

    def __lt__(self, other: 'JackPort'):
        return self.uuid < other.uuid


class MainObject:
    port_list = list[JackPort]()
    connection_list = list[tuple[str]]()
    metadata_list = list[dict]()
    client_list = list[dict]()
    client_names_queue = list[str]()
    jack_running = False
    osc_server = None
    terminate = False
    jack_client = None
    samplerate = 48000
    buffer_size = 1024
    
    dsp_wanted = True
    transport_wanted = TransportWanted.FULL
    
    def __init__(self, daemon_port: str, gui_url: str):
        self._daemon_port = daemon_port
        self.last_sent_dsp_load = 0
        self.max_dsp_since_last_sent = 0.00
        self._waiting_jack_client_open = True
        self.last_transport_pos = TransportPosition(0, False, False, 0, 0, 0, 0.0)

        self.osc_server = osc_server.OscJackPatch(self)
        self.osc_server.set_tmp_gui_url(gui_url)
        self.write_existence_file()
        self.start_jack_client()
    
    @staticmethod
    def get_metadata_value_str(prop: jacklib.Property) -> str:
        value = prop.value
        if isinstance(value, bytes):
            return value.decode()
        elif isinstance(value, str):
            return value
        else:
            try:
                value = str(value)
            except:
                return ''
        return value
    
    def write_existence_file(self):
        if not os.path.isdir(EXISTENCE_PATH):
            os.makedirs(EXISTENCE_PATH)
        
        try:
            file = open(EXISTENCE_PATH + self._daemon_port, 'w')
        except PermissionError:
            sys.stderr.write(
                'ray-patchbay_to_osc: Error, no permission for existence file\n')
            sys.exit(1)

        contents = 'pid:%i\n' % os.getpid()
        contents += 'port:%i\n' % self.osc_server.port

        file.write(contents)
        file.close()
    
    def remove_existence_file(self):
        if not os.path.exists(EXISTENCE_PATH + self._daemon_port):
            return 

        try:
            os.remove(EXISTENCE_PATH + self._daemon_port)
        except PermissionError:
            sys.stderr.write(
                'ray-patchbay_to_osc: Error, unable to remove %s\n'
                % EXISTENCE_PATH + self._daemon_port)
    
    @classmethod
    def signal_handler(cls, sig: int, frame):
        if sig in (signal.SIGINT, signal.SIGTERM):
            cls.terminate = True
            
    def eat_client_names_queue(self):
        while self.client_names_queue:
            client_name = self.client_names_queue.pop(0)
            b_uuid = jacklib.get_uuid_for_client_name(self.jack_client, client_name)

            # convert bytes uuid to int
            uuid = 0
            if isinstance(b_uuid, bytes):
                str_uuid = b_uuid.decode()
                if str_uuid.isdigit():
                    uuid = int(str_uuid)

            if not uuid:
                continue

            for client_dict in self.client_list:
                if client_dict['name'] == client_name:
                    client_dict['uuid'] = uuid
                    break
            else:
                self.client_list.append({'name': client_name, 'uuid': uuid})
    
    def add_gui(self, gui_url: str):
        self.osc_server.add_gui(gui_url)
    
    def check_jack_client_responding(self):
        for i in range(100): # JACK has 5s to answer
            time.sleep(0.050)

            if not self._waiting_jack_client_open:
                break
        else:
            # server never answer
            self.osc_server.send_server_lose()
            self.remove_existence_file()
            
            # JACK is not responding at all
            # probably it is started but totally bugged
            # finally kill this program from system
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
    
    def set_transport_wanted(self, transport_wanted: int):
        try:
            self.transport_wanted = TransportWanted(transport_wanted)
        except:
            self.transport_wanted = TransportWanted.FULL

    def _send_transport_pos(self):
        if not self.jack_running:
            return
        
        pos = jacklib.jack_position_t()
        pos.valid = 0

        state = jacklib.transport_query(self.jack_client, jacklib.pointer(pos))
        
        if (self.transport_wanted is TransportWanted.STATE_ONLY
                and bool(state) == self.last_transport_pos.rolling):
            return

        transport_position = TransportPosition(
            int(pos.frame),
            bool(state),
            bool(pos.valid & jacklib.JackPositionBBT),
            int(pos.bar),
            int(pos.beat),
            int(pos.tick),
            float(pos.beats_per_minute))
        
        if transport_position == self.last_transport_pos:
            return
        
        self.last_transport_pos = transport_position
        self.osc_server.send_transport_position(transport_position)
    
    def start_loop(self):
        n = 0

        while True:
            self.osc_server.recv(50)
            
            if self.is_terminate():
                break

            if self.jack_running:
                if n % 4 == 0:
                    self.remember_dsp_load()
                    if self.dsp_wanted and n % 20 == 0:
                        self.send_dsp_load()
                
                self.eat_client_names_queue()
                if self.transport_wanted is not TransportWanted.NO:
                    self._send_transport_pos()

            else:
                if n % 10 == 0:
                    self.start_jack_client()
            n += 1
            
            # for faster modulos
            if n == 20:
                n = 0
                
    def exit(self):
        if self.jack_running:
            jacklib.deactivate(self.jack_client)
            jacklib.client_close(self.jack_client)
        self.remove_existence_file()
        del self.osc_server
    
    def start_jack_client(self):
        self._waiting_jack_client_open = True
        
        # Sometimes JACK never registers the client
        # and never answers. This thread will allow to exit
        # if JACK didn't answer 5 seconds after register ask
        jack_waiter_thread = threading.Thread(
            target=self.check_jack_client_responding)
        jack_waiter_thread.start()

        with suppress_stdout_stderr():
            self.jack_client = jacklib.client_open(
                "ray-patch_to_osc",
                jacklib.JackNoStartServer | jacklib.JackSessionID,
                None)

        self._waiting_jack_client_open = False
        ## Some problems happens to the JACK server sometimes without it
        #time.sleep(0.030)

        jack_waiter_thread.join()

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

    def is_terminate(self)->bool:
        if self.terminate or self.osc_server.is_terminate():
            return True
        
        return False
    
    def set_registrations(self):
        if not self.jack_client:
            return
        
        jacklib.set_client_registration_callback(
            self.jack_client, self.jack_client_registration_callback, None)
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
        jacklib.set_property_change_callback(
            self.jack_client, self.jack_properties_change_callback, None)
        jacklib.on_shutdown(
            self.jack_client, self.jack_shutdown_callback, None)
        jacklib.activate(self.jack_client)
    
    def get_all_ports_and_connections(self):
        self.port_list.clear()
        self.connection_list.clear()
        self.metadata_list.clear()

        #get all currents Jack ports and connections
        port_name_list = c_char_p_p_to_list(
            jacklib.get_ports(self.jack_client, "", "", 0))
        
        client_names = []
        
        for port_name in port_name_list:
            port_ptr = jacklib.port_by_name(self.jack_client, port_name)
            jport = JackPort(port_name, self.jack_client)
            self.port_list.append(jport)
            
            client_name = port_name.partition(':')[0]
            if not client_name in client_names:
                client_names.append(client_name)

            # get port metadatas
            for key in (jacklib.JACK_METADATA_CONNECTED,
                        jacklib.JACK_METADATA_ORDER,
                        jacklib.JACK_METADATA_PORT_GROUP,
                        jacklib.JACK_METADATA_PRETTY_NAME):
                prop = jacklib.get_property(jport.uuid, key)
                if prop is None:
                    continue

                value = self.get_metadata_value_str(prop)
                self.metadata_list.append(
                    {'uuid': jport.uuid,
                     'key': key,
                     'value': value})

            if jport.flags & jacklib.JackPortIsInput:
                continue

            port_ptr = jacklib.port_by_name(self.jack_client, jport.name)
            
            # this port is output, list its connections
            port_connection_names = tuple(
                jacklib.port_get_all_connections(self.jack_client, port_ptr))

            for port_con_name in port_connection_names:
                self.connection_list.append((jport.name, port_con_name))
        
        for client_name in client_names:
            uuid = jacklib.get_uuid_for_client_name(self.jack_client, client_name)
            if not uuid:
                continue

            self.client_list.append({'name': client_name, 'uuid': int(uuid)})
            
            # we only look for icon_name now, but in the future other client
            # metadatas could be enabled
            for key in (jacklib.JACK_METADATA_ICON_NAME,):
                prop = jacklib.get_property(int(uuid), jacklib.JACK_METADATA_ICON_NAME)
                if prop is None:
                    continue
                value = self.get_metadata_value_str(prop)
                self.metadata_list.append(
                    {'uuid': int(uuid),
                    'key': key,
                    'value': value})
    
    def jack_shutdown_callback(self, arg=None)->int:
        self.jack_running = False
        self.port_list.clear()
        self.connection_list.clear()
        self.osc_server.server_stopped()
        return 0

    def jack_xrun_callback(self, arg=None)->int:
        self.osc_server.send_one_xrun()
        return 0

    def jack_sample_rate_callback(self, samplerate, arg=None) -> int:
        self.samplerate = samplerate
        self.osc_server.send_samplerate()
        return 0

    def jack_buffer_size_callback(self, buffer_size, arg=None) -> int:
        self.buffer_size = buffer_size
        self.osc_server.send_buffersize()
        return 0

    def jack_client_registration_callback(self, client_name: bytes,
                                          register: int, arg=None) -> int:
        client_name = client_name.decode()
        self.client_names_queue.append(client_name)
        return 0
        
    def jack_port_registration_callback(self, port_id: int, register: bool,
                                        arg=None) -> int:
        if not self.jack_client:
            return 0
        
        port_ptr = jacklib.port_by_id(self.jack_client, port_id)
        port_name = jacklib.port_name(port_ptr)
        
        if register:
            jport = JackPort(port_name, self.jack_client, port_ptr)
            self.port_list.append(jport)
            self.osc_server.port_added(jport)
        else:
            for jport in self.port_list:
                if jport.name == port_name:
                    self.port_list.remove(jport)
                    self.osc_server.port_removed(jport)
                    break
        return 0
    
    def jack_port_rename_callback(self, port_id: int, old_name: bytes,
                                  new_name: bytes, arg=None)->int:
        for jport in self.port_list:
            if jport.name == str(old_name.decode()):
                ex_name = jport.name
                jport.name = str(new_name.decode())
                self.osc_server.port_renamed(jport, ex_name)
                break
        return 0
    
    def jack_port_connect_callback(self, port_id_A: int, port_id_B: int,
                                   connect_yesno: bool, arg=None)->int:
        port_ptr_A = jacklib.port_by_id(self.jack_client, port_id_A)
        port_ptr_B = jacklib.port_by_id(self.jack_client, port_id_B)

        port_str_A = jacklib.port_name(port_ptr_A)
        port_str_B = jacklib.port_name(port_ptr_B)

        connection = (port_str_A, port_str_B)

        if connect_yesno:
            self.connection_list.append(connection)
            self.osc_server.connection_added(connection)
        elif connection in self.connection_list:
            self.connection_list.remove(connection)
            self.osc_server.connection_removed(connection)

        return 0

    def jack_properties_change_callback(self, uuid: int, name: bytes,
                                        type_: int, arg=None)->int:
        if name is not None:
            name = name.decode()
        
        value = ''

        if name and type_ != jacklib.PropertyDeleted:
            prop = jacklib.get_property(uuid, name)
            if prop is None:
                return 0
            
            value = self.get_metadata_value_str(prop)
        
        for metadata in self.metadata_list:
            if metadata['uuid'] == uuid and metadata['key'] == name:
                metadata['value'] = value
                break
        else:
            self.metadata_list.append(
                {'uuid': uuid, 'key': name, 'value': value})
        
        self.osc_server.metadata_updated(uuid, name, value)

        return 0
    
    def set_buffer_size(self, buffer_size: int):
        jacklib.set_buffer_size(self.jack_client, buffer_size)

    def set_metadata(self, uuid: int, key: str, value: str):
        jacklib.set_property(uuid, key, value, 'text/plain', jacklib.ENCODING)

    def transport_play(self, play: bool):
        if play:
            jacklib.transport_start(self.jack_client)
        else:
            jacklib.transport_stop(self.jack_client)
            
    def transport_stop(self):
        jacklib.transport_stop(self.jack_client)
        jacklib.transport_locate(self.jack_client, 0)
        
    def transport_relocate(self, frame: int):
        jacklib.transport_locate(self.jack_client, frame)


def main_process():
    args = sys.argv.copy()
    daemon_port = ''
    gui_url = ''

    if args:
        this_exec = args.pop(0)

    if args:
        daemon_port = args.pop(0)
    
    if args:
        gui_url = args[0]
    
    main_object = MainObject(daemon_port, gui_url)

    for gui_url in args:
        main_object.add_gui(gui_url)
    
    main_object.start_loop()
    main_object.exit()


if __name__ == '__main__':
    # prevent deprecation warnings python messages
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    
    signal.signal(signal.SIGINT, MainObject.signal_handler)
    signal.signal(signal.SIGTERM, MainObject.signal_handler)
    
    main_process()
