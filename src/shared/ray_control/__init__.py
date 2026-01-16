'''Python module giving access to all functions available with
`ray_control` executable.

It does not manages the `ray_control` executable, it gives access to
the same functions, but in python, not in shell.'''

import os
from pathlib import Path
import subprocess
import time

from . import utils
from .sender import OscServer


class NoServerStarted(Exception):
    def __init__(self, *args):
        super().__init__(*args)


class ServerStopFailed(Exception):
    def __init__(self, *args):
        super().__init__(*args)


class MainObject:
    wanted_port = 0
    daemon_port = 0
    daemon_started = False
    daemon_announced = False
    last_daemons_check = 0.0
    daemon_process: subprocess.Popen | None = None
    daemon_list = list[utils.Daemon]()
    sender = OscServer()


m = MainObject()


def start():
    _update_daemons()
    if m.daemon_started:
        return
    _start_daemon()
    
def start_new():
    _update_daemons()
    _start_daemon()
    
def start_new_hidden():
    _update_daemons()
    _start_daemon(hidden=True)

def stop():
    _update_daemons()
    if not m.daemon_started:
        return
    
    daemon_port_list = list[int]()

    if m.wanted_port:
        daemon_port_list.append(m.wanted_port)
    else:
        for daemon in m.daemon_list:
            if (daemon.user == os.getenv('USER')
                    and not daemon.not_default):
                daemon_port_list.append(daemon.port)

    m.sender.stop_daemons(daemon_port_list)

    start_loop = time.time()
    while True:
        if m.sender.recv(50):
            if not m.sender._stop_port_list:
                break
        
        if time.time() - start_loop > 30.0:
            raise ServerStopFailed

    while True:
        _update_daemons()
        if not m.daemon_started:
            break
        time.sleep(0.001)
        if time.time() - start_loop > 30.0:
            raise ServerStopFailed
        

def list_daemons() -> list[int]:
    _update_daemons()
    return [d.port for d in m.daemon_list if not d.not_default]

def get_root() -> str:
    _update_daemons()
    for daemon in m.daemon_list:
        if daemon.port == m.daemon_port:
            return daemon.root
    
    raise NoServerStarted

def get_port() -> int:
    _update_daemons()
    return m.daemon_port

def get_port_gui_free(wanted_session_root='') -> int | None:
    _update_daemons()
    for daemon in m.daemon_list:
        if (daemon.user == os.environ['USER']
                and (daemon.root == wanted_session_root
                    or not wanted_session_root)
                and not daemon.not_default):
            if not daemon.has_local_gui:
                return daemon.port

            for pid in daemon.local_gui_pids:
                if pid == 0:
                    # This means we don't know the pid of the local GUI
                    # So consider this daemon has already a GUI
                    break

                if utils.pid_exists(pid) and not utils.pid_is_stopped(pid):
                    break
            else:
                return daemon.port

def get_pid() -> int:
    _update_daemons()
    for daemon in m.daemon_list:
        if daemon.port == m.daemon_port:
            return daemon.pid
    
    raise NoServerStarted

def get_session_path() -> str:
    _update_daemons()
    for daemon in m.daemon_list:
        if daemon.port == m.daemon_port:
            return daemon.session_path
    
    raise NoServerStarted

def has_local_gui() -> bool:
    _update_daemons()
    for daemon in m.daemon_list:
        if daemon.port == m.daemon_port:
            return bool(daemon.has_local_gui)
    return False

def has_gui() -> bool:
    _update_daemons()
    for daemon in m.daemon_list:
        if daemon.port == m.daemon_port:
            return bool(daemon.has_gui)
    return False

def _start_daemon(hidden=False):
    session_root = Path.home() / 'Ray Sessions'
    try:
        config_file = Path.home() / '.config/RaySession/RaySession.conf'
        with open(config_file, 'r') as f:
            contents = f.read()
    except:
        pass
    else:
        for line in contents.splitlines():
            if line.startswith('default_session_root='):
                session_root = line.partition('=')[2]
                break
    
    process_args = ['ray-daemon', '--control-url', str(m.sender.url),
                    '--session-root', session_root]

    if m.wanted_port:
        process_args.append('--osc-port')
        process_args.append(str(m.wanted_port))

    if hidden:
        process_args.append('--hidden')
        process_args.append('--no-options')

    m.daemon_process = subprocess.Popen(
        process_args, -1, None, None,
        subprocess.DEVNULL, subprocess.DEVNULL)

    m.sender.wait_for_start = True
    
    for i in range(60): # 3 seconds
        if m.sender.recv(50):
            if not m.sender.wait_for_start:
                break
    else:
        raise NoServerStarted
        
    # server.wait_for_start()

    # if (operation_type is OperationType.CONTROL
    #         and operation in ('start', 'start_new', 'start_new_hidden')):
    #     server.wait_for_start_only()

def _update_daemons():
    m.daemon_announced = False
    m.daemon_list = utils.get_daemon_list()
    m.last_daemons_check = time.time()
    m.daemon_port = 0
    m.daemon_started = True
    
    for daemon in m.daemon_list:
        if ((daemon.user == os.environ['USER']
                    and not m.wanted_port and not daemon.not_default)
                or (m.wanted_port == daemon.port)):
            m.daemon_port = daemon.port
            break
    else:
        m.daemon_started = False
    

if True:
    utils.add_self_bin_to_path()
    
    m.wanted_port = 0

    dport = os.getenv('RAY_CONTROL_PORT')
    if dport is not None and dport.isdigit():
        m.wanted_port = int(dport)
    
    _update_daemons()