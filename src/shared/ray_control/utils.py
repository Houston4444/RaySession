import json
import os
from pathlib import Path


class Daemon:
    net_daemon_id = 0
    root = ""
    session_path = ""
    pid = 0
    port = 0
    user = ""
    not_default = False
    has_gui = 0
    has_local_gui = 0
    
    def __init__(self):
        self.local_gui_pids = list[int]()


def pid_exists(pid: int | str) -> bool:
    if isinstance(pid, str):
        pid = int(pid)

    try:
        os.kill(pid, 0)
    except OSError:
        return False
    else:
        return True

def pid_is_stopped(pid: int) -> bool:
    proc_file_path = f'/proc/{pid}/status'
    if os.path.exists(proc_file_path):
        proc_file = open(proc_file_path)
        for line in proc_file.readlines():
            if line.startswith('State:	'):
                value = line.replace('State:	', '', 1)
                if value and value[0] == 'T':
                    return True
        return False
    return True

def get_daemon_list() -> list[Daemon]:
    try:
        with open('/tmp/RaySession/multi-daemon.json') as f:
            json_list = json.load(f)
    
    except:
        return list[Daemon]()
    
    if not isinstance(json_list, list):
        return list[Daemon]()
    
    l_daemon_list = list[Daemon]()

    for dmn in json_list:
        if not isinstance(dmn, dict):
            continue
        
        l_daemon = Daemon()
        
        for key, value in dmn.items():
            match key:
                case 'root':
                    l_daemon.root = str(value)
                case 'session_path':
                    l_daemon.session_path = str(value)
                case 'user':
                    l_daemon.user = str(value)
                case 'not_default':
                    l_daemon.not_default = bool(value)
                case 'net_daemon_id':
                    if isinstance(value, int):
                        l_daemon.net_daemon_id = int(value)
                case 'pid':
                    if isinstance(value, int) and pid_exists(value):
                        l_daemon.pid = value
                case 'port':
                    if isinstance(value, int):
                        l_daemon.port = value
                case 'has_gui':
                    if isinstance(value, int):
                        l_daemon.has_gui = bool(value == 1)
                        l_daemon.has_local_gui = bool(value == 3)
                    
                case 'local_gui_pids':
                    if isinstance(value, list):
                        for pid in value:
                            if isinstance(pid, int):
                                l_daemon.local_gui_pids.append(pid)

        if not (l_daemon.net_daemon_id
                and l_daemon.pid
                and l_daemon.port):
            continue

        l_daemon_list.append(l_daemon)
    return l_daemon_list

def add_self_bin_to_path():
    # Add raysession/src/bin to $PATH to can use ray executables after make
    # Warning, will works only if link to this file is in RaySession/*/*/*.py
    bin_path = Path(__file__).parents[2] / 'bin'
    path_env = os.environ.get('PATH', '')
    if path_env.split(':')[0] != bin_path:
        os.environ['PATH'] = f'{bin_path}:{path_env}'