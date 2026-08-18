
from qtpy.QtGui import QPixmap

import osc_paths.ray as r
import ray

from gui_tools import is_dark_theme, RS
from .child_dialog import ChildDialog

import ui.waiting_close_user


class WaitingCloseUserDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui.waiting_close_user.Ui_Dialog()
        self.ui.setupUi(self)

        if is_dark_theme(self):
            self.ui.labelSaveIcon.setPixmap(
                QPixmap(
                    ':scalable/breeze-dark/document-nosave.svg')) # type:ignore

        self.ui.pushButtonOk.setFocus()
        self.ui.pushButtonUndo.clicked.connect(self._undo_close)
        self.ui.pushButtonSkip.clicked.connect(self._skip)
        self.ui.checkBox.setChecked(not RS.is_hidden(RS.HD_WaitCloseUser))
        self.ui.checkBox.clicked.connect(self._check_box_clicked)

    def _server_status_changed(self, server_status: ray.ServerStatus):
        if server_status is not ray.ServerStatus.WAIT_USER:
            self.accept()

    def _undo_close(self):
        self.to_daemon(r.session.CANCEL_CLOSE)

    def _skip(self):
        self.to_daemon(r.session.SKIP_WAIT_USER)

    def _check_box_clicked(self, state):
        RS.set_hidden(RS.HD_WaitCloseUser, bool(state))
