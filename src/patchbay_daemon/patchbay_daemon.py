#!/usr/bin/python3 -u

# standard lib imports
from dataclasses import dataclass
from enum import IntEnum, Enum, auto
import os
import signal
import sys
from typing import Optional, TypeAlias
import warnings
import threading
import time
from pathlib import Path
import logging
import json
from queue import Queue

# third party imports
import jack
from osc_paths.ray.patchbay.monitor import CONNECTION_REMOVED

# imports from shared/
from proc_name import set_proc_name

# imports from HoustonPatchbay
from patshared import JackMetadatas, JackMetadata, PrettyNames, PrettyDiff

# local imports
from port_data import PortData, PortDataList
from osc_server import PatchbayDaemonServer
from alsa_lib_check import ALSA_LIB_OK
if ALSA_LIB_OK:
    from alsa_manager import AlsaManager


IS_INTERNAL = not Path(sys.path[0]).name == __name__
if IS_INTERNAL:
    _logger = logging.getLogger(__name__)
else:
    _logger = logging.getLogger()
    _log_handler = logging.StreamHandler()
    _log_handler.setFormatter(logging.Formatter(
        f"%(levelname)s:%(name)s - %(message)s"))
    _logger.addHandler(_log_handler)

PORT_TYPE_NULL = 0
PORT_TYPE_AUDIO = 1
PORT_TYPE_MIDI = 2

EXISTENCE_PATH = Path('/tmp/RaySession/patchbay_daemons')

JACK_CLIENT_NAME = 'ray-patch_dmn'
METADATA_LOCKER = 'ray-patch_dmn.locker'


# Define a context manager to suppress stdout and stderr.
class SuppressStdoutStderr(object):
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
        os.dup2(self.null_fds[0], 1)
        os.dup2(self.null_fds[1], 2)

    def __exit__(self, *_):
        # Re-assign the real stdout/stderr back to (1) and (2)
        os.dup2(self.save_fds[0], 1)
        os.dup2(self.save_fds[1], 2)
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
    NO = 0
    'do not send any transport info'
    
    STATE_ONLY = 1
    'send transport info only when play/pause changed'

    FULL = 2
    'send all transport infos'


class PatchEvent(Enum):
    CLIENT_ADDED = auto()
    CLIENT_REMOVED = auto()
    PORT_ADDED = auto()
    PORT_REMOVED = auto()
    PORT_RENAMED = auto()
    CONNECTION_ADDED = auto()
    CONNECTION_REMOVED = auto()
    METADATA_CHANGED = auto()


PatchEventArg: TypeAlias = str | tuple[str, str] | tuple[int, str, str]
    


class PrettyDiffChecker:
    def __init__(self, metadatas: JackMetadatas,
                 pretty_names: PrettyNames,
                 client_name_uuids: dict[str, int],
                 ports: PortDataList):
        self.metadatas = metadatas
        self.pretty_names = pretty_names
        self.client_name_uuids = client_name_uuids
        self.ports = ports
        
        self.clients_diff = dict[int, PrettyDiff]()
        self.ports_diff = dict[int, PrettyDiff]()
        self.pretty_diff = PrettyDiff.NO_DIFF
        self.full_update()
    
    def uuid_change(self, uuid: int):
        change_diff_old = PrettyDiff.NO_DIFF
        change_diff_new = PrettyDiff.NO_DIFF
        glob_diff_old = self.pretty_diff
        glob_diff_new = PrettyDiff.NO_DIFF

        if uuid in self.clients_diff:
            change_diff_old = self.clients_diff[uuid]

            for client_name, client_uuid in self.client_name_uuids.items():
                if client_uuid != uuid:
                    continue

                self.clients_diff[uuid] = self._get_diff(
                    self.pretty_names.pretty_group(client_name),
                    self.metadatas.pretty_name(uuid))
                change_diff_new = self.clients_diff[uuid]
                break
        
        elif uuid in self.ports_diff:
            change_diff_old = self.ports_diff[uuid]
            port = self.ports.from_uuid(uuid)
            if port is not None:
                self.ports_diff[uuid] = self._get_diff(
                    self.pretty_names.pretty_port(port.name),
                    self.metadatas.pretty_name(uuid))
                change_diff_new = self.ports_diff[uuid]
        
        else:
            port = self.ports.from_uuid(uuid)
            if port is None:
                for client_name, client_uuid \
                        in self.client_name_uuids.items():
                    if client_uuid != uuid:
                        continue
                    
                    self.clients_diff[uuid] = self._get_diff(
                        self.pretty_names.pretty_group(client_name),
                        self.metadatas.pretty_name(uuid))
                    change_diff_new = self.clients_diff[uuid]
                    break
            else:
                self.ports_diff[uuid] = self._get_diff(
                    self.pretty_names.pretty_port(port.name),
                    self.metadatas.pretty_name(uuid))
                change_diff_new = self.ports_diff[uuid]
        
        # In many cases, no need to reevaluate all pretty names change states
        # to know the diff state
        match glob_diff_old:
            case PrettyDiff.NO_DIFF:
                glob_diff_new = change_diff_new
            case PrettyDiff.NON_BOTH:
                if change_diff_old is PrettyDiff.NO_DIFF:
                    glob_diff_new = PrettyDiff.NON_BOTH
                else:
                    glob_diff_new = self.get_glob_diff()
            case _:
                if glob_diff_old in change_diff_old:
                    glob_diff_new = self.get_glob_diff()
                else:
                    glob_diff_new = glob_diff_old | change_diff_new
        
        self.pretty_diff = glob_diff_new
    
    def _get_diff(self, pretty_name: str, jack_pretty_name: str):
        if pretty_name == jack_pretty_name:
            return PrettyDiff.NO_DIFF
        
        if pretty_name and jack_pretty_name:
            return PrettyDiff.NON_BOTH
        
        if pretty_name:
            return PrettyDiff.NON_EXPORTED
        return PrettyDiff.NON_IMPORTED
    
    def full_update(self):
        self.clients_diff.clear()
        self.ports_diff.clear()

        for client_name, client_uuid in self.client_name_uuids.items():
            self.clients_diff[client_uuid] = self._get_diff(
                self.pretty_names.pretty_group(client_name),
                self.metadatas.pretty_name(client_uuid))
                
        for port in self.ports:
            self.ports_diff[port.uuid] = self._get_diff(
                self.pretty_names.pretty_port(port.name),
                self.metadatas.pretty_name(port.uuid))
            
        self.pretty_diff = self.get_glob_diff()

    def get_glob_diff(self) -> PrettyDiff:
        glob_diff = PrettyDiff.NO_DIFF
        for pretty_diff in self.clients_diff.values():
            glob_diff |= pretty_diff
            if glob_diff is PrettyDiff.NON_BOTH:
                return glob_diff
            
        for pretty_diff in self.ports_diff.values():
            glob_diff |= pretty_diff
            if glob_diff is PrettyDiff.NON_BOTH:
                return glob_diff
        return glob_diff

    def metadatas_cleared(self):
        if self.pretty_diff in (PrettyDiff.NO_DIFF, PrettyDiff.NON_EXPORTED):
            return

        self.full_update()            


