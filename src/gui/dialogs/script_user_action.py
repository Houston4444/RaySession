
from qtpy.QtWidgets import QDialogButtonBox

import osc_paths
import osc_paths.ray.gui as rg
import ray

from .child_dialog import ChildDialog

import ui.script_user_action


class ScriptUserActionDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui.script_user_action.Ui_Dialog()
        self.ui.setupUi(self)

        self.ui.buttonBox.clicked.connect(self._button_box_clicked)
        self.ui.infoLabel.setVisible(False)
        self.ui.infoLine.setVisible(False)

        self._is_terminated = False

    def _validate(self):
        self.to_daemon(osc_paths.REPLY, rg.SCRIPT_USER_ACTION,
                      'Dialog window validated')
        self._is_terminated = True
        self.accept()

    def _abort(self):
        self.to_daemon(osc_paths.ERROR, rg.SCRIPT_USER_ACTION,
                       ray.Err.ABORT_ORDERED, 'Script user action aborted!')
        self._is_terminated = True
        self.accept()

    def _button_box_clicked(self, button):
        if button == self.ui.buttonBox.button(
                QDialogButtonBox.StandardButton.Yes): # type:ignore
            self._validate()
        elif button == self.ui.buttonBox.button(
                QDialogButtonBox.StandardButton.Ignore): # type:ignore
            self._abort()

    def set_main_text(self, text: str):
        self.ui.label.setText(text)

    def should_be_removed(self):
        return self._is_terminated
