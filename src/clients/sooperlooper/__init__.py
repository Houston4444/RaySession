#!/usr/bin/python3 -u


import logging
import os
import signal
import sys
from typing import TYPE_CHECKING, Optional
import xml.etree.ElementTree as ET
from pathlib import Path
from enum import Enum, auto
import time
import subprocess
import shutil

from shared.osclib import Address, get_free_osc_port, is_osc_port_free
from shared.nsm_client import NsmServer, NsmCallback, Err
from shared.xml_tools import XmlElement

if TYPE_CHECKING:
    from . import jacklib


_logger = logging.getLogger(__name__)

print('galop')

def signal_handler(sig, frame):
    if sig in (signal.SIGINT, signal.SIGTERM):
        print('I receive sig', main.full_client_id, nsm_server.sl_addr.port)
        main.leaving = True


class ArgRead(Enum):
    NONE = auto()
    LOG = auto()
    OSC_PORT = auto()


class SlServer(NsmServer):
    def __init__(self, daemon_address: Address):
        super().__init__(daemon_address)
        
        self.wait_pong = False
        self.save_error = False
        self.load_error = False
        
        self.sl_addr = Address(9951)

        self.add_method('/sl_pong', 'ssi', self.sl_pong)
        self.add_method('/sl_save_error', None, self.sl_save_error)
        self.add_method('/sl_load_error', None, self.sl_load_error)

    def sl_pong(self, path: str, args: list, types: str, src_adrr: Address):
        self.wait_pong = False

    def sl_save_error(
            self, path: str, args: list, types: str, src_adrr: Address):
        self.save_error = True
        
    def sl_load_error(
            self, path: str, args: list, types: str, src_adrr: Address):
        self.load_error = True

    def set_sl_port(self, port: int):
        self.sl_addr = Address(port)
        
    def send_sl(self, *args):
        self.send(self.sl_addr, *args)


class MainObject:
    def __init__(self):
        self.project_path = Path()
        self.full_client_id = 'SooperLooper'
        self.session_file = Path()
        self.session_bak = Path()
        self.midi_bindings_file = Path()
        
        self.follow_jack_naming = False
        self.wanted_osc_port: Optional[int] = None
        
        # self.gui_process = QProcess()
        self.gui_process: Optional[subprocess.Popen] = None

        self.sl_process: Optional[subprocess.Popen] = None
        self.sl_port = 9951
        self.not_started_yet = True
        
        self.last_gui_state = False
        self.leaving = False
        
        # for transport workaroung
        self.transport_playing = False
        self.will_trig = False
        
    def sl_running(self) -> bool:
        'return True if sooperlooper process is running, else False'
        if self.sl_process is None:
            return False
        
        return self.sl_process.poll() is None

    def gui_running(self) -> bool:
        'return True if slgui process is running, else False'
        if self.gui_process is None:
            return False
        
        return self.gui_process.poll() is None


main = MainObject()
jack_client = None


def check_transport():
    pos = jacklib.jack_position_t()
    pos.valid = 0

    state = jacklib.transport_query(jack_client, jacklib.pointer(pos))

    if main.will_trig:
        if pos.beat == pos.beats_per_bar:
            if (pos.ticks_per_beat - pos.tick) <= 4:
                # we are at 4 ticks or less from next bar (arbitrary)
                # so we send a trig message to sooperlooper.
                nsm_server.send_sl('/sl/-1/hit', 'trigger')
                main.will_trig = False
                return

    if (main.transport_playing
            and state == jacklib.JackTransportState.STOPPED):
        if main.will_trig:
            main.will_trig = False
        else:
            nsm_server.send_sl('/sl/-1/hit', 'pause_on')

        main.transport_playing = False

    elif (not main.transport_playing
            and state == jacklib.JackTransportState.ROLLING):
        if pos.beat == 1 and pos.tick == 0:
            nsm_server.send_sl('/sl/-1/hit', 'trigger')

        else:
            main.will_trig = True

        main.transport_playing = True

