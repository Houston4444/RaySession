
# Standard lib imports
from enum import Enum
from typing import TYPE_CHECKING, Optional
from pathlib import Path
import os
import logging
import threading
import time

# Third party imports
from qtpy.QtCore import QProcess

# HoustonPatchbay imports
from patshared import Naming

# shared/ imports
from osclib import Address
import osc_paths.ray as r

# local imports
from internal_client import InternalClient
from daemon_tools import RS, CommandLineArgs, Terminal

if TYPE_CHECKING:
    from osc_server_thread import OscServerThread


_logger = logging.getLogger(__name__)


class _MainObj:
    daemon_server: 'Optional[OscServerThread]' = None
    
    is_internal = True
    '''True if the patchbay daemon is a thread of the daemon,
    False if it is an independant process'''
    
    internal_client: Optional[InternalClient] = None
    process: Optional[QProcess] = None
    check_thread: Optional[threading.Thread] = None
    
    waiting_guis = set[str]()
    '''URLs of GUI asking for patchbay when patchbay daemon
    is started but not ready for OSC communication'''

    ready = False
    port = 0
    
    
class State(Enum):
    STOPPED = 0
    LAUNCHED = 1
    READY = 2

def _check_thread_target():
    while True:
        time.sleep(0.020)
        if not is_running():
            break
        
    _process_finished()

def _send(*args, **kwargs):
    if _MainObj.daemon_server is None:
        _logger.warning(
            'Attempting to send an OSC message without daemon_server')
        return
    
    _MainObj.daemon_server.send(*args, **kwargs)

def _process_stdout():
    if not isinstance(_MainObj.process, QProcess):
        return
    Terminal.patchbay_message(
        _MainObj.process.readAllStandardOutput().data())

def _process_finished():
    if _MainObj.is_internal:
        _logger.info('Patchbay daemon internal thread finished')
    else:
        _logger.info('Patchbay daemon process finished')

    _MainObj.ready = False
    _MainObj.port = 0

    if _MainObj.daemon_server is not None:
        _MainObj.daemon_server.patchbay_process_finished()

def set_daemon_server(daemon_server: 'OscServerThread'):
    _MainObj.daemon_server = daemon_server
    _MainObj.is_internal = RS.settings.value(
        'daemon/internal_patchbay', False, type=bool)

def get_port() -> Optional[int]:
    if _MainObj.port:
        return _MainObj.port

    patchbay_file = (Path('/tmp/RaySession/patchbay_daemons')
                     / str(_MainObj.daemon_server.port))

    if not patchbay_file.exists():
        return None

    with open(patchbay_file, 'r') as file:
        contents = file.read()
        for line in contents.splitlines():
            if line.startswith('pid:'):
                pid_str = line.rpartition(':')[2]
                if pid_str.isdigit():
                    pid = int(pid_str)
                    try:
                        os.kill(pid, 0)
                    except OSError:
                        # pid is not OK,
                        # consider patchbay_dmn as not started
                        return None
                    else:
                        # pid is okay, let check the osc port next
                        continue
                else:
                    return None

            if line.startswith('port:'):
                port_str = line.rpartition(':')[2]
                good_port = False

                try:
                    patchbay_addr = Address(int(port_str))
                    good_port = True
                except:
                    patchbay_addr = None
                    _logger.error(
                        f'port given for patchbay {port_str} '
                        'is not a valid osc UDP port')

                if good_port:
                    _MainObj.port = patchbay_addr.port
                    return patchbay_addr.port
                break

def start(gui_url=''):    
    _logger.debug(f'patchbay_dmn_mng.start(gui_url={gui_url})')

    if is_running():
        if gui_url:    
            patchbay_port = get_port()
            if patchbay_port is None:
                _MainObj.waiting_guis.add(gui_url)
            else:
                _send(patchbay_port, r.patchbay.ADD_GUI, gui_url)
        return

    pretty_names_active = True
    pretty_names_value = RS.settings.value(
        'daemon/jack_export_naming', 'INTERNAL_PRETTY', type=str)
    
    naming = Naming.from_config_str(pretty_names_value)
    if not naming & Naming.INTERNAL_PRETTY:
        pretty_names_active = False

    _MainObj.ready = False
    _MainObj.port = 0

    _MainObj.check_thread = threading.Thread(target=_check_thread_target)
    _MainObj.check_thread.start()

    if _MainObj.is_internal:
        try:
            _MainObj.internal_client = InternalClient(
                'ray-patchbay_daemon',
                (str(_MainObj.daemon_server.port),
                    gui_url,
                    str(pretty_names_active)),
                ''
            ) 
            _MainObj.internal_client.start()
            
            _logger.info('Patchbay daemon started internal')

        except:
            _logger.warning('Failed to launch ray-patch_dmn as internal')

    else:
        START_IN_KONSOLE = True

        try:
            _MainObj.process = QProcess()
            _MainObj.process.setProcessChannelMode(
                QProcess.ProcessChannelMode.MergedChannels)
            _MainObj.process.readyReadStandardOutput.connect(
                _process_stdout)
            _MainObj.process.finished.connect(_process_finished)
            
            if START_IN_KONSOLE:
                _MainObj.process.setProgram('konsole')
                _MainObj.process.setArguments(
                    ['--hold', '-e', 'ray-patch_dmn',
                    str(_MainObj.daemon_server.port),
                        gui_url,
                        str(pretty_names_active),
                        '',
                        '--log', CommandLineArgs.log,
                        '--dbg', CommandLineArgs.dbg])
            else:
                _MainObj.process.setProgram('ray-patch_dmn')
                _MainObj.process.setArguments(
                    [str(_MainObj.daemon_server.port),
                        gui_url,
                        str(pretty_names_active),
                        '',
                        '--log', CommandLineArgs.log,
                        '--dbg', CommandLineArgs.dbg])

            _MainObj.process.start()            
            _logger.info('ray-patch_dmn process started')

        except:
            _logger.warning('Failed to launch ray-patch_dmn')
    
def set_ready():
    port = get_port()
    if port is None:
        _logger.warning(
            'patchbay_dmn_mng.set_ready() but its port is not found')
        return
    
    for url in _MainObj.waiting_guis:
        _send(port, r.patchbay.ADD_GUI, url)
    
    _MainObj.waiting_guis.clear()
    _MainObj.ready = True

def is_running() -> bool:
    if _MainObj.is_internal:
        if _MainObj.internal_client is None:
            return False
        return _MainObj.internal_client.running
    
    if _MainObj.process is None:
        return False
    return _MainObj.process.state() != QProcess.ProcessState.NotRunning

def is_internal() -> bool:
    return _MainObj.is_internal

def state() -> State:
    if is_running():
        if _MainObj.ready:
            return State.READY
        return State.LAUNCHED
    return State.STOPPED

def daemon_exit():
    if _MainObj.process is not None:
        _MainObj.process.waitForFinished(500)
