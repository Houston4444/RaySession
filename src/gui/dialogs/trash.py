from .child_dialog import ChildDialog

import ui.trash


class TrashDialog(ChildDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.ui = ui.trash.Ui_TrashDialog()
        self.ui.setupUi(self)
        
        self._fill_trash()

    def _fill_trash(self):
        session = self.parent().session
        
        self.ui.listWidgetPreview.clear()
        
        for trashed_client in session.trashed_clients:
            self.ui.listWidgetPreview.create_client_widget(trashed_client)