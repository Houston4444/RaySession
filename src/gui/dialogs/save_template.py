from typing import TYPE_CHECKING
from qtpy.QtWidgets import QMessageBox

import osc_paths.ray as r
import ray

from gui_tools import _translate, get_app_icon
from .child_dialog import ChildDialog

import ui.save_template_session

if TYPE_CHECKING:
    from gui_client import Client


class _AbstractSaveTemplateDialog(ChildDialog):
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

        self.template_list = list[str]()

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

    def _add_templates_to_list(self, template_list: list[str]):
        self.template_list += template_list

        for template in template_list:
            if template == self.ui.lineEdit.text():
                self.ui.pushButtonAccept.setText(self._update_template_text)
                break

    def get_template_name(self)->str:
        return self.ui.lineEdit.text()


class SaveTemplateSessionDialog(_AbstractSaveTemplateDialog):
    def __init__(self, parent):
        super().__init__(parent)
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


class SaveTemplateClientDialog(_AbstractSaveTemplateDialog):
    def __init__(self, parent, client: 'Client'):
        super().__init__(parent)
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
