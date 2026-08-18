from gui_tools import RS
from .child_dialog import ChildDialog

import ui.nsm_open_info


class OpenNsmSessionInfoDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui.nsm_open_info.Ui_Dialog()
        self.ui.setupUi(self)
        self.ui.checkBox.stateChanged.connect(self._show_this)

    def _show_this(self, state: bool):
        RS.set_hidden(RS.HD_OpenNsmSession, bool(state))
