from pathlib import Path

import ray

from .child_dialog import ChildDialog

import ui.jack_config_info


class JackConfigInfoDialog(ChildDialog):
    def __init__(self, parent, session_path: Path):
        super.__init__(parent)
        self.ui = ui.jack_config_info.Ui_Dialog()
        self.ui.setupUi(self)

        session_scripts_text = self.ui.textSessionScripts.toHtml()
        self.ui.textSessionScripts.setHtml(
            session_scripts_text % (
                session_path / ray.SCRIPTS_DIR,
                session_path.parent,
                session_path.parent / ray.SCRIPTS_DIR))

    def not_again_value(self) -> bool:
        return self.ui.checkBoxNotAgain.isChecked()

    def auto_start_value(self) -> bool:
        return self.ui.checkBoxAutoStart.isChecked()
