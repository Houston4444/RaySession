
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


_logger = logging.getLogger(__name__)
_instance = None


class Daemon:
    net_daemon_id = 0
    root = ""
    session_path = ""
    pid = 0
    port = 0
    user = ""
    not_default = False


class MultiDaemonFile:
    FILE_PATH = Path('/tmp/RaySession/multi-daemon.xml')

    def __init__(self, session: 'Session', server: 'OscServerThread'):
        self.session = session
        self.server = server

        self._xml_tree: Optional[ElementTree] = None

        global _instance
        _instance = self

        self._locked_session_paths = set[str]()

    @staticmethod
    def get_instance():
        return _instance

    def _pid_exists(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        else:
            return True

    def _remove_file(self):
        try:
            self.FILE_PATH.unlink(missing_ok=True)
        except BaseException as e:
            _logger.warning(
                f"Failed to remove multi_daemon_file {self.FILE_PATH}\n"
                f"{str(e)}")
            return

    def _open_file(self) -> bool:
        if not self.FILE_PATH.exists():
            self.FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
            # give read/write access for all users
            os.chmod(self.FILE_PATH.parent, 0o777)
            
            return False

        try:
            self._xml_tree = ET.parse(self.FILE_PATH)
            return True

        except:
            self._remove_file()
            self._xml_tree = None
            return False

    def _write_file(self):        
        try:
            ET.indent(self._xml_tree.getroot(), space='  ', level=0)
            self._xml_tree.write(
                self.FILE_PATH, encoding="UTF-8", xml_declaration=True)
        except:
            return

    def _set_attributes(self, xel: XmlElement):
        xel.set_int('net_daemon_id', self.server.net_daemon_id)
        xel.set_str('root', self.session.root)
        xel.set_str('session_path', self.session.path)
        xel.set_int('pid', os.getpid())
        xel.set_int('port', self.server.port)
        xel.set_str('user', os.getenv('USER', ''))
        xel.set_bool('not_default',
                     self.server.is_nsm_locked or self.server.not_default)
        xel.set_bool('has_gui', self.server.has_gui())
        xel.set_str('version', ray.VERSION)
        xel.set_str('local_gui_pids', self.server.get_local_gui_pid_list())

        for locked_path in self._locked_session_paths:
            lp_xml = ET.Element('locked_session')
            lp_xml.attrib['path'] = locked_path
            xel.el.append(lp_xml)

    def _clean_dirty_pids(self):
        root = self._xml_tree.getroot()
        rm_childs = list[ET.Element]()
        
        for child in root:
            xchild = XmlElement(child)
            pid = xchild.int('pid')
            if not pid or not self._pid_exists(pid):
                rm_childs.append(child)
        
        for child in rm_childs:
            root.remove(child)

    def update(self):
        if not self._open_file():
            root = ET.Element('Daemons')
            dm_child = ET.Element('Daemon')

            self._set_attributes(XmlElement(dm_child))

            root.append(dm_child)
            self._xml_tree = ET.ElementTree(element=root)

        else:
            has_dirty_pid = False
            
            root = self._xml_tree.getroot()
            self_child: Optional[ET.Element] = None
            
            for child in root:
                xchild = XmlElement(child)
                pid = xchild.int('pid')
                
                if pid == os.getpid():
                    self_child = child
                elif pid and self._pid_exists(pid):
                    has_dirty_pid = True
            
            if self_child is not None:
                root.remove(self_child)
                
            dm_child = ET.Element('Daemon')            
            self._set_attributes(XmlElement(dm_child))
            root.append(dm_child)
            
            if has_dirty_pid:
                self._clean_dirty_pids()
        
        self._write_file()

    def quit(self):
        if not self._open_file():
            return

        root = self._xml_tree.getroot()
        
        for child in root:
            xchild = XmlElement(child)
            if xchild.int('pid') == os.getpid():
                root.remove(child)
                self._write_file()
                break

    def is_free_for_root(self, daemon_id: int, root_path: Path) -> bool:
        if not self._open_file():
            return True

        root = self._xml_tree.getroot()
        
        for child in root:
            xchild = XmlElement(child)
            if (xchild.int('net_daemon_id') == daemon_id
                    and xchild.str('root') == str(root_path)):
                pid = xchild.int('pid')
                if pid and self._pid_exists(pid):
                    return False
            
        return True

    def is_free_for_session(self, session_path: Union[str, Path]) -> bool:
        session_path = str(session_path)
        
        if not self._open_file():
            return True

        root = self._xml_tree.getroot()
        
        for child in root:
            xchild = XmlElement(child)
            pid = xchild.int('pid')
            if xchild.str('session_path') == session_path:
                if pid and self._pid_exists(pid):
                    return False
                
            for cchild in child:
                xc_child = XmlElement(cchild)
                if xc_child.str('path') == session_path:
                    if pid and self._pid_exists(pid):
                        return False
                    
        return True

    def get_all_session_paths(self) -> list[str]:
        all_session_paths = list[str]()

        if not self._open_file():
            return all_session_paths

        root = self._xml_tree.getroot()
        
        for child in root:
            xchild = XmlElement(child)
            spath = xchild.str('session_path')
            pid = xchild.int('pid')
            if spath and pid and self._pid_exists(pid):
                all_session_paths.append(spath)
        
        return all_session_paths

    def add_locked_path(self, path: Path):
        self._locked_session_paths.add(str(path))
        self.update()
    
    def unlock_path(self, path: Path):
        self._locked_session_paths.discard(str(path))
        self.update()

    def get_daemon_list(self) -> list[Daemon]:
        daemon_list = list[Daemon]()

        if not self._open_file():
            return daemon_list

        root = self._xml_tree.getroot()
        
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
            
            if not self._pid_exists(daemon.pid):
                continue
            
            if not (daemon.net_daemon_id
                    and daemon.pid
                    and daemon.port):
                continue

            daemon_list.append(daemon)
            
        return daemon_list
