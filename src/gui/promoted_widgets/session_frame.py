from qtpy.QtCore import Signal # type:ignore
from qtpy.QtWidgets import QFrame


class SessionFrame(QFrame):
    frame_resized = Signal()

    def __init__(self, parent):
        QFrame.__init__(self)

    def resizeEvent(self, event):
        QFrame.resizeEvent(self, event)
        self.frame_resized.emit()
