import time

import osc_paths.ray as r
import ray

from gui_tools import _translate
from .child_dialog import ChildDialog

import ui.stop_client
import ui.stop_client_no_save


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
                    "<strong>%s</strong> seems to has not been saved "
                    "for %i minute(s).<br />"
                    "Do you really want to stop it ?") \
                        % (self.client.prettier_name(), minutes)
            self.ui.label.setText(text)

            self.client.status_changed.connect(
                self._server_updates_client_status)

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
            self.client.status_changed.connect(
                self._server_updates_client_status)

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
