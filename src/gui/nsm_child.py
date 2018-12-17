
import ray
import nsm_client
from gui_tools import CommandLineArgs, _translate
from gui_server_thread import GUIServerThread

class NSMChild:
    def __init__(self, session):
        self._session = session
        self.nsm_signaler = nsm_client.NSMSignaler()
        self.nsm_signaler.server_sends_open.connect(self.open)
        self.nsm_signaler.server_sends_save.connect(self.save)
        self.nsm_signaler.show_optional_gui.connect(self.showOptionalGui)
        self.nsm_signaler.hide_optional_gui.connect(self.hideOptionalGui)
        
        self.wait_for_open = False
        self.wait_for_save = False
        self.project_path  = ''
        
        self.serverNSM = nsm_client.NSMThread('raysession_child',
                                              self.nsm_signaler,
                                              CommandLineArgs.NSM_URL,
                                              CommandLineArgs.debug)        
        self.serverNSM.start()
        
        self._session._signaler.daemon_announce_ok.connect(
            self.announceToParent)
        self._session._signaler.server_status_changed.connect(
            self.serverStatusChanged)
    
    def announceToParent(self):
        self.serverNSM.announce(_translate('child_session', 'Child Session'),
                                ':switch:optional-gui:', 'raysession')
    
    def serverStatusChanged(self, server_status):
        if server_status == ray.ServerStatus.READY:
            if self.wait_for_open:
                self.serverNSM.openReply()
                self.wait_for_open = False
            
            elif self.wait_for_save:
                self.serverNSM.saveReply()
                self.wait_for_save = False
    
    def open(self, project_path, session_name, jack_client_name):
        self.wait_for_open = True
        self.project_path  = project_path
        
        server = GUIServerThread.instance()
        if server:
            server.openSession(project_path)
    
    def save(self):
        if self._session._main_win:
            self._session._main_win.saveWindowSettings()
        
        self.wait_for_save = True
        
        server = GUIServerThread.instance()
        if server:
            server.saveSession()
        
    def showOptionalGui(self):
        if self._session._main_win:
            self._session._main_win.show()
        self.serverNSM.sendGuiState(True)
        
    def hideOptionalGui(self):
        if self._session._main_win:
            self._session._main_win.hide()
            
        self.serverNSM.sendGuiState(False)
        
        
class NSMChildOutside(NSMChild):
    def __init__(self, session):
        NSMChild.__init__(self, session)
        self.wait_for_close = False
        
        self.session_name = ''
        self.template_name = ''
        
    def announceToParent(self):
        self.serverNSM.announce(_translate('network_session',
                                           'Network Session'),
                                ':switch:optional-gui:ray-network:',
                                'ray-network')
        
        daemon_manager = self._session._daemon_manager
        
        self.serverNSM.sendToDaemon(
            '/nsm/client/network_properties',
            self._session._daemon_manager.url,
            self._session._daemon_manager.session_root)
    
    def save(self):
        self.serverNSM.sendToDaemon(
            '/nsm/client/network_properties',
            self._session._daemon_manager.url,
            self._session._daemon_manager.session_root)
        
        NSMChild.save(self)
        
    def open(self, project_path, session_name, jack_client_name):
        self.wait_for_open = True
        
        #Here project_path is used for template if needed
        self.template_name = project_path
        self.session_name  = session_name
        
        server = GUIServerThread.instance()
        if server:
            server.openSession(self.session_name, self.template_name)
        
    def closeSession(self):
        self.wait_for_close = True
        
        server = GUIServerThread.instance()
        if server:
            server.closeSession()
