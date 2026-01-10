import time

from qtpy.QtCore import QTimer, Signal # type:ignore
from qtpy.QtGui import QFont, QFontDatabase, QFontMetrics
from qtpy.QtWidgets import QLineEdit


class StatusBar(QLineEdit):
    status_pressed = Signal()

    def __init__(self, parent):
        super().__init__()
        self._next_texts = list[str]()
        self._timer = QTimer()
        self._timer.setInterval(350)
        self._timer.timeout.connect(self._show_next_text)

        self._ubuntu_font = QFont(
            QFontDatabase.applicationFontFamilies(0)[0], 8)
        self._ubuntu_font_cond = QFont(
            QFontDatabase.applicationFontFamilies(1)[0], 8)
        self._ubuntu_font.setBold(True)
        self._ubuntu_font_cond.setBold(True)

        self._basecolor = self.palette().base().color().name()
        self._bluecolor = self.palette().highlight().color().name()

        self._last_status_time = 0.0

        # ui_client_slot.py will display "stopped" status.
        # we need to not stay on this status text
        # especially at client switch because widget is recreated.
        self._first_text_done = False

    def _show_next_text(self):
        if self._next_texts:
            if len(self._next_texts) >= 4:
                interval = int(1000 / len(self._next_texts))
                self._timer.setInterval(interval)
            elif len(self._next_texts) == 3:
                self._timer.setInterval(350)
            self.setText(self._next_texts.pop(0), True)
        else:
            self._timer.stop()

    def _set_font_for_text(self, text):
        if (QFontMetrics(self._ubuntu_font).horizontalAdvance(text)
                >= (self.width() - 16)):
            self.setFont(self._ubuntu_font_cond)
        else:
            self.setFont(self._ubuntu_font)

    def setText(self, text, from_timer=False):
        self._last_status_time = time.time()

        if not self._first_text_done:
            self._set_font_for_text(text)
            super().setText(text)
            self._first_text_done = True
            return

        if text and not from_timer:
            if self._timer.isActive():
                self._next_texts.append(text)
                return

            self._timer.start()

        if not text:
            self._next_texts.clear()

        self._set_font_for_text(text)

        self.setStyleSheet('')

        super().setText(text)

    def set_progress(self, progress: float):
        if not 0.0 <= progress <= 1.0:
            return

        # no progress display in the first second
        if time.time() - self._last_status_time < 1.0:
            return

        pre_progress = progress - 0.03
        if pre_progress < 0:
            pre_progress = 0

        style = "QLineEdit{background-color: " \
                + "qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0," \
                + "stop:0 %s, stop:%f %s, stop:%f %s, stop:1 %s)}" \
                    % (self._bluecolor, pre_progress, self._bluecolor,
                       progress, self._basecolor, self._basecolor)

        self.setStyleSheet(style)

    def mousePressEvent(self, event):
        self.status_pressed.emit()


class StatusBarNegativ(StatusBar):
    def __init__(self, parent):
        super().__init__(parent)