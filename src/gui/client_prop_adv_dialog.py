
from typing import TYPE_CHECKING, Union
from PyQt5.QtWidgets import QApplication, QAbstractButton, QDialogButtonBox
from PyQt5.QtCore import pyqtSlot

import ray
from child_dialogs import ChildDialog
from gui_server_thread import GuiServerThread

if TYPE_CHECKING:
    from client_properties_dialog import ClientPropertiesDialog
    from gui_client import Client, TrashedClient

import ui.client_advanced_properties

_translate = QApplication.translate


class AdvancedPropertiesDialog(ChildDialog):
    def __init__(self, parent: 'ClientPropertiesDialog',
                 client: ray.ClientData):
        super().__init__(parent)
        self.ui = ui.client_advanced_properties.Ui_Dialog()
        self.ui.setupUi(self)
        
        self._client = client
        self._client_is_real = hasattr(client, 'session')
        
        self.ui.comboBoxPrefixMode.addItem(
            _translate('new_executable', 'Custom'))
        self.ui.comboBoxPrefixMode.addItem(
            _translate('new_executable', 'Client Name'))
        self.ui.comboBoxPrefixMode.addItem(
            _translate('new_executable', 'Session Name'))

        self.ui.lineEditClientId.setText(client.client_id)
        self.ui.comboBoxPrefixMode.setCurrentIndex(client.prefix_mode.value)

        if client.prefix_mode is ray.PrefixMode.CUSTOM:
            self.ui.lineEditCustomPrefix.setText(client.custom_prefix)
        else:
            self.ui.lineEditCustomPrefix.setEnabled(False)
        
        self.ui.checkBoxLongJackNaming.setChecked(
            client.jack_naming is ray.JackNaming.LONG)
        
        self.ui.lineEditClientId.textEdited.connect(self._client_id_line_edited)
        self.ui.comboBoxPrefixMode.currentIndexChanged.connect(
            self._prefix_mode_changed)
        self.ui.lineEditCustomPrefix.textEdited.connect(self._update_preview)
        self.ui.checkBoxLongJackNaming.stateChanged.connect(self._update_preview)
        self.ui.buttonBox.clicked.connect(self._button_box_clicked)
        
        if hasattr(client, 'status_changed'):
            if TYPE_CHECKING:
                assert(isinstance(client, Client))
            self._client_status_changed(client.status)
            client.status_changed.connect(self._client_status_changed)
        
        self._update_preview()
    
    # pyqtSlot(int)
    def _client_status_changed(self, status: int):
        self.ui.buttonBox.button(QDialogButtonBox.Apply).setEnabled(
            status == ray.ClientStatus.STOPPED)
    
    @pyqtSlot()
    def _client_id_line_edited(self):
        self.ui.lineEditClientId.setText(
            self.ui.lineEditClientId.text().replace(' ', '_'))
        self._update_preview()
    
    def _update_preview(self, *args):
        if self.ui.comboBoxPrefixMode.currentIndex() == ray.PrefixMode.SESSION_NAME.value:
            if self._client_is_real:
                if TYPE_CHECKING:
                    assert isinstance(self._client, (Client, TrashedClient))
                prefix_str = self._client.session.name
            else:
                prefix_str = "SESSION NAME"
        elif self.ui.comboBoxPrefixMode.currentIndex() == ray.PrefixMode.CLIENT_NAME.value:
            prefix_str = self._client.name
        else:
            prefix_str = self.ui.lineEditCustomPrefix.text()
        
        client_id = self.ui.lineEditClientId.text()
        
        self.ui.labelProjectPathPreview.setText(
            f"{prefix_str}.{client_id}")

        if self.ui.checkBoxLongJackNaming.isChecked():
            self.ui.labelJackNamePreview.setText(
                f"{self._client.name}.{client_id}")
        else:
            self.ui.labelJackNamePreview.setText(self._client.name)
    
    @pyqtSlot(int)
    def _prefix_mode_changed(self, index: int):
        if index == 0 and not self.ui.lineEditCustomPrefix.text():
            self.ui.lineEditCustomPrefix.setText('CustomString')
        self.ui.lineEditCustomPrefix.setEnabled(index == 0)
        self._update_preview()

    def _button_box_clicked(self, button: QAbstractButton):
        if button is self.ui.buttonBox.button(QDialogButtonBox.Apply):
            server = GuiServerThread.instance()
            if server is not None:
                server.to_daemon(
                    '/ray/client/change_advanced_properties',
                    self._client.client_id,
                    self.ui.lineEditClientId.text(),
                    self.ui.comboBoxPrefixMode.currentIndex(),
                    self.ui.lineEditCustomPrefix.text(),
                    int(self.ui.checkBoxLongJackNaming.isChecked()))

            self.hide()
            
    def lock_widgets(self):
        self.ui.lineEditClientId.setReadOnly(True)
        self.ui.comboBoxPrefixMode.setEnabled(False)
        self.ui.lineEditCustomPrefix.setReadOnly(True)
        self.ui.checkBoxLongJackNaming.setEnabled(False)
        self.ui.buttonBox.button(QDialogButtonBox.Apply).setEnabled(False)