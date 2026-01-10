from qtpy.QtCore import Qt, Signal # type:ignore
from qtpy.QtGui import QKeyEvent
from qtpy.QtWidgets import QDialogButtonBox, QPushButton


class StartupDialogButtonBox(QDialogButtonBox):
    key_event = Signal(object)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self.key_event.emit(event)
            return

        super().keyPressEvent(event)


class StartupDialogPushButtonNew(QPushButton):
    focus_on_list = Signal()
    focus_on_open = Signal()

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            self.focus_on_open.emit()
            return

        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            self.focus_on_list.emit()
            return

        super().keyPressEvent(event)


class StartupDialogPushButtonOpen(StartupDialogPushButtonNew):
    focus_on_new = Signal()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            self.focus_on_new.emit()
            return

        super().keyPressEvent(event)
