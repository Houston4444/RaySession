from .child_dialog import ChildDialog
from.client_properties import ClientPropertiesDialog

import ui.trash


class TrashDialog(ChildDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.ui = ui.trash.Ui_TrashDialog()
        self.ui.setupUi(self)
        
        self._fill_trash()
        self.ui.listWidgetTrash.properties_request.connect(
            self._show_client_properties)

    def _fill_trash(self):
        session = self.parent().session
        
        self.ui.listWidgetTrash.clear()
        
        for trashed_client in session.trashed_clients:
            self.ui.listWidgetTrash.create_client_widget(trashed_client)
            
    def _show_client_properties(self, client_id: str):
        for trashed_client in self.session.trashed_clients:
            if trashed_client.client_id == client_id:
                properties_dialog = ClientPropertiesDialog.create(
                    self, trashed_client)
                properties_dialog.update_contents()
                properties_dialog.lock_widgets()
                properties_dialog.show()
                break