from qtpy.QtCore import Qt, Signal # type:ignore
from qtpy.QtGui import QKeyEvent
from qtpy.QtWidgets import QLabel, QLineEdit, QStackedWidget


class _CustomLineEdit(QLineEdit):
    def __init__(self, parent: 'StackedSessionName'):
        super().__init__()
        self._parent = parent

    def mouseDoubleClickEvent(self, event):
        self._parent.mouseDoubleClickEvent(event)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key.Key_Enter, Qt.Key.Key_Return):
            self._parent.name_changed.emit(self.text())
            self._parent.setCurrentIndex(0)
            return

        super().keyPressEvent(event)


class StackedSessionName(QStackedWidget):
    name_changed = Signal(str)

    def __init__(self, parent):
        QStackedWidget.__init__(self)
        self._is_editable = True

        self._label_widget = QLabel()
        self._label_widget.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        self._label_widget.setStyleSheet("QLabel {font-weight : bold}")

        self._line_edit_widget = _CustomLineEdit(self)
        self._line_edit_widget.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self.addWidget(self._label_widget)
        self.addWidget(self._line_edit_widget)

        self.setCurrentIndex(0)

    def mouseDoubleClickEvent(self, event):
        if self.currentIndex() == 1:
            self.setCurrentIndex(0)
            self.name_changed.emit(self._line_edit_widget.text())
            return

        if self.currentIndex() == 0 and self._is_editable:
            self.setCurrentIndex(1)
            self._line_edit_widget.setText(self._label_widget.text())
            self._line_edit_widget.selectAll()
            return

        QStackedWidget.mouseDoubleClickEvent(self, event)

    def set_editable(self, yesno: bool):
        self._is_editable = yesno

        if not yesno:
            self.setCurrentIndex(0)

    def set_text(self, text: str):
        self._label_widget.setText(text)
        self._line_edit_widget.setText(text)

        self.setCurrentIndex(0)

    def toggle_edit(self):
        if not self._is_editable:
            self.setCurrentIndex(0)
            return

        if self.currentIndex() == 0:
            self.setCurrentIndex(1)
            self._line_edit_widget.setFocus()
        else:
            self.setCurrentIndex(0)

    def set_on_edit(self):
        if not self._is_editable:
            return

        self.setCurrentIndex(1)
