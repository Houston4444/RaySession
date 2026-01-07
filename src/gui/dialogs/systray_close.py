from .child_dialog import ChildDialog

import ui.systray_close


class SystrayCloseDialog(ChildDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.ui = ui.systray_close.Ui_Dialog()
        self.ui.setupUi(self)

    def not_again(self) -> bool:
        return self.ui.checkBox.isChecked()
