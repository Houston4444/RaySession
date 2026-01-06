import subprocess

from qtpy.QtCore import QTimer
from qtpy.QtWidgets import QApplication

from gui_tools import _translate
from .child_dialog import ChildDialog

import ui.quit_app


class WrongVersionLocalDialog(ChildDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.ui = ui.quit_app.Ui_DialogQuitApp()
        self.ui.setupUi(self)
        self.ui.pushButtonCancel.setVisible(False)
        self.ui.pushButtonSaveQuit.clicked.connect(self._close_session)
        self.ui.pushButtonQuitNoSave.clicked.connect(self._abort_session)
        self.ui.pushButtonDaemon.clicked.connect(self._leave_daemon_running)

        self.ui.labelMainText.setText(
            _translate(
                'wrong_version',
                "The running daemon has not the same version "
                "than the interface\n"
                "RaySession will quit now.\n\n"
                "What do you want to do with the current session ?"))

    def _close_session(self):
        # can make the GUI freeze a little
        # but the GUI will quit just after
        # and this case is rare enough to be acceptable
        subprocess.run(['ray_control', 'close'])
        self.accept()

    def _abort_session(self):
        # see _close_session
        subprocess.run(['ray_control', 'abort'])
        self.accept()

    def _leave_daemon_running(self):
        QTimer.singleShot(10, QApplication.quit)