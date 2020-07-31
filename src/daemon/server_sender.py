
from PyQt5.QtCore import QObject

import ray

from osc_server_thread import OscServerThread

class ServerSender(QObject):
    def __init__(self):
        QObject.__init__(self)
        self.is_dummy = False

    def hasServer(self):
        if not OscServerThread.getInstance():
            return False

        return not self.is_dummy

    def send(self, *args):
        if self.is_dummy:
            return

        server = OscServerThread.getInstance()
        if not server:
            return

        server.send(*args)

    def sendEvenDummy(self, *args):
        server = OscServerThread.getInstance()
        if not server:
            return

        server.send(*args)

    def sendGui(self, *args):
        if self.is_dummy:
            return

        server = OscServerThread.getInstance()
        if not server:
            return

        server.sendGui(*args)

    def sendGuiMessage(self, message):
        self.sendGui('/ray/gui/server/message', message)

        server = OscServerThread.getInstance()
        if server:
            server.sendControllerMessage(message)

    def setServerStatus(self, server_status):
        if self.is_dummy:
            return

        server = OscServerThread.getInstance()
        if not server:
            return

        server.setServerStatus(server_status)

    def getServerStatus(self):
        if self.is_dummy:
            return -1

        server = OscServerThread.getInstance()
        if not server:
            return -1

        return server.server_status

    def isNsmLocked(self):
        if self.is_dummy:
            return False

        server = OscServerThread.getInstance()
        if not server:
            return False

        return server.is_nsm_locked

    def getServer(self):
        return OscServerThread.getInstance()

    def getServerUrl(self):
        server = OscServerThread.getInstance()
        if server:
            return server.url

        return ''

    def getServerPort(self):
        server = OscServerThread.getInstance()
        if server:
            return server.port

        return 0

    def answer(self, src_addr, src_path, message, err=ray.Err.OK):
        if err == ray.Err.OK:
            self.send(src_addr, '/reply', src_path, message)
        else:
            self.send(src_addr, '/error', src_path, err, message)