def xml_correction():
    try:
        tree = ET.parse(main.session_file)
        root = tree.getroot()
    except:
        _logger.warning(f'Failed to modify XML file {main.session_file}')
        return
    
    if root.tag != 'SLSession':
        return
    
    for child in root:
        if child.tag != 'Loopers':
            continue
        
        for c_child in child:
            if c_child.tag != 'Looper':
                continue
            
            xc_child = XmlElement(c_child)
            audio_file_name = Path(xc_child.str('loop_audio'))
            if main.project_path in audio_file_name.parents:
                xc_child.set_str(
                    'loop_audio',
                    audio_file_name.relative_to(main.project_path))
                
    try:
        tree.write(main.session_file)
    except:
        _logger.warning(
            f'Failed to save audio files in {main.session_file}')

def open_file(
        project_path: str, session_name: str,
        full_client_id: str) -> tuple[Err, str]:
    main.project_path = Path(project_path)
    main.session_file = main.project_path / 'session.slsess'
    main.session_bak = main.project_path / 'session.slsess.bak'
    main.midi_bindings_file = main.project_path / 'session.slb'

    if not main.follow_jack_naming:
        full_client_id = 'sooperlooper'

    main.full_client_id = full_client_id

    # STOP GUI
    if main.gui_running():
        main.gui_process.terminate()
    
    # STOP sooperlooper
    if main.sl_running():
        nsm_server.send_sl('/quit')
        
        for i in range(100):
            time.sleep(0.050)
            if main.sl_process.poll() is not None:
                break
            
            if main.leaving:
                break
            
        if main.sl_process.poll() is None:
            main.sl_process.terminate()
            for i in range(100):
                time.sleep(0.050)
                if main.sl_process.poll() is not None:
                    break
                
                if main.leaving:
                    break
    
    # create project folder and go inside
    # it is required to save audio files correctly
    try:
        main.project_path.mkdir(parents=True, exist_ok=True)
        os.chdir(main.project_path)
    except:
        return Err.CREATE_FAILED, f'Impossible to create {main.project_path}'
    
    if main.wanted_osc_port is not None:
        if is_osc_port_free(main.wanted_osc_port):
            nsm_server.set_sl_port(main.wanted_osc_port)
        else:
            main.leaving = True
            return (Err.LAUNCH_FAILED,
                    f'Wanted OSC port {main.wanted_osc_port} is busy')

    else:
        nsm_server.set_sl_port(get_free_osc_port(main.sl_port))
    
    # START sooperlooper
    try:
        main.sl_process = subprocess.Popen(
            ['sooperlooper',
             '-p', str(nsm_server.sl_addr.port), '-j', main.full_client_id])
    except BaseException as e:
        return Err.LAUNCH_FAILED, 'failed to start sooperlooper'
    
    # PING sooperlooper until it is ready to communicate
    pong_ok = False
    nsm_server.wait_pong = True

    for i in range(1000):
        nsm_server.send_sl('/ping', nsm_server.url, '/sl_pong')
        nsm_server.recv(10)
        
        if not nsm_server.wait_pong:
            pong_ok = True
            break
        
        if not main.sl_running():
            break
        
        if main.leaving:
            break

    if not pong_ok:
        return (
            Err.LAUNCH_FAILED,
            'Failed to launch sooperlooper, or fail to communicate with it')

    # LOAD midi bindings
    if main.midi_bindings_file.exists():
        nsm_server.send_sl(
            '/load_midi_bindings', str(main.midi_bindings_file), '')

    # LOAD project
    if main.session_file.exists():
        nsm_server.load_error = False
        nsm_server.send_sl(
            '/load_session', str(main.session_file),
            nsm_server.url, '/sl_load_error')
        
        # Wait 500ms for an error loading project
        # Unfortunately, sooperlooper replies only if there is an error.
        for i in range(10):
            nsm_server.recv(50)
            if nsm_server.load_error:
                return Err.BAD_PROJECT, 'Session Failed to load'
            
            if main.leaving:
                return Err.LAUNCH_FAILED, 'leaving process'

    # if jack_client:
    #     self.transport_timer.start()
    main.not_started_yet = False
        
    return Err.OK, f'Session {main.session_file} loaded'

