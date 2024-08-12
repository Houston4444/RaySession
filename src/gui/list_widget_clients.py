
from typing import TYPE_CHECKING
from PyQt5.QtWidgets import (QListWidget, QListWidgetItem,
                             QFrame, QMenu, QBoxLayout)
from PyQt5.QtGui import (QIcon, QPixmap, QFontMetrics, QContextMenuEvent,
                         QMouseEvent, QKeyEvent)
from PyQt5.QtCore import pyqtSlot, QSize, Qt, pyqtSignal

import ray
import child_dialogs
import snapshots_dialog

from gui_server_thread import GuiServerThread
from gui_tools import (client_status_string, _translate, is_dark_theme,
                       RayIcon, split_in_two, get_app_icon)

if TYPE_CHECKING:
    from gui_client import Client
    from gui_session import Session

import ui.client_slot


class ClientSlot(QFrame):
    clicked = pyqtSignal(str)
    
    def __init__(self, list_widget: 'ListWidgetClients',
                 list_widget_item: 'ClientItem', client: 'Client'):
        QFrame.__init__(self)
        self.ui = ui.client_slot.Ui_ClientSlotWidget()
        self.ui.setupUi(self)
        self.client = client
        self.main_win = self.client.session.main_win

        self.list_widget = list_widget
        self.list_widget_item = list_widget_item
        self._gui_state = False
        self._stop_is_kill = False
        self._very_short = False
        self._icon_on = QIcon()
        self._icon_off = QIcon()

        self.ui.toolButtonGUI.setVisible(False)
        if client.protocol is not ray.Protocol.RAY_HACK:
            self.ui.toolButtonHack.setVisible(False)

        # connect buttons to functions
        self.ui.toolButtonHack.order_hack_visibility.connect(
            self._order_hack_visibility)
        self.ui.toolButtonGUI.clicked.connect(self._change_gui_state)
        self.ui.startButton.clicked.connect(self._start_client)
        self.ui.stopButton.clicked.connect(self._stop_client)
        self.ui.saveButton.clicked.connect(self._save_client)
        self.ui.closeButton.clicked.connect(self._trash_client)
        self.ui.lineEditClientStatus.status_pressed.connect(self._abort_copy)

        self.ui.actionSaveAsApplicationTemplate.triggered.connect(
            self._save_as_application_template)
        self.ui.actionRename.triggered.connect(self._rename_dialog)
        self.ui.actionReturnToAPreviousState.triggered.connect(
            self._open_snapshots_dialog)
        self.ui.actionFindBoxesInPatchbay.triggered.connect(
            self._find_patchbay_boxes)
        self.ui.actionProperties.triggered.connect(
            self.client.show_properties_dialog)

        self._menu = QMenu(self)

        self._menu.addAction(self.ui.actionSaveAsApplicationTemplate)
        self._menu.addAction(self.ui.actionRename)
        self._menu.addAction(self.ui.actionReturnToAPreviousState)
        self._menu.addAction(self.ui.actionFindBoxesInPatchbay)
        self._menu.addAction(self.ui.actionProperties)

        self.ui.actionReturnToAPreviousState.setVisible(
            self.main_win.has_git)

        self.ui.iconButton.setMenu(self._menu)
        
        dark = is_dark_theme(self)
        
        self._save_icon = RayIcon('document-save', dark)
        self._saved_icon = RayIcon('document-saved', dark)
        self._unsaved_icon = RayIcon('document-unsaved', dark)
        self._no_save_icon = RayIcon('document-nosave', dark)
        self._icon_visible = RayIcon('visibility', dark)
        self._icon_invisible = RayIcon('hint', dark)
        self._stop_icon = RayIcon('media-playback-stop', dark)
        self._kill_icon = RayIcon('media-playback-stop_red', dark)

        self.ui.startButton.setIcon(RayIcon('media-playback-start', dark))
        self.ui.closeButton.setIcon(RayIcon('window-close', dark))
        self.ui.saveButton.setIcon(self._save_icon)
        self.ui.stopButton.setIcon(self._stop_icon)

        if ':optional-gui:' in self.client.capabilities:
            self.set_gui_state(self.client.gui_state)
            self.ui.toolButtonGUI.setVisible(True)

        if self.client.has_dirty:
            self.set_dirty_state(self.client.dirty_state)

        self.update_client_data()

    @classmethod
    def to_daemon(cls, *args):
        server = GuiServerThread.instance()
        if server:
            server.to_daemon(*args)

    def _change_gui_state(self):
        if self._gui_state:
            self.to_daemon('/ray/client/hide_optional_gui', self.get_client_id())
        else:
            self.to_daemon('/ray/client/show_optional_gui', self.get_client_id())

    def _order_hack_visibility(self, state):
        if self.client.protocol is not ray.Protocol.RAY_HACK:
            return

        if state:
            self.client.show_properties_dialog(second_tab=True)
        else:
            self.client.close_properties_dialog()

    def _start_client(self):
        self.to_daemon('/ray/client/resume', self.get_client_id())

    def _stop_client(self):
        if self._stop_is_kill:
            self.to_daemon('/ray/client/kill', self.get_client_id())
            return

        # we need to prevent accidental stop with a window confirmation
        # under conditions
        self.main_win.stop_client(self.get_client_id())

    def _save_client(self):
        self.to_daemon('/ray/client/save', self.get_client_id())

    def _trash_client(self):
        self.to_daemon('/ray/client/trash', self.get_client_id())

    def _abort_copy(self):
        self.main_win.abort_copy_client(self.get_client_id())

    def _save_as_application_template(self):
        dialog = child_dialogs.SaveTemplateClientDialog(
            self.main_win, self.client)
        dialog.exec()
        if not dialog.result():
            return

        template_name = dialog.get_template_name()
        self.to_daemon('/ray/client/save_as_template',
                       self.get_client_id(), template_name)

    def _open_snapshots_dialog(self):
        dialog = snapshots_dialog.ClientSnapshotsDialog(self.main_win,
                                                        self.client)
        dialog.exec()
        if dialog.result():
            snapshot = dialog.get_selected_snapshot()
            self.to_daemon('/ray/client/open_snapshot',
                          self.get_client_id(), snapshot)

    def _find_patchbay_boxes(self):
        self.main_win.set_patchbay_filter_text(
            'client:' + self.get_client_id())
        self.list_widget_item.setSelected(True)

    def _rename_dialog(self):
        dialog = child_dialogs.ClientRenameDialog(self.main_win,
                                                  self.client)
        dialog.exec()
        if dialog.result():
            label = dialog.get_new_label()
            
            if dialog.is_identifiant_renamed():
                self.to_daemon(
                    '/ray/client/full_rename',
                    self.client.client_id,
                    label)
                return

            self.client.label = label
            self.client.send_properties_to_daemon()


    def _set_very_short(self, yesno: bool):
        self._very_short = yesno

        if yesno:
            if not (self.ui.startButton.isEnabled()
                    or self.ui.stopButton.isEnabled()):
                self.ui.startButton.setVisible(True)
                self.ui.stopButton.setVisible(False)
            else:
                self.ui.startButton.setVisible(
                    self.ui.startButton.isEnabled())
                self.ui.stopButton.setVisible(self.ui.stopButton.isEnabled())
            self.ui.toolButtonHack.setVisible(False)
        else:
            self.ui.startButton.setVisible(True)
            self.ui.stopButton.setVisible(True)
            self.ui.toolButtonHack.setVisible(
                self.client.protocol is ray.Protocol.RAY_HACK)

    def _set_fat(self, yesno: bool, very_fat=False):
        if yesno:
            self.ui.mainLayout.setDirection(QBoxLayout.TopToBottom)
            self.ui.spacerLeftOfDown.setVisible(True)
            self.list_widget_item.setSizeHint(
                QSize(100, 80 if very_fat else 70))
        else:
            self.ui.spacerLeftOfDown.setVisible(False)
            self.ui.mainLayout.setDirection(QBoxLayout.LeftToRight)
            self.list_widget_item.setSizeHint(QSize(100, 45))

    def _gray_icon(self, gray: bool):
        if gray:
            self.ui.iconButton.setIcon(self._icon_off)
        else:
            self.ui.iconButton.setIcon(self._icon_on)

    def get_client_id(self):
        return self.client.client_id

    def update_layout(self):
        font = self.ui.ClientName.font()
        main_size = QFontMetrics(font).width(self.client.prettier_name())

        layout_width = self.list_widget.width()

        self._set_very_short(layout_width < 233)

        scroll_bar = self.list_widget.verticalScrollBar()
        if scroll_bar.isVisible():
            layout_width -= scroll_bar.width()

        max_label_width = layout_width - 231

        if self.ui.toolButtonGUI.isVisible():
            max_label_width -= self.ui.toolButtonGUI.width()
        if self.ui.toolButtonHack.isVisible():
            max_label_width -= self.ui.toolButtonHack.width()

        if main_size <= max_label_width:
            self.ui.ClientName.setText(self.client.prettier_name())
            self._set_fat(False)
            return

        # split title in two lines
        top, bottom = split_in_two(self.client.prettier_name())

        max_size = 0

        for text in (top, bottom):
            if not text:
                continue

            size = QFontMetrics(font).width(text)
            max_size = max(max_size, size)

        if max_size <= max_label_width:
            self.ui.ClientName.setText('\n'.join((top, bottom)))
            self._set_fat(False)
            return

        # responsive design, put label at top of the controls
        # if there is not enought space for label

        max_label_width = layout_width - 50

        if main_size <= max_label_width:
            self._set_fat(True)
            self.ui.ClientName.setText(self.client.prettier_name())
            return

        self._set_fat(True, very_fat=True)

        top, bottom = split_in_two(self.client.prettier_name())
        self.ui.ClientName.setText('\n'.join((top, bottom)))

    def update_client_data(self):
        # set main label and main disposition
        self.update_layout()

        # set tool tip
        tool_tip = "<html><head/><body>"
        tool_tip += "<p><span style=\" font-weight:600;\">%s<br></span>" \
            % self.client.name
        tool_tip += "<span style=\" font-style:italic;\">%s</span></p>" \
            % self.client.description
        tool_tip += "<p></p>"
        tool_tip += "<p>%s : %s<br>" \
            % (_translate('client_slot', 'Protocol'),
               self.client.protocol.to_string())
        tool_tip += "%s : %s<br>" \
            % (_translate('client_slot', 'Executable'),
               self.client.executable_path)
        tool_tip += "%s : %s</p>" \
            % (_translate('client_slot', 'client id'), self.client.client_id)
        tool_tip += "</body></html>"

        self.ui.ClientName.setToolTip(tool_tip)

        # set icon
        self._icon_on = get_app_icon(self.client.icon, self)
        self._icon_off = QIcon(self._icon_on.pixmap(32, 32, QIcon.Disabled))

        self._gray_icon(
            bool(self.client.status in (
                    ray.ClientStatus.STOPPED,
                    ray.ClientStatus.PRECOPY)))

        if not self.ui.toolButtonGUI.isVisible():
            self.ui.toolButtonGUI.setVisible(
                bool(':optional-gui:' in self.client.capabilities))
            self.set_gui_state(self.client.gui_state)

        if self.client.executable_path in ('ray-proxy', 'nsm-proxy'):
            if is_dark_theme(self):
                self._icon_visible = QIcon()
                self._icon_visible.addPixmap(
                    QPixmap(':scalable/breeze-dark/emblem-symbolic-link'),
                    QIcon.Normal, QIcon.Off)
                self._icon_invisible = QIcon()
                self._icon_invisible.addPixmap(
                    QPixmap(':scalable/breeze-dark/link'),
                    QIcon.Normal, QIcon.Off)
                self._icon_invisible.addPixmap(
                    QPixmap(':scalable/breeze-dark/disabled/link'),
                    QIcon.Disabled, QIcon.Off)
            else:
                self._icon_visible = QIcon()
                self._icon_visible.addPixmap(
                    QPixmap(':scalable/breeze/emblem-symbolic-link'),
                    QIcon.Normal, QIcon.Off)
                self._icon_invisible = QIcon()
                self._icon_invisible.addPixmap(
                    QPixmap(':scalable/breeze/link'), QIcon.Normal, QIcon.Off)
                self._icon_invisible.addPixmap(
                    QPixmap(':scalable/breeze/disabled/link'),
                    QIcon.Disabled, QIcon.Off)

    def update_status(self, status: int):
        self.ui.lineEditClientStatus.setText(client_status_string(status))
        self.ui.lineEditClientStatus.setEnabled(
            status != ray.ClientStatus.STOPPED)
        self.ui.actionFindBoxesInPatchbay.setEnabled(
            status not in (ray.ClientStatus.STOPPED, ray.ClientStatus.PRECOPY)) 

        ray_hack = bool(self.client.protocol is ray.Protocol.RAY_HACK)

        if status in (
                ray.ClientStatus.LAUNCH,
                ray.ClientStatus.OPEN,
                ray.ClientStatus.SWITCH,
                ray.ClientStatus.NOOP,
                ray.ClientStatus.LOSE):
            self.ui.startButton.setEnabled(False)
            self.ui.stopButton.setEnabled(True)
            self.ui.saveButton.setEnabled(False)
            self.ui.closeButton.setEnabled(False)
            self.ui.ClientName.setStyleSheet('QLabel {font-weight : bold}')
            self.ui.ClientName.setEnabled(True)
            self.ui.toolButtonGUI.setEnabled(True)
            self._gray_icon(False)

            if self._very_short:
                self.ui.startButton.setVisible(False)
                self.ui.stopButton.setVisible(True)

        elif status == ray.ClientStatus.READY:
            self.ui.startButton.setEnabled(False)
            self.ui.stopButton.setEnabled(True)
            self.ui.closeButton.setEnabled(False)
            self.ui.ClientName.setStyleSheet('QLabel {font-weight : bold}')
            self.ui.ClientName.setEnabled(True)
            self.ui.toolButtonGUI.setEnabled(True)
            self.ui.saveButton.setEnabled(True)
            self._gray_icon(False)

            if self._very_short:
                self.ui.startButton.setVisible(False)
                self.ui.stopButton.setVisible(True)

        elif status == ray.ClientStatus.STOPPED:
            self.ui.startButton.setEnabled(True)
            self.ui.stopButton.setEnabled(False)
            self.ui.saveButton.setEnabled(False)
            self.ui.closeButton.setEnabled(True)
            self.ui.ClientName.setStyleSheet('QLabel {font-weight : normal}')
            self.ui.ClientName.setEnabled(False)
            self.ui.toolButtonGUI.setEnabled(False)
            self._gray_icon(True)

            if self._very_short:
                self.ui.startButton.setVisible(True)
                self.ui.stopButton.setVisible(False)

            self.ui.saveButton.setIcon(self._save_icon)
            self.ui.stopButton.setIcon(self._stop_icon)
            self._stop_is_kill = False

            if not ray_hack:
                self.set_gui_state(False)

        elif status == ray.ClientStatus.PRECOPY:
            self.ui.startButton.setEnabled(False)
            self.ui.stopButton.setEnabled(False)
            self.ui.saveButton.setEnabled(False)
            self.ui.closeButton.setEnabled(True)
            self.ui.ClientName.setStyleSheet('QLabel {font-weight : normal}')
            self.ui.ClientName.setEnabled(False)
            self.ui.toolButtonGUI.setEnabled(False)
            self._gray_icon(True)

            if self._very_short:
                self.ui.startButton.setVisible(True)
                self.ui.stopButton.setVisible(False)

            self.ui.saveButton.setIcon(self._save_icon)
            self.ui.stopButton.setIcon(self._stop_icon)
            self._stop_is_kill = False

        elif status == ray.ClientStatus.COPY:
            self.ui.saveButton.setEnabled(False)

    def allow_kill(self):
        self._stop_is_kill = True
        self.ui.stopButton.setIcon(self._kill_icon)

    def flash_if_open(self, flash: bool):
        if flash:
            self.ui.lineEditClientStatus.setText(
                client_status_string(ray.ClientStatus.OPEN))
        else:
            self.ui.lineEditClientStatus.setText('')

    def set_hack_button_state(self, state: bool):
        self.ui.toolButtonHack.setChecked(state)

    def show_gui_button(self):
        self.ui.toolButtonGUI.setIcon(self._icon_invisible)
        self.ui.toolButtonGUI.setVisible(True)

    def set_gui_state(self, state: bool):
        if state:
            self.ui.toolButtonGUI.setIcon(self._icon_visible)
        else:
            self.ui.toolButtonGUI.setIcon(self._icon_invisible)

        self._gui_state = state

    def set_dirty_state(self, dirty: bool):
        self.ui.saveButton.setIcon(
            self._unsaved_icon if dirty else self._saved_icon)

    def set_no_save_level(self, no_save_level: int):
        self.ui.saveButton.setIcon(
            self._no_save_icon if no_save_level else self._save_icon)

    def set_progress(self, progress: float):
        self.ui.lineEditClientStatus.set_progress(progress)

    def set_daemon_options(self, options):
        has_git = bool(options & ray.Option.HAS_GIT)
        self.ui.actionReturnToAPreviousState.setVisible(has_git)

    def patchbay_is_shown(self, yesno: bool):
        self.ui.actionFindBoxesInPatchbay.setVisible(yesno)

    def contextMenuEvent(self, event: QContextMenuEvent):
        act_selected = self._menu.exec(self.mapToGlobal(event.pos()))
        event.accept()
        
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if (event.button() == Qt.LeftButton
                and self.client.status != ray.ClientStatus.STOPPED
                and self.client.jack_client_name
                and self.list_widget_item.isSelected()):
            self.client.session.patchbay_manager.select_client_box(
                self.client.jack_client_name)
        super().mousePressEvent(event)


