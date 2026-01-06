
from qtpy.QtWidgets import QMessageBox
from qtpy.QtGui import QIcon

import osc_paths.ray as r
import ray

import client_properties_dialog
from gui_tools import _translate
from .child_dialog import ChildDialog

import ui.client_trash


class ClientTrashDialog(ChildDialog):
    def __init__(self, parent, client_data: ray.ClientData):
        ChildDialog.__init__(self, parent)
        self.ui = ui.client_trash.Ui_Dialog()
        self.ui.setupUi(self)

        self.client_data = client_data

        self.ui.labelPrettierName.setText(self.client_data.prettier_name())
        self.ui.labelDescription.setText(self.client_data.description)
        self.ui.labelExecutable.setText(self.client_data.executable)
        self.ui.labelId.setText(self.client_data.client_id)
        self.ui.toolButtonIcon.setIcon(QIcon.fromTheme(self.client_data.icon))

        self.ui.toolButtonAdvanced.clicked.connect(self._show_properties)
        self.ui.pushButtonRemove.clicked.connect(self._remove_client)
        self.ui.pushButtonCancel.setFocus()

        self._remove_client_message_box = QMessageBox(
            QMessageBox.Icon.Warning,
            _translate('trashed_client', 'Remove definitely'),
            _translate('trashed_client',
                "Are you sure to want to remove definitely this client "
                "and all its files ?"),
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            self)
        self._remove_client_message_box.setDefaultButton(
            QMessageBox.StandardButton.Cancel)

    def _server_status_changed(self, server_status: ray.ServerStatus):
        if server_status in (ray.ServerStatus.CLOSE,
                             ray.ServerStatus.OFF,
                             ray.ServerStatus.OUT_SAVE,
                             ray.ServerStatus.OUT_SNAPSHOT,
                             ray.ServerStatus.WAIT_USER):
            self._remove_client_message_box.reject()
            self.reject()

    def _remove_client(self):
        self._remove_client_message_box.exec()

        if (self._remove_client_message_box.clickedButton()
                != self._remove_client_message_box.button(
                    QMessageBox.StandardButton.Ok)):
            return

        self.to_daemon(
            r.trashed_client.REMOVE_DEFINITELY,
            self.client_data.client_id)
        self.reject()

    def _show_properties(self):
        properties_dialog = \
            client_properties_dialog.ClientPropertiesDialog.create(
                self, self.client_data)
        properties_dialog.update_contents()
        properties_dialog.lock_widgets()
        properties_dialog.show()
