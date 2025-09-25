
# Imports from standard library
import os
import logging
import time
import subprocess
from typing import TYPE_CHECKING

# third party imports
from qtpy.QtWidgets import (
    QDialog, QDialogButtonBox, QCompleter, QMessageBox,
    QFileDialog, QApplication, QListWidgetItem)
from qtpy.QtGui import QIcon, QPixmap, QGuiApplication, QKeyEvent
from qtpy.QtCore import Qt, QTimer

# Imports from src/shared
from osclib import Address, verified_address
import ray
import osc_paths
import osc_paths.ray as r
import osc_paths.ray.gui as rg

# Local imports
import client_properties_dialog
from gui_server_thread import GuiServerThread
from gui_tools import (ErrDaemon, _translate, get_app_icon,
                       CommandLineArgs, RS, is_dark_theme)

# Import UIs made with Qt-Designer
import ui.new_session
import ui.save_template_session
import ui.client_trash
import ui.abort_session
import ui.abort_copy
import ui.session_notes
import ui.nsm_open_info
import ui.quit_app
import ui.about_raysession
import ui.new_executable
import ui.stop_client
import ui.stop_client_no_save
import ui.client_rename
import ui.snapshot_progress
import ui.script_info
import ui.script_user_action
import ui.session_scripts_info
import ui.jack_config_info
import ui.daemon_url
import ui.waiting_close_user
import ui.donations
import ui.systray_close
import ui.startup_dialog
import ui.error_dialog

if TYPE_CHECKING:
    from main_window import MainWindow
    from gui_client import Client


_logger = logging.getLogger(__name__)


class ChildDialog(QDialog):
    def __init__(self, parent: 'MainWindow'):
        QDialog.__init__(self, parent)
        self.session = parent.session
        self.signaler = self.session.signaler
        self.daemon_manager = self.session.daemon_manager

        self.signaler.server_status_changed.connect(self._server_status_changed)
        self.signaler.server_copying.connect(self._server_copying)

        self._root_folder_file_dialog = None
        self._root_folder_message_box = QMessageBox(
            QMessageBox.Icon.Critical,
            _translate('root_folder_dialogs', 'unwritable dir'),
            '', QMessageBox.StandardButton.NoButton, self)

        self.server_copying = parent.server_copying

    @classmethod
    def to_daemon(cls, *args):
        server = GuiServerThread.instance()
        if server is not None:
            server.to_daemon(*args)
        else:
            _logger.error(f'No GUI OSC Server, can not send {args}.')

    def _server_status_changed(self, server_status: ray.ServerStatus):
        ...

    def _server_copying(self, copying: bool):
        self.server_copying = copying
        self._server_status_changed(self.session.server_status)

    def _change_root_folder(self):
        # construct this here only because it can be quite long
        if self._root_folder_file_dialog is None:
            self._root_folder_file_dialog = QFileDialog(
                self,
                _translate("root_folder_dialogs",
                        "Choose root folder for sessions"),
                CommandLineArgs.session_root)
            self._root_folder_file_dialog.setFileMode(QFileDialog.FileMode.Directory)
            self._root_folder_file_dialog.setOption(QFileDialog.Option.ShowDirsOnly)
        else:
            self._root_folder_file_dialog.setDirectory(CommandLineArgs.session_root)

        self._root_folder_file_dialog.exec()
        if not self._root_folder_file_dialog.result():
            return

        selected_files = self._root_folder_file_dialog.selectedFiles()
        if not selected_files:
            return

        root_folder = selected_files[0]

        # Security, kde dialogs sends $HOME if user type a folder path
        # that doesn't already exists.
        if os.getenv('HOME') and root_folder == os.getenv('HOME'):
            return

        self._root_folder_message_box.setText(
            _translate('root_folder_dialogs',
                "<p>You have no permissions for %s,<br>choose another directory !</p>")
                    % root_folder)

        if not os.path.exists(root_folder):
            try:
                os.makedirs(root_folder)
            except:
                self._root_folder_message_box.exec()
                return

        if not os.access(root_folder, os.W_OK):
            self._root_folder_message_box.exec()
            return

        RS.settings.setValue('default_session_root', root_folder)
        self.to_daemon(r.server.CHANGE_ROOT, root_folder)

    def parent(self) -> 'MainWindow':
        return super().parent() # type:ignore

    def leaveEvent(self, event):
        parent = self.parent()
        
        if parent is not None and self.isActiveWindow():
            parent.mouse_is_inside = False
        QDialog.leaveEvent(self, event)

    def enterEvent(self, event):
        parent = self.parent()
        if parent is not None:
            parent.mouse_is_inside = True
        QDialog.enterEvent(self, event)


