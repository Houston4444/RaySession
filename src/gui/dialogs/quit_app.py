from qtpy.QtCore import Qt, QTimer
from qtpy.QtWidgets import QApplication

import osc_paths.ray as r
import ray

from gui_tools import CommandLineArgs
from .child_dialog import ChildDialog

import ui.quit_app


class QuitAppDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui.quit_app.Ui_DialogQuitApp()
        self.ui.setupUi(self)
        self.ui.pushButtonCancel.setFocus(
            Qt.FocusReason.OtherFocusReason) # type:ignore
        self.ui.pushButtonSaveQuit.clicked.connect(self._close_session)
        self.ui.pushButtonQuitNoSave.clicked.connect(self._abort_session)
        self.ui.pushButtonDaemon.clicked.connect(self._leave_daemon_running)

        original_text = self.ui.labelMainText.text()
        self.ui.labelMainText.setText(
            original_text % f'<strong>{self.session.name}</strong>')

        if CommandLineArgs.under_nsm:
            self.ui.pushButtonDaemon.setVisible(False)
        self._server_status_changed(self.session.server_status)

    def _server_status_changed(self, server_status: ray.ServerStatus):
        if server_status is ray.ServerStatus.OFF:
            self.accept()
            return

        self.ui.pushButtonSaveQuit.setEnabled(
            bool(server_status is ray.ServerStatus.READY))
        self.ui.pushButtonQuitNoSave.setEnabled(
            bool(server_status is not ray.ServerStatus.CLOSE))

    def _close_session(self):
        self.to_daemon(r.session.CLOSE)

    def _abort_session(self):
        self.to_daemon(r.session.ABORT)

    def _leave_daemon_running(self):
        if CommandLineArgs.under_nsm:
            return

        self.daemon_manager.disannounce()
        QTimer.singleShot(10, QApplication.quit)