def jack_pretty_name(uuid: int) -> str:
    value_type = jack.get_property(uuid, JackMetadata.PRETTY_NAME)
    if value_type is None:
        return ''
    return value_type[0].decode()


class MainObject:
    ports = PortDataList()
    connections = list[tuple[str, str]]()
    metadatas = JackMetadatas()
    'JACK metadatas, written in JACK callback thread'

    client_name_uuids = dict[str, int]()
    cliports_events_queue = Queue[tuple[PatchEvent, PatchEventArg, float]]()
    '''Clients and ports registration events: 
    is_client, appears, name, time'''
    delayed_events_queue = Queue[tuple[PatchEvent, PatchEventArg, float]]()
    '''Clients and ports registration events: 
    is_client, appears, name, time'''
    mdata_events = Queue()
    jack_running = False
    osc_server = None
    alsa_mng: Optional['AlsaManager'] = None
    terminate = False
    client = None
    samplerate = 48000
    buffer_size = 1024
    
    pretty_name_locked = False
    '''True when another ray-patch_dmn instance
    is already running on the same JACK server. In this case, 
    this instance will NOT apply any pretty-name metadata, because
    it could easily create conflicts with the other instance.'''
    pretty_names_export = True
    '''True if the patchbay option 'Export pretty names to JACK' is activated
    (True by default).'''
    
    dsp_wanted = True
    transport_wanted = TransportWanted.FULL
    
    def __init__(self, daemon_port: int, gui_url: str,
                 pretty_name_active=True):
        self.daemon_port = daemon_port
        self.pretty_names_export = pretty_name_active

        self.last_sent_dsp_load = 0
        self.max_dsp_since_last_sent = 0.00

        self._waiting_jack_client_open = True

        self.last_transport_pos = TransportPosition(
            0, False, False, 0, 0, 0, 0.0)

        self.pretty_names = PrettyNames()
        '''Contains all internal pretty names,
        including some groups and ports not existing now'''

        self.uuid_pretty_names = dict[int, str]()
        '''Contains pairs of 'uuid: pretty_name' of all pretty_names
        exported to JACK metadatas by this program.'''
        
        self.uuid_waiting_pretty_names = dict[int, str]()
        '''Contains pairs of 'uuid: pretty_name' of pretty_names just
        set and waiting for the property change callback.'''

        self.pretty_diff_checker = PrettyDiffChecker(
            self.metadatas, self.pretty_names,
            self.client_name_uuids, self.ports)

        self.pretty_tmp_path = (Path('/tmp/RaySession/')
                                / f'pretty_names.{daemon_port}.json')
        
        self.osc_server = PatchbayDaemonServer(self)
        self.osc_server.set_tmp_gui_url(gui_url)
        self.write_existence_file()
        self.start_jack_client()
        
        if ALSA_LIB_OK:
            self.alsa_mng = AlsaManager(self)
            self.alsa_mng.add_all_ports()
    
    def write_existence_file(self):
        EXISTENCE_PATH.mkdir(parents=True, exist_ok=True)
        
        try:
            with open(EXISTENCE_PATH / str(self.daemon_port), 'w') as file:
                contents = f'pid:{os.getpid()}\nport:{self.osc_server.port}\n'
                file.write(contents)

        except PermissionError:
            _logger.critical('no permission for existence file')

    def remove_existence_file(self):
        existence_path = EXISTENCE_PATH / str(self.daemon_port)
        if not existence_path.exists():
            return 

        try:
            existence_path.unlink()
        except PermissionError:
            sys.stderr.write(
                'ray-patchbay_to_osc: Error, '
                f'unable to remove {existence_path}\n')
    
    @classmethod
    def signal_handler(cls, sig: int, frame):
        if sig in (signal.SIGINT, signal.SIGTERM):
            cls.terminate = True
    
    def internal_stop(self):
        self.terminate = True
    
    def eat_client_names_queue(self):
        while self.cliports_events_queue.qsize():
            event, event_arg, add_time = self.delayed_events_queue.put((event, event_arg, add_time))
            
            uuid: Optional[int] = None

            match event:
                case PatchEvent.CLIENT_ADDED:
                    name = event_arg
                    try:
                        uuid = int(
                            self.client.get_uuid_for_client_name(name))
                    except:
                        ...
                    finally:
                        self.client_name_uuids[name] = uuid
                        self.osc_server.associate_client_name_and_uuid(
                            name, uuid)

                case PatchEvent.CLIENT_REMOVED:
                    uuid = self.client_name_uuids[event_arg]

                case PatchEvent.PORT_ADDED | PatchEvent.PORT_REMOVED:
                    port = self.ports.from_name(name)
                    if port is not None:
                        uuid = port.uuid
            
            if uuid is not None:
                self.pretty_diff_checker.uuid_change(uuid)

    def _check_pretty_names_export(self):
        client_names = set[str]()
        port_names = set[str]()
        
        while self.delayed_events_queue.qsize():
            if time.time() - self.delayed_events_queue.queue[0][2] < 0.200:
                break
            
            event, event_arg, add_time = self.cliports_events_queue.get()
            
            match event:
                case PatchEvent.CLIENT_ADDED:
                    client_names.add(event_arg)
                case PatchEvent.CLIENT_REMOVED:
                    client_names.discard(event_arg)
                case PatchEvent.PORT_ADDED:
                    port_names.add(event_arg)
                case PatchEvent.PORT_REMOVED:
                    port_names.discard(event_arg)
        
        if not self.jack_running:
            return
        
        if not self.pretty_names_export:
            return
        
        has_changes = False
        
        for client_name in client_names:
            client_uuid = self.client_name_uuids.get(client_name)
            if client_uuid is None:
                continue
            
            if self.set_jack_pretty_name_conditionally(
                    True, client_name, client_uuid):
                has_changes = True
                
        for port_name in port_names:
            try:
                port = self.client.get_port_by_name(port_name)
            except:
                continue
            
            if self.set_jack_pretty_name_conditionally(
                    False, port_name, port.uuid):
                has_changes = True
        
        if has_changes:
            self.save_uuid_pretty_names()
    
    def _check_pretty_diff(self) -> PrettyDiff:
        pretty_diff = PrettyDiff.NO_DIFF

        for client_name, client_uuid in self.client_name_uuids.items():
            jack_pretty = self.metadatas.pretty_name(client_uuid)
            pretty_name = self.pretty_names.pretty_group(client_name)
            if jack_pretty != pretty_name:
                if jack_pretty:
                    pretty_diff |= PrettyDiff.NON_IMPORTED
                if pretty_name:
                    pretty_diff |= PrettyDiff.NON_EXPORTED

                if pretty_diff is PrettyDiff.NON_BOTH:
                    return pretty_diff
                
        for port in self.ports:
            jack_pretty = self.metadatas.pretty_name(port.uuid)
            pretty_name = self.pretty_names.pretty_port(port.uuid)
            if jack_pretty != pretty_name:
                if jack_pretty:
                    pretty_diff |= PrettyDiff.NON_IMPORTED
                if pretty_name:
                    pretty_diff |= PrettyDiff.NON_EXPORTED
            
                if pretty_diff is PrettyDiff.NON_BOTH:
                    return pretty_diff

        return pretty_diff
    
    def _check_jack_client_responding(self):
        for i in range(100): # JACK has 5s to answer
            time.sleep(0.050)

            if not self._waiting_jack_client_open:
                break
        else:
            # server never answer
            _logger.error(
                'Server never answer when trying to open JACK client !')
            self.osc_server.send_server_lose()
            self.remove_existence_file()
            
            # JACK is not responding at all
            # probably it is started but totally bugged
            # finally kill this program from system
            self.terminate = True
    
    def refresh(self):
        _logger.debug(f'refresh jack running {self.jack_running}')
        if self.jack_running:
            self.get_all_ports_and_connections()
            self.osc_server.server_restarted()
            
        if self.alsa_mng is not None:
            self.alsa_mng.add_all_ports()
    
    def remember_dsp_load(self):
        self.max_dsp_since_last_sent = max(
            self.max_dsp_since_last_sent,
            self.client.cpu_load())
        
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
        
        state, pos_dict = self.client.transport_query()
        
        if (self.transport_wanted is TransportWanted.STATE_ONLY
                and bool(state) == self.last_transport_pos.rolling):
            return

        transport_position = TransportPosition(
            pos_dict['frame'],
            state == jack.ROLLING,
            'bar' in pos_dict,
            pos_dict.get('bar', 0),
            pos_dict.get('beat', 0),
            pos_dict.get('tick', 0),
            pos_dict.get('beats_per_minute', 0.0))
        
        if transport_position == self.last_transport_pos:
            return
        
        self.last_transport_pos = transport_position
        self.osc_server.send_transport_position(transport_position)
    
    def connect_ports(self, port_out_name: str, port_in_name: str,
                      disconnect=False):
        if self.alsa_mng is not None and port_out_name.startswith(':ALSA_OUT:'):
            self.alsa_mng.connect_ports(
                port_out_name, port_in_name, disconnect=disconnect)
            return

        if disconnect:
            try:
                self.client.disconnect(port_out_name, port_in_name)
            except jack.JackErrorCode:
                # ports already disconnected
                ...
            except BaseException as e:
                _logger.warning(
                    f"Failed to disconnect '{port_out_name}' "
                    f"from '{port_in_name}'\n{str(e)}")
        else:
            try:
                self.client.connect(port_out_name, port_in_name)
            except jack.JackErrorCode:
                # ports already connected
                ...
            except BaseException as e:
                _logger.warning(
                    f"Failed to connect '{port_out_name}' "
                    f"to '{port_in_name}'\n{str(e)}")
    
    def set_buffer_size(self, blocksize: int):
        if not self.jack_running:
            return
        
        self.client.blocksize = blocksize
    
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
                self._check_pretty_names_export()

                if self.transport_wanted is not TransportWanted.NO:
                    self._send_transport_pos()

            else:
                if n % 10 == 0:
                    if self.client is not None:
                        _logger.debug(
                            'deactivate JACK client after server shutdown')
                        self.client.deactivate()
                        _logger.debug('close JACK client after server shutdown')
                        self.client.close()
                        _logger.debug('close JACK client done')
                        self.client = None
                    _logger.debug('try to start JACK')
                    self.start_jack_client()
            n += 1
            
            # for faster modulos
            if n == 20:
                n = 0

        self.exit()
                
    def exit(self):
        self.save_uuid_pretty_names()
        
        if self.jack_running:
            _logger.debug('deactivate JACK client')
            self.client.deactivate()
            _logger.debug('close JACK client')
            self.client.close()
            _logger.debug('JACK client closed')

        if self.alsa_mng is not None:
            self.alsa_mng.stop_events_loop()
            del self.alsa_mng

        self.remove_existence_file()
        _logger.debug('Exit, bye bye.')
    
    def start_jack_client(self):
        self._waiting_jack_client_open = True
        
        # Sometimes JACK never registers the client
        # and never answers. This thread will allow to exit
        # if JACK didn't answer 5 seconds after register ask
        jack_waiter_thread = threading.Thread(
            target=self._check_jack_client_responding)
        jack_waiter_thread.start()

        fail_info = False
        self.client = None

        _logger.debug('Start JACK client')

        with SuppressStdoutStderr():
            try:
                self.client = jack.Client(
                    JACK_CLIENT_NAME,
                    no_start_server=True)

            except jack.JackOpenError:
                fail_info = True
                del self.client
                self.client = None
        
        if fail_info:
            _logger.info('Failed to connect client to JACK server')
        else:
            _logger.info('JACK client started successfully')
                
        self._waiting_jack_client_open = False

        jack_waiter_thread.join()
        if self.terminate:
            return

        self.jack_running = bool(self.client is not None)

        if self.jack_running:
            self.set_registrations()
            self.get_all_ports_and_connections()
            self.samplerate = self.client.samplerate
            self.buffer_size = self.client.blocksize
            self.osc_server.server_restarted()
        
        if self.pretty_tmp_path.exists():
            # read the contents of pretty names set by this program
            # in a previous run (with same daemon osc port).
            try:
                with open(self.pretty_tmp_path, 'r') as f:
                    pretty_dict = json.load(f)
                    if isinstance(pretty_dict, dict):
                        self.uuid_pretty_names.clear()
                        for key, value in pretty_dict.items():
                            self.uuid_pretty_names[int(key)] = value
            except ValueError:
                _logger.warning(
                    f'{self.pretty_tmp_path} badly written, ignored.')
            except:
                _logger.warning(
                    f'Failed to read {self.pretty_tmp_path}, ignored.')
        
        self.osc_server.set_ready_for_daemon()

    def is_terminate(self) -> bool:
        if self.terminate or self.osc_server.is_terminate():
            return True
        
        return False
    
    def set_registrations(self):
        if self.client is None:
            return

        @self.client.set_client_registration_callback
        def client_registration(name: str, register: bool):
            _logger.debug(f'client registration {register} "{name}"')
            if register:
                self.cliports_events_queue.put(
                    (PatchEvent.CLIENT_ADDED, name, time.time()))
            else:
                self.cliports_events_queue.put(
                    (PatchEvent.CLIENT_REMOVED, name, time.time()))
            
        @self.client.set_port_registration_callback
        def port_registration(port: jack.Port, register: bool):
            port_type_int = PORT_TYPE_NULL
            if port.is_audio:
                port_type_int = PORT_TYPE_AUDIO
            elif port.is_midi:
                port_type_int = PORT_TYPE_MIDI
            flags = jack._lib.jack_port_flags(port._ptr)
            port_name = port.name
            port_uuid = port.uuid

            _logger.debug(
                f'port registration {register} "{port_name}" {port_uuid}')

            if register:                
                self.ports.append(
                    PortData(port_name, port_type_int, flags, port_uuid))
                self.osc_server.port_added(
                    port_name, port_type_int, flags, port.uuid)
                self.cliports_events_queue.put(
                    (PatchEvent.PORT_ADDED, port_name, time.time()))
            else:
                self.ports.remove_from_name(port_name)
                self.osc_server.port_removed(port_name)
                self.cliports_events_queue.put(
                    (PatchEvent.PORT_REMOVED, port_name, time.time()))

        @self.client.set_port_connect_callback
        def port_connect(port_a: jack.Port, port_b: jack.Port, connect: bool):
            conn = (port_a.name, port_b.name)
            _logger.debug(f'ports connected {connect} {conn}')

            if connect:
                self.connections.append(conn)
                self.osc_server.connection_added(conn)
                self.cliports_events_queue.put(
                    (PatchEvent.CONNECTION_ADDED, conn, time.time()))
            else:
                if conn in self.connections:
                    self.connections.remove(conn)
                self.osc_server.connection_removed(conn)
                self.cliports_events_queue.put(
                    (PatchEvent.CONNECTION_REMOVED, conn, time.time()))
            
        @self.client.set_port_rename_callback
        def port_rename(port: jack.Port, old: str, new: str):
            _logger.debug(f'port renamed "{old}" to "{new}"')
            self.ports.rename(old, new)
            self.osc_server.port_renamed(old, new, port.uuid)
            self.cliports_events_queue.put(
                (PatchEvent.PORT_RENAMED, (old, new), time.time()))

        @self.client.set_xrun_callback
        def xrun(delayed_usecs: float):
            self.osc_server.send_one_xrun()
            
        @self.client.set_blocksize_callback
        def blocksize(size: int):
            self.buffer_size = size
            self.osc_server.send_buffersize()
            
        @self.client.set_samplerate_callback
        def samplerate(samplerate: int):
            self.samplerate = samplerate
            self.osc_server.send_samplerate()
            
        try:
            @self.client.set_property_change_callback
            def property_change(subject: int, key: str, change: int):
                if change == jack.PROPERTY_DELETED:
                    if subject == 0 and key == '':
                        for uuid, mdata_dict in self.metadatas.items():
                            for k in mdata_dict:
                                self.osc_server.metadata_updated(uuid, k, '') 
                        self.metadatas.clear()
                        self.uuid_pretty_names.clear()
                        self.save_uuid_pretty_names()
                        self.cliports_events_queue.put(
                            (PatchEvent.METADATA_CHANGED,
                             (0, '', ''), time.time()))
                        return
                    
                    if key in (JackMetadata.PRETTY_NAME, ''):
                        if subject in self.uuid_waiting_pretty_names:
                            self.uuid_waiting_pretty_names.pop(subject)
                        
                        if key == '':
                            if subject in self.metadatas:
                                self.metadatas.pop(subject)

                    self.metadatas.add(subject, key, '')
                    self.osc_server.metadata_updated(subject, key, '')
                    self.cliports_events_queue.put(
                        (PatchEvent.METADATA_CHANGED,
                         (subject, '', ''), time.time()))
                    return                            
                
                value_type = jack.get_property(subject, key)
                if value_type is None:
                    return
                value = value_type[0].decode()
                
                if key == JackMetadata.PRETTY_NAME:
                    if subject in self.uuid_waiting_pretty_names:
                        if value != self.uuid_waiting_pretty_names[subject]:
                            _logger.warning(
                                f'Incoming pretty-name property does not '
                                f'have the expected value\n'
                                f'expected: {self.uuid_pretty_names[subject]}\n'
                                f'value   : {value}')

                        self.uuid_waiting_pretty_names.pop(subject)
                
                self.metadatas.add(subject, key, value)
                self.osc_server.metadata_updated(subject, key, value)
                self.cliports_events_queue.put(
                    (PatchEvent.METADATA_CHANGED, (subject, key, value), time.time()))
                
                if key == JackMetadata.PRETTY_NAME:
                    pretty_diff = PrettyDiff.NO_DIFF

                    for client_name, uuid in self.client_name_uuids.items():
                        if uuid != subject:
                            continue
                        pretty_name = self.pretty_names.pretty_group(client_name)
                        jack_pretty_name = self.metadatas.pretty_name(uuid)
                        if pretty_name != jack_pretty_name:
                            if pretty_name:
                                pretty_diff |= PrettyDiff.NON_EXPORTED
                            if jack_pretty_name:
                                pretty_diff |= PrettyDiff.NON_IMPORTED
                    
                    port = self.ports.from_uuid(subject)
                    if port is not None:
                        pretty_name = self.pretty_names.pretty_port(port.name)
                        jack_pretty_name = self.metadatas.pretty_name(port.uuid)
                        if pretty_name != jack_pretty_name:
                            if pretty_name:
                                pretty_diff |= PrettyDiff.NON_EXPORTED
                            if jack_pretty_name:
                                pretty_diff |= PrettyDiff.NON_IMPORTED                                        

        except jack.JackError as e:
            _logger.warning(
                "jack-metadatas are not available,"
                "probably due to the way JACK has been compiled."
                + str(e))
            
        @self.client.set_shutdown_callback
        def on_shutdown(status: jack.Status, reason: str):
            _logger.debug('Jack shutdown')
            self.jack_running = False
            self.ports.clear()
            self.connections.clear()
            self.metadatas.clear()
            self.osc_server.server_stopped()
            
        self.client.activate()
        
        if self.client.name != JACK_CLIENT_NAME:
            try:
                existant_uuid = self.client.get_uuid_for_client_name(
                    JACK_CLIENT_NAME)
                locker_port = jack.get_property(
                    existant_uuid, METADATA_LOCKER)
                if locker_port is not None:
                    locker_port = int(locker_port[0].decode())
                self.pretty_name_locked = True
                _logger.warning(
                    f'This instance will NOT write any pretty-name metadata '
                    f'because the patchbay daemon depending on daemon '
                    f'at port {locker_port} is running '
                    f'in the same JACK server')
            except:
                _logger.warning(
                    f'Strange, the {JACK_CLIENT_NAME} JACK client has been renamed '
                    f'to {self.client.name}.')
        
        # set locker identifier.
        # Multiple daemons can co-exist,
        # But if we want things going right,
        # we have to ensure that each daemon runs on a different JACK server
        try:
            self.client.set_property(
                self.client.uuid, METADATA_LOCKER,
                str(self.daemon_port))
        except:
            _logger.warning(
                'Failed to set locker metadata for ray-patch_dmn, '
                'could cause troubles if you start multiple daemons.')
    
    def get_all_ports_and_connections(self):
        self.ports.clear()
        self.connections.clear()
        self.metadatas.clear()

        client_names = set[str]()

        #get all currents Jack ports and connections
        for port in self.client.get_ports():
            flags = jack._lib.jack_port_flags(port._ptr)
            port_name = port.name
            port_uuid = port.uuid
            port_type = PORT_TYPE_NULL
            if port.is_audio:
                port_type = PORT_TYPE_AUDIO
            elif port.is_midi:
                port_type = PORT_TYPE_MIDI

            self.ports.append(
                PortData(port_name, port_type, flags, port_uuid))

            client_names.add(port_name.partition(':')[0])
                
            if port.is_input:
                continue

            # this port is output, list its connections
            for conn_port in self.client.get_all_connections(port):
                self.connections.append((port_name, conn_port.name))
        
        for client_name in client_names:
            try:
                client_uuid = int(
                    self.client.get_uuid_for_client_name(client_name))
            except jack.JackError:
                continue
            except ValueError:
                _logger.warning(
                    f"uuid for client name {client_name} is not digit")
                continue

            self.client_name_uuids[client_name] = client_uuid
        
        for uuid, uuid_dict in jack.get_all_properties().items():
            for key, valuetype in uuid_dict.items():
                value = valuetype[0].decode()
                self.metadatas.add(uuid, key, value)

    def set_metadata(self, uuid: int, key: str, value: str):
        self.client.set_property(uuid, key, value, 'text/plain')

    def save_uuid_pretty_names(self):
        'save the contents of self.uuid_pretty_names in /tmp'
        try:
            with open(self.pretty_tmp_path, 'w') as f:
                json.dump(self.uuid_pretty_names, f)
        except:
            _logger.warning(f'Failed to save {self.pretty_tmp_path}')

    def set_jack_pretty_name(self, uuid: int, pretty_name: str):
        'write pretty-name metadata, or remove it if value is empty'

        if self.pretty_name_locked:
            return
        
        if pretty_name:
            try:
                self.client.set_property(
                    uuid, JackMetadata.PRETTY_NAME, pretty_name)
                _logger.info(f'Pretty-name set to "{pretty_name}" on {uuid}')
            except:
                _logger.warning(
                    f'Failed to set pretty-name "{pretty_name}" for {uuid}')
                return
            
            self.uuid_pretty_names[uuid] = pretty_name
            self.uuid_waiting_pretty_names[uuid] = pretty_name

        else:
            try:
                self.client.remove_property(uuid, JackMetadata.PRETTY_NAME)
                _logger.info(f'Pretty-name removed from {uuid}')
            except:
                _logger.warning(
                    f'Failed to remove pretty-name for {uuid}')
                return
            
            if uuid in self.uuid_pretty_names:
                self.uuid_pretty_names.pop(uuid)
            if uuid in self.uuid_waiting_pretty_names:
                self.uuid_waiting_pretty_names.pop(uuid)

    def jack_pretty_name_if_not_mine(self, uuid: int) -> str:
        mdata_pretty_name = jack_pretty_name(uuid)
        if not mdata_pretty_name:
            return ''
        
        if mdata_pretty_name == self.uuid_pretty_names.get(uuid):
            return ''
        
        return mdata_pretty_name

    def set_all_pretty_names(self):
        '''Set all pretty names once all pretty names are received,
        or clear them if self.pretty_name_active is False and some
        pretty names have been written by a previous process.'''
        self.pretty_diff_checker.full_update()
        if not self.jack_running or self.pretty_name_locked:
            return
        
        self.set_pretty_name_active(self.pretty_names_export, force=True)
        
        if (not self.pretty_names_export
                and not self.osc_server.can_have_gui()):
            self.terminate = True

    def write_group_pretty_name(self, client_name: str, pretty_name: str):
        if not self.jack_running:
            return
        
        client_uuid = self.client_name_uuids.get(client_name)
        if client_uuid is None:
            return

        mdata_pretty_name = self.jack_pretty_name_if_not_mine(client_uuid)
        self.pretty_names.save_group(
            client_name, pretty_name, mdata_pretty_name)
        
        self.set_jack_pretty_name(client_uuid, pretty_name)
        self.save_uuid_pretty_names()

    def write_port_pretty_name(self, port_name: str, pretty_name: str):        
        if not self.jack_running:
            return

        try:
            port = self.client.get_port_by_name(port_name)
        except BaseException as e:
            _logger.warning(
                f'Unable to find port {port_name} '
                f'to set the pretty-name {pretty_name}')
            return

        if port is None:
            return

        port_uuid = port.uuid
        mdata_pretty_name = self.jack_pretty_name_if_not_mine(port_uuid)
        self.pretty_names.save_port(port_name, pretty_name, mdata_pretty_name)
        self.set_jack_pretty_name(port.uuid, pretty_name)
        self.save_uuid_pretty_names()

    def set_jack_pretty_name_conditionally(
            self, for_client: bool, name: str, uuid: int) -> bool:
        '''set jack pretty name if checks are ok.
        checks are :
        - an internal pretty name exists for this item
        - this internal pretty name is not the current pretty name
        - the current pretty name is empty or known to be overwritable
        
        return False if one of theses checks fails.'''

        mdata_pretty_name = jack_pretty_name(uuid)
        if for_client:
            ptov = self.pretty_names.groups.get(name)
        else:
            ptov = self.pretty_names.ports.get(name)

        if (ptov is None
                or not ptov.pretty
                or ptov.pretty == mdata_pretty_name):
            return False
        
        if (mdata_pretty_name and ptov.above_pretty
                and mdata_pretty_name != ptov.above_pretty
                and mdata_pretty_name != self.uuid_pretty_names.get(uuid)):
            item_type = 'client' if for_client else 'port'
            _logger.warning(
                f"pretty-name not set\n"
                f"  {item_type}: {name}\n"
                f"  uuid: {uuid}\n"
                f"  wanted   : '{ptov.pretty}'\n"
                f"  above    : '{ptov.above_pretty}'\n"
                f"  existing : '{mdata_pretty_name}'\n")
            return False
        
        self.set_jack_pretty_name(uuid, ptov.pretty)
        return True

    def set_pretty_name_active(self, active: bool, force=False):
        if not force and active is self.pretty_names_export:
            return

        self.pretty_names_export = True
        
        if active:
            for client_name, client_uuid in self.client_name_uuids.items():
                self.set_jack_pretty_name_conditionally(
                    True, client_name, client_uuid)
                    
            for port_name in self.pretty_names.ports:
                try:
                    port = self.client.get_port_by_name(port_name)
                except jack.JackError:
                    continue
                
                self.set_jack_pretty_name_conditionally(
                    False, port_name, port.uuid)

        else:
            # clear pretty-name metadata created by this from JACK

            for client_name, client_uuid in self.client_name_uuids.items():
                if client_uuid not in self.uuid_pretty_names:
                    continue

                mdata_pretty_name = jack_pretty_name(client_uuid)
                pretty_name = self.pretty_names.pretty_group(client_name)
                if pretty_name == mdata_pretty_name:
                    self.set_jack_pretty_name(client_uuid, '')
                    
            for port in self.client.get_ports():
                port_uuid = port.uuid
                if port_uuid not in self.uuid_pretty_names:
                    continue
                
                port_name = port.name
                mdata_pretty_name = jack_pretty_name(port_uuid)
                pretty_name = self.pretty_names.pretty_port(port_name)
                if pretty_name == mdata_pretty_name:
                    self.set_jack_pretty_name(port_uuid, '')

            self.uuid_pretty_names.clear()
        
        self.pretty_names_export = active
        self.save_uuid_pretty_names()

    def import_all_pretty_names_from_jack(
            self) -> tuple[dict[str, str], dict[str, str]]:
        clients_dict = dict[str, str]()
        ports_dict = dict[str, str]()

        for client_name, uuid in self.client_name_uuids.items():
            jack_pretty = jack_pretty_name(uuid)
            if not jack_pretty:
                continue

            pretty_name = self.pretty_names.pretty_group(client_name)
            if pretty_name != jack_pretty:
                self.pretty_names.save_group(client_name, jack_pretty)
                clients_dict[client_name] = jack_pretty

        for jport in self.ports:
            jack_pretty = jack_pretty_name(jport.uuid)
            if not jack_pretty:
                continue
            
            pretty_name = self.pretty_names.pretty_port(jport.name)
            if pretty_name != jack_pretty:
                self.pretty_names.save_port(jport.name, jack_pretty)
                ports_dict[jport.name] = jack_pretty
        
        return clients_dict, ports_dict

    def export_all_pretty_names_to_jack_now(self):
        for client_name, uuid in self.client_name_uuids.items():
            pretty_name = self.pretty_names.pretty_group(client_name)
            if pretty_name:
                self.set_jack_pretty_name(uuid, pretty_name)
        
        for jport in self.ports:
            pretty_name = self.pretty_names.pretty_port(jport.name)
            if pretty_name:
                self.set_jack_pretty_name(jport.uuid, pretty_name)

    def transport_play(self, play: bool):
        if play:
            self.client.transport_start()
        else:
            self.client.transport_stop()
            
    def transport_stop(self):
        self.client.transport_stop()
        self.client.transport_locate(0)
        
    def transport_relocate(self, frame: int):
        self.client.transport_locate(frame)


