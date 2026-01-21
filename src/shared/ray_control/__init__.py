'''Python module giving access to all functions available with
`ray_control` executable.

It does not manages the `ray_control` executable, it gives access to
the same functions, but in python, not in shell.'''

import os
from pathlib import Path
import subprocess
import time
import types
import sys
from typing import TYPE_CHECKING, Callable

import osc_paths.ray as r

from . import utils
from .sender import OscServer

client = types.ModuleType('client')
trashed_client = types.ModuleType('trashed_client')

if TYPE_CHECKING:
    from server import *
    from session import *
    import client
    import trashed_client


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


class Client:
    def __init__(self, client_id: str) -> None:
        self.client_id = client_id
        
    @property
    def executable(self) -> str:
        props = client.get_properties(self.client_id)
        for line in props.splitlines():
            if line.startswith('executable:'):
                return line.partition(':')[2]
        return ''
    
    @executable.setter
    def executable(self, value: str):
        props = client.get_properties(self.client_id)
        if not isinstance(props, str):
            return
        
        split_props = props.splitlines()
        for i, line in enumerate(split_props):
            if line.startswith('executable:'):
                split_props[i] = f'executable:{value}'
        
        client.set_properties(self.client_id, '\n'.join(split_props))


if TYPE_CHECKING:
    from Client import Client


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

def _send_and_wait(path: str, *args, start_server=False):
    _update_daemons()
    if not m.daemon_started:
        if start_server:
            _start_daemon()
            _update_daemons()
        else:
            raise NoServerStarted

    # print(f'{m.daemon_port=} {path=} {args=}')
    m.sender.send(m.daemon_port, path, *args)
    while not m.sender.op_done:
        m.sender.recv(50)
    
    return m.sender.ret

def create_function(osc_path: str, start_server=False):
    return lambda *args: _send_and_wait(
        osc_path, *args, start_server=start_server)

# def _send_and_wait_cl(self: Client, path: str, *args):
#     _update_daemons()
#     if not m.daemon_started:
#         raise NoServerStarted

#     print(f'{m.daemon_port=} {path=} {args=}')
#     m.sender.send(m.daemon_port, path, self.client_id, *args)
#     while not m.sender.op_done:
#         m.sender.recv(50)
    
#     return m.sender.ret

# def create_function_cl(osc_path: str):
#     return lambda *args: _send_and_wait_cl(osc_path, *args)


for var, value in r.server.__dict__.items():
    if isinstance(value, str) and value.startswith('/ray/server/'):
        setattr(sys.modules[__name__], var.lower(),
                create_function(value, start_server=True))

for var, value in r.session.__dict__.items():
    if isinstance(value, str) and value.startswith('/ray/session/'):
        setattr(sys.modules[__name__], var.lower(), create_function(value))

client_funcs = dict[str, Callable]()

for var, value in r.client.__dict__.items():
    if isinstance(value, str) and value.startswith('/ray/client/'):
        client_func = create_function(value)
        client_funcs[var.lower()] = client_func
        setattr(client, var.lower(), client_func)
        
for var, value in r.trashed_client.__dict__.items():
    if isinstance(value, str) and value.startswith('/ray/trashed_client/'):
        client_func = create_function(value)
        client_funcs[var.lower()] = client_func
        setattr(trashed_client, var.lower(), client_func)

func_names = set(client_funcs.keys())
for func_name in func_names:
    def generate_method(name):
        def method(self: 'Client', *args):
            client_func = client_funcs[name]
            return client_func(self.client_id, *args)
        return method
    setattr(Client, func_name, generate_method(func_name))


def clients(started: bool | None =None,
            active: bool | None =None,
            auto_start: bool | None=None,
            no_save_level: bool | None =None) -> list[Client]:
    d = {'started': started,
         'active': active,
         'auto_start': auto_start,
         'no_save_level': no_save_level}
    options = list[str]()
    for key, value in d.items():
        if value is not None:
            if value:
                options.append(key)
            else:
                options.append('not_' + key)
    print(f'{options=}')
    return [Client(client_id) for client_id in list_clients(*options)]

def trashed_clients() -> list[Client]:
    return [Client(client_id) for client_id in list_trashed_clients()]

# from .server import *
# from .session import *

utils.add_self_bin_to_path()

m.wanted_port = 0

dport = os.getenv('RAY_CONTROL_PORT')
if dport is not None and dport.isdigit():
    m.wanted_port = int(dport)

_update_daemons()
    


# Client._generate_subs()
    