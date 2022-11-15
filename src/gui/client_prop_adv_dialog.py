
from typing import TYPE_CHECKING
from PyQt5.QtWidgets import QApplication

import ray
from child_dialogs import ChildDialog
import ui.client_advanced_properties

if TYPE_CHECKING:
    from client_properties_dialog import ClientPropertiesDialog
    from gui_client import Client

_translate = QApplication.translate

class AdvancedPropertiesDialog(ChildDialog):
    def __init__(self, parent: 'ClientPropertiesDialog', client: 'Client'):
        super().__init__(parent)
        self.ui = ui.client_advanced_properties.Ui_Dialog()
        self.ui.setupUi(self)
        
        self._client = client
                
        self.ui.comboBoxPrefixMode.addItem(
            _translate('new_executable', 'Custom'))
        self.ui.comboBoxPrefixMode.addItem(
            _translate('new_executable', 'Client Name'))
        self.ui.comboBoxPrefixMode.addItem(
            _translate('new_executable', 'Session Name'))

        self.ui.lineEditClientId.setText(client.client_id)
        self.ui.comboBoxPrefixMode.setCurrentIndex(client.prefix_mode)

        if client.prefix_mode == ray.PrefixMode.CUSTOM:
            self.ui.lineEditCustomPrefix.setText(client.custom_prefix)
        else:
            self.ui.lineEditCustomPrefix.setEnabled(False)
        
        self.ui.checkBoxLongJackNaming.setChecked(client.jack_naming == 1)
        
        self.ui.lineEditClientId.textEdited.connect(self._update_preview)
        self.ui.comboBoxPrefixMode.currentIndexChanged.connect(
            self._prefix_mode_changed)
        self.ui.lineEditCustomPrefix.textEdited.connect(self._update_preview)
        self.ui.checkBoxLongJackNaming.stateChanged.connect(self._update_preview)
        self._update_preview()
        
    def _update_preview(self, *args):
        if self.ui.comboBoxPrefixMode.currentIndex() == ray.PrefixMode.SESSION_NAME:
            prefix_str = self._client.session.name
        elif self.ui.comboBoxPrefixMode.currentIndex() == ray.PrefixMode.CLIENT_NAME:
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
    
    def _prefix_mode_changed(self, index: int):
        self.ui.lineEditCustomPrefix.setEnabled(index == 0)
        self._update_preview()