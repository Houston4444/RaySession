from .child_dialog import ChildDialog

import ui.error_dialog


class ErrorDialog(ChildDialog):
    def __init__(self, parent, message: str):
        super().__init__(parent)
        self.ui = ui.error_dialog.Ui_Dialog()
        self.ui.setupUi(self)

        self.ui.label.setText(message)