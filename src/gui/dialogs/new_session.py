
# Imports from standard library
import os

# third party imports
from qtpy.QtWidgets import QDialogButtonBox, QCompleter
from qtpy.QtCore import Qt, QTimer

# Imports from src/shared
import ray
import osc_paths.ray as r

# Local imports
from gui_tools import _translate, CommandLineArgs, RS
from .child_dialog import ChildDialog

# Import UIs made with Qt-Designer
import ui.new_session


class NewSessionDialog(ChildDialog):
    def __init__(self, parent, duplicate_window=False):
        ChildDialog.__init__(self, parent)
        self.ui = ui.new_session.Ui_DialogNewSession()
        self.ui.setupUi(self)

        self._is_duplicate = bool(duplicate_window)

        self.ui.currentSessionsFolder.setText(CommandLineArgs.session_root)
        self.ui.toolButtonFolder.clicked.connect(self._change_root_folder)
        self._ok_button.setEnabled(False)
        self.ui.lineEdit.setFocus(
            Qt.FocusReason.OtherFocusReason) # type:ignore
        self.ui.lineEdit.textChanged.connect(self._text_changed)

        self.session_list = list[str]()
        self.template_list = list[str]()
        self.sub_folders = list[str]()

        self.signaler.server_status_changed.connect(
            self._server_status_changed)
        self.signaler.add_sessions_to_list.connect(
            self._add_sessions_to_list)
        self.signaler.session_template_found.connect(
            self._add_templates_to_list)
        self.signaler.root_changed.connect(self._root_changed)

        self.to_daemon(r.server.LIST_SESSIONS, 1)

        if self._is_duplicate:
            self.ui.labelTemplate.setVisible(False)
            self.ui.comboBoxTemplate.setVisible(False)
            self.ui.labelOriginalSessionName.setText(
                self.session.get_short_path())
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

    @property
    def _ok_button(self):
        return self.ui.buttonBox.button(
            QDialogButtonBox.StandardButton.Ok) # type:ignore

    def _server_status_changed(self, server_status: ray.ServerStatus):
        self.ui.toolButtonFolder.setEnabled(
            bool(server_status is ray.ServerStatus.OFF))

        self._server_will_accept = bool(
            server_status in (
                ray.ServerStatus.OFF,
                ray.ServerStatus.READY)
            and not self.server_copying)

        if self._is_duplicate:
            self._server_will_accept = bool(
                server_status is ray.ServerStatus.READY
                and not self.server_copying)

        if server_status is not ray.ServerStatus.OFF:
            if self._root_folder_file_dialog is not None:
                self._root_folder_file_dialog.reject()
            self._root_folder_message_box.reject()

        self._prevent_ok()

    def _root_changed(self, session_root: str):
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
        last_used_template: str = RS.settings.value(
            'last_used_template', type=str)

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
                last_subfolder = sess.rpartition('/')[0]
            break

        if last_subfolder and not self.ui.lineEdit.text():
            self.ui.lineEdit.setText(last_subfolder + '/')

    def _add_sessions_to_list(self, session_names: list[str]):
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

    def _add_templates_to_list(self, template_list: list[str]):
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
        self._text_is_valid = bool(
            text and not text.endswith('/')
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
        self._ok_button.setEnabled(
            bool(self._server_will_accept and self._text_is_valid))

    def get_session_short_path(self) -> str:
        return self.ui.lineEdit.text()

    def get_template_name(self)->str:
        index = self.ui.comboBoxTemplate.currentIndex()

        if index == 0:
            return ""

        if index <= len(ray.FACTORY_SESSION_TEMPLATES):
            return '///' + ray.FACTORY_SESSION_TEMPLATES[index-1]

        return self.ui.comboBoxTemplate.currentText()
