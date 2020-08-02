# -*- coding: utf-8 -*-

import os
import sys
from PyQt5.QtCore import QObject, pyqtSignal
from liblo import ServerThread, make_method



class NSMSignaler(QObject):
    server_sends_open = pyqtSignal(str, str, str)
    server_sends_save = pyqtSignal()
    session_is_loaded = pyqtSignal()
    show_optional_gui = pyqtSignal()
    hide_optional_gui = pyqtSignal()

instance = None

class NSMThread(ServerThread):
    def __init__(self, name, signaler, daemon_address, debug):
        ServerThread.__init__(self)
        self.name = name
        self.signaler = signaler
        self.daemon_address = daemon_address
        self.debug = debug
        self.server_capabilities = ""

        global instance
        instance = self

    @staticmethod
    def instance():
        return instance

    @make_method('/reply', None)
    def serverReply(self, path, args):
        if args:
            reply_path = args[0]
        else:
            return

        if reply_path == '/nsm/server/announce':
            self.server_capabilities = args[3]

    @make_method('/nsm/client/open', 'sss')
    def nsmClientOpen(self, path, args):
        self.ifDebug(
            'serverOSC::%s_receives %s, %s' %
            (self.name, path, str(args)))

        self.signaler.server_sends_open.emit(*args)

    @make_method('/nsm/client/save', '')
    def nsmClientSave(self, path, args):
        self.ifDebug(
            'serverOSC::%s_receives %s, %s' %
            (self.name, path, str(args)))
        self.signaler.server_sends_save.emit()

    @make_method('/nsm/client/session_is_loaded', '')
    def nsmClientSessionIsLoaded(self, path, args):
        self.ifDebug(
            'serverOSC::%s_receives %s, %s' %
            (self.name, path, str(args)))
        self.signaler.session_is_loaded.emit()

    @make_method('/nsm/client/show_optional_gui', '')
    def nsmClientShow_optional_gui(self, path, args):
        self.ifDebug(
            'serverOSC::%s_receives %s, %s' %
            (self.name, path, str(args)))
        self.signaler.show_optional_gui.emit()

    @make_method('/nsm/client/hide_optional_gui', '')
    def nsmClientHide_optional_gui(self, path, args):
        self.ifDebug(
            'serverOSC::%s_receives %s, %s' %
            (self.name, path, str(args)))
        self.signaler.hide_optional_gui.emit()

    def getServerCapabilities(self):
        return self.server_capabilities

    def ifDebug(self, string):
        if self.debug:
            sys.stderr.write("%s\n" % string)

    def sendToDaemon(self, *args):
        self.send(self.daemon_address, *args)

    def announce(self, client_name, capabilities, executable_path):
        major = 1
        minor = 0
        pid = os.getpid()

        self.sendToDaemon(
            '/nsm/server/announce',
            client_name,
            capabilities,
            executable_path,
            major,
            minor,
            pid)

    def openReply(self):
        self.sendToDaemon('/reply', '/nsm/client/open', 'Ready')

    def saveReply(self):
        self.sendToDaemon('/reply', '/nsm/client/save', 'Saved')

    def sendDirtyState(self, bool_dirty):
        if bool_dirty:
            self.sendToDaemon('/nsm/client/is_dirty')
        else:
            self.sendToDaemon('/nsm/client/is_clean')

    def sendGuiState(self, state):
        if state:
            self.sendToDaemon('/nsm/client/gui_is_shown')
        else:
            self.sendToDaemon('/nsm/client/gui_is_hidden')
