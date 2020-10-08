
import ray
import nsm_client
from gui_tools import CommandLineArgs, _translate
from gui_server_thread import GUIServerThread

class NSMChild:
    @classmethod
    def announceToParent(cls):
        serverNSM = nsm_client.NSMThread.instance()

        if serverNSM:
            serverNSM.announce(_translate('child_session', 'Child Session'),
                               ':switch:optional-gui:', 'raysession')

    def __init__(self, session):
        self._session = session
        self.nsm_signaler = nsm_client.NSMSignaler()
        self.nsm_signaler.server_sends_open.connect(self.open)
        self.nsm_signaler.server_sends_save.connect(self.save)
        self.nsm_signaler.show_optional_gui.connect(self.showOptionalGui)
        self.nsm_signaler.hide_optional_gui.connect(self.hideOptionalGui)

        self.wait_for_open = False
        self.wait_for_save = False
        self.project_path = ''

        serverNSM = nsm_client.NSMThread('raysession_child',
                                         self.nsm_signaler,
                                         CommandLineArgs.NSM_URL,
                                         CommandLineArgs.debug)
        serverNSM.start()

        self._session._signaler.daemon_announce_ok.connect(
            self.announceToParent)
        self._session._signaler.server_status_changed.connect(
            self.serverStatusChanged)

    def serverStatusChanged(self, server_status):
        if server_status == ray.ServerStatus.READY:
            serverNSM = nsm_client.NSMThread.instance()
            if not serverNSM:
                return

            if self.wait_for_open:
                serverNSM.openReply()
                self.wait_for_open = False

            elif self.wait_for_save:
                serverNSM.saveReply()
                self.wait_for_save = False

    def open(self, project_path, session_name, jack_client_name):
        self.wait_for_open = True
        self.project_path = project_path

        server = GUIServerThread.instance()
        if server:
            server.openSession(project_path, 0)

        self.sendGuiState(self._session._main_win.isVisible())

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

        #self.sendGuiState(True)

    def hideOptionalGui(self):
        if self._session._main_win:
            self._session._main_win.hide()

        #self.sendGuiState(False)
    
    def sendGuiState(self, state: bool):
        serverNSM = nsm_client.NSMThread.instance()

        if serverNSM:
            serverNSM.sendGuiState(state)

class NSMChildOutside(NSMChild):
    def __init__(self, session):
        NSMChild.__init__(self, session)
        self.wait_for_close = False

    def announceToParent(self):
        serverNSM = nsm_client.NSMThread.instance()

        if serverNSM:
            serverNSM.announce(_translate('network_session',
                                           'Network Session'),
                                ':switch:optional-gui:ray-network:',
                                ray.RAYNET_BIN)

            serverNSM.sendToDaemon(
                '/nsm/client/network_properties',
                self._session._daemon_manager.url,
                self._session._daemon_manager.session_root)

    def save(self):
        serverNSM = nsm_client.NSMThread.instance()

        if serverNSM:
            serverNSM.sendToDaemon(
                '/nsm/client/network_properties',
                self._session._daemon_manager.url,
                self._session._daemon_manager.session_root)

        NSMChild.save(self)

    def open(self, project_path, session_name, jack_client_name):
        self.wait_for_open = True

        #Here project_path is used for template if needed
        template_name = jack_client_name

        server = GUIServerThread.instance()
        if server:
            server.openSession(project_path, 0, template_name)

        self._session._main_win.hide()
        self.sendGuiState(self._session._main_win.isVisible())

    def closeSession(self):
        self.wait_for_close = True

        server = GUIServerThread.instance()
        if server:
            server.closeSession()
