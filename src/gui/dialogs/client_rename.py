
from typing import TYPE_CHECKING

from qtpy.QtWidgets import QDialogButtonBox

import ray

from gui_tools import get_app_icon, _translate
from .child_dialog import ChildDialog

import ui.client_rename

if TYPE_CHECKING:
    from gui_client import Client


class ClientRenameDialog(ChildDialog):
    def __init__(self, parent, client: 'Client'):
        super().__init__(parent)
        self.ui = ui.client_rename.Ui_Dialog()
        self.ui.setupUi(self)

        self.client = client
        self.ui.toolButtonIcon.setIcon(get_app_icon(client.icon, self))
        self.ui.labelClientLabel.setText(client.prettier_name())
        self.ui.lineEdit.setText(client.prettier_name())
        self.ui.lineEdit.selectAll()
        self.ui.lineEdit.setFocus()
        self.ui.lineEdit.textEdited.connect(self._text_edited)
        self.ui.checkBoxIdRename.stateChanged.connect(
            self._id_rename_state_changed)

        if client.protocol not in (ray.Protocol.NSM,
                                   ray.Protocol.RAY_HACK,
                                   ray.Protocol.INTERNAL):
            self.ui.checkBoxIdRename.setVisible(False)

        self._change_box_text_with_status(client.status)
        client.status_changed.connect(self._client_status_changed)

    @property
    def _ok_button(self):
        return self.ui.buttonBox.button(
            QDialogButtonBox.StandardButton.Ok) # type:ignore

    def _change_box_text_with_status(self, status: ray.ClientStatus):
        can_switch = ':switch:' in self.client.capabilities

        if status in (
                ray.ClientStatus.STOPPED, ray.ClientStatus.PRECOPY,
                ray.ClientStatus.QUIT, ray.ClientStatus.LOSE):
            text = ''
        elif status is ray.ClientStatus.READY and can_switch:
            text = _translate(
                'id_renaming', 'The client project will be reload')
        else:
            text = _translate(
                'id_renaming', 'The client will be restarted')
        
        full_text = _translate('id_renaming', 'Rename Identifier')
        if text:
            full_text += f'\n({text})'
        
        self.ui.checkBoxIdRename.setText(full_text)    

    def _client_status_changed(self, status: ray.ClientStatus):
        if status is ray.ClientStatus.REMOVED:
            self.reject()
            
        self._change_box_text_with_status(status)
    
    def _id_rename_state_changed(self, state: int):
        if state:
            self._text_edited(self.ui.lineEdit.text())
    
    def _text_edited(self, text: str):
        if not self.is_identifiant_renamed():
            return
        
        out_text = ''.join([c for c in text if c.isalnum() or c == ' '])

        if out_text != text:
            self.ui.lineEdit.setText(out_text)
        
        out_id = out_text.replace(' ', '_')
        session = self.client.session
        ok = True
        
        for cl in session.clients:
            if cl.client_id == out_id:
                self._ok_button.setEnabled(False)
                return
        
        for cl in session.trashed_clients:
            if cl.client_id == out_id:
                self._ok_button.setEnabled(False)
                return
        
        self._ok_button.setEnabled(True)
    
    def is_identifiant_renamed(self) -> bool:
        return self.ui.checkBoxIdRename.isChecked()

    def get_new_label(self) -> str:
        return self.ui.lineEdit.text()
    