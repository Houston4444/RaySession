

from typing import TYPE_CHECKING

import ray
from nsm_client_qt import NSMThread, NSMSignaler
from gui_tools import CommandLineArgs, _translate
from gui_server_thread import GuiServerThread

if TYPE_CHECKING:
    from gui_session import SignaledSession


class NsmChild:
    def __init__(self, session: 'SignaledSession'):
        self.session = session
        self.nsm_signaler = NSMSignaler()
        self.nsm_signaler.server_sends_open.connect(self._open)
        self.nsm_signaler.server_sends_save.connect(self._save)
        self.nsm_signaler.show_optional_gui.connect(self._show_optional_gui)
        self.nsm_signaler.hide_optional_gui.connect(self._hide_optional_gui)

        self.wait_for_open = False
        self.wait_for_save = False
        self.project_path = ''

        serverNSM = NSMThread(
            'raysession_child', self.nsm_signaler,
            CommandLineArgs.NSM_URL, CommandLineArgs.debug)
        serverNSM.start()

        self.session.signaler.daemon_announce_ok.connect(
            self._announce_to_parent)
        self.session.signaler.server_status_changed.connect(
            self._server_status_changed)

    def _announce_to_parent(self):
        server_nsm = NSMThread.instance()

        if server_nsm:
            server_nsm.announce(_translate('child_session', 'Child Session'),
                                ':switch:optional-gui:', 'raysession')

    def _server_status_changed(self, server_status: int):
        if server_status == ray.ServerStatus.READY:
            server_nsm = NSMThread.instance()
            if not server_nsm:
                return

            if self.wait_for_open:
                server_nsm.openReply()
                self.wait_for_open = False

            elif self.wait_for_save:
                server_nsm.saveReply()
                self.wait_for_save = False

    def _open(self, project_path: str, session_name: str, jack_client_name: str):
        self.wait_for_open = True
        self.project_path = project_path

        server = GuiServerThread.instance()
        if server:
            server.open_session(project_path, 0)

        self.send_gui_state(self.session.main_win.isVisible())

    def _save(self):
        if self.session.main_win:
            self.session.main_win.save_window_settings()

        self.wait_for_save = True

        server = GuiServerThread.instance()
        if server:
            server.save_session()

    def _show_optional_gui(self):
        if self.session.main_win:
            self.session.main_win.show()

    def _hide_optional_gui(self):
        if self.session.main_win:
            self.session.main_win.hide()

    def send_gui_state(self, state: bool):
        serverNSM = NSMThread.instance()

        if serverNSM:
            serverNSM.sendGuiState(state)


class NsmChildOutside(NsmChild):
    def __init__(self, session):
        NsmChild.__init__(self, session)
        self.wait_for_close = False

    def _announce_to_parent(self):
        server_nsm = NSMThread.instance()

        if server_nsm:
            server_nsm.announce(
                _translate('network_session', 'Network Session'),
                ':switch:optional-gui:ray-network:', ray.RAYNET_BIN)

            server_nsm.sendToDaemon(
                '/nsm/client/network_properties',
                self.session.daemon_manager.url,
                self.session.daemon_manager.session_root)
        self.session.main_win.hide()

    def _save(self):
        server_nsm = NSMThread.instance()

        if server_nsm:
            server_nsm.sendToDaemon(
                '/nsm/client/network_properties',
                self.session.daemon_manager.url,
                self.session.daemon_manager.session_root)

        NsmChild._save(self)

    def _open(self, project_path: str, session_name: str, jack_client_name: str):
        self.wait_for_open = True

        #Here project_path is used for template if needed
        template_name = jack_client_name

        server = GuiServerThread.instance()
        if server:
            server.open_session(project_path, 0, template_name)

        self.send_gui_state(self.session.main_win.isVisible())
