from .child_dialog import ChildDialog

import ui.script_info


class ScriptInfoDialog(ChildDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.ui = ui.script_info.Ui_Dialog()
        self.ui.setupUi(self)

    def set_info_label(self, text: str):
        self.ui.infoLabel.setText(text)

    def should_be_removed(self):
        return False
