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

        self.xml = QDomDocument()

        global instance
        instance = self

    @staticmethod
    def getInstance():
        return instance

    def pidExists(self, pid):
        if isinstance(pid, str):
            pid = int(pid)

        try:
            os.kill(pid, 0)
        except OSError:
            return False
        else:
            return True

    def removeFile(self):
        try:
            os.remove(self.file_path)
        except:
            return

    def openFile(self):
        if not os.path.exists(self.file_path):
            dir_path = os.path.dirname(self.file_path)
            if not os.path.exists(dir_path):
                os.makedirs(dir_path)
                # give read/write access for all users
                os.chmod(dir_path, 0o777)

            return False

        try:
            file = open(self.file_path, 'r')
            self.xml.setContent(file.read())
            file.close()
            return True

        except:
            self.removeFile()
            return False

    def writeFile(self):
        try:
            file = open(self.file_path, 'w')
            file.write(self.xml.toString())
            file.close()
        except:
            return

    def setAttributes(self, element):
        element.setAttribute('net_daemon_id', self.server.net_daemon_id)
        element.setAttribute('root', self.session.root)
        element.setAttribute('session_path', self.session.path)
        element.setAttribute('pid', os.getpid())
        element.setAttribute('port', self.server.port)
        element.setAttribute('user', os.getenv('USER'))
        element.setAttribute('not_default',
            int(bool(self.server.is_nsm_locked or self.server.not_default)))
        element.setAttribute('has_gui', int(self.server.hasGui()))
        element.setAttribute('version', ray.VERSION)

    def update(self):
        has_dirty_pid = False

        if not self.openFile():
            ds = self.xml.createElement('Daemons')
            dm_xml = self.xml.createElement('Daemon')

            self.setAttributes(dm_xml)

            ds.appendChild(dm_xml)
            self.xml.appendChild(ds)

        else:
            found = False
            xml_content = self.xml.documentElement()

            nodes = xml_content.childNodes()
            for i in range(nodes.count()):
                node = nodes.at(i)
                dxe = node.toElement()
                pid = dxe.attribute('pid')

                if pid.isdigit() and pid == str(os.getpid()):
                    self.setAttributes(dxe)
                    found = True
                elif not pid.isdigit() or not self.pidExists(int(pid)):
                    has_dirty_pid = True

            if not found:
                dm_xml = self.xml.createElement('Daemon')
                self.setAttributes(dm_xml)
                self.xml.firstChild().appendChild(dm_xml)

        if has_dirty_pid:
            self.cleanDirtyPids()

        self.writeFile()

    def quit(self):
        if not self.openFile():
            return

        xml_content = self.xml.documentElement()
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
        self.writeFile()

    def isFreeForRoot(self, daemon_id, root_path):
        if not self.openFile():
            return True

        xml_content = self.xml.documentElement()
        nodes = xml_content.childNodes()

        for i in range(nodes.count()):
            node = nodes.at(i)
            dxe = node.toElement()
            if (dxe.attribute('net_daemon_id') == str(daemon_id)
                    and dxe.attribute('root') == root_path):
                pid = dxe.attribute('pid')
                if pid.isdigit() and self.pidExists(int(pid)):
                    return False

        return True

    def isFreeForSession(self, session_path):
        if not self.openFile():
            return True

        xml_content = self.xml.documentElement()
        nodes = xml_content.childNodes()

        for i in range(nodes.count()):
            node = nodes.at(i)
            dxe = node.toElement()
            if dxe.attribute('session_path') == session_path:
                pid = dxe.attribute('pid')
                if pid.isdigit() and self.pidExists(int(pid)):
                    return False

        return True

    def getAllSessionPaths(self):
        if not self.openFile():
            return []

        all_session_paths = []

        xml_content = self.xml.documentElement()
        nodes = xml_content.childNodes()

        for i in range(nodes.count()):
            node = nodes.at(i)
            dxe = node.toElement()
            spath = dxe.attribute('session_path')
            pid = dxe.attribute('pid')
            if spath and pid.isdigit() and self.pidExists(int(pid)):
                all_session_paths.append(spath)

        return all_session_paths

    def cleanDirtyPids(self):
        xml_content = self.xml.documentElement()
        nodes = xml_content.childNodes()
        rm_nodes = []

        for i in range(nodes.count()):
            node = nodes.at(i)
            dxe = node.toElement()
            pid = dxe.attribute('pid')
            if not pid.isdigit() or not self.pidExists(int(pid)):
                rm_nodes.append(node)

        for node in rm_nodes:
            xml_content.removeChild(node)

    def getDaemonList(self):
        daemon_list = []
        has_dirty_pid = False

        if not self.openFile():
            return daemon_list

        xml_content = self.xml.documentElement()
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

            if not self.pidExists(daemon.pid):
                has_dirty_pid = True
                continue

            if not (daemon.net_daemon_id
                    and daemon.pid
                    and daemon.port):
                continue

            daemon_list.append(daemon)

        if has_dirty_pid:
            self.cleanDirtyPids()

        return daemon_list