def save_file():
    main.session_bak.unlink(missing_ok=True)

    if main.session_file.exists():
        main.session_file.rename(main.session_bak)

    nsm_server.send_sl('/save_midi_bindings', str(main.midi_bindings_file), '')

    nsm_server.save_error = False
    nsm_server.send_sl(
        '/save_session', str(main.session_file),
        nsm_server.url, '/sl_save_error', 1)
    
    for i in range(200):
        nsm_server.recv(50)
        if nsm_server.save_error:
            return Err.BAD_PROJECT, f'Failed to save {main.session_file}'
        
        if main.session_file.exists():
            break
        
        if main.leaving:
            return Err.CREATE_FAILED, 'Quitting program'

    if not main.session_file.exists():
        return Err.BAD_PROJECT, f'{main.session_file} has not been saved'

    xml_correction()

    return (Err.OK, f'Session {main.session_file} saved')

def show_optional_gui():
    if not main.gui_running():
        main.gui_process = subprocess.Popen(
            ['slgui', '-P', str(nsm_server.sl_addr.port)])
    nsm_server.send_gui_state(True)
    
def hide_optional_gui():
    if main.gui_running():
        main.gui_process.terminate()
    nsm_server.send_gui_state(False)

def run():
    global nsm_server, jack_client

    if not shutil.which('sooperlooper'):
        _logger.critical('SooperLooper is not installed.')
        sys.exit(1)

    transport_wk = False

    # set log level and other parameters with exec arguments
    if len(sys.argv) > 1:
        arg_read = ArgRead.NONE
        log_level = logging.WARNING

        for arg in sys.argv[1:]:
            if arg in ('-log', '--log'):
                arg_read = ArgRead.LOG
                log_level = logging.DEBUG

            elif arg in ('-osc-port', '--osc-port'):
                arg_read = ArgRead.OSC_PORT

            elif arg == '--transport_workaround':
                transport_wk = True
                arg_read = ArgRead.NONE

            elif arg == '--follow-jack-naming':
                main.follow_jack_naming = True
                arg_read = ArgRead.NONE

            else:
                if arg_read is ArgRead.LOG:
                    if arg.isdigit():
                        log_level = int(uarg)
                    else:
                        uarg = arg.upper()
                        if (uarg in logging.__dict__.keys()
                                and isinstance(logging.__dict__[uarg], int)):
                            log_level = logging.__dict__[uarg]
                
                elif arg_read is ArgRead.OSC_PORT:
                    if arg.isdigit():
                        main.wanted_osc_port = int(arg)

                arg_read = ArgRead.NONE

        _logger.setLevel(log_level)
    
    nsm_url = os.getenv('NSM_URL')
    if not nsm_url:
        _logger.error('Could not register as NSM client.')
        sys.exit(1)
    
    try:
        daemon_address = Address(nsm_url)
    except:
        _logger.error('NSM_URL seems to be invalid.')
        sys.exit(1)
        
    nsm_server = SlServer(daemon_address)
    nsm_server.set_callback(NsmCallback.OPEN, open_file)
    nsm_server.set_callback(NsmCallback.SAVE, save_file)
    nsm_server.set_callback(NsmCallback.SHOW_OPTIONAL_GUI, show_optional_gui)
    nsm_server.set_callback(NsmCallback.HIDE_OPTIONAL_GUI, hide_optional_gui)
    nsm_server.announce(
        'SooperLooper', ':optional-gui:switch:', Path(sys.argv[0]).name)
    
    # connect program interruption signals
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    if transport_wk:
        global jacklib
        from . import jacklib
        jack_client = jacklib.client_open(
            "sooper_ray_wk",
            jacklib.JackOptions.NO_START_SERVER
            | jacklib.JackOptions.SESSION_ID,
            None)

    loop_time = 50
    if transport_wk:
        loop_time = 2

    # main loop
    while True:
        if main.leaving:
            break

        nsm_server.recv(loop_time)
        
        if transport_wk:
            check_transport()
        
        if main.last_gui_state is not main.gui_running():
            main.last_gui_state = main.gui_running()
            nsm_server.send_gui_state(main.last_gui_state)

        if not main.not_started_yet:
            if not main.sl_running():
                break

    # QUIT
    
    # stop GUI
    if main.gui_running():
        main.gui_process.terminate()

    # stop sooperlooper
    if main.sl_running():
        nsm_server.send_sl('/quit')  
        for i in range(1000):
            time.sleep(0.0010)
            if not main.sl_running():
                break
        
        if main.sl_running():
            main.sl_process.terminate()
            for i in range(1000):
                time.sleep(0.0010)
                if not main.sl_running():
                    break

            if main.sl_running():
                main.sl_process.kill()

    sys.exit(0)


if True:
    run()
