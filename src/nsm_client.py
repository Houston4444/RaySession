# -*- coding: utf-8 -*-

from PyQt5.QtCore import QObject, pyqtSignal
from liblo import ServerThread, make_method
import os
        
class NSMSignaler(QObject):
    server_sends_open = pyqtSignal(str, str, str)
    server_sends_save = pyqtSignal()
    show_optional_gui = pyqtSignal()
    hide_optional_gui = pyqtSignal()

class NSMThread(ServerThread):
    def __init__(self, name, signaler, daemon_address, debug):
        ServerThread.__init__(self)
        self.name           = name
        self.signaler       = signaler
        self.daemon_address = daemon_address
        self.debug          = debug

    @make_method('/nsm/client/open', 'sss')
    def nsmClientOpen(self, path, args):
        self.ifDebug('serverOSC::%s_receives %s, %s' % (self.name, path, str(args)))
        self.signaler.server_sends_open.emit(*args)
    
    @make_method('/nsm/client/save', '')
    def nsmClientSave(self, path, args):
        self.ifDebug('serverOSC::%s_receives %s, %s' % (self.name, path, str(args)))
        self.signaler.server_sends_save.emit()
        
    @make_method('/nsm/client/show_optional_gui', '')
    def nsmClientShow_optional_gui(self, path, args):
        self.ifDebug('serverOSC::%s_receives %s, %s' % (self.name, path, str(args)))
        self.signaler.show_optional_gui.emit()

    @make_method('/nsm/client/hide_optional_gui', '')
    def nsmClientHide_optional_gui(self, path, args):
        self.ifDebug('serverOSC::%s_receives %s, %s' % (self.name, path, str(args)))
        self.signaler.hide_optional_gui.emit()
        
    def ifDebug(self, string):
        if self.debug:
           print(string, file=sys.stderr)
           
    def sendToDaemon(self, *args):
        self.send(self.daemon_address, *args)
        
    def announce(self, client_name, capabilities, executable_path):
        major = 1
        minor = 0
        pid   = os.getpid()
        
        self.sendToDaemon('/nsm/server/announce', client_name, capabilities, executable_path, major, minor, pid)
        
    def openReply(self):
        self.sendToDaemon('/reply', '/nsm/client/open', 'Ready')
        
    def saveReply(self):
        print('saveReply')
        self.sendToDaemon('/reply', '/nsm/client/save', 'Saved')
        
    def sendDirtyState(self, bool_dirty):
        if bool_dirty:
            self.sendToDaemon('/nsm/client/is_clean')
        else:
            self.sendToDaemon('/nsm/client/is_dirty')
        
    def sendGuiState(self, state):
        if state:
            self.sendToDaemon('/nsm/client/gui_is_shown')
        else:
            self.sendToDaemon('/nsm/client/gui_is_hidden')
