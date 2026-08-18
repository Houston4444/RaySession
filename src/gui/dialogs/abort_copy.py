import ray

from .child_dialog import ChildDialog

import ui.abort_copy


class AbortServerCopyDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui.abort_copy.Ui_Dialog()
        self.ui.setupUi(self)

        self.signaler.server_progress.connect(self._set_progress)

        self._server_status_changed(self.session.server_status)

    def _server_status_changed(self, server_status: ray.ServerStatus):
        if server_status not in (
                ray.ServerStatus.PRECOPY,
                ray.ServerStatus.COPY):
            self.reject()

    def _set_progress(self, progress: float):
        self.ui.progressBar.setValue(int(progress * 100))


class AbortClientCopyDialog(ChildDialog):
    def __init__(self, parent, client_id: str):
        ChildDialog.__init__(self, parent)
        self.ui = ui.abort_copy.Ui_Dialog()
        self.ui.setupUi(self)

        self._client_id = client_id

        self.signaler.client_progress.connect(self._set_progress)

    def _set_progress(self, client_id: str, progress: float):
        if client_id != self._client_id:
            return

        self.ui.progressBar.setValue(int(progress * 100))

    def _server_status_changed(self, server_status: ray.ServerStatus):
        if not self.server_copying:
            self.reject()