
# Imports from standard library
import logging
import os
from typing import TYPE_CHECKING, Union, Optional
from pathlib import Path
import xml.etree.ElementTree as ET
from xml.etree.ElementTree import ElementTree

# Imports from src/shared
import ray
from xml_tools import XmlElement

if TYPE_CHECKING:
    from session import Session
    from osc_server_thread import OscServerThread



class _Main:
    def __init__(self):
        self.session: 'Optional[Session]' = None
        self.server: 'Optional[OscServerThread]' = None
        self.xml_tree: 'Optional[ElementTree]' = None
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
FILE_PATH = Path('/tmp/RaySession/multi-daemon.xml')

def _pid_exists(pid: int) -> bool:
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
        _main.xml_tree = ET.parse(FILE_PATH)
        return True

    except:
        _remove_file()
        _main.xml_tree = None
        return False

def _write_file():
    if _main.xml_tree is None:
        return
    
    try:
        ET.indent(_main.xml_tree.getroot(), space='  ', level=0)
        _main.xml_tree.write(
            FILE_PATH, encoding="UTF-8", xml_declaration=True)
    except:
        return

def _set_attributes(xel: XmlElement):
    if _main.server is None or _main.session is None:
        return
    
    xel.set_int('net_daemon_id', _main.server.net_daemon_id)
    xel.set_str('root', _main.session.root)
    xel.set_str('session_path', _main.session.path)
    xel.set_int('pid', os.getpid())
    xel.set_int('port', _main.server.port)
    xel.set_str('user', os.getenv('USER', ''))
    xel.set_bool('not_default',
                    _main.server.is_nsm_locked or _main.server.not_default)
    xel.set_bool('has_gui', _main.server.has_gui())
    xel.set_str('version', ray.VERSION)
    xel.set_str('local_gui_pids', _main.server.get_local_gui_pid_list())

    for locked_path in _main.locked_sess_paths:
        lp_xml = ET.Element('locked_session')
        lp_xml.attrib['path'] = locked_path
        xel.el.append(lp_xml)

def _clean_dirty_pids():
    if _main.xml_tree is None:
        return
    
    root = _main.xml_tree.getroot()
    rm_childs = list[ET.Element]()
    
    for child in root:
        xchild = XmlElement(child)
        pid = xchild.int('pid')
        if not pid or not _pid_exists(pid):
            rm_childs.append(child)
    
    for child in rm_childs:
        root.remove(child)

def init(session :'Session', server: 'OscServerThread'):
    _main.session = session
    _main.server = server

def update():
    if not _open_file():
        root = ET.Element('Daemons')
        dm_child = ET.Element('Daemon')

        _set_attributes(XmlElement(dm_child))

        root.append(dm_child)
        _main.xml_tree = ET.ElementTree(element=root)

    else:
        has_dirty_pid = False
        
        root = _main.xml_tree.getroot()
        self_child: Optional[ET.Element] = None
        
        for child in root:
            xchild = XmlElement(child)
            pid = xchild.int('pid')
            
            if pid == os.getpid():
                self_child = child
            elif pid and _pid_exists(pid):
                has_dirty_pid = True
        
        if self_child is not None:
            root.remove(self_child)
            
        dm_child = ET.Element('Daemon')            
        _set_attributes(XmlElement(dm_child))
        root.append(dm_child)
        
        if has_dirty_pid:
            _clean_dirty_pids()
    
    _write_file()

def quit():
    if not _open_file():
        return

    root = _main.xml_tree.getroot()
    
    for child in root:
        xchild = XmlElement(child)
        if xchild.int('pid') == os.getpid():
            root.remove(child)
            _write_file()
            break

def is_free_for_root(daemon_id: int, root_path: Path) -> bool:
    if not _open_file() or _main.xml_tree is None:
        return True

    root = _main.xml_tree.getroot()
    
    for child in root:
        xchild = XmlElement(child)
        if (xchild.int('net_daemon_id') == daemon_id
                and xchild.str('root') == str(root_path)):
            pid = xchild.int('pid')
            if pid and _pid_exists(pid):
                return False
        
    return True

def is_free_for_session(session_path: Union[str, Path]) -> bool:
        session_path = str(session_path)
        
        if not _open_file() or _main.xml_tree is None:
            return True

        root = _main.xml_tree.getroot()
        
        for child in root:
            xchild = XmlElement(child)
            pid = xchild.int('pid')
            if xchild.str('session_path') == session_path:
                if pid and _pid_exists(pid):
                    return False
                
            for cchild in child:
                xc_child = XmlElement(cchild)
                if xc_child.str('path') == session_path:
                    if pid and _pid_exists(pid):
                        return False
                    
        return True

def get_all_session_paths() -> list[str]:
    all_session_paths = list[str]()

    if not _open_file() or _main.xml_tree is None:
        return all_session_paths

    root = _main.xml_tree.getroot()
    
    for child in root:
        xchild = XmlElement(child)
        spath = xchild.str('session_path')
        pid = xchild.int('pid')
        if spath and pid and _pid_exists(pid):
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

    if not _open_file() or _main.xml_tree is None:
        return daemon_list

    root = _main.xml_tree.getroot()
    
    for child in root:
        xchild = XmlElement(child)
        daemon = Daemon()
        daemon.root = xchild.str('root')
        daemon.session_path = xchild.str('session_path')
        daemon.user = xchild.str('user')
        daemon.not_default = xchild.bool('not_default')
        daemon.net_daemon_id = xchild.int('net_daemon_id')
        daemon.pid = xchild.int('pid')
        daemon.port = xchild.int('port')
        
        if not _pid_exists(daemon.pid):
            continue
        
        if not (daemon.net_daemon_id
                and daemon.pid
                and daemon.port):
            continue

        daemon_list.append(daemon)
        
    return daemon_list
