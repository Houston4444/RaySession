import ray

from .child_dialog import ChildDialog

import ui.about_raysession


class AboutRaySessionDialog(ChildDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.ui = ui.about_raysession.Ui_DialogAboutRaysession()
        self.ui.setupUi(self)
        all_text = self.ui.labelRayAndVersion.text()
        self.ui.labelRayAndVersion.setText(all_text % ray.VERSION)