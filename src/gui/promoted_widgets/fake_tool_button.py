from qtpy.QtGui import QMouseEvent
from qtpy.QtWidgets import QDialog, QToolButton, QWidget


class FakeToolButton(QToolButton):
    def __init__(self, parent: QDialog):
        QToolButton.__init__(self, parent)
        self.setStyleSheet("QToolButton{border:none}")

    def mousePressEvent(self, event: QMouseEvent):
        parent = self.parent()
        if isinstance(parent, QWidget):
            parent.mousePressEvent(event)
