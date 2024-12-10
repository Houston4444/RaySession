
# Imports from standard library
import os
from pathlib import Path
import shutil
import time
from typing import Optional

# third party imports
from qtpy.QtWidgets import (QApplication, QTreeWidget, QTreeWidgetItem,
                             QDialogButtonBox, QMenu, QMessageBox)
from qtpy.QtGui import QIcon, QCursor
from qtpy.QtCore import Qt, QTimer, QDateTime, QLocale, QPoint

# Imports from src/shared
import ray
from osclib import get_net_url, TCP

# Local imports
import child_dialogs
from gui_tools import CommandLineArgs, ray_icon, is_dark_theme, basename
from child_dialogs import ChildDialog
from client_properties_dialog import ClientPropertiesDialog
from snapshots_dialog import (
    Snapshot, SnapGroup, SnGroup)
from gui_tcp_thread import GuiTcpThread

# Import UIs made with Qt-Designer
import ui.open_session

_translate = QApplication.translate

COLUMN_NAME = 0
COLUMN_NOTES = 1
COLUMN_SCRIPTS = 2
COLUMN_DATE = 3

PENDING_ACTION_NONE = 0
PENDING_ACTION_RENAME = 1
PENDING_ACTION_DUPLICATE = 2
PENDING_ACTION_TEMPLATE = 3

CORNER_HIDDEN = 0
CORNER_LISTING = 1
CORNER_COPY = 2
CORNER_NOTIFICATION = 3

DATA_SIZE = Qt.ItemDataRole.UserRole + 1


