
# Standard lib imports
from typing import TYPE_CHECKING, Optional
from pathlib import Path
import os
import logging

# Third party imports
from qtpy.QtCore import QProcess

# HoustonPatchbay imports
from patshared import Naming

# shared/ imports
from osclib import Address
import osc_paths.ray as r

# local imports
from internal_client import InternalClient
from daemon_tools import RS, Terminal

if TYPE_CHECKING:
    from osc_server_thread import OscServerThread


_logger = logging.getLogger(__name__)


class _MainObj:
    daemon_server: 'Optional[OscServerThread]' = None
    
    is_internal = False
    '''True if the patchbay daemon is a thread of the daemon,
    False if it is an independant process'''
    
    internal_client: Optional[InternalClient] = None
    process: Optional[QProcess] = None
    
    waiting_guis = set[str]()
    '''URLs of GUI asking for patchbay when patchbay daemon
    is started but not ready for OSC communication'''


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
    _logger.info('Patchbay daemon process finished')
    if _MainObj.daemon_server is not None:
        _MainObj.daemon_server.patchbay_process_finished()

def set_daemon_server(daemon_server: int):
    _MainObj.daemon_server = daemon_server

def get_port() -> Optional[int]:
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
                    return patchbay_addr.port
                break

def start(src_url=''):    
    _logger.debug(f'patchbay_dmn_mng.start(src_url={src_url})')

    patchbay_running = False

    if _MainObj.is_internal:
        if _MainObj.internal_client is not None:
            if _MainObj.internal_client.running:
                patchbay_running = True
    else:
        if _MainObj.process is not None:
            if _MainObj.process.state() != QProcess.ProcessState.NotRunning:
                patchbay_running = True

    patchbay_port = get_port()

    if patchbay_running:
        if src_url:    
            if patchbay_port is None:
                _MainObj.waiting_guis.add(src_url)
            else:
                _send(patchbay_port, r.patchbay.ADD_GUI, src_url)
        return

    pretty_names_active = True
    pretty_names_value = RS.settings.value(
        'daemon/jack_export_naming', 'INTERNAL_PRETTY', type=str)
    
    naming = Naming.from_config_str(pretty_names_value)
    if not naming & Naming.INTERNAL_PRETTY:
        pretty_names_active = False

    if _MainObj.is_internal:
        try:
            _MainObj.internal_client = InternalClient(
                'ray-patchbay_daemon',
                (str(_MainObj.daemon_server.port),
                    src_url,
                    str(pretty_names_active)),
                ''
            ) 
            _MainObj.internal_client.start()
        except:
            _logger.warning('Failed to launch ray-patch_dmn as internal')

    else:
        try:
            _MainObj.process = QProcess()
            _MainObj.process.setProcessChannelMode(
                QProcess.ProcessChannelMode.MergedChannels)
            _MainObj.process.readyReadStandardOutput.connect(
                _process_stdout)
            _MainObj.process.finished.connect(_process_finished)
            _MainObj.process.setProgram('ray-patch_dmn')
            _MainObj.process.setArguments(
                [str(_MainObj.daemon_server.port),
                    src_url,
                    str(pretty_names_active),
                    '']
            )
            _MainObj.process.start()

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

def is_running() -> bool:
    if _MainObj.is_internal:
        if _MainObj.internal_client is None:
            return False
        return _MainObj.internal_client.running
    
    if _MainObj.process is None:
        return False
    return _MainObj.process.state() != QProcess.ProcessState.NotRunning

def daemon_exit():
    if _MainObj.process is not None:
        _MainObj.process.waitForFinished(500)
