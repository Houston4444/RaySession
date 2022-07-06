from PyQt5.QtCore import Qt, pyqtSignal, QPoint
from PyQt5.QtGui import QWheelEvent, QKeyEvent
from PyQt5.QtWidgets import (QApplication, QProgressBar, QSlider, QToolTip,
                             QLineEdit)


class FilterBar(QLineEdit):
    up_down_pressed = pyqtSignal(int)
    key_event = pyqtSignal(object)

    def __init__(self, parent):
        QLineEdit.__init__(self)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key_Up, Qt.Key_Down):
            self.up_down_pressed.emit(event.key())
            self.key_event.emit(event)
        QLineEdit.keyPressEvent(self, event)


class ProgressBarDsp(QProgressBar):
    def __init__(self, parent):
        QProgressBar.__init__(self)

    def setValue(self, value: int):
        color_border = "rgba(%i%%, %i%%, 0, 55%%)" % (value, 100 - value)
        color_center = "rgba(%i%%, %i%%, 0, 45%%)" % (value, 100 - value)
        self.setStyleSheet(
            "QProgressBar:chunk{background-color: "
            + "qlineargradient(x1:0, y1:0, x2:0, y1:1, "
            + "stop:0 " + color_border + ','
            + "stop:0.5 " + color_center + ','
            + "stop:1 " + color_border + ',' + ')}')
        QProgressBar.setValue(self, value)
        

class ZoomSlider(QSlider):
    zoom_fit_asked = pyqtSignal()

    def __init__(self, parent):
        QSlider.__init__(self, parent)

    @staticmethod
    def map_float_to(x: float, min_a: int, max_a: int,
                     min_b: int, max_b: int) -> float:
        if max_a == min_a:
            return min_b
        return min_b + ((x - min_a) / (max_a - min_a)) * (max_b - min_b)

    def _show_tool_tip(self):
        win = QApplication.activeWindow()
        if win and win.isFullScreen():
            return
        string = "  Zoom: %i%%  " % int(self.zoom_percent())
        QToolTip.showText(self.mapToGlobal(QPoint(0, 12)), string)

    def zoom_percent(self) -> int:
        if self.value() <= 500:
            return self.map_float_to(self.value(), 0, 500, 20, 100)
        return self.map_float_to(self.value(), 500, 1000, 100, 300)

    def set_percent(self, percent: float):
        if 99.99999 < percent < 100.00001:
            self.setValue(500)
        elif percent < 100:
            self.setValue(int(self.map_float_to(percent, 20, 100, 0, 500)))
        else:
            self.setValue(int(self.map_float_to(percent, 100, 300, 500, 1000)))
        self._show_tool_tip()

    def mouseDoubleClickEvent(self, event):
        self.zoom_fit_asked.emit()

    def contextMenuEvent(self, event):
        self.setValue(500)
        self._show_tool_tip()

    def wheelEvent(self, event: QWheelEvent):
        direction = 1 if event.angleDelta().y() > 0 else -1

        if QApplication.keyboardModifiers() & Qt.ControlModifier:
            self.set_percent(self.zoom_percent() + direction)
        else:
            self.set_percent(self.zoom_percent() + direction * 5)
            #QSlider.wheelEvent(self, event)
        self._show_tool_tip()

    def mouseMoveEvent(self, event):
        QSlider.mouseMoveEvent(self, event)
        self._show_tool_tip()

