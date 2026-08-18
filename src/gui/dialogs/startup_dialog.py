from qtpy.QtCore import Qt
from qtpy.QtGui import QKeyEvent
from qtpy.QtWidgets import QApplication, QListWidgetItem

import ray

from .child_dialog import ChildDialog

import ui.startup_dialog


class StartupDialog(ChildDialog):
    ACTION_NO = 0
    ACTION_NEW = 1
    ACTION_OPEN = 2

    def __init__(self, parent):
        super().__init__(parent)
        self.ui = ui.startup_dialog.Ui_Dialog()
        self.ui.setupUi(self)

        self._clicked_action = self.ACTION_NO

        self.ui.listWidgetRecentSessions.itemDoubleClicked.connect(
            self.accept)

        for recent_session in self.session.recent_sessions:
            session_item = QListWidgetItem(recent_session.replace('/', ' / '),
                                           self.ui.listWidgetRecentSessions)
            session_item.setData(Qt.ItemDataRole.UserRole, recent_session)
            self.ui.listWidgetRecentSessions.addItem(
                session_item) # type:ignore

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

        self.ui.listWidgetRecentSessions.setFocus()

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
        self.ui.pushButtonNewSession.setFocus()

    def _focus_on_open(self):
        self.ui.pushButtonOpenSession.setFocus()

    def not_again_value(self) -> bool:
        return not self.ui.checkBox.isChecked()

    def get_selected_session(self) -> str:
        current_item = self.ui.listWidgetRecentSessions.currentItem()
        if current_item:
            return current_item.data(Qt.ItemDataRole.UserRole)
        return ''

    def get_clicked_action(self) -> int:
        return self._clicked_action

    def keyPressEvent(self, event: QKeyEvent):
        match event.key():
            case Qt.Key.Key_Left:
                self.ui.pushButtonNewSession.setFocus()
            case Qt.Key.Key_Right:
                self.ui.pushButtonOpenSession.setFocus()
            case Qt.Key.Key_Up | Qt.Key.Key_Down:
                self.ui.listWidgetRecentSessions.setFocus()

        if (QApplication.keyboardModifiers()
                & Qt.KeyboardModifier.ControlModifier):
            match event.key():
                case Qt.Key.Key_N:
                    self._new_session_clicked()
                case Qt.Key.Key_O:
                    self._open_session_clicked()

        super().keyPressEvent(event)
