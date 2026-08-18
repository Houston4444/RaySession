from qtpy.QtCore import Qt
from qtpy.QtWidgets import QSplitter, QSplitterHandle


class _CanvasSplitterHandle(QSplitterHandle):
    def __init__(self, parent):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._default_cursor = self.cursor()
        self._active = True

    def set_active(self, yesno: bool):
        self._active = yesno

        if yesno:
            self.setCursor(self._default_cursor)
        else:
            self.unsetCursor()

    def mouseMoveEvent(self, event):
        if not self._active:
            return

        super().mouseMoveEvent(event)
        

class CanvasSplitter(QSplitter):
    def __init__(self, parent):
        QSplitter.__init__(self, parent)

    def handle(self, index: int) -> _CanvasSplitterHandle:
        # just for output type redefinition
        return super().handle(index) # type:ignore

    def set_active(self, yesno: bool):
        handle = self.handle(1)
        if handle:
            handle.set_active(yesno)

    def createHandle(self):
        return _CanvasSplitterHandle(self)
