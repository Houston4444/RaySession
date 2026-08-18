from typing import TYPE_CHECKING

from qtpy.QtCore import QSize
from qtpy.QtWidgets import QListWidgetItem

from .client_slot import ClientSlot

if TYPE_CHECKING:
    from .list_widget_clients import ListWidgetClients


class ClientItem(QListWidgetItem):
    def __init__(self, parent: 'ListWidgetClients', client_data):
        super().__init__(parent, QListWidgetItem.ItemType.UserType + 1)

        self.sort_number = 0
        self.widget = ClientSlot(parent, self, client_data)
        parent.setItemWidget(self, self.widget)
        self.setSizeHint(QSize(100, 45))

    def __lt__(self, other: 'ClientItem'):
        return self.sort_number < other.sort_number

    def __gt__(self, other: 'ClientItem'):
        return self.sort_number > other.sort_number

    @property
    def client_id(self):
        return self.widget.client_id
