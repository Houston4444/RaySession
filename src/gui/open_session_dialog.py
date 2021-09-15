
import os
import time

from PyQt5.QtWidgets import QTreeWidget, QTreeWidgetItem, QDialogButtonBox
from PyQt5.QtGui import QIcon
from PyQt5.QtCore import Qt, QTimer

import ray

from gui_tools import CommandLineArgs, RS
from child_dialogs import ChildDialog
from client_properties_dialog import ClientPropertiesDialog

import ui.open_session

class PreviewClient(ray.ClientData):
    def __init__(self):
        ray.ClientData.__init__(self)
        self.properties_dialog = ClientPropertiesDialog.create(self)


class SessionItem(QTreeWidgetItem):
    def __init__(self, l_list):
        QTreeWidgetItem.__init__(self, l_list)

    def __lt__(self, other):
        if self.childCount() and not other.childCount():
            return True

        if other.childCount() and not self.childCount():
            return False

        return bool(self.text(0).lower() < other.text(0).lower())

    def show_conditionnaly(self, string: str)->bool:
        show = bool(string.lower() in self.data(0, Qt.UserRole).lower())

        n = 0
        for i in range(self.childCount()):
            if self.child(i).show_conditionnaly(string.lower()):
                n += 1
        if n:
            show = True

        self.setExpanded(bool(n and string))
        self.setHidden(not show)
        return show

    def find_item_with(self, string):
        if self.data(0, Qt.UserRole) == string:
            return self

        item = None

        for i in range(self.childCount()):
            item = self.child(i).find_item_with(string)
            if item:
                break

        return item

class SessionFolder:
    name = ""
    has_session = True
    path = ""

    def __init__(self, name):
        self.name = name
        self.subfolders = []

    def set_path(self, path):
        self.path = path

    def make_item(self):
        item = SessionItem([self.name])

        item.setData(0, Qt.UserRole, self.path)
        if self.subfolders:
            item.setIcon(0, QIcon.fromTheme('folder'))

        if not self.path:
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable)

        for folder in self.subfolders:
            sub_item = folder.make_item()
            item.addChild(sub_item)

        return item

class OpenSessionDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui.open_session.Ui_DialogOpenSession()
        self.ui.setupUi(self)

        self._timer_progress_n = 0
        self._timer_progress = QTimer()
        self._timer_progress.setInterval(50)
        self._timer_progress.timeout.connect(self._timer_progress_timeout)
        self._timer_progress.start()
        self._progress_inverted = False

        self.ui.widgetSpacer.setVisible(False)

        self.ui.labelSessionName.setText('')
        self.ui.tabWidget.setEnabled(False)
        self.ui.tabWidget.tabBar().setExpanding(True)
        
        self.ui.toolButtonFolder.clicked.connect(self._change_root_folder)
        self.ui.sessionList.currentItemChanged.connect(
            self._current_item_changed)
        self.ui.sessionList.setFocus(Qt.OtherFocusReason)
        self.ui.sessionList.itemDoubleClicked.connect(self._go_if_any)
        self.ui.sessionList.itemClicked.connect(self._deploy_item)
        self.ui.filterBar.textEdited.connect(self._update_filtered_list)
        self.ui.filterBar.key_event.connect(self._up_down_pressed)
        self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(False)
        self.ui.currentSessionsFolder.setText(CommandLineArgs.session_root)

        self.signaler.add_sessions_to_list.connect(self._add_sessions)
        self.signaler.root_changed.connect(self._root_changed)
        self.signaler.session_preview_update.connect(
            self._session_preview_update)

        self.to_daemon('/ray/server/list_sessions', 0)

        if not self.daemon_manager.is_local:
            self.ui.toolButtonFolder.setVisible(False)
            self.ui.currentSessionsFolder.setVisible(False)
            self.ui.labelSessionsFolder.setVisible(False)

        self._server_will_accept = False
        self._has_selection = False
        self._last_mouse_click = 0
        self._last_session_item = None

        self._server_status_changed(self.session.server_status)

        self.folders = []
        self.all_items = []

        self.ui.filterBar.setFocus(Qt.OtherFocusReason)

    def _server_status_changed(self, server_status):
        self.ui.toolButtonFolder.setEnabled(
            bool(server_status in (ray.ServerStatus.OFF,
                                   ray.ServerStatus.READY,
                                   ray.ServerStatus.CLOSE)))

        self._server_will_accept = bool(
            server_status in (
                ray.ServerStatus.OFF,
                ray.ServerStatus.READY) and not self.server_copying)

        if server_status != ray.ServerStatus.OFF:
            if self._root_folder_file_dialog is not None:
                self._root_folder_file_dialog.reject()
            self._root_folder_message_box.reject()

        self._prevent_ok()

    def _timer_progress_timeout(self):
        self.ui.progressBar.setValue(self._timer_progress_n)
        if self._timer_progress_n >= 100:
            self._timer_progress_n = 0
            self._progress_inverted = not self._progress_inverted
            self.ui.progressBar.setInvertedAppearance(
                self._progress_inverted)
        self._timer_progress_n += 5

    def _root_changed(self, session_root):
        self.ui.currentSessionsFolder.setText(session_root)
        self.ui.sessionList.clear()
        self.folders.clear()
        self.to_daemon('/ray/server/list_sessions', 0)

    def _add_sessions(self, session_names):
        if not session_names:
            self._timer_progress.stop()
            height = self.ui.progressBar.size().height()
            self.ui.progressBar.setVisible(False)
            self.ui.widgetSpacer.setVisible(True)

            # Try to select last used session
            root_item = self.ui.sessionList.invisibleRootItem()
            for i in range(root_item.childCount()):
                item = root_item.child(i)
                last_session_item = item.find_item_with(
                    RS.settings.value('last_session', type=str))

                if last_session_item:
                    self.ui.sessionList.setCurrentItem(last_session_item)
                    self.ui.sessionList.scrollToItem(last_session_item)
                    break
            return

        for session_name in session_names:
            folder_div = session_name.split('/')
            folders = self.folders

            for i in range(len(folder_div)):
                f = folder_div[i]
                for g in folders:
                    if g.name == f:
                        if i+1 == len(folder_div):
                            g.set_path(session_name)

                        folders = g.subfolders
                        break
                else:
                    new_folder = SessionFolder(f)
                    if i+1 == len(folder_div):
                        new_folder.set_path(session_name)
                    folders.append(new_folder)
                    folders = new_folder.subfolders

        self.ui.sessionList.clear()

        for folder in self.folders:
            item = folder.make_item()
            self.ui.sessionList.addTopLevelItem(item)

        self.ui.sessionList.sortByColumn(0, Qt.AscendingOrder)

    def _update_filtered_list(self, filt):
        filter_text = self.ui.filterBar.displayText()
        root_item = self.ui.sessionList.invisibleRootItem()

        ## hide all non matching items
        for i in range(root_item.childCount()):
            root_item.child(i).show_conditionnaly(filter_text)

        # if selected item not in list, then select the first visible
        if (not self.ui.sessionList.currentItem()
                or self.ui.sessionList.currentItem().isHidden()):
            for i in range(root_item.childCount()):
                item = root_item.child(i)
                if not item.isHidden():
                    self.ui.sessionList.setCurrentItem(item)
                    break

        if (not self.ui.sessionList.currentItem()
                or self.ui.sessionList.currentItem().isHidden()):
            self.ui.filterBar.setStyleSheet(
                "QLineEdit { background-color: red}")
            self.ui.sessionList.setCurrentItem(None)
        else:
            self.ui.filterBar.setStyleSheet("")
            self.ui.sessionList.scrollTo(self.ui.sessionList.currentIndex())

    def _up_down_pressed(self, event):
        start_item = self.ui.sessionList.currentItem()
        QTreeWidget.keyPressEvent(self.ui.sessionList, event)
        if not start_item:
            return

        current_item = self.ui.sessionList.currentItem()
        if current_item == start_item:
            return

        ex_item = current_item

        while not current_item.flags() & Qt.ItemIsSelectable:
            ex_item = current_item
            QTreeWidget.keyPressEvent(self.ui.sessionList, event)
            current_item = self.ui.sessionList.currentItem()
            if current_item == ex_item:
                self.ui.sessionList.setCurrentItem(start_item)
                return

    def _current_item_changed(self, item, previous_item):
        self._has_selection = bool(item and item.data(0, Qt.UserRole))
        
        self.ui.listWidgetPreview.clear()
        
        if item is not None:
            session_full_name = item.data(0, Qt.UserRole)
            self.ui.labelSessionName.setText(
                os.path.basename(session_full_name))
            self.ui.tabWidget.setEnabled(bool(session_full_name))
            if session_full_name:
                self.to_daemon('/ray/server/get_session_preview', session_full_name)

        self._prevent_ok()

    def _prevent_ok(self):
        self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(
            bool(self._server_will_accept and self._has_selection))

    def _deploy_item(self, item, column):
        if not item.childCount():
            return

        if time.time() - self._last_mouse_click > 0.35:
            item.setExpanded(not item.isExpanded())

        self._last_mouse_click = time.time()

    def _go_if_any(self, item, column):
        if item.childCount():
            return

        if (self._server_will_accept and self._has_selection
                and self.ui.sessionList.currentItem().data(0, Qt.UserRole)):
            self.accept()

    def _session_preview_update(self):
        self.ui.plainTextEditNotes.setPlainText(self.session.preview_notes)
        self.ui.tabWidget.setTabEnabled(1, bool(self.session.preview_notes))

        for pv_client in self.session.preview_client_list:
            client_slot = self.ui.listWidgetPreview.create_client_widget(pv_client)
            client_slot.set_launched(
                pv_client.client_id in self.session.preview_started_clients)

    def get_selected_session(self)->str:
        if self.ui.sessionList.currentItem():
            return self.ui.sessionList.currentItem().data(0, Qt.UserRole)
