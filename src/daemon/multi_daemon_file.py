
# Imports from standard library
import logging
import os
from typing import TYPE_CHECKING, Union, Optional
from pathlib import Path
import json

# Imports from src/shared
import ray

if TYPE_CHECKING:
    from session import Session
    from osc_server_thread import OscServerThread


class _Main:
    def __init__(self):
        self.session: 'Optional[Session]' = None
        self.server: 'Optional[OscServerThread]' = None
        self.json_list: Optional[list[dict]] = None
        self.locked_sess_paths = set[str]()


class Daemon:
    net_daemon_id = 0
    root = ""
    session_path = ""
    pid = 0
    port = 0
    user = ""
    not_default = False


_logger = logging.getLogger(__name__)
_main = _Main()
FILE_PATH = Path('/tmp/RaySession/multi-daemon.json')


def _pid_exists(pid: int) -> bool:
    if not isinstance(pid, int):
        return False
    
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    else:
        return True

def _remove_file():
    try:
        FILE_PATH.unlink(missing_ok=True)
    except BaseException as e:
        _logger.warning(
            f"Failed to remove multi_daemon_file {FILE_PATH}\n"
            f"{str(e)}")
        return

def _open_file() -> bool:
    if not FILE_PATH.exists():
        FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        # give read/write access for all users
        os.chmod(FILE_PATH.parent, 0o777)
        
        return False

    try:
        with open(FILE_PATH, 'r') as f:
            json_list = json.load(f)
            assert isinstance(json_list, list)
            for dmn in json_list:
                assert isinstance(dmn, dict)
            _main.json_list = json_list
        return True

    except:
        _remove_file()
        _main.json_list = None
        return False

def _write_file():
    if _main.json_list is None:
        return

    try:
        with open(FILE_PATH, 'w') as f:
            json.dump(_main.json_list, f, indent=2)
    except BaseException as e:
        _logger.warning(f'failed to write {FILE_PATH}\n{str(e)}')
        return

def _get_dict_for_this() -> dict[str, str | int | bool]:
    if _main.server is None or _main.session is None:
        return {}
    
    ret_dict = {
        'net_daemon_id': _main.server.net_daemon_id,
        'root': str(_main.session.root),
        'session_path': str(_main.session.path) if _main.session.path else '',
        'pid': os.getpid(),
        'port': _main.server.port,
        'user': os.getenv('USER', ''),
        'not_default': _main.server.is_nsm_locked or _main.server.not_default,
        'has_gui': _main.server.has_gui(),
        'version': ray.VERSION,
        'local_gui_pids': _main.server.get_local_gui_pid_list()
    }
    
    ret_dict['locked_sessions'] = list[str]()
    for locked_path in _main.locked_sess_paths:
        ret_dict['locked_sessions'].append(locked_path)
    return ret_dict

def _clean_dirty_pids():
    if _main.json_list is None:
        return
    
    rm_dmns = list[dict]()
    
    for dmn in _main.json_list:
        pid = dmn.get('pid')        
        if not isinstance(pid, int) or not pid or not _pid_exists(pid):
            rm_dmns.append(dmn)
    
    for dmn in rm_dmns:
        _main.json_list.remove(dmn)

def init(session :'Session', server: 'OscServerThread'):
    _main.session = session
    _main.server = server

def update():
    if not _open_file():
        _main.json_list = [_get_dict_for_this()]

    else:
        has_dirty_pid = False
        self_dmn: Optional[dict] = None
        
        if _main.json_list is not None:
            for dmn in _main.json_list:
                pid = dmn.get('pid')
                if pid == os.getpid():
                    self_dmn = dmn
                elif pid and not _pid_exists(pid):
                    has_dirty_pid = True
        
            if self_dmn is not None:
                _main.json_list.remove(self_dmn)
            _main.json_list.append(_get_dict_for_this())
        
        if has_dirty_pid:
            _clean_dirty_pids()
        
    _write_file()

def quit():
    if not _open_file():
        return

    if _main.json_list is None:
        return

    for dmn in _main.json_list:
        if dmn.get('pid') == os.getpid():
            _main.json_list.remove(dmn)
            _write_file()
            break

def is_free_for_root(daemon_id: int, root_path: Path) -> bool:
    if not _open_file() or _main.json_list is None:
        return True

    for dmn in _main.json_list:
        if (dmn.get('net_daemon_id') == daemon_id
                and dmn.get('root') == str(root_path)):
            pid = dmn.get('pid')
            if pid and _pid_exists(pid):
                return False
    return True

def is_free_for_session(session_path: Union[str, Path]) -> bool:
        session_path = str(session_path)
        
        if not _open_file() or _main.json_list is None:
            return True

        for dmn in _main.json_list:
            pid = dmn.get('pid')
            if dmn.get('session_path') == str(session_path):
                if pid and _pid_exists(pid):
                    return False
                
            locked_sessions = dmn.get('locked_sessions')
            if not isinstance(locked_sessions, list):
                continue
            
            for locked_session in locked_sessions:
                if locked_session == str(session_path):
                    if pid and _pid_exists(pid):
                        return False

        return True

def get_all_session_paths() -> list[str]:
    all_session_paths = list[str]()

    if not _open_file() or _main.json_list is None:
        return all_session_paths

    for dmn in _main.json_list:
        spath = dmn.get('session_path')
        pid = dmn.get('pid')
        if isinstance(spath, str) and pid and _pid_exists(pid):
            all_session_paths.append(spath)
    
    return all_session_paths

def add_locked_path(path: Path):
    _main.locked_sess_paths.add(str(path))
    update()

def unlock_path(path: Path):
    _main.locked_sess_paths.discard(str(path))
    update()

def get_daemon_list() -> list[Daemon]:
    daemon_list = list[Daemon]()

    if not _open_file() or _main.json_list is None:
        return daemon_list

    for dmn in _main.json_list:
        daemon = Daemon()
        daemon.root = str(dmn.get('root'))
        daemon.session_path = str(dmn.get('session_path'))
        daemon.user = str(dmn.get('user'))
        daemon.not_default = bool(dmn.get('not_default'))
        daemon.net_daemon_id = int(dmn.get('net_daemon_id'))
        daemon.pid = int(dmn.get('pid'))
        daemon.port = int(dmn.get('port'))
        
        if not _pid_exists(daemon.pid):
            continue
        
        if not (daemon.net_daemon_id
                and daemon.pid
                and daemon.port):
            continue
        
        daemon_list.append(daemon)
    return daemon_list