def main_process(daemon_port_str: str, gui_tcp_url: str,
                 pretty_names_active: bool):
    try:
        daemon_port = int(daemon_port_str)
    except:
        _logger.critical(
            f'daemon port must be an integer, not "{daemon_port_str}"')
        return
        
    main_object = MainObject(daemon_port, gui_tcp_url, pretty_names_active)
    main_object.osc_server.add_gui(gui_tcp_url)
    if main_object.osc_server.gui_list:
        main_object.start_loop()
    # main_object.exit()

def start():
    '''launch the process when it is a process (not internal).'''
    set_proc_name('ray-patch_dmn')
    
    # prevent deprecation warnings python messages
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    
    signal.signal(signal.SIGINT, MainObject.signal_handler)
    signal.signal(signal.SIGTERM, MainObject.signal_handler)
    
    args = sys.argv.copy()
    daemon_port_str = ''
    gui_url = ''
    pretty_names_active = True
    log = ''
    dbg = ''

    args.pop(0)

    if args:
        daemon_port_str = args.pop(0)
    if args:
        gui_url = args.pop(0)
    if args:
        pns = args.pop(0)
        pretty_names_active = not bool(pns.lower() in ('0', 'false'))
        args.pop(0)
    if args[0] == '--log':
        args.pop(0)
        log = args.pop(0)
    if args[0] == '--dbg':
        args.pop(0)
        dbg = args.pop(0)
    
    level = logging.INFO
    for lv_info in (log, dbg):
        for module_name in lv_info.split(':'):
            if module_name == 'patchbay_daemon':
                _logger.setLevel(level)
            elif module_name.startswith('patchbay_daemon.'):
                sh_mod_name = module_name.partition('.')[2]
                mod_logger = logging.getLogger(sh_mod_name)
                mod_logger.setLevel(level)

        level = logging.DEBUG
    
    try:
        daemon_port = int(daemon_port_str)
    except:
        _logger.critical(
            f'daemon port must be an integer, not "{daemon_port_str}"')
        return
    
    main_object = MainObject(daemon_port, gui_url, pretty_names_active)
    if gui_url:
        main_object.osc_server.add_gui(gui_url)
    main_object.start_loop()
    
def internal_prepare(daemon_port: str, gui_url: str,
                     pretty_names_active: str, nsm_url=''):
    pretty_name_active_bool = not bool(
        pretty_names_active.lower() in ('0', 'false'))
    main_object = MainObject(int(daemon_port), gui_url,
                             pretty_name_active_bool)
    if gui_url:
        main_object.osc_server.add_gui(gui_url)
        if not main_object.osc_server.gui_list:
            return 1
    return main_object.start_loop, main_object.internal_stop