class NewSessionDialog(ChildDialog):
    def __init__(self, parent, duplicate_window=False):
        ChildDialog.__init__(self, parent)
        self.ui = ui.new_session.Ui_DialogNewSession()
        self.ui.setupUi(self)

        self._is_duplicate = bool(duplicate_window)

        self.ui.currentSessionsFolder.setText(CommandLineArgs.session_root)
        self.ui.toolButtonFolder.clicked.connect(self._change_root_folder)
        self.ui.buttonBox.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False) # type:ignore
        self.ui.lineEdit.setFocus(Qt.FocusReason.OtherFocusReason) # type:ignore
        self.ui.lineEdit.textChanged.connect(self._text_changed)

        self.session_list = []
        self.template_list = []
        self.sub_folders = []

        self.signaler.server_status_changed.connect(self._server_status_changed)
        self.signaler.add_sessions_to_list.connect(self._add_sessions_to_list)
        self.signaler.session_template_found.connect(self._add_templates_to_list)
        self.signaler.root_changed.connect(self._root_changed)

        self.to_daemon(r.server.LIST_SESSIONS, 1)

        if self._is_duplicate:
            self.ui.labelTemplate.setVisible(False)
            self.ui.comboBoxTemplate.setVisible(False)
            self.ui.labelOriginalSessionName.setText(self.session.get_short_path())
            self.ui.labelNewSessionName.setText(
                _translate('Duplicate', 'Duplicated session name :'))
            self.setWindowTitle(_translate('Duplicate', 'Duplicate Session'))
        else:
            self.ui.frameOriginalSession.setVisible(False)
            self.to_daemon(r.server.LIST_SESSION_TEMPLATES)

        if not self.daemon_manager.is_local:
            self.ui.toolButtonFolder.setVisible(False)
            self.ui.currentSessionsFolder.setVisible(False)
            self.ui.labelSessionsFolder.setVisible(False)

        self._init_templates_combo_box()
        self._set_last_template_selected()

        self._server_will_accept = False
        self._text_is_valid = False

        self._completer = QCompleter(self.sub_folders)
        self.ui.lineEdit.setCompleter(self._completer) # type:ignore

        self._server_status_changed(self.session.server_status)
        
        self._text_was_empty = True

    def _server_status_changed(self, server_status: ray.ServerStatus):
        self.ui.toolButtonFolder.setEnabled(
            bool(server_status is ray.ServerStatus.OFF))

        self._server_will_accept = bool(
            server_status in (
                ray.ServerStatus.OFF,
                ray.ServerStatus.READY) and not self.server_copying)
        if self._is_duplicate:
            self._server_will_accept = bool(
                server_status is ray.ServerStatus.READY and not self.server_copying)

        if server_status is not ray.ServerStatus.OFF:
            if self._root_folder_file_dialog is not None:
                self._root_folder_file_dialog.reject()
            self._root_folder_message_box.reject()

        self._prevent_ok()

    def _root_changed(self, session_root):
        self.ui.currentSessionsFolder.setText(session_root)
        self.session_list.clear()
        self.sub_folders.clear()
        self.to_daemon(r.server.LIST_SESSIONS, 1)

    def _init_templates_combo_box(self):
        self.ui.comboBoxTemplate.clear()
        self.ui.comboBoxTemplate.addItem(
            _translate('session_template', "empty"))
        self.ui.comboBoxTemplate.addItem(
            _translate('session_template', "with JACK patch memory"))
        self.ui.comboBoxTemplate.addItem(
            _translate('session_template', "with JACK config memory"))
        self.ui.comboBoxTemplate.addItem(
            _translate('session_template', "with basic scripts"))

        misscount = self.ui.comboBoxTemplate.count() \
                    - 1 - len(ray.FACTORY_SESSION_TEMPLATES)

        for i in range(misscount):
            self.ui.comboBoxTemplate.addItem(
                ray.FACTORY_SESSION_TEMPLATES[-i])

        self.ui.comboBoxTemplate.insertSeparator(
                                    len(ray.FACTORY_SESSION_TEMPLATES) + 1)

    def _set_last_template_selected(self):
        last_used_template: str = RS.settings.value('last_used_template', type=str)

        if last_used_template.startswith('///'):
            last_factory_template = last_used_template.replace('///', '', 1)

            for i, factory_template in enumerate(
                    ray.FACTORY_SESSION_TEMPLATES):
                if factory_template == last_factory_template:
                    self.ui.comboBoxTemplate.setCurrentIndex(i+1)
                    break
        else:
            if last_used_template in self.template_list:
                self.ui.comboBoxTemplate.setCurrentText(last_used_template)

        if not last_used_template:
            self.ui.comboBoxTemplate.setCurrentIndex(1)

    def _set_last_sub_folder_selected(self):
        last_subfolder = ''

        for sess in self.session.recent_sessions:
            if sess.startswith('/'):
                continue

            if '/' in sess:
                last_subfolder, sep, sess_name = sess.rpartition('/')
            break

        if last_subfolder and not self.ui.lineEdit.text():
            self.ui.lineEdit.setText(last_subfolder + '/')

    def _add_sessions_to_list(self, session_names):
        self.session_list += session_names

        for session_name in session_names:
            if '/' in session_name:
                new_dir = os.path.dirname(session_name)
                if not new_dir in self.sub_folders:
                    self.sub_folders.append(new_dir)

        self.sub_folders.sort()
        del self._completer
        self._completer = QCompleter([f + '/' for f in self.sub_folders])
        self.ui.lineEdit.setCompleter(self._completer) # type:ignore

        if not session_names:
            # all sessions are listed, pre-fill last subfolder
            self._set_last_sub_folder_selected()

    def _add_templates_to_list(self, template_list):
        for template in template_list:
            if template not in self.template_list:
                self.template_list.append(template)

        if not self.template_list:
            return

        self.template_list.sort()

        self._init_templates_combo_box()

        for template_name in self.template_list:
            self.ui.comboBoxTemplate.addItem(template_name)

        self._set_last_template_selected()

    def _text_changed(self, text: str):
        self._text_is_valid = bool(text
                                   and not text.endswith('/')
                                   and text not in self.session_list)
        self._prevent_ok()

        if self._text_was_empty:
            if text:
                self._completer.setCompletionMode(
                    QCompleter.CompletionMode.PopupCompletion)
                self._completer.complete()
                self._text_was_empty = False
        
        elif not text:
            QTimer.singleShot(50, self._set_completer_for_empty_text)
            self._text_was_empty = True

    def _set_completer_for_empty_text(self):
        del self._completer
        self._completer = QCompleter([f + '/' for f in self.sub_folders])
        self._completer.setCompletionMode(
            QCompleter.CompletionMode.UnfilteredPopupCompletion)
        self.ui.lineEdit.setCompleter(self._completer) # type:ignore
        QTimer.singleShot(50, self._completer.complete)

    def _show_completer_at_start(self):
        self._completer.complete()

    def showEvent(self, event):
        ChildDialog.showEvent(self, event)
        QTimer.singleShot(800, self._show_completer_at_start)

    def _prevent_ok(self):
        self.ui.buttonBox.button(QDialogButtonBox.StandardButton.Ok).setEnabled( # type:ignore
            bool(self._server_will_accept and self._text_is_valid))

    def get_session_short_path(self)->str:
        return self.ui.lineEdit.text()

    def get_template_name(self)->str:
        index = self.ui.comboBoxTemplate.currentIndex()

        if index == 0:
            return ""

        if index <= len(ray.FACTORY_SESSION_TEMPLATES):
            return '///' + ray.FACTORY_SESSION_TEMPLATES[index-1]

        return self.ui.comboBoxTemplate.currentText()


class AbstractSaveTemplateDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui.save_template_session.Ui_DialogSaveTemplateSession()
        self.ui.setupUi(self)

        self._server_will_accept = False
        self._update_template_text = _translate(
            "session template", "Update the template")
        self._create_template_text = self.ui.pushButtonAccept.text()
        self._overwrite_message_box = QMessageBox(
            QMessageBox.Icon.Question,
            _translate(
                    'session template',
                    'Overwrite Template ?'),
            '',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            self)

        self.template_list = []

        self.ui.lineEdit.textEdited.connect(self._text_edited)
        self.ui.pushButtonAccept.clicked.connect(self._verify_and_accept)
        self.ui.pushButtonAccept.setEnabled(False)

    def _text_edited(self, text: str):
        if '/' in text:
            self.ui.lineEdit.setText(text.replace('/', '⁄'))
        if self.ui.lineEdit.text() in self.template_list:
            self.ui.pushButtonAccept.setText(self._update_template_text)
        else:
            self.ui.pushButtonAccept.setText(self._create_template_text)
        self._allow_ok_button()

    def _allow_ok_button(self, text=''):
        self.ui.pushButtonAccept.setEnabled(
            bool(self._server_will_accept and self.ui.lineEdit.text()))

    def _verify_and_accept(self):
        template_name = self.get_template_name()
        if template_name in self.template_list:
            self._overwrite_message_box.setText(
                _translate(
                    'session_template',
                    'Template <strong>%s</strong> already exists.\nOverwrite it ?') %
                template_name)

            self._overwrite_message_box.exec()

            if (self._overwrite_message_box.clickedButton()
                    == self._overwrite_message_box.button(QMessageBox.StandardButton.No)):
                return
        self.accept()

    def _add_templates_to_list(self, template_list):
        self.template_list += template_list

        for template in template_list:
            if template == self.ui.lineEdit.text():
                self.ui.pushButtonAccept.setText(self._update_template_text)
                break

    def get_template_name(self)->str:
        return self.ui.lineEdit.text()


class SaveTemplateSessionDialog(AbstractSaveTemplateDialog):
    def __init__(self, parent):
        AbstractSaveTemplateDialog.__init__(self, parent)
        self.ui.toolButtonClientIcon.setVisible(False)
        self.ui.labelLabel.setText(self.session.get_short_path())

        self.signaler.session_template_found.connect(self._add_templates_to_list)
        self.to_daemon(r.server.LIST_SESSION_TEMPLATES)

        self._server_status_changed(self.session.server_status)

    def _server_status_changed(self, server_status: ray.ServerStatus):
        self._server_will_accept = bool(server_status is ray.ServerStatus.READY)

        if server_status is ray.ServerStatus.OFF:
            self._overwrite_message_box.reject()
            self.reject()

        self._allow_ok_button()


class SaveTemplateClientDialog(AbstractSaveTemplateDialog):
    def __init__(self, parent, client: 'Client'):
        AbstractSaveTemplateDialog.__init__(self, parent)
        self.ui.labelSessionTitle.setVisible(False)
        self.ui.toolButtonClientIcon.setIcon(
            get_app_icon(client.icon, self))
        self.ui.labelLabel.setText(client.prettier_name())

        self.ui.pushButtonAccept.setEnabled(False)

        self.ui.labelNewTemplateName.setText(
            _translate(
                'new client template',
                "New application template name :"))

        self.signaler.user_client_template_found.connect(
            self._add_templates_to_list)

        self.to_daemon(r.server.LIST_USER_CLIENT_TEMPLATES)
        self.ui.lineEdit.setText(client.template_origin)
        self.ui.lineEdit.selectAll()
        self.ui.lineEdit.setFocus()
        self._server_status_changed(self.session.server_status)

    def _server_status_changed(self, server_status: ray.ServerStatus):
        self._server_will_accept = bool(
            server_status not in (
                ray.ServerStatus.OFF,
                ray.ServerStatus.CLOSE) and not self.server_copying)

        if server_status in (ray.ServerStatus.OFF, ray.ServerStatus.CLOSE):
            self._overwrite_message_box.reject()
            self.reject()

        self._allow_ok_button()


class ClientTrashDialog(ChildDialog):
    def __init__(self, parent, client_data: ray.ClientData):
        ChildDialog.__init__(self, parent)
        self.ui = ui.client_trash.Ui_Dialog()
        self.ui.setupUi(self)

        self.client_data = client_data

        self.ui.labelPrettierName.setText(self.client_data.prettier_name())
        self.ui.labelDescription.setText(self.client_data.description)
        self.ui.labelExecutable.setText(self.client_data.executable_path)
        self.ui.labelId.setText(self.client_data.client_id)
        self.ui.toolButtonIcon.setIcon(QIcon.fromTheme(self.client_data.icon))

        self.ui.toolButtonAdvanced.clicked.connect(self._show_properties)
        self.ui.pushButtonRemove.clicked.connect(self._remove_client)
        self.ui.pushButtonCancel.setFocus()

        self._remove_client_message_box = QMessageBox(
            QMessageBox.Icon.Warning,
            _translate('trashed_client', 'Remove definitely'),
            _translate('trashed_client',
                "Are you sure to want to remove definitely this client and all its files ?"),
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            self
            )
        self._remove_client_message_box.setDefaultButton(
            QMessageBox.StandardButton.Cancel)

    def _server_status_changed(self, server_status: ray.ServerStatus):
        if server_status in (ray.ServerStatus.CLOSE,
                             ray.ServerStatus.OFF,
                             ray.ServerStatus.OUT_SAVE,
                             ray.ServerStatus.OUT_SNAPSHOT,
                             ray.ServerStatus.WAIT_USER):
            self._remove_client_message_box.reject()
            self.reject()

    def _remove_client(self):
        self._remove_client_message_box.exec()

        if (self._remove_client_message_box.clickedButton()
                != self._remove_client_message_box.button(
                    QMessageBox.StandardButton.Ok)):
            return

        self.to_daemon(
            r.trashed_client.REMOVE_DEFINITELY,
            self.client_data.client_id)
        self.reject()

    def _show_properties(self):
        properties_dialog = client_properties_dialog.ClientPropertiesDialog.create(
            self, self.client_data)
        properties_dialog.update_contents()
        properties_dialog.lock_widgets()
        properties_dialog.show()


class AbortSessionDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui.abort_session.Ui_AbortSession()
        self.ui.setupUi(self)

        self.ui.pushButtonAbort.clicked.connect(self.accept)
        self.ui.pushButtonCancel.clicked.connect(self.reject)
        self.ui.pushButtonCancel.setFocus(Qt.FocusReason.OtherFocusReason) # type:ignore

        self._server_status_changed(self.session.server_status)

    def _server_status_changed(self, server_status: ray.ServerStatus):
        self.ui.pushButtonAbort.setEnabled(
            not bool(
                server_status in (
                    ray.ServerStatus.CLOSE,
                    ray.ServerStatus.OFF,
                    ray.ServerStatus.COPY)))
        if server_status == ray.ServerStatus.OFF:
            self.reject()


class AbortServerCopyDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui.abort_copy.Ui_Dialog()
        self.ui.setupUi(self)

        self.signaler.server_progress.connect(self._set_progress)

        self._server_status_changed(self.session.server_status)

    def _server_status_changed(self, server_status: ray.ServerStatus):
        if server_status not in (
                ray.ServerStatus.PRECOPY,
                ray.ServerStatus.COPY):
            self.reject()

    def _set_progress(self, progress: float):
        self.ui.progressBar.setValue(int(progress * 100))


class AbortClientCopyDialog(ChildDialog):
    def __init__(self, parent, client_id: str):
        ChildDialog.__init__(self, parent)
        self.ui = ui.abort_copy.Ui_Dialog()
        self.ui.setupUi(self)

        self._client_id = client_id

        self.signaler.client_progress.connect(self._set_progress)

    def _set_progress(self, client_id: str, progress: float):
        if client_id != self._client_id:
            return

        self.ui.progressBar.setValue(int(progress * 100))

    def _server_status_changed(self, server_status: ray.ServerStatus):
        if not self.server_copying:
            self.reject()


class SessionNotesDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui.session_notes.Ui_Dialog()
        self.ui.setupUi(self)

        if RS.settings.value('SessionNotes/geometry'):
            self.restoreGeometry(RS.settings.value('SessionNotes/geometry'))
        if RS.settings.value('SessionNotes/position'):
            self.move(RS.settings.value('SessionNotes/position'))

        self._message_box = None
        self.update_session()
        self.ui.plainTextEdit.textChanged.connect(self._text_edited)

        # use a timer to prevent osc message each time a letter is written
        # here, a message is sent when user made not change during 400ms
        self._timer_text = QTimer()
        self._timer_text.setInterval(400)
        self._timer_text.setSingleShot(True)
        self._timer_text.timeout.connect(self._send_notes)

        self.server_off = False

        self._anti_timer = False
        self.notes_updated()

    def _server_status_changed(self, server_status: ray.ServerStatus):
        if server_status is ray.ServerStatus.OFF:
            self.server_off = True
            if self._message_box is not None:
                self._message_box.close()
            self.close()
        else:
            self.server_off = False

    def _text_edited(self):
        if not self._anti_timer:
            self._timer_text.start()
        self._anti_timer = False

    def _send_notes(self):
        notes = self.ui.plainTextEdit.toPlainText()
        if len(notes) >= 65000:
            self._message_box = QMessageBox(
                QMessageBox.Icon.Critical,
                _translate('session_notes', 'Too long notes'),
                _translate('session_notes',
                           "<p>Because notes are spread to the OSC server,<br>"
                           "they can't be longer than 65000 characters.<br>Sorry !</p>"),
                QMessageBox.StandardButton.Cancel,
                self)
            self._message_box.exec()
            self.ui.plainTextEdit.setPlainText(notes[:64999])
            return

        self.session.notes = notes
        self.to_daemon(r.session.SET_NOTES, self.session.notes)

    def update_session(self):
        self.setWindowTitle(_translate('notes_dialog', "%s Notes - %s")
                            % (ray.APP_TITLE, self.session.name))
        self.ui.labelSessionName.setText(self.session.name)

    def notes_updated(self):
        self._anti_timer = True
        self.ui.plainTextEdit.setPlainText(self.session.notes)

    def closeEvent(self, event):
        RS.settings.setValue('SessionNotes/geometry', self.saveGeometry())
        RS.settings.setValue('SessionNotes/position', self.pos())
        if not self.server_off:
            self.to_daemon(r.session.HIDE_NOTES)
        ChildDialog.closeEvent(self, event)


class OpenNsmSessionInfoDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui.nsm_open_info.Ui_Dialog()
        self.ui.setupUi(self)
        self.ui.checkBox.stateChanged.connect(self._show_this)

    def _show_this(self, state: bool):
        RS.set_hidden(RS.HD_OpenNsmSession, bool(state))


class QuitAppDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui.quit_app.Ui_DialogQuitApp()
        self.ui.setupUi(self)
        self.ui.pushButtonCancel.setFocus(Qt.FocusReason.OtherFocusReason) # type:ignore
        self.ui.pushButtonSaveQuit.clicked.connect(self._close_session)
        self.ui.pushButtonQuitNoSave.clicked.connect(self._abort_session)
        self.ui.pushButtonDaemon.clicked.connect(self._leave_daemon_running)

        original_text = self.ui.labelMainText.text()
        self.ui.labelMainText.setText(
            original_text %
            ('<strong>%s</strong>' %
             self.session.name))

        if CommandLineArgs.under_nsm:
            self.ui.pushButtonDaemon.setVisible(False)
        self._server_status_changed(self.session.server_status)

    def _server_status_changed(self, server_status: ray.ServerStatus):
        if server_status == ray.ServerStatus.OFF:
            self.accept()
            return

        self.ui.pushButtonSaveQuit.setEnabled(
            bool(server_status is ray.ServerStatus.READY))
        self.ui.pushButtonQuitNoSave.setEnabled(
            bool(server_status is not ray.ServerStatus.CLOSE))

    def _close_session(self):
        self.to_daemon(r.session.CLOSE)

    def _abort_session(self):
        self.to_daemon(r.session.ABORT)

    def _leave_daemon_running(self):
        if CommandLineArgs.under_nsm:
            return

        self.daemon_manager.disannounce()
        QTimer.singleShot(10, QGuiApplication.quit)


class WrongVersionLocalDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui.quit_app.Ui_DialogQuitApp()
        self.ui.setupUi(self)
        self.ui.pushButtonCancel.setVisible(False)
        self.ui.pushButtonSaveQuit.clicked.connect(self._close_session)
        self.ui.pushButtonQuitNoSave.clicked.connect(self._abort_session)
        self.ui.pushButtonDaemon.clicked.connect(self._leave_daemon_running)

        self.ui.labelMainText.setText(
            _translate(
                'wrong_version',
                "The running daemon has not the same version than the interface\n"
                "RaySession will quit now.\n\n"
                "What do you want to do with the current session ?"))

    def _close_session(self):
        # can make the GUI freeze a little
        # but the GUI will quit just after
        # and this case is rare enough to be acceptable
        subprocess.run(['ray_control', 'close'])
        self.accept()

    def _abort_session(self):
        # see _close_session
        subprocess.run(['ray_control', 'abort'])
        self.accept()

    def _leave_daemon_running(self):
        QTimer.singleShot(10, QGuiApplication.quit)


class AboutRaySessionDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui.about_raysession.Ui_DialogAboutRaysession()
        self.ui.setupUi(self)
        all_text = self.ui.labelRayAndVersion.text()
        self.ui.labelRayAndVersion.setText(all_text % ray.VERSION)


class NewExecutableDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui.new_executable.Ui_DialogNewExecutable()
        self.ui.setupUi(self)

        self.ui.groupBoxAdvanced.setVisible(False)
        self.resize(0, 0)
        self.ui.labelPrefixMode.setToolTip(
            self.ui.comboBoxPrefixMode.toolTip())
        self.ui.labelClientId.setToolTip(self.ui.lineEditClientId.toolTip())

        self.ui.buttonBox.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False) # type:ignore

        self.ui.lineEdit.setFocus(Qt.FocusReason.OtherFocusReason) # type:ignore
        self.ui.lineEdit.textChanged.connect(self._check_allow)
        self.ui.checkBoxNsm.stateChanged.connect(self._check_allow)

        self.ui.lineEditPrefix.setEnabled(False)
        self.ui.toolButtonAdvanced.clicked.connect(self._show_advanced)

        self.ui.comboBoxPrefixMode.addItem(
            _translate('new_executable', 'Custom'))
        self.ui.comboBoxPrefixMode.addItem(
            _translate('new_executable', 'Client Name'))
        self.ui.comboBoxPrefixMode.addItem(
            _translate('new_executable', 'Session Name'))
        self.ui.comboBoxPrefixMode.setCurrentIndex(1)

        self.ui.comboBoxPrefixMode.currentIndexChanged.connect(
            self._prefix_mode_changed)

        self.signaler.new_executable.connect(self._add_executable_to_completer)
        self.to_daemon(r.server.LIST_PATH)

        self.exec_list = []

        self._completer = QCompleter(self.exec_list)
        self.ui.lineEdit.setCompleter(self._completer) # type:ignore

        self.ui.lineEdit.returnPressed.connect(self._close_now)

        self._server_status_changed(self.session.server_status)

    def _server_status_changed(self, server_status: ray.ServerStatus):
        if server_status in (ray.ServerStatus.OUT_SAVE,
                             ray.ServerStatus.OUT_SNAPSHOT,
                             ray.ServerStatus.WAIT_USER,
                             ray.ServerStatus.CLOSE,
                             ray.ServerStatus.OFF):
            self.reject()

    def _show_advanced(self):
        self.ui.groupBoxAdvanced.setVisible(True)
        self.ui.toolButtonAdvanced.setVisible(False)

    def _prefix_mode_changed(self, index: int):
        self.ui.lineEditPrefix.setEnabled(bool(index == 0))

    def _add_executable_to_completer(self, executable_list: list):
        self.exec_list += executable_list
        self.exec_list.sort()

        del self._completer
        self._completer = QCompleter(self.exec_list)
        self.ui.lineEdit.setCompleter(self._completer) # type:ignore

    def _is_allowed(self) -> bool:
        nsm = self.ui.checkBoxNsm.isChecked()
        text = self.ui.lineEdit.text()
        return bool(bool(text) and (not nsm or text in self.exec_list))

    def _check_allow(self):
        allow = self._is_allowed()
        self.ui.buttonBox.button(QDialogButtonBox.StandardButton.Ok).setEnabled(allow) # type:ignore

    def _close_now(self):
        if self._is_allowed():
            self.accept()

    def get_selection(self) -> tuple[str, bool, bool, int, str, str, bool]:
        return (self.ui.lineEdit.text(),
                self.ui.checkBoxStartClient.isChecked(),
                not self.ui.checkBoxNsm.isChecked(),
                self.ui.comboBoxPrefixMode.currentIndex(),
                self.ui.lineEditPrefix.text(),
                self.ui.lineEditClientId.text(),
                self.ui.checkBoxJackNaming.isChecked())


class StopClientDialog(ChildDialog):
    def __init__(self, parent, client_id):
        ChildDialog.__init__(self, parent)
        self.ui = ui.stop_client.Ui_Dialog()
        self.ui.setupUi(self)

        self._client_id = client_id
        self._wait_for_save = False

        self.client = self.session.get_client(client_id)

        if self.client:
            text = self.ui.label.text() % self.client.prettier_name()

            if not self.client.has_dirty:
                minutes = int((time.time() - self.client.last_save) / 60)
                text = _translate(
                    'client_stop',
                    "<strong>%s</strong> seems to has not been saved for %i minute(s).<br />"
                    "Do you really want to stop it ?") \
                        % (self.client.prettier_name(), minutes)
            self.ui.label.setText(text)

            self.client.status_changed.connect(self._server_updates_client_status)

        self.ui.pushButtonSaveStop.clicked.connect(self._save_and_stop)
        self.ui.checkBox.stateChanged.connect(self._check_box_clicked)

    def _save_and_stop(self):
        self._wait_for_save = True
        self.to_daemon(r.client.SAVE, self._client_id)

    def _check_box_clicked(self, state):
        if self.client is None:
            return
        self.client.check_last_save = not bool(state)
        self.client.send_properties_to_daemon()

    def _server_updates_client_status(self, status: int):
        if status in (ray.ClientStatus.STOPPED, ray.ClientStatus.REMOVED):
            self.reject()
            return

        if status is ray.ClientStatus.READY and self._wait_for_save:
            self._wait_for_save = False
            self.accept()


class StopClientNoSaveDialog(ChildDialog):
    def __init__(self, parent, client_id):
        ChildDialog.__init__(self, parent)
        self.ui = ui.stop_client_no_save.Ui_Dialog()
        self.ui.setupUi(self)

        self.client = self.session.get_client(client_id)

        if self.client:
            text = self.ui.label.text() % self.client.prettier_name()
            self.ui.label.setText(text)
            self.client.status_changed.connect(self._server_updates_client_status)

        self.ui.checkBox.stateChanged.connect(self._check_box_clicked)
        self.ui.pushButtonCancel.setFocus()

    def _server_updates_client_status(self, status: int):
        if status in (ray.ClientStatus.STOPPED, ray.ClientStatus.REMOVED):
            self.reject()
            return

    def _check_box_clicked(self, state):
        if self.client is None:
            return
        self.client.check_last_save = not bool(state)
        self.client.send_properties_to_daemon()


class ClientRenameDialog(ChildDialog):
    def __init__(self, parent, client: 'Client'):
        ChildDialog.__init__(self, parent)
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
        
        for cl in session.client_list:
            if cl.client_id == out_id:
                self.ui.buttonBox.button(
                    QDialogButtonBox.StandardButton.Ok).setEnabled(False) # type:ignore
                return
        
        for cl in session.trashed_clients:
            if cl.client_id == out_id:
                self.ui.buttonBox.button(
                    QDialogButtonBox.StandardButton.Ok).setEnabled(False) # type:ignore
                return
        
        self.ui.buttonBox.button(
            QDialogButtonBox.StandardButton.Ok).setEnabled(True) # type:ignore
    
    def is_identifiant_renamed(self) -> bool:
        return self.ui.checkBoxIdRename.isChecked()

    def get_new_label(self) -> str:
        return self.ui.lineEdit.text()
    

class SnapShotProgressDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui.snapshot_progress.Ui_Dialog()
        self.ui.setupUi(self)
        self.signaler.server_progress.connect(self.server_progress)

    def _server_status_changed(self, server_status: ray.ServerStatus):
        self.close()

    def server_progress(self, value: float):
        self.ui.progressBar.setValue(int(value * 100))


class ScriptInfoDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui.script_info.Ui_Dialog()
        self.ui.setupUi(self)

    def set_info_label(self, text: str):
        self.ui.infoLabel.setText(text)

    def should_be_removed(self):
        return False


class ScriptUserActionDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui.script_user_action.Ui_Dialog()
        self.ui.setupUi(self)

        self.ui.buttonBox.clicked.connect(self._button_box_clicked)
        self.ui.infoLabel.setVisible(False)
        self.ui.infoLine.setVisible(False)

        self._is_terminated = False

    def _validate(self):
        self.to_daemon(osc_paths.REPLY, rg.SCRIPT_USER_ACTION,
                      'Dialog window validated')
        self._is_terminated = True
        self.accept()

    def _abort(self):
        self.to_daemon(osc_paths.ERROR, rg.SCRIPT_USER_ACTION,
                      ray.Err.ABORT_ORDERED, 'Script user action aborted!')
        self._is_terminated = True
        self.accept()

    def _button_box_clicked(self, button):
        if button == self.ui.buttonBox.button(
                QDialogButtonBox.StandardButton.Yes): # type:ignore
            self._validate()
        elif button == self.ui.buttonBox.button(
                QDialogButtonBox.StandardButton.Ignore): # type:ignore
            self._abort()

    def set_main_text(self, text: str):
        self.ui.label.setText(text)

    def should_be_removed(self):
        return self._is_terminated


class SessionScriptsInfoDialog(ChildDialog):
    def __init__(self, parent, session_path):
        ChildDialog.__init__(self, parent)
        self.ui = ui.session_scripts_info.Ui_Dialog()
        self.ui.setupUi(self)

        scripts_dir = "%s/%s" % (session_path, ray.SCRIPTS_DIR)
        parent_path = os.path.dirname(session_path)
        parent_scripts = "%s/%s" % (parent_path, ray.SCRIPTS_DIR)

        session_scripts_text = self.ui.textSessionScripts.toHtml()

        self.ui.textSessionScripts.setHtml(
            session_scripts_text % (scripts_dir, parent_scripts, parent_path))

    def not_again_value(self)->bool:
        return self.ui.checkBoxNotAgain.isChecked()


class JackConfigInfoDialog(ChildDialog):
    def __init__(self, parent, session_path):
        ChildDialog.__init__(self, parent)
        self.ui = ui.jack_config_info.Ui_Dialog()
        self.ui.setupUi(self)

        scripts_dir = "%s/%s" % (session_path, ray.SCRIPTS_DIR)
        parent_path = os.path.dirname(session_path)
        parent_scripts = "%s/%s" % (parent_path, ray.SCRIPTS_DIR)

        session_scripts_text = self.ui.textSessionScripts.toHtml()

        self.ui.textSessionScripts.setHtml(
            session_scripts_text % (scripts_dir, parent_scripts, parent_path))

    def not_again_value(self)->bool:
        return self.ui.checkBoxNotAgain.isChecked()

    def auto_start_value(self)->bool:
        return self.ui.checkBoxAutoStart.isChecked()


class DaemonUrlWindow(ChildDialog):
    def __init__(self, parent, err_code, ex_url):
        ChildDialog.__init__(self, parent)
        self.ui = ui.daemon_url.Ui_Dialog()
        self.ui.setupUi(self)

        self.ui.lineEdit.textChanged.connect(self._allow_url)

        error_text = ''
        if err_code == ErrDaemon.NO_ANNOUNCE:
            error_text = _translate(
                "url_window",
                "<p>daemon at<br><strong>%s</strong><br>didn't announce !<br></p>") % ex_url
        elif err_code == ErrDaemon.NOT_OFF:
            error_text = _translate(
                "url_window",
                "<p>daemon at<br><strong>%s</strong><br>has a loaded session.<br>It can't be used for slave session</p>") % ex_url
        elif err_code == ErrDaemon.WRONG_ROOT:
            error_text = _translate(
                "url_window",
                "<p>daemon at<br><strong>%s</strong><br>uses an other session root folder !<.p>") % ex_url
        elif err_code == ErrDaemon.FORBIDDEN_ROOT:
            error_text = _translate(
                "url_window",
                "<p>daemon at<br><strong>%s</strong><br>uses a forbidden session root folder !<.p>") % ex_url
        elif err_code == ErrDaemon.WRONG_VERSION:
            error_text = _translate(
                "url_window",
                "<p>daemon at<br><strong>%s</strong><br>uses another %s version.<.p>") % (ex_url, ray.APP_TITLE)
        else:
            error_text = _translate("url window", "<p align=\"left\">To run a network session,<br>open a terminal on another computer of this network.<br>Launch ray-daemon on port 1234 (for example)<br>by typing the command :</p><p align=\"left\"><code>ray-daemon -p 1234</code></p><p align=\"left\">Then paste below the first url<br>that ray-daemon gives you at startup.</p><p></p>")

        self.ui.labelError.setText(error_text)
        self.ui.buttonBox.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False) # type:ignore

        self.tried_urls = ray.get_list_in_settings(RS.settings, 'network/tried_urls')
        last_tried_url = RS.settings.value('network/last_tried_url', '', type=str)

        self._completer = QCompleter(self.tried_urls)
        self.ui.lineEdit.setCompleter(self._completer) # type:ignore

        if ex_url:
            self.ui.lineEdit.setText(ex_url)
        elif last_tried_url:
            self.ui.lineEdit.setText(last_tried_url)

    def _allow_url(self, text: str):
        if not text:
            self.ui.lineEdit.completer().complete()
            self.ui.buttonBox.button(
                QDialogButtonBox.StandardButton.Ok).setEnabled(False) # type:ignore
            return

        if not text.startswith('osc.udp://'):
            self.ui.buttonBox.button(
                QDialogButtonBox.StandardButton.Ok).setEnabled(False) # type:ignore
            return

        addr = verified_address(text)
        self.ui.buttonBox.button(
                QDialogButtonBox.StandardButton.Ok).setEnabled( # type:ignore
                    isinstance(addr, Address))

    def get_url(self):
        return self.ui.lineEdit.text()


class WaitingCloseUserDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui.waiting_close_user.Ui_Dialog()
        self.ui.setupUi(self)

        if is_dark_theme(self):
            self.ui.labelSaveIcon.setPixmap(
                QPixmap(':scalable/breeze-dark/document-nosave.svg')) # type:ignore

        self.ui.pushButtonOk.setFocus()
        self.ui.pushButtonUndo.clicked.connect(self._undo_close)
        self.ui.pushButtonSkip.clicked.connect(self._skip)
        self.ui.checkBox.setChecked(not RS.is_hidden(RS.HD_WaitCloseUser))
        self.ui.checkBox.clicked.connect(self._check_box_clicked)

    def _server_status_changed(self, server_status: ray.ServerStatus):
        if server_status is not ray.ServerStatus.WAIT_USER:
            self.accept()

    def _undo_close(self):
        self.to_daemon(r.session.CANCEL_CLOSE)

    def _skip(self):
        self.to_daemon(r.session.SKIP_WAIT_USER)

    def _check_box_clicked(self, state):
        RS.set_hidden(RS.HD_WaitCloseUser, bool(state))


class DonationsDialog(ChildDialog):
    def __init__(self, parent, display_no_again):
        ChildDialog.__init__(self, parent)
        self.ui = ui.donations.Ui_Dialog()
        self.ui.setupUi(self)

        self.ui.checkBox.setVisible(display_no_again)
        self.ui.checkBox.clicked.connect(self._check_box_clicked)

    def _check_box_clicked(self, state):
        RS.set_hidden(RS.HD_Donations, state)


class SystrayCloseDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui.systray_close.Ui_Dialog()
        self.ui.setupUi(self)

    def not_again(self)->bool:
        return self.ui.checkBox.isChecked()


class StartupDialog(ChildDialog):
    ACTION_NO = 0
    ACTION_NEW = 1
    ACTION_OPEN = 2

    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui.startup_dialog.Ui_Dialog()
        self.ui.setupUi(self)

        self._clicked_action = self.ACTION_NO

        self.ui.listWidgetRecentSessions.itemDoubleClicked.connect(
            self.accept)

        for recent_session in self.session.recent_sessions:
            session_item = QListWidgetItem(recent_session.replace('/', ' / '),
                                           self.ui.listWidgetRecentSessions)
            session_item.setData(Qt.ItemDataRole.UserRole, recent_session)
            self.ui.listWidgetRecentSessions.addItem(session_item) # type:ignore

        self.ui.listWidgetRecentSessions.setMinimumHeight(
            30 * len(self.session.recent_sessions))
        self.ui.listWidgetRecentSessions.setCurrentRow(0)
        self.ui.pushButtonNewSession.clicked.connect(
            self._new_session_clicked)
        self.ui.pushButtonOpenSession.clicked.connect(
            self._open_session_clicked)
        #self.ui.buttonBox.key_event.connect(self._up_down_pressed)
        self.ui.pushButtonNewSession.focus_on_list.connect(
            self._focus_on_list)
        self.ui.pushButtonOpenSession.focus_on_list.connect(
            self._focus_on_list)
        self.ui.pushButtonNewSession.focus_on_open.connect(
            self._focus_on_open)
        self.ui.pushButtonOpenSession.focus_on_new.connect(
            self._focus_on_new)

        self.ui.listWidgetRecentSessions.setFocus(
            Qt.FocusReason.OtherFocusReason) # type:ignore

    def _server_status_changed(self, server_status: ray.ServerStatus):
        if server_status is not ray.ServerStatus.OFF:
            self.reject()

    def _new_session_clicked(self):
        self._clicked_action = self.ACTION_NEW
        self.reject()

    def _open_session_clicked(self):
        self._clicked_action = self.ACTION_OPEN
        self.reject()

    def _focus_on_list(self):
        self.ui.listWidgetRecentSessions.setFocus(
            Qt.FocusReason.OtherFocusReason) # type:ignore

    def _focus_on_new(self):
        self.ui.pushButtonNewSession.setFocus(Qt.FocusReason.OtherFocusReason)

    def _focus_on_open(self):
        self.ui.pushButtonOpenSession.setFocus(Qt.FocusReason.OtherFocusReason)

    def not_again_value(self)->bool:
        return not self.ui.checkBox.isChecked()

    def get_selected_session(self)->str:
        current_item = self.ui.listWidgetRecentSessions.currentItem()
        if current_item:
            return current_item.data(Qt.ItemDataRole.UserRole)
        return ''

    def get_clicked_action(self)->int:
        return self._clicked_action

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Left:
            self.ui.pushButtonNewSession.setFocus(Qt.FocusReason.OtherFocusReason)
        elif event.key() == Qt.Key.Key_Right:
            self.ui.pushButtonOpenSession.setFocus(Qt.FocusReason.OtherFocusReason)
        elif event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self.ui.listWidgetRecentSessions.setFocus(
                Qt.FocusReason.OtherFocusReason) # type:ignore

        if QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier:
            if event.key() == Qt.Key.Key_N:
                self._new_session_clicked()
            elif event.key() == Qt.Key.Key_O:
                self._open_session_clicked()

        ChildDialog.keyPressEvent(self, event)


class ErrorDialog(ChildDialog):
    def __init__(self, parent, message):
        ChildDialog.__init__(self, parent)
        self.ui = ui.error_dialog.Ui_Dialog()
        self.ui.setupUi(self)

        self.ui.label.setText(message)