class ClientItem(QListWidgetItem):
    def __init__(self, parent: 'ListWidgetClients', client_data):
        QListWidgetItem.__init__(self, parent, QListWidgetItem.UserType + 1)

        self.sort_number = 0
        self.widget = ClientSlot(parent, self, client_data)
        parent.setItemWidget(self, self.widget)
        self.setSizeHint(QSize(100, 45))

    def __lt__(self, other: 'ClientItem'):
        return self.sort_number < other.sort_number

    def __gt__(self, other: 'ClientItem'):
        return self.sort_number > other.sort_number

    def get_client_id(self):
        return self.widget.get_client_id()


class ListWidgetClients(QListWidget):
    def __init__(self, parent):
        QListWidget.__init__(self, parent)
        self._last_n = 0
        self.session = None

    @classmethod
    def to_daemon(self, *args):
        server = GuiServerThread.instance()
        if server:
            server.to_daemon(*args)

    @pyqtSlot()
    def _launch_favorite(self):
        template_name, factory = self.sender().data()
        self.to_daemon(
            '/ray/session/add_client_template',
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
            item: ClientItem = self.item(i)
            if item.get_client_id() == client_id:
                widget = item.widget
                self.takeItem(i)
                del item
                break

    def client_properties_state_changed(self, client_id: str, visible: bool):
        for i in range(self.count()):
            item: ClientItem = self.item(i)
            if item.get_client_id() == client_id:
                widget = item.widget
                widget.set_hack_button_state(visible)
                break

    def set_session(self, session: 'Session'):
        self.session = session

    def patchbay_is_shown(self, yesno: bool):
        for i in range(self.count()):
            item: ClientItem = self.item(i)
            widget = item.widget
            widget.patchbay_is_shown(yesno)

    def currentItem(self) -> ClientItem:
        return super().currentItem()

    def dropEvent(self, event):
        QListWidget.dropEvent(self, event)

        client_ids_list = []

        for i in range(self.count()):
            item: ClientItem = self.item(i)
            client_id = item.get_client_id()
            client_ids_list.append(client_id)

        server = GuiServerThread.instance()
        if server:
            server.to_daemon('/ray/session/reorder_clients', *client_ids_list)

    def mousePressEvent(self, event):
        if not self.itemAt(event.pos()):
            self.setCurrentRow(-1)

        QListWidget.mousePressEvent(self, event)

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
                        get_app_icon(favorite.icon, self), favorite.display_name)
                    act_app.setData([favorite.name, favorite.factory])
                    act_app.triggered.connect(self._launch_favorite)

                menu.addMenu(fav_menu)

                menu.addAction(
                    self.session.main_win.ui.actionAddApplication)
                menu.addAction(self.session.main_win.ui.actionAddExecutable)

                act_selected = menu.exec(self.mapToGlobal(event.pos()))
            event.accept()
            return

    def resizeEvent(self, event):
        QListWidget.resizeEvent(self, event)
        for i in range(self.count()):
            item: ClientItem = self.item(i)
            widget: ClientSlot = self.itemWidget(item)
            if widget is not None:
                widget.update_layout()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        super().keyPressEvent(event)
        
        # parse patchbay boxes of the selected client 
        if event.key() in (Qt.Key_Left, Qt.Key_Right):
            client = self.currentItem().widget.client
            if (client.status != ray.ClientStatus.STOPPED
                    and client.jack_client_name
                    and self.currentItem().isSelected()
                    and self.session is not None):
                self.session.patchbay_manager.select_client_box(
                    client.jack_client_name,
                    previous=bool(event.key() == Qt.Key_Left))