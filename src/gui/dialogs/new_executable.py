
from qtpy.QtCore import Qt
from qtpy.QtWidgets import QDialogButtonBox, QCompleter

import osc_paths.ray as r
import ray

from gui_tools import _translate
from .child_dialog import ChildDialog

import ui.new_executable


class NewExecutableDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui.new_executable.Ui_DialogNewExecutable()
        self.ui.setupUi(self)

        self.ui.groupBoxAdvanced.setVisible(False)
        self.resize(0, 0)
        self.ui.labelPrefixMode.setToolTip(
            self.ui.comboBoxPrefixMode.toolTip())
        self.ui.labelClientId.setToolTip(self.ui.lineEditClientId.toolTip())

        self.ui.buttonBox.button(
            QDialogButtonBox.StandardButton.Ok).setEnabled(False) # type:ignore

        self.ui.lineEdit.setFocus(Qt.FocusReason.OtherFocusReason) # type:ignore
        self.ui.lineEdit.textChanged.connect(self._check_allow)
        self.ui.checkBoxNsm.stateChanged.connect(self._check_allow)

        self.ui.lineEditPrefix.setEnabled(False)
        self.ui.toolButtonAdvanced.clicked.connect(self._show_advanced)

        self.ui.comboBoxPrefixMode.addItem(
            _translate('new_executable', 'Custom'))
        self.ui.comboBoxPrefixMode.addItem(
            _translate('new_executable', 'Client Name'))
        self.ui.comboBoxPrefixMode.addItem(
            _translate('new_executable', 'Session Name'))
        self.ui.comboBoxPrefixMode.setCurrentIndex(1)

        self.ui.comboBoxPrefixMode.currentIndexChanged.connect(
            self._prefix_mode_changed)

        self.signaler.new_executable.connect(
            self._add_executable_to_completer)
        self.to_daemon(r.server.LIST_PATH)

        self.exec_list = list[str]()

        self._completer = QCompleter(self.exec_list)
        self.ui.lineEdit.setCompleter(self._completer) # type:ignore

        self.ui.lineEdit.returnPressed.connect(self._close_now)

        self._server_status_changed(self.session.server_status)

    def _server_status_changed(self, server_status: ray.ServerStatus):
        if server_status in (ray.ServerStatus.OUT_SAVE,
                             ray.ServerStatus.OUT_SNAPSHOT,
                             ray.ServerStatus.WAIT_USER,
                             ray.ServerStatus.CLOSE,
                             ray.ServerStatus.OFF):
            self.reject()

    def _show_advanced(self):
        self.ui.groupBoxAdvanced.setVisible(True)
        self.ui.toolButtonAdvanced.setVisible(False)

    def _prefix_mode_changed(self, index: int):
        self.ui.lineEditPrefix.setEnabled(bool(index == 0))

    def _add_executable_to_completer(self, executable_list: list):
        self.exec_list += executable_list
        self.exec_list.sort()

        del self._completer
        self._completer = QCompleter(self.exec_list)
        self.ui.lineEdit.setCompleter(self._completer) # type:ignore

    def _is_allowed(self) -> bool:
        nsm = self.ui.checkBoxNsm.isChecked()
        text = self.ui.lineEdit.text()
        return bool(bool(text) and (not nsm or text in self.exec_list))

    def _check_allow(self):
        allow = self._is_allowed()
        self.ui.buttonBox.button(
            QDialogButtonBox.StandardButton.Ok).setEnabled(allow) # type:ignore

    def _close_now(self):
        if self._is_allowed():
            self.accept()

    def get_selection(self) -> tuple[str, bool, bool, int, str, str, bool]:
        return (self.ui.lineEdit.text(),
                self.ui.checkBoxStartClient.isChecked(),
                not self.ui.checkBoxNsm.isChecked(),
                self.ui.comboBoxPrefixMode.currentIndex(),
                self.ui.lineEditPrefix.text(),
                self.ui.lineEditClientId.text(),
                self.ui.checkBoxJackNaming.isChecked())

