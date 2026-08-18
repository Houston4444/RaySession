import ray

from .child_dialog import ChildDialog

import ui.snapshot_progress


class SnapShotProgressDialog(ChildDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.ui = ui.snapshot_progress.Ui_Dialog()
        self.ui.setupUi(self)
        self.signaler.server_progress.connect(self.server_progress)

    def _server_status_changed(self, server_status: ray.ServerStatus):
        self.close()

    def server_progress(self, value: float):
        self.ui.progressBar.setValue(int(value * 100))
