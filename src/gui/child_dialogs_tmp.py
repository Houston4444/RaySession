
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
from qtpy.QtGui import (
    QIcon, QPixmap, QGuiApplication, QKeyEvent, QDesktopServices)
from qtpy.QtCore import Qt, QTimer, QUrl

# Imports from src/shared
from osclib import Address, verified_address
import ray
import osc_paths
import osc_paths.ray as r
import osc_paths.ray.gui as rg

# Local imports
import client_properties_dialog
from dialogs import ChildDialog
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
        
        for cl in session.clients:
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

    def not_again_value(self) -> bool:
        return self.ui.checkBoxNotAgain.isChecked()

    def auto_start_value(self) -> bool:
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

        dark = '-dark' if is_dark_theme(self) else ''
        self.ui.toolButtonImage.setIcon(
            QIcon(f':scalable/breeze{dark}/handshake-deal.svg'))

        self.ui.toolButtonDonate.clicked.connect(self._donate)

        self.ui.checkBox.setVisible(display_no_again)
        self.ui.checkBox.clicked.connect(self._check_box_clicked)

    def _check_box_clicked(self, state):
        RS.set_hidden(RS.HD_Donations, state)
        
    def _donate(self):
        QDesktopServices.openUrl(
            QUrl('https://liberapay.com/Houston4444'))


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
