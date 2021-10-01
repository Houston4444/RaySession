
import os
import time

from PyQt5.QtWidgets import (QApplication, QTreeWidget, QTreeWidgetItem,
                             QDialogButtonBox, QMenu)
from PyQt5.QtGui import QIcon, QColor
from PyQt5.QtCore import Qt, QTimer, QDateTime, QSize, QLocale

import ray

from gui_tools import CommandLineArgs, RS, RayIcon, is_dark_theme, basename
from child_dialogs import ChildDialog
from client_properties_dialog import ClientPropertiesDialog
from snapshots_dialog import (
    Snapshot, SnapGroup, GROUP_MAIN)

import ui.open_session

_translate = QApplication.translate

COLUMN_NAME = 0
COLUMN_NOTES = 1
COLUMN_SCRIPTS = 2
COLUMN_DATE = 3


class PreviewClient(ray.ClientData):
    def __init__(self):
        ray.ClientData.__init__(self)
        self.properties_dialog = ClientPropertiesDialog.create(self)


class SessionItem(QTreeWidgetItem):
    def __init__(self, l_list, is_session=False):
        QTreeWidgetItem.__init__(self, l_list)
        self.is_session = is_session
        self.setTextAlignment(3, Qt.AlignRight | Qt.AlignVCenter)

    def __lt__(self, other):
        if self.childCount() and not other.childCount():
            return True

        if other.childCount() and not self.childCount():
            return False

        if OpenSessionDialog.sort_by_date:
            self_date_int = self.data(COLUMN_DATE, Qt.UserRole)
            other_date_int = other.data(COLUMN_DATE, Qt.UserRole)
            if self_date_int is None:
                if other_date_int is None:
                    return bool(self.text(COLUMN_NAME).lower()
                                < other.text(COLUMN_NAME).lower())
                return False
            
            if other_date_int is None:
                return True
            
            return self_date_int > other_date_int

        return bool(self.text(COLUMN_NAME).lower()
                    < other.text(COLUMN_NAME).lower())

    def show_conditionnaly(self, string: str)->bool:
        show = bool(
            string.lower() in self.data(COLUMN_NAME, Qt.UserRole).lower())

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
        if self.data(COLUMN_NAME, Qt.UserRole) == string:
            return self

        item = None

        for i in range(self.childCount()):
            item = self.child(i).find_item_with(string)
            if item:
                break

        return item
    
    def set_notes_icon(self, icon):
        self.setIcon(COLUMN_NOTES, icon)

    def set_scripted(self, script_flags:int, for_child=False):
        if script_flags == ray.ScriptFile.PREVENT:
            self.setText(COLUMN_SCRIPTS, "")
        else:
            if for_child:
                self.setText(COLUMN_SCRIPTS, "^_")
            else:
                self.setText(COLUMN_SCRIPTS, ">_")

        for i in range(self.childCount()):
            item = self.child(i)
            item.set_scripted(script_flags, for_child=True)
    
    def set_modified_date(self, date_int:int):
        self.setData(COLUMN_DATE, Qt.UserRole, date_int)

        date = QDateTime.fromSecsSinceEpoch(date_int)
        date_string =  date.toString("dd/MM/yy hh:mm")
        if QLocale.system().country() == QLocale.UnitedStates:
            date_string = date.toString("MM/dd/yy hh:mm")

        self.setText(COLUMN_DATE, date_string)
            
    def add_modified_date(self, path:str, date_int:int):
        self_path = self.data(COLUMN_NAME, Qt.UserRole)
        if not self_path:
            return
        
        if path == self_path:
            self.set_modified_date(date_int)
            return
        
        if path.startswith(self_path + '/'):
            current_data_date = self.data(COLUMN_DATE, Qt.UserRole)
            if current_data_date is None:
                current_data_date = 0
            
            if date_int > current_data_date:
                self.set_modified_date(date_int)
                
            for i in range(self.childCount()):
                child_item = self.child(i)
                child_item.add_modified_date(path, date_int)

    def set_locked(self, locked:bool):
        if locked:
            self.setFlags(self.flags() & ~Qt.ItemIsEnabled)
        else:
            self.setFlags(self.flags() | Qt.ItemIsEnabled)


class SessionFolder:
    name = ""
    path = ""
    is_session = False

    def __init__(self, name):
        self.name = name
        self.subfolders = []
        self.item = None

    def set_path(self, path):
        self.path = path

    def make_item(self):
        self.item = SessionItem([self.name, "", "", ""], self.is_session)
        self.item.setData(COLUMN_NAME, Qt.UserRole, self.path)

        if self.subfolders:
            self.item.setIcon(COLUMN_NAME, QIcon.fromTheme('folder'))

        if not self.is_session:
            self.item.setFlags(self.item.flags() & ~Qt.ItemIsSelectable)

        for folder in self.subfolders:
            sub_item = folder.make_item()
            self.item.addChild(sub_item)

        return self.item

    def sort_childrens(self):
        if self.item is None:
            return
        
        self.item.sortChildren(COLUMN_NAME, Qt.AscendingOrder)
        
        for folder in self.subfolders:
            folder.sort_childrens()
            


class OpenSessionDialog(ChildDialog):
    sort_by_date = False
    
    @classmethod
    def set_sort_by_date(cls, sort_by_date:bool):
        cls.sort_by_date = sort_by_date
    
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui.open_session.Ui_DialogOpenSession()
        self.ui.setupUi(self)

        self._session_renaming = ('', '')

        self._timer_progress_n = 0
        self._timer_progress = QTimer()
        self._timer_progress.setInterval(50)
        self._timer_progress.timeout.connect(self._timer_progress_timeout)
        self._timer_progress.start()
        self._progress_inverted = False

        self.session_menu = QMenu()
        self.action_rename = self.session_menu.addAction(
            QIcon.fromTheme('edit-rename'),
            _translate('session_menu', 'Rename session'))
        
        self.action_rename.triggered.connect(self._ask_for_session_rename)
        self.ui.toolButtonSessionMenu.setMenu(self.session_menu)

        self.ui.splitterMain.setSizes([240, 800])
        self.ui.stackedWidgetSessionName.set_text('')
        self.ui.previewFrame.setEnabled(False)
        self.ui.tabWidget.tabBar().setExpanding(True)
        self.ui.toolButtonFolder.clicked.connect(self._change_root_folder)
        
        self.ui.splitterMain.splitterMoved.connect(
            self._splitter_moved)
        self.ui.stackedWidgetSessionName.name_changed.connect(
            self._session_name_changed)
        self.ui.sessionList.currentItemChanged.connect(
            self._current_item_changed)
        self.ui.sessionList.setFocus(Qt.OtherFocusReason)
        self.ui.sessionList.itemDoubleClicked.connect(self._go_if_any)
        self.ui.sessionList.itemClicked.connect(self._deploy_item)
        self.ui.filterBar.textEdited.connect(self._update_filtered_list)
        self.ui.filterBar.key_event.connect(self._up_down_pressed)
        self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(False)
        self.ui.currentSessionsFolder.setText(CommandLineArgs.session_root)
        self.ui.checkBoxShowDates.stateChanged.connect(
            self._set_full_sessions_view)

        self.signaler.add_sessions_to_list.connect(self._add_sessions)
        self.signaler.root_changed.connect(self._root_changed)
        self.signaler.session_preview_update.connect(
            self._session_preview_update)
        self.signaler.session_details.connect(
            self._update_session_details)
        self.signaler.scripted_dir.connect(
            self._scripted_dir)
        self.signaler.other_session_renamed.connect(
            self._session_renamed_by_server)

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
        
        # snapshots related
        self.main_snap_group = SnapGroup()
        #self.ui.sessionList.setColumnWidth(0, 100)
        #self.ui.sessionList.setColumnWidth(1, 20)
        #self.ui.sessionList.setColumnWidth(2, 20)
        
        self._full_view = True
        
        self._set_full_sessions_view(False)
    
    def _set_full_sessions_view(self, full_view:bool):
        self.ui.sessionList.setHeaderHidden(not full_view)
        
        if full_view:
            self.ui.sessionList.setColumnCount(4)
        else:
            self.ui.sessionList.setColumnCount(3)
            
        self._full_view = full_view
        self._resize_session_names_column()
        
        OpenSessionDialog.set_sort_by_date(full_view)
        root_item = self.ui.sessionList.invisibleRootItem()
        root_item.sortChildren(COLUMN_NAME, Qt.AscendingOrder)
        for folder in self.folders:
            folder.sort_childrens()
        
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

            root_item = self.ui.sessionList.invisibleRootItem()
            sess_item = None

            for sess in self.session.recent_sessions:
                if sess == self.session.get_short_path():
                    continue

                for i in range(root_item.childCount()):
                    item = root_item.child(i)
                    sess_item = item.find_item_with(sess)
                    if sess_item is not None:
                        break
                
                if sess_item is not None:
                    self.ui.sessionList.setCurrentItem(sess_item)
                    self.ui.sessionList.scrollToItem(sess_item)
                    break
                
            QTimer.singleShot(20, self._resize_session_names_column)
            return

        for session_name in session_names:
            folder_div = session_name.split('/')
            folders = self.folders
            #folder_path_list = []

            for i in range(len(folder_div)):
                f = folder_div[i]
                for g in folders:
                    if g.name == f:
                        if i + 1 == len(folder_div):
                            g.set_path(session_name)
                            g.is_session = True

                        folders = g.subfolders
                        break
                else:
                    new_folder = SessionFolder(f)
                    if i + 1 == len(folder_div):
                        new_folder.set_path(session_name)
                        new_folder.is_session = True
                    else:
                        new_folder.set_path('/'.join(folder_div[:i+1]))

                    folders.append(new_folder)
                    folders = new_folder.subfolders

        self.ui.sessionList.clear()

        for folder in self.folders:
            item = folder.make_item()
            self.ui.sessionList.addTopLevelItem(item)

        self.ui.sessionList.sortByColumn(COLUMN_NAME, Qt.AscendingOrder)

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
        self._has_selection = bool(item and item.data(COLUMN_NAME, Qt.UserRole))
        
        self.ui.listWidgetPreview.clear()
        self.ui.treeWidgetSnapshots.clear()

        self._session_renaming = ('', '')
        
        if item is not None and item.is_session:
            session_full_name = item.data(COLUMN_NAME, Qt.UserRole)
            self.ui.stackedWidgetSessionName.set_text(basename(session_full_name))
            self.ui.previewFrame.setEnabled(True)
            if session_full_name:
                self.to_daemon('/ray/server/get_session_preview', session_full_name)
        else:
            self.ui.stackedWidgetSessionName.set_text('')
            self.ui.previewFrame.setEnabled(False)

        self._prevent_ok()

    def _prevent_ok(self):
        self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(
            bool(self._server_will_accept and self._has_selection))

    def _ask_for_session_rename(self):
        if not self.ui.previewFrame.isEnabled():
            return

        self.ui.stackedWidgetSessionName.toggle_edit()

    def _session_name_changed(self, new_name:str):
        item = self.ui.sessionList.currentItem()
        if item is None:
            return

        old_name = item.data(COLUMN_NAME, Qt.UserRole)

        # prevent accidental renaming to same name
        if basename(old_name) == new_name:
            return
        
        self._session_renaming = (old_name, new_name)
        self.to_daemon('/ray/server/rename_session', old_name, new_name)

    def _session_renamed_by_server(self):
        old_name, new_name = self._session_renaming
        self._session_renaming = ('', '')
        
        item = self.ui.sessionList.currentItem()
        if item is None:
            return

        current_name = item.data(COLUMN_NAME, Qt.UserRole)

        if current_name != old_name:
            return
        
        new_long_name = new_name
        if '/' in old_name:
            new_long_name = old_name.rpartition('/')[0] + '/' + new_name
        
        item.setData(COLUMN_NAME, Qt.UserRole, new_long_name)
        item.setText(COLUMN_NAME, new_name)
        self.ui.stackedWidgetSessionName.set_text(new_name)

    def _deploy_item(self, item, column):
        if column == COLUMN_NOTES and not item.icon(COLUMN_NOTES).isNull():
            # set preview tab to 'Notes' tab if user clicked on a notes icon 
            self.ui.tabWidget.setCurrentIndex(1)

        if not item.childCount():
            return

        if time.time() - self._last_mouse_click > 0.35:
            item.setExpanded(not item.isExpanded())

        self._last_mouse_click = time.time()

    def _go_if_any(self, item, column):
        if item.childCount():
            return

        if (self._server_will_accept and self._has_selection
                and self.ui.sessionList.currentItem().data(
                    COLUMN_NAME, Qt.UserRole)):
            self.accept()

    def _session_preview_update(self):
        self.ui.plainTextEditNotes.setPlainText(self.session.preview_notes)
        #self.ui.tabWidget.setTabEnabled(1, bool(self.session.preview_notes))

        for pv_client in self.session.preview_client_list:
            client_slot = self.ui.listWidgetPreview.create_client_widget(pv_client)
            client_slot.set_launched(
                pv_client.client_id in self.session.preview_started_clients)
        
        self.main_snap_group.snapshots.clear()
        self._add_snapshots(self.session.preview_snapshots)

    def _add_snapshots(self, snaptexts):
        if not snaptexts and not self.main_snap_group.snapshots:
            # Snapshot list finished without any snapshot
            #self._no_snapshot_found()
            return

        for snaptext in snaptexts:
            if not snaptext:
                continue

            snapshot = Snapshot.new_from_snaptext(snaptext)
            self.main_snap_group.add(snapshot)

        self.main_snap_group.sort()

        self.ui.treeWidgetSnapshots.clear()

        for snapshot in self.main_snap_group.snapshots:
            item = snapshot.make_item(GROUP_MAIN)
            self.ui.treeWidgetSnapshots.addTopLevelItem(item)

        #self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(False)
        self.ui.treeWidgetSnapshots.clearSelection()

    def _update_session_details(self, session_name:str,
                                has_notes:int, modified:int, locked:int):
        for i in range(self.ui.sessionList.topLevelItemCount()):
            item = self.ui.sessionList.topLevelItem(i)
            session_item = item.find_item_with(session_name)
            if session_item is not None:
                if has_notes:
                    session_item.set_notes_icon(
                        RayIcon('notes', is_dark_theme(self)))
                
                # we add directly date to top item
                # this way folder also read the last date
                item.add_modified_date(session_name, modified)

                session_item.set_locked(bool(locked))
                break

    def _scripted_dir(self, dir_name, script_flags):
        if dir_name == '':
            # means that all the session root directory is scripted
            for i in range(self.ui.sessionList.topLevelItemCount()):
                item = self.ui.sessionList.topLevelItem(i)
                item.set_scripted(script_flags)
            return

        for i in range(self.ui.sessionList.topLevelItemCount()):
            item = self.ui.sessionList.topLevelItem(i)
            scripted_item = item.find_item_with(dir_name)
            if scripted_item is not None:
                scripted_item.set_scripted(script_flags)

    def _resize_session_names_column(self):
        self.ui.sessionList.setColumnWidth(COLUMN_NOTES, 20)
        self.ui.sessionList.setColumnWidth(COLUMN_SCRIPTS, 20)
        scroll_bar = self.ui.sessionList.verticalScrollBar()
        width = 20
        
        if self._full_view:
            self.ui.sessionList.setColumnWidth(COLUMN_DATE, 105)

            width = self.ui.sessionList.width() - 150
            if scroll_bar.isVisible():
                width -= scroll_bar.width()
            
            width = max(width, 20)
            
        else:
            width = self.ui.sessionList.width() - 45            
            if scroll_bar.isVisible():
                width -= scroll_bar.width()
            
            width = max(width, 40)

        self.ui.sessionList.setColumnWidth(COLUMN_NAME, width)

    def _splitter_moved(self, pos:int, index:int):
        self._resize_session_names_column()

    def resizeEvent(self, event):
        ChildDialog.resizeEvent(self, event)
        self._resize_session_names_column()

    def get_selected_session(self)->str:
        if self.ui.sessionList.currentItem():
            return self.ui.sessionList.currentItem().data(
                COLUMN_NAME, Qt.UserRole)
