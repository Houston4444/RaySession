

# Imports from standard library
from typing import TYPE_CHECKING

# third party imports
from qtpy.QtWidgets import (
    QListWidget, QListWidgetItem, QMenu)
from qtpy.QtGui import QIcon, QContextMenuEvent, QKeyEvent
from qtpy.QtCore import Slot, QSize, Qt # type:ignore

# Imports from src/shared
import ray
import osc_paths.ray as r

# Local imports
from client_slot import ClientSlot
from gui_server_thread import GuiServerThread
from gui_tools import _translate, get_app_icon

if TYPE_CHECKING:
    from gui_session import SignaledSession


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


class ListWidgetClients(QListWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self._last_n = 0
        self.session = None

    @classmethod
    def to_daemon(cls, *args):
        server = GuiServerThread.instance()
        if server:
            server.to_daemon(*args)

    @Slot()
    def _launch_favorite(self):
        template_name, factory = self.sender().data() # type:ignore
        self.to_daemon(
            r.session.ADD_CLIENT_TEMPLATE,
            int(factory),
            template_name,
            'start',
            '')

    def create_client_widget(self, client_data):
        item = ClientItem(self, client_data)
        item.sort_number = self._last_n
        self._last_n += 1

        return item.widget

    def remove_client_widget(self, client_id):
        for i in range(self.count()):
            item: ClientItem = self.item(i) # type:ignore
            if item.client_id == client_id:
                widget = item.widget
                self.takeItem(i)
                del item
                break

    def client_properties_state_changed(self, client_id: str, visible: bool):
        for i in range(self.count()):
            item: ClientItem = self.item(i)
            if item.client_id == client_id:
                widget = item.widget
                widget.set_hack_button_state(visible)
                break

    def set_session(self, session: 'SignaledSession'):
        self.session = session

    def patchbay_is_shown(self, yesno: bool):
        for i in range(self.count()):
            item: ClientItem = self.item(i)
            widget = item.widget
            widget.patchbay_is_shown(yesno)

    def item(self, index: int) -> ClientItem:
        return super().item(index) # type:ignore

    def currentItem(self) -> ClientItem:
        return super().currentItem() # type:ignore

    def dropEvent(self, event):
        super().dropEvent(event)

        self.to_daemon(
            r.session.REORDER_CLIENTS,
            *[self.item(i).client_id for i in range(self.count())])

    def mousePressEvent(self, event):
        if not self.itemAt(event.pos()):
            self.setCurrentRow(-1)

        super().mousePressEvent(event)

    def contextMenuEvent(self, event: QContextMenuEvent):
        if not self.itemAt(event.pos()):
            self.setCurrentRow(-1)

            if (self.session is not None
                    and not self.session.server_status in (
                        ray.ServerStatus.OFF,
                        ray.ServerStatus.CLOSE,
                        ray.ServerStatus.OUT_SAVE,
                        ray.ServerStatus.WAIT_USER,
                        ray.ServerStatus.OUT_SNAPSHOT)):
                menu = QMenu()
                fav_menu = QMenu(_translate('menu', 'Favorites'), menu)
                fav_menu.setIcon(QIcon(':scalable/breeze/star-yellow'))

                for favorite in self.session.favorite_list:
                    act_app = fav_menu.addAction(
                        get_app_icon(favorite.icon, self),
                        favorite.display_name)
                    act_app.setData([favorite.name, favorite.factory])
                    act_app.triggered.connect(self._launch_favorite)

                menu.addMenu(fav_menu)

                menu.addAction(
                    self.session.main_win.ui.actionAddApplication) # type:ignore
                menu.addAction(
                    self.session.main_win.ui.actionAddExecutable) # type:ignore

                act_selected = menu.exec(self.mapToGlobal(event.pos()))
            event.accept()
            return

    def resizeEvent(self, event):
        super().resizeEvent(event)
        for i in range(self.count()):
            item: ClientItem = self.item(i) # type:ignore
            widget: ClientSlot = self.itemWidget(item) # type:ignore
            if widget is not None:
                widget.update_layout()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        super().keyPressEvent(event)
        
        # parse patchbay boxes of the selected client 
        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            client = self.currentItem().widget.client
            if (client.status is not ray.ClientStatus.STOPPED
                    and client.jack_client_name
                    and self.currentItem().isSelected()
                    and self.session is not None):
                self.session.patchbay_manager.select_client_box(
                    client.jack_client_name,
                    previous=bool(event.key() == Qt.Key.Key_Left))