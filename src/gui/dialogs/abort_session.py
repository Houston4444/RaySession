from qtpy.QtCore import Qt

import ray

from .child_dialog import ChildDialog

import ui.abort_session


class AbortSessionDialog(ChildDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.ui = ui.abort_session.Ui_AbortSession()
        self.ui.setupUi(self)

        self.ui.pushButtonAbort.clicked.connect(self.accept)
        self.ui.pushButtonCancel.clicked.connect(self.reject)
        self.ui.pushButtonCancel.setFocus(
            Qt.FocusReason.OtherFocusReason) # type:ignore

        self._server_status_changed(self.session.server_status)

    def _server_status_changed(self, server_status: ray.ServerStatus):
        self.ui.pushButtonAbort.setEnabled(
            not bool(
                server_status in (
                    ray.ServerStatus.CLOSE,
                    ray.ServerStatus.OFF,
                    ray.ServerStatus.COPY)))
        if server_status is ray.ServerStatus.OFF:
            self.reject()