from qtpy.QtCore import Signal, Qt # type:ignore
from qtpy.QtGui import QKeyEvent
from qtpy.QtWidgets import QLineEdit


class OpenSessionFilterBar(QLineEdit):
    up_down_pressed = Signal(int)
    key_event = Signal(object)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self.up_down_pressed.emit(event.key())
            self.key_event.emit(event)
        super().keyPressEvent(event)