class SessionItem(QTreeWidgetItem):
    def __init__(self, l_list, is_session=False):
        QTreeWidgetItem.__init__(self, l_list)
        self.is_session = is_session
        self.setTextAlignment(
            3, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def __lt__(self, other: 'SessionItem'):
        if self.childCount() and not other.childCount():
            return True

        if other.childCount() and not self.childCount():
            return False

        if OpenSessionDialog.sort_by_date:
            self_date_int = self.data(COLUMN_DATE, Qt.ItemDataRole.UserRole)
            other_date_int = other.data(COLUMN_DATE, Qt.ItemDataRole.UserRole)
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

    def show_conditionnaly(self, string: str) -> bool:
        show = bool(
            string.lower() in self.data(COLUMN_NAME, Qt.ItemDataRole.UserRole).lower())

        n = 0
        for i in range(self.childCount()):
            if self.child(i).show_conditionnaly(string.lower()):
                n += 1
        if n:
            show = True

        self.setExpanded(bool(n and string))
        self.setHidden(not show)
        return show

    def find_item_with(self, string: str) -> 'Optional[SessionItem]':
        if self.data(COLUMN_NAME, Qt.ItemDataRole.UserRole) == string:
            return self

        item = None

        for i in range(self.childCount()):
            item = self.child(i).find_item_with(string)
            if item:
                break

        return item
    
    def set_notes_icon(self, icon):
        self.setIcon(COLUMN_NOTES, icon)

    def set_scripted(self, script_flags: ray.ScriptFile, for_child=False):
        if script_flags is ray.ScriptFile.PREVENT:
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
        self.setData(COLUMN_DATE, Qt.ItemDataRole.UserRole, date_int)

        date = QDateTime.fromSecsSinceEpoch(date_int)
        date_string =  date.toString("dd/MM/yy hh:mm")
        if QLocale.system().country() == QLocale.Country.UnitedStates:
            date_string = date.toString("MM/dd/yy hh:mm")

        self.setText(COLUMN_DATE, date_string)
            
    def add_modified_date(self, path:str, date_int:int):
        self_path = self.data(COLUMN_NAME, Qt.ItemDataRole.UserRole)
        if not self_path:
            return
        
        if path == self_path:
            self.set_modified_date(date_int)
            return
        
        if path.startswith(self_path + '/'):
            current_data_date = self.data(COLUMN_DATE, Qt.ItemDataRole.UserRole)
            if current_data_date is None:
                current_data_date = 0
            
            if date_int > current_data_date:
                self.set_modified_date(date_int)
                
            for i in range(self.childCount()):
                child_item = self.child(i)
                child_item.add_modified_date(path, date_int)

    def set_locked(self, locked:bool):
        if locked:
            self.setFlags(self.flags() & ~Qt.ItemFlag.ItemIsEnabled)
        else:
            self.setFlags(self.flags() | Qt.ItemFlag.ItemIsEnabled)

    # Re-implemented protected Qt function
    def child(self, index: int) -> 'SessionItem':
        return QTreeWidgetItem.child(self, index)


class SessionFolder:
    name = ""
    path = ""
    is_session = False

    def __init__(self, name):
        self.name = name
        self.subfolders = list[SessionFolder]()
        self.item = None

    def set_path(self, path):
        self.path = path

    def make_item(self):
        self.item = SessionItem([self.name, "", "", ""], self.is_session)
        self.item.setData(COLUMN_NAME, Qt.ItemDataRole.UserRole, self.path)

        if self.subfolders:
            self.item.setIcon(COLUMN_NAME, QIcon.fromTheme('folder'))

        if not self.is_session:
            self.item.setFlags(self.item.flags() & ~Qt.ItemFlag.ItemIsSelectable)

        for folder in self.subfolders:
            sub_item = folder.make_item()
            self.item.addChild(sub_item)

        return self.item

    def sort_childrens(self):
        if self.item is None:
            return
        
        self.item.sortChildren(COLUMN_NAME, Qt.SortOrder.AscendingOrder)
        
        for folder in self.subfolders:
            folder.sort_childrens()
            
    def find_item_with(self, sess_name:str):
        if self.item is None:
            return None
        
        return self.item.find_item_with(sess_name)


class SaveSessionTemplateDialog(child_dialogs.SaveTemplateSessionDialog):
    def __init__(self, parent):
        child_dialogs.SaveTemplateSessionDialog.__init__(self, parent)
        self._server_will_accept = True

    def _server_status_changed(self, server_status: ray.ServerStatus):
        # server will always accept, whatever the status
        pass
    
    def set_original_session_name(self, session_name:str):
        self.ui.labelLabel.setText(session_name)


class DuplicateDialog(child_dialogs.NewSessionDialog):
    def __init__(self, parent):
        child_dialogs.NewSessionDialog.__init__(
            self, parent, duplicate_window=True)
        self._server_will_accept = True
        self.ui.toolButtonFolder.setEnabled(False)
        self.ui.toolButtonFolder.setVisible(False)
        self._original_session_name = ''
    
    def _server_status_changed(self, server_status: ray.ServerStatus):
        # server will always accept, whatever the status
        pass
    
    def _add_sessions_to_list(self, session_names: list):
        child_dialogs.NewSessionDialog._add_sessions_to_list(self, session_names)
        if not session_names:
            subfolder, sep, after = self._original_session_name.rpartition('/')
            
            self.ui.lineEdit.setText(subfolder + sep)
    
    def set_original_session_name(self, session_name:str):
        self._original_session_name = session_name
        self.ui.labelOriginalSessionName.setText(session_name)


class OpenSessionDialog(ChildDialog):
    sort_by_date = False
    
    @classmethod
    def set_sort_by_date(cls, sort_by_date:bool):
        cls.sort_by_date = sort_by_date
    
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui.open_session.Ui_DialogOpenSession()
        self.ui.setupUi(self)

        self._pending_action = PENDING_ACTION_NONE
        self._session_renaming = ('', '')
        self._session_duplicating = ('', '')
        self._session_templating = ('', '')

        self._listing_timer_progress_n = 0
        self._listing_timer_progress = QTimer()
        self._listing_timer_progress.setInterval(50)
        self._listing_timer_progress.timeout.connect(
            self._listing_timer_progress_timeout)
        self._listing_timer_progress.start()
        self._progress_inverted = False

        self.session_menu = QMenu()
        self.action_duplicate = self.session_menu.addAction(
            QIcon.fromTheme('duplicate'),
            _translate('session_menu', 'Duplicate session'))
        self.action_save_as_template = self.session_menu.addAction(
            QIcon.fromTheme('template'),
            _translate('session_menu', 'Save session as template'))
        self.action_rename = self.session_menu.addAction(
            QIcon.fromTheme('edit-rename'),
            _translate('session_menu', 'Rename session'))
        self.action_remove = self.session_menu.addAction(
            QIcon.fromTheme('remove'),
            _translate('session_menu', 'Remove session'))

        dark = is_dark_theme(self)
        self.action_duplicate.setIcon(
            ray_icon('xml-node-duplicate', dark))
        self.action_save_as_template.setIcon(
            ray_icon('document-save-as-template', dark))

        self.action_rename.triggered.connect(self._ask_for_session_rename)
        self.action_duplicate.triggered.connect(self._ask_for_session_duplicate)
        self.action_save_as_template.triggered.connect(
            self._ask_for_session_save_as_template)
        self.action_remove.triggered.connect(self._ask_for_session_remove)
        self.ui.toolButtonSessionMenu.setMenu(self.session_menu)
        self.ui.toolButtonFolderPreview.clicked.connect(
            self._open_preview_folder)
        
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
        self.ui.sessionList.setFocus(Qt.FocusReason.OtherFocusReason)
        self.ui.sessionList.itemDoubleClicked.connect(self._go_if_any)
        self.ui.sessionList.itemClicked.connect(self._deploy_item)
        self.ui.sessionList.customContextMenuRequested.connect(
            self._show_context_menu)
        self.ui.filterBar.textEdited.connect(self._update_filtered_list)
        self.ui.filterBar.key_event.connect(self._up_down_pressed)
        self.ui.listWidgetPreview.properties_request.connect(
            self._show_client_properties)
        self.ui.listWidgetPreview.add_to_session_request.connect(
            self._add_client_to_current_session)
        self.ui.buttonBox.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self.ui.currentSessionsFolder.setText(CommandLineArgs.session_root)
        self.ui.checkBoxShowDates.stateChanged.connect(
            self._set_full_sessions_view)
        self.ui.pushButtonCancelProgress.clicked.connect(
            self._cancel_copy_clicked)

        self.signaler.add_sessions_to_list.connect(self._add_sessions)
        self.signaler.root_changed.connect(self._root_changed)
        self.signaler.session_preview_update.connect(
            self._session_preview_update)
        self.signaler.session_details.connect(
            self._update_session_details)
        self.signaler.scripted_dir.connect(
            self._scripted_dir)
        self.signaler.parrallel_copy_state.connect(
            self._parrallel_copy_state)
        self.signaler.parrallel_copy_progress.connect(
            self._parrallel_copy_progress)
        self.signaler.parrallel_copy_aborted.connect(
            self._parrallel_copy_aborted)
        self.signaler.other_session_renamed.connect(
            self._session_renamed_by_server)
        self.signaler.other_session_duplicated.connect(
            self._session_duplicated_by_server)
        self.signaler.other_session_templated.connect(
            self._session_templated_by_server)

        self.to_daemon('/ray/server/list_sessions', 0)
        
        self.ui.groupBoxProgress.setVisible(False)

        if not self.daemon_manager.is_local:
            self.ui.toolButtonFolder.setVisible(False)
            self.ui.currentSessionsFolder.setVisible(False)
            self.ui.labelSessionsFolder.setVisible(False)

        self._server_will_accept = False
        self._has_selection = False
        self._last_mouse_click = 0
        self._last_session_item = None

        self._server_status_changed(self.session.server_status)

        self._set_preview_scripted(False)

        self.folders = list[SessionFolder]()
        self.all_items = []

        self.ui.filterBar.setFocus(Qt.FocusReason.OtherFocusReason)
        
        # snapshots related
        self.main_snap_group = SnapGroup()

        self._full_view = True        
        self._set_full_sessions_view(False)
        
        self._current_parrallel_copy_id = 0
        self._corner_mode = CORNER_HIDDEN
        self._set_corner_group(CORNER_HIDDEN)
        
        self.ui.checkBoxSaveCurrentSession.setVisible(
            self.session.server_status is ray.ServerStatus.READY)
        self.ui.listWidgetPreview.server_status_changed(
            self.session.server_status)
        
        self._last_selected_session = ''
        self._listing_sessions = False
    
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
        root_item.sortChildren(COLUMN_NAME, Qt.SortOrder.AscendingOrder)
        for folder in self.folders:
            folder.sort_childrens()
        
    def _server_status_changed(self, server_status: ray.ServerStatus):
        self.ui.toolButtonFolder.setEnabled(
            bool(server_status in (ray.ServerStatus.OFF,
                                   ray.ServerStatus.READY,
                                   ray.ServerStatus.CLOSE)))

        self._server_will_accept = bool(
            server_status in (
                ray.ServerStatus.OFF,
                ray.ServerStatus.READY) and not self.server_copying)

        if server_status is not ray.ServerStatus.OFF:
            if self._root_folder_file_dialog is not None:
                self._root_folder_file_dialog.reject()
            self._root_folder_message_box.reject()

        self.ui.checkBoxSaveCurrentSession.setVisible(
            server_status is ray.ServerStatus.READY)
        
        self.ui.listWidgetPreview.server_status_changed(server_status)

        self._prevent_ok()

    def _listing_timer_progress_timeout(self):
        # server is listing sessions
        if self._listing_timer_progress_n >= 10: # 10 x 50ms = 500 ms
            # display groupBoxProgress only if listing takes at least 500ms
            # to prevent flircks
            self._set_corner_group(CORNER_LISTING)
        
        self.ui.progressBar.setValue(self._listing_timer_progress_n)
        if self._listing_timer_progress_n >= 100:
            self._listing_timer_progress_n = 0
            self._progress_inverted = not self._progress_inverted
            self.ui.progressBar.setInvertedAppearance(
                self._progress_inverted)
        self._listing_timer_progress_n += 5

    def _root_changed(self, session_root):
        self.ui.currentSessionsFolder.setText(session_root)
        self.ui.sessionList.clear()
        self.folders.clear()
        self.to_daemon('/ray/server/list_sessions', 0)

    def _add_sessions(self, session_names: list[str], out_of_listing=False):
        if not self._listing_sessions and not out_of_listing:
            # in case session server is listing sessions
            # but they are already listed.
            # Check which one is selected and clear all of them. 
            item = self.ui.sessionList.currentItem()
            if item is not None:
                self._last_selected_session = item.data(
                    COLUMN_NAME, Qt.ItemDataRole.UserRole)
            
            self.folders.clear()
            self.ui.sessionList.clear()
            
        if not session_names:
            # there are no session_names here if session listing
            # is finished.
            self._listing_sessions = False
            self._listing_timer_progress.stop()
            height = self.ui.groupBoxProgress.size().height()
            self._set_corner_group(CORNER_HIDDEN)

            root_item = self.ui.sessionList.invisibleRootItem()
            sess_item = None
            
            if self._last_selected_session:
                for folder in self.folders:
                    item = folder.find_item_with(
                        self._last_selected_session)
                    if item is not None:
                        self.ui.sessionList.setCurrentItem(item)
                        self.ui.sessionList.scrollToItem(item)
                        break
                else:
                    self._last_selected_session = ''
            
            if not self._last_selected_session:
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

        if not out_of_listing:
            self._listing_sessions = True
        self.ui.sessionList.clear()

        for folder in self.folders:
            item = folder.make_item()
            self.ui.sessionList.addTopLevelItem(item)

        self.ui.sessionList.sortByColumn(
            COLUMN_NAME, Qt.SortOrder.AscendingOrder)

    def _update_filtered_list(self, filt):
        filter_text = self.ui.filterBar.displayText()
        root_item = self.ui.sessionList.invisibleRootItem()

        ## hide all non matching items
        for i in range(root_item.childCount()):
            sess_item: SessionItem = root_item.child(i)
            sess_item.show_conditionnaly(filter_text)

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

        while not current_item.flags() & Qt.ItemFlag.ItemIsSelectable:
            ex_item = current_item
            QTreeWidget.keyPressEvent(self.ui.sessionList, event)
            current_item = self.ui.sessionList.currentItem()
            if current_item == ex_item:
                self.ui.sessionList.setCurrentItem(start_item)
                return

    def _current_item_changed(
            self, item: SessionItem, previous_item: SessionItem):
        self._has_selection = bool(
            item and item.data(COLUMN_NAME, Qt.ItemDataRole.UserRole))
        
        self.ui.listWidgetPreview.clear()
        self.ui.treeWidgetSnapshots.clear()
        self.ui.labelSessionSize.setText('')
        
        if item is not None and item.is_session:
            session_full_name: str = item.data(
                COLUMN_NAME, Qt.ItemDataRole.UserRole)
            self.ui.stackedWidgetSessionName.set_text(
                Path(session_full_name).name)
            self.ui.previewFrame.setEnabled(True)
            if session_full_name:
                tcp_server = GuiTcpThread.instance()
                tcp_url = get_net_url(tcp_server.port, protocol=TCP)
                self.to_daemon(
                    '/ray/server/get_session_preview',
                    tcp_url, session_full_name)

            if item.text(COLUMN_SCRIPTS):
                self._set_preview_scripted(True)
            else:
                self._set_preview_scripted(False)
        else:
            self.ui.stackedWidgetSessionName.set_text('')
            self.ui.previewFrame.setEnabled(False)
            self._set_preview_scripted(False)

        if item is not None:
            self._last_current_item = item

        self._prevent_ok()

    def _set_preview_scripted(self, scripted:bool):
        if scripted:
            self.ui.labelPreviewScript.setText('>_')
            self.ui.labelPreviewScript.setToolTip(
                _translate('open_session', 'This session is scripted'))
            self.ui.labelPreviewScript.setStyleSheet(
                'QLabel{color:green;background-color:black}')
        else:
            self.ui.labelPreviewScript.setText('')
            self.ui.labelPreviewScript.setToolTip('')
            self.ui.labelPreviewScript.setStyleSheet('')

    def _prevent_ok(self):
        self.ui.buttonBox.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
            bool(self._server_will_accept and self._has_selection))

    def _show_context_menu(self):
        item: SessionItem = self.ui.sessionList.currentItem()
        if item is None:
            return

        if not item.is_session:
            return

        x = QCursor.pos().x()
        rect = self.ui.sessionList.visualItemRect(item)
        y = self.ui.sessionList.mapToGlobal(rect.bottomLeft()).y()
        
        self.session_menu.exec(QPoint(x, y+1))

    def _set_pending_action(self, action:int):
        self._pending_action = action
        self._update_session_menu()

    def _open_preview_folder(self):
        item = self.ui.sessionList.currentItem()
        if item is None:
            return
        
        session_name = item.data(COLUMN_NAME, Qt.ItemDataRole.UserRole)
        self.to_daemon(
            '/ray/server/open_file_manager_at',
            os.path.join(CommandLineArgs.session_root, session_name))

    def _set_corner_group(self, corner_mode:int):
        self._corner_mode = corner_mode
        self.ui.groupBoxProgress.setVisible(corner_mode != CORNER_HIDDEN)
        self.ui.pushButtonCancelProgress.setVisible(
            corner_mode != CORNER_LISTING)

        if corner_mode == CORNER_LISTING:
            self.ui.labelProgress.setText(
                _translate('open_session', 'Listing sessions'))
        elif corner_mode == CORNER_COPY:
            self.ui.pushButtonCancelProgress.setText(
                _translate('open_session', 'Cancel'))
            self.ui.labelProgress.setText(
                _translate('open_session', 'Session copy'))
            self.ui.progressBar.setValue(0)
        elif corner_mode == CORNER_NOTIFICATION:
            self.ui.pushButtonCancelProgress.setText(
                _translate('open_session', 'Ok'))
            self.ui.labelProgress.setText(
                _translate('open_session', 'Session saved as template'))
            self.ui.progressBar.setValue(100)

    def _ask_for_session_rename(self):
        if not self.ui.previewFrame.isEnabled():
            return

        self.ui.stackedWidgetSessionName.toggle_edit()

    def _ask_for_session_duplicate(self):
        item = self.ui.sessionList.currentItem()
        if item is None:
            return
        
        old_session_name = item.data(COLUMN_NAME, Qt.ItemDataRole.UserRole)
        
        if self._pending_action:
            return

        dialog = DuplicateDialog(self)
        dialog.set_original_session_name(old_session_name)
        dialog.exec()
        if not dialog.result():
            return
        
        new_session_name = dialog.get_session_short_path()

        self._set_pending_action(PENDING_ACTION_DUPLICATE)
        self._session_duplicating = (old_session_name, new_session_name)
        self.to_daemon('/ray/session/duplicate_only', old_session_name,
                       new_session_name, CommandLineArgs.session_root)

    def _ask_for_session_save_as_template(self):
        item = self.ui.sessionList.currentItem()
        if item is None:
            return

        if self._pending_action:
            return

        session_name = item.data(COLUMN_NAME, Qt.ItemDataRole.UserRole)

        dialog = SaveSessionTemplateDialog(self)
        dialog.set_original_session_name(session_name)
        dialog.exec()
        if not dialog.result():
            return
        
        template_name = dialog.get_template_name()

        self._set_pending_action(PENDING_ACTION_TEMPLATE)
        self._session_templating = (session_name, template_name)
        self.to_daemon('/ray/server/save_session_template',
                       session_name, template_name)

    def _ask_for_session_remove(self):
        # we won't call the server to remove a session
        # because it would enable a very dangerous OSC path.
        # we will remove it directly in the GUI process and thread
        if CommandLineArgs.out_daemon:
            return

        # do not allow to remove from GUI a too big session
        # totally arbitrary choice : 95.37 Mb
        if self.session.preview_size >= 100000000:
            return
        
        item = self.ui.sessionList.currentItem()
        if item is None:
            return
        
        session_name = item.data(COLUMN_NAME, Qt.ItemDataRole.UserRole)
        full_path = os.path.join(CommandLineArgs.session_root, session_name)

        if not os.path.isdir(full_path):
            return
        
        ret = QMessageBox.critical(
            self,
            _translate('open_session', 'Remove session'),
            _translate(
                'open_session',
                '<p>Are you really sure to want to remove '
                'the following session:</p>'
                '<p><strong>%s</strong></p>'
                '<p>This action is irreversible.')
            % session_name,
            QMessageBox.StandardButton.No | QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.No)
        
        if ret != QMessageBox.StandardButton.Yes:
            return
            
        try:
            shutil.rmtree(full_path)
        except:
            # TODO
            return

        parent = item.parent()
        if parent is None:
            parent = self.ui.sessionList.invisibleRootItem()
        parent.removeChild(item)

    def _session_name_changed(self, new_name:str):
        item = self.ui.sessionList.currentItem()
        if item is None:
            return

        old_name: str = item.data(COLUMN_NAME, Qt.ItemDataRole.UserRole)

        # prevent accidental renaming to same name
        if Path(old_name).name == new_name:
            return
        
        if self._pending_action:
            return

        self._set_pending_action(PENDING_ACTION_RENAME)
        self._session_renaming = (old_name, new_name)
        self.to_daemon('/ray/server/rename_session', old_name, new_name)

    def _parrallel_copy_state(self, session_id:int, state:int):
        if state and self._current_parrallel_copy_id:
            return
        
        self._current_parrallel_copy_id = session_id if state else 0

        if not state:
            self._set_corner_group(CORNER_HIDDEN)

    def _parrallel_copy_progress(self, session_id:int, progress:float):
        if session_id != self._current_parrallel_copy_id:
            return

        self._set_corner_group(CORNER_COPY)
        self.ui.progressBar.setValue(int(progress * 100))

    def _parrallel_copy_aborted(self):
        self._set_corner_group(CORNER_HIDDEN)
        self._set_pending_action(PENDING_ACTION_NONE)

    def _cancel_copy_clicked(self):
        if not self._current_parrallel_copy_id:
            if self._corner_mode == CORNER_NOTIFICATION:
                self._set_corner_group(CORNER_HIDDEN)
            return
        
        self.to_daemon('/ray/server/abort_parrallel_copy',
                       self._current_parrallel_copy_id)

    def _session_renamed_by_server(self):
        old_name, new_name = self._session_renaming
        self._session_renaming = ('', '')
        current_name = ''

        item = self.ui.sessionList.currentItem()
        if item is not None:
            current_name = item.data(COLUMN_NAME, Qt.ItemDataRole.UserRole)

        new_long_name = new_name
        if '/' in old_name:
            new_long_name = old_name.rpartition('/')[0] + '/' + new_name

        if current_name != old_name:
            # should rarely happens because rename session is very fast
            # in case session has been renamed but is not selected anymore
            for i in range(self.ui.sessionList.topLevelItemCount()):
                item: SessionItem = self.ui.sessionList.topLevelItem(i)
                session_item = item.find_item_with(old_name)
                if session_item is not None:
                    session_item.setData(
                        COLUMN_NAME, Qt.ItemDataRole.UserRole, new_long_name)
                    session_item.setText(COLUMN_DATE, new_name)
                    break
            return
        
        if item is None:
            return

        item.setData(COLUMN_NAME, Qt.ItemDataRole.UserRole, new_long_name)
        item.setText(COLUMN_NAME, new_name)
        self.ui.stackedWidgetSessionName.set_text(new_name)
        self._set_pending_action(PENDING_ACTION_NONE)

    def _session_duplicated_by_server(self):
        old_name, new_name = self._session_duplicating
        self._session_duplicating = ('', '')
        self._set_pending_action(PENDING_ACTION_NONE)

        self._add_sessions([new_name], out_of_listing=True)

        for folder in self.folders:
            item = folder.find_item_with(new_name)
            if item is not None:
                self.ui.sessionList.setCurrentItem(item)
                filter_text = self.ui.filterBar.text()

                if filter_text.lower() in new_name.lower():
                    self._update_filtered_list('')
                else:
                    self.ui.filterBar.setText('')

                parent_item = item.parent()
                while parent_item is not None:
                    parent_item.setExpanded(True)
                    parent_item = parent_item.parent()
                self.ui.sessionList.scrollToItem(item)
                break

        self._set_corner_group(CORNER_HIDDEN)
    
    def _session_templated_by_server(self):
        session_name, template_name = self._session_templating
        self._session_templating = ('', '')
        if self._pending_action == PENDING_ACTION_TEMPLATE:
            self._set_corner_group(CORNER_NOTIFICATION)
        self._set_pending_action(PENDING_ACTION_NONE)
    
    def _deploy_item(self, item: SessionItem, column):
        if column == COLUMN_NOTES and not item.icon(COLUMN_NOTES).isNull():
            # set preview tab to 'Notes' tab if user clicked on a notes icon 
            self.ui.tabWidget.setCurrentIndex(1)

        if not item.childCount():
            return

        if time.time() - self._last_mouse_click > 0.35:
            item.setExpanded(not item.isExpanded())

        self._last_mouse_click = time.time()

    def _go_if_any(self, item: SessionItem, column):
        if item.childCount():
            return

        if (self._server_will_accept and self._has_selection
                and self.ui.sessionList.currentItem().data(
                    COLUMN_NAME, Qt.ItemDataRole.UserRole)):
            self.accept()

    def _session_preview_update(self, state: int):
        self.ui.plainTextEditNotes.setPlainText(self.session.preview_notes)

        for pv_client in self.session.preview_client_list:
            client_slot = self.ui.listWidgetPreview.create_client_widget(pv_client)
            client_slot.set_launched(
                pv_client.client_id in self.session.preview_started_clients)
        
        self.main_snap_group.snapshots.clear()
        self._add_snapshots(self.session.preview_snapshots)
        
        locale = QLocale()
        self.ui.labelSessionSize.setText(
            locale.formattedDataSize(self.session.preview_size))
        
        # store size in item
        item = self.ui.sessionList.currentItem()
        if item is not None:
            item.setData(COLUMN_NAME, DATA_SIZE, self.session.preview_size)
            self._set_preview_scripted(
                bool(item.text(COLUMN_SCRIPTS)))
        else:
            self._set_preview_scripted(False)
                
        self._update_session_menu()

    def _update_session_menu(self):
        item = self.ui.sessionList.currentItem()
        if item is None:
            self.session_menu.setEnabled(False)
            return
        
        self.session_menu.setEnabled(True)
        session_size = item.data(COLUMN_NAME, DATA_SIZE)
        allow_remove = False
        remove_title = _translate('session_menu', 'Remove session')
        
        if session_size is not None:
            if session_size >= 100000000:
                remove_title = _translate('session_menu', 'Remove session (too big)')
            else:
                allow_remove = True
        
        self.action_remove.setText(remove_title)
        
        ok = not bool(self._pending_action)
        self.action_duplicate.setEnabled(ok)
        self.action_rename.setEnabled(ok)
        self.action_save_as_template.setEnabled(ok)
        self.action_remove.setEnabled(ok and allow_remove)

    def _add_snapshots(self, snaptexts: list[str]):
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
            item = snapshot.make_item(SnGroup.MAIN)
            self.ui.treeWidgetSnapshots.addTopLevelItem(item)

        self.ui.treeWidgetSnapshots.clearSelection()

    def _update_session_details(self, session_name: str,
                                has_notes: int, modified: int, locked: int):
        for i in range(self.ui.sessionList.topLevelItemCount()):
            item: SessionItem = self.ui.sessionList.topLevelItem(i)
            session_item = item.find_item_with(session_name)
            if session_item is not None:
                if has_notes:
                    session_item.set_notes_icon(
                        ray_icon('notes', is_dark_theme(self)))
                
                # we add directly date to top item
                # this way folder also read the last date
                item.add_modified_date(session_name, modified)

                session_item.set_locked(bool(locked))
                break

    def _scripted_dir(self, dir_name: str, script_flags: int):
        if dir_name == '':
            # means that all the session root directory is scripted
            for i in range(self.ui.sessionList.topLevelItemCount()):
                item: SessionItem = self.ui.sessionList.topLevelItem(i)
                item.set_scripted(ray.ScriptFile(script_flags))
            return

        for i in range(self.ui.sessionList.topLevelItemCount()):
            item = self.ui.sessionList.topLevelItem(i)
            scripted_item = item.find_item_with(dir_name)
            if scripted_item is not None:
                scripted_item.set_scripted(ray.ScriptFile(script_flags))

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

    def _show_client_properties(self, client_id:str):
        for pv_client in self.session.preview_client_list:
            if pv_client.client_id == client_id:
                properties_dialog = ClientPropertiesDialog.create(
                    self, pv_client)
                properties_dialog.update_contents()
                properties_dialog.lock_widgets()
                properties_dialog.show()
                break

    def _add_client_to_current_session(self, client_id:str):
        item = self.ui.sessionList.currentItem()
        if item is None:
            return
        
        session_name = item.data(COLUMN_NAME, Qt.ItemDataRole.UserRole)
        self.to_daemon('/ray/session/add_other_session_client',
                       session_name, client_id)
        self.reject()

    def _splitter_moved(self, pos:int, index:int):
        self._resize_session_names_column()

    def resizeEvent(self, event):
        ChildDialog.resizeEvent(self, event)
        self._resize_session_names_column()

    def closeEvent(self, event):
        self._cancel_copy_clicked()
        ChildDialog.closeEvent(self, event)

    def get_selected_session(self)->str:
        if self.ui.sessionList.currentItem():
            return self.ui.sessionList.currentItem().data(
                COLUMN_NAME, Qt.ItemDataRole.UserRole)

    def want_to_save_previous(self)->bool:
        if self.ui.checkBoxSaveCurrentSession.isHidden():
            return True

        return self.ui.checkBoxSaveCurrentSession.isChecked()
