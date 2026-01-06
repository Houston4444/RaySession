from qtpy.QtCore import QTimer
from qtpy.QtWidgets import QMessageBox

import osc_paths.ray as r
import ray

from gui_tools import RS, _translate
from .child_dialog import ChildDialog

import ui.session_notes


class SessionNotesDialog(ChildDialog):
    def __init__(self, parent):
        super().__init__(parent)
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
                _translate(
                    'session_notes',
                    "<p>Because notes are spread to the OSC server,<br>"
                    "they can't be longer than 65000 characters.<br>"
                    "Sorry !</p>"),
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
