import os
from PyQt5.QtXml import QDomDocument

import ray

instance = None

class Daemon:
    net_daemon_id = 0
    root = ""
    session_path = ""
    pid = 0
    port = 0
    user = ""
    not_default = False

class MultiDaemonFile:
    file_path = '/tmp/RaySession/multi-daemon.xml'

    def __init__(self, session, server):
        self.session = session
        self.server = server

        self._xml = QDomDocument()

        global instance
        instance = self

    @staticmethod
    def get_instance():
        return instance

    def _pid_exists(self, pid)->bool:
        if isinstance(pid, str):
            pid = int(pid)

        try:
            os.kill(pid, 0)
        except OSError:
            return False
        else:
            return True

    def _remove_file(self):
        try:
            os.remove(self.file_path)
        except:
            return

    def _open_file(self)->bool:
        if not os.path.exists(self.file_path):
            dir_path = os.path.dirname(self.file_path)
            if not os.path.exists(dir_path):
                os.makedirs(dir_path)
                # give read/write access for all users
                os.chmod(dir_path, 0o777)

            return False

        try:
            file = open(self.file_path, 'r')
            self._xml.setContent(file.read())
            file.close()
            return True

        except:
            self._remove_file()
            return False

    def _write_file(self):
        try:
            file = open(self.file_path, 'w')
            file.write(self._xml.toString())
            file.close()
        except:
            return

    def _set_attributes(self, element):
        element.setAttribute('net_daemon_id', self.server.net_daemon_id)
        element.setAttribute('root', self.session.root)
        element.setAttribute('session_path', self.session.path)
        element.setAttribute('pid', os.getpid())
        element.setAttribute('port', self.server.port)
        element.setAttribute('user', os.getenv('USER'))
        element.setAttribute('not_default',
            int(bool(self.server.is_nsm_locked or self.server.not_default)))
        element.setAttribute('has_gui', int(self.server.has_gui()))
        element.setAttribute('version', ray.VERSION)
        element.setAttribute('local_gui_pids', self.server.get_local_gui_pid_list())

    def _clean_dirty_pids(self):
        xml_content = self._xml.documentElement()
        nodes = xml_content.childNodes()
        rm_nodes = []

        for i in range(nodes.count()):
            node = nodes.at(i)
            dxe = node.toElement()
            pid = dxe.attribute('pid')
            if not pid.isdigit() or not self._pid_exists(int(pid)):
                rm_nodes.append(node)

        for node in rm_nodes:
            xml_content.removeChild(node)

    def update(self):
        has_dirty_pid = False

        if not self._open_file():
            ds = self._xml.createElement('Daemons')
            dm_xml = self._xml.createElement('Daemon')

            self._set_attributes(dm_xml)

            ds.appendChild(dm_xml)
            self._xml.appendChild(ds)

        else:
            found = False
            xml_content = self._xml.documentElement()

            nodes = xml_content.childNodes()
            for i in range(nodes.count()):
                node = nodes.at(i)
                dxe = node.toElement()
                pid = dxe.attribute('pid')

                if pid.isdigit() and pid == str(os.getpid()):
                    self._set_attributes(dxe)
                    found = True
                elif not pid.isdigit() or not self._pid_exists(int(pid)):
                    has_dirty_pid = True

            if not found:
                dm_xml = self._xml.createElement('Daemon')
                self._set_attributes(dm_xml)
                self._xml.firstChild().appendChild(dm_xml)

        if has_dirty_pid:
            self._clean_dirty_pids()

        self._write_file()

    def quit(self):
        if not self._open_file():
            return

        xml_content = self._xml.documentElement()
        nodes = xml_content.childNodes()

        for i in range(nodes.count()):
            node = nodes.at(i)
            dxe = node.toElement()
            pid = dxe.attribute('pid')

            if pid.isdigit() and pid == str(os.getpid()):
                break
        else:
            return

        xml_content.removeChild(node)
        self._write_file()

    def is_free_for_root(self, daemon_id, root_path)->bool:
        if not self._open_file():
            return True

        xml_content = self._xml.documentElement()
        nodes = xml_content.childNodes()

        for i in range(nodes.count()):
            node = nodes.at(i)
            dxe = node.toElement()
            if (dxe.attribute('net_daemon_id') == str(daemon_id)
                    and dxe.attribute('root') == root_path):
                pid = dxe.attribute('pid')
                if pid.isdigit() and self._pid_exists(int(pid)):
                    return False

        return True

    def is_free_for_session(self, session_path)->bool:
        if not self._open_file():
            return True

        xml_content = self._xml.documentElement()
        nodes = xml_content.childNodes()

        for i in range(nodes.count()):
            node = nodes.at(i)
            dxe = node.toElement()
            if dxe.attribute('session_path') == session_path:
                pid = dxe.attribute('pid')
                if pid.isdigit() and self._pid_exists(int(pid)):
                    return False

        return True

    def get_all_session_paths(self)->list:
        if not self._open_file():
            return []

        all_session_paths = []

        xml_content = self._xml.documentElement()
        nodes = xml_content.childNodes()

        for i in range(nodes.count()):
            node = nodes.at(i)
            dxe = node.toElement()
            spath = dxe.attribute('session_path')
            pid = dxe.attribute('pid')
            if spath and pid.isdigit() and self._pid_exists(int(pid)):
                all_session_paths.append(spath)

        return all_session_paths

    def get_daemon_list(self)->list:
        daemon_list = []
        has_dirty_pid = False

        if not self._open_file():
            return daemon_list

        xml_content = self._xml.documentElement()
        nodes = xml_content.childNodes()

        for i in range(nodes.count()):
            node = nodes.at(i)
            dxe = node.toElement()

            daemon = Daemon()
            daemon.root = dxe.attribute('root')
            daemon.session_path = dxe.attribute('session_path')
            daemon.user = dxe.attribute('user')
            daemon.not_default = bool(dxe.attribute('not_default') == 'true')
            net_daemon_id = dxe.attribute('net_daemon_id')
            pid = dxe.attribute('pid')
            port = dxe.attribute('port')

            if net_daemon_id.isdigit():
                daemon.net_daemon_id = net_daemon_id
            if pid.isdigit():
                daemon.pid = pid
            if port.isdigit():
                daemon.port = port

            if not self._pid_exists(daemon.pid):
                has_dirty_pid = True
                continue

            if not (daemon.net_daemon_id
                    and daemon.pid
                    and daemon.port):
                continue

            daemon_list.append(daemon)

        if has_dirty_pid:
            self._clean_dirty_pids()

        return daemon_list
