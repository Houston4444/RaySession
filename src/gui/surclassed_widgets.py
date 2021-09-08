from PyQt5.QtWidgets import (
    QLineEdit, QStackedWidget, QLabel, QToolButton, QFrame, QGraphicsView,
    QSplitter, QSplitterHandle, QSlider, QToolTip, QApplication, QProgressBar,
    QDialogButtonBox, QPushButton)
from PyQt5.QtGui import (QFont, QFontDatabase, QFontMetrics, QPalette,
                         QIcon, QCursor, QMouseEvent)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QPoint, QPointF, QRectF, QSizeF

import time
import ray

from gui_tools import is_dark_theme
from gui_signaler import Signaler

class RayHackButton(QToolButton):
    order_hack_visibility = pyqtSignal(bool)

    def __init__(self, parent):
        QToolButton.__init__(self, parent)

        basecolor = self.palette().base().color().name()
        textcolor = self.palette().buttonText().color().name()
        textdbcolor = self.palette().brush(
            QPalette.Disabled, QPalette.WindowText).color().name()

        style = "QToolButton{border-radius: 2px ;border-left: 1px solid " \
            + "qlineargradient(spread:pad, x1:0, y1:0, x2:0, y2:1, stop:0 " \
            + textcolor + ", stop:0.35 " + basecolor + ", stop:0.75 " \
            + basecolor + ", stop:1 " + textcolor + ")" \
            + ";border-right: 1px solid " \
            + "qlineargradient(spread:pad, x1:0, y1:0, x2:0, y2:1, stop:0 " \
            + textcolor + ", stop:0.25 " + basecolor + ", stop:0.75 " \
            + basecolor + ", stop:1 " + textcolor + ")" \
            + ";border-top: 1px solid " + textcolor \
            + ";border-bottom : 1px solid " + textcolor \
            +  "; background-color: " + basecolor + "; font-size: 11px" + "}"\
            + "QToolButton::checked{background-color: " \
            + "qlineargradient(spread:pad, x1:0, y1:0, x2:0, y2:1, stop:0 " \
            + textcolor + ", stop:0.25 " + basecolor + ", stop:0.85 " \
            + basecolor + ", stop:1 " + textcolor + ")" \
            + "; margin-top: 0px; margin-left: 0px " + "}" \
            + "QToolButton::disabled{;border-left: 1px solid " \
            + "qlineargradient(spread:pad, x1:0, y1:0, x2:0, y2:1, stop:0 " \
            + textdbcolor + ", stop:0.25 " + basecolor + ", stop:0.75 " \
            + basecolor + ", stop:1 " + textdbcolor + ")" \
            + ";border-right: 1px solid " \
            + "qlineargradient(spread:pad, x1:0, y1:0, x2:0, y2:1, stop:0 " \
            + textdbcolor + ", stop:0.25 " + basecolor + ", stop:0.75 " \
            + basecolor + ", stop:1 " + textdbcolor + ")" \
            + ";border-top: 1px solid " + textdbcolor \
            + ";border-bottom : 1px solid " + textdbcolor \
            + "; background-color: " + basecolor + "}"

        self.setStyleSheet(style)

    def mousePressEvent(self, event):
        self.order_hack_visibility.emit(not self.isChecked())
        # and not toggle button, the client will emit a gui state that will
        # toggle this button


class OpenSessionFilterBar(QLineEdit):
    up_down_pressed = pyqtSignal(int)
    key_event = pyqtSignal(object)

    def __init__(self, parent):
        QLineEdit.__init__(self)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Up, Qt.Key_Down):
            self.up_down_pressed.emit(event.key())
            self.key_event.emit(event)
        QLineEdit.keyPressEvent(self, event)


class CustomLineEdit(QLineEdit):
    def __init__(self, parent):
        QLineEdit.__init__(self)
        self.parent = parent

    def mouseDoubleClickEvent(self, event):
        self.parent.mouseDoubleClickEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Enter, Qt.Key_Return):
            self.parent.name_changed.emit(self.text())
            self.parent.setCurrentIndex(0)
            return

        QLineEdit.keyPressEvent(self, event)


class SessionFrame(QFrame):
    frame_resized = pyqtSignal()

    def __init__(self, parent):
        QFrame.__init__(self)

    def resizeEvent(self, event):
        QFrame.resizeEvent(self, event)
        self.frame_resized.emit()


class StackedSessionName(QStackedWidget):
    name_changed = pyqtSignal(str)

    def __init__(self, parent):
        QStackedWidget.__init__(self)
        self._is_editable = True

        self._label_widget = QLabel()
        self._label_widget.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        self._label_widget.setStyleSheet("QLabel {font-weight : bold}")

        self._line_edit_widget = CustomLineEdit(self)
        self._line_edit_widget.setAlignment(Qt.AlignHCenter)

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
            self._line_edit_widget.setFocus(Qt.OtherFocusReason)
        else:
            self.setCurrentIndex(0)

    def set_on_edit(self):
        if not self._is_editable:
            return

        self.setCurrentIndex(1)


class StatusBar(QLineEdit):
    status_pressed = pyqtSignal()

    def __init__(self, parent):
        QLineEdit.__init__(self)
        self._next_texts = []
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
        if QFontMetrics(self._ubuntu_font).width(text) >= (self.width() - 16):
            self.setFont(self._ubuntu_font_cond)
        else:
            self.setFont(self._ubuntu_font)

    def setText(self, text, from_timer=False):
        self._last_status_time = time.time()

        if not self._first_text_done:
            self._set_font_for_text(text)
            QLineEdit.setText(self, text)
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

        QLineEdit.setText(self, text)

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
        StatusBar.__init__(self, parent)


class FakeToolButton(QToolButton):
    def __init__(self, parent):
        QToolButton.__init__(self, parent)
        self.setStyleSheet("QToolButton{border:none}")

    def mousePressEvent(self, event):
        self.parent().mousePressEvent(event)


class FavoriteToolButton(QToolButton):
    def __init__(self, parent):
        QToolButton.__init__(self, parent)
        self._template_name = ""
        self._template_icon = ""
        self._factory = True
        self._state = False
        self._favicon_not = QIcon(':scalable/breeze/draw-star.svg')
        self._favicon_yes = QIcon(':scalable/breeze/star-yellow.svg')

        self.session = None

        self.setIcon(self._favicon_not)

    def set_dark_theme(self):
        self._favicon_not = QIcon(':scalable/breeze-dark/draw-star.svg')
        if not self._state:
            self.setIcon(self._favicon_not)

    def set_session(self, session):
        self.session = session

    def set_template(self, template_name: str,
                    template_icon: str, factory: bool):
        self._template_name = template_name
        self._template_icon = template_icon
        self._factory = factory

    def set_as_favorite(self, yesno: bool):
        self._state = yesno
        self.setIcon(self._favicon_yes if yesno else self._favicon_not)

    def mouseReleaseEvent(self, event):
        QToolButton.mouseReleaseEvent(self, event)
        if self.session is None:
            return

        if self._state:
            self.session.remove_favorite(self._template_name, self._factory)
        else:
            self.session.add_favorite(
                self._template_name, self._template_icon, self._factory)


# taken from carla (falktx)
class DraggableGraphicsView(QGraphicsView):
    def __init__(self, parent):
        QGraphicsView.__init__(self, parent)

        self._panning = False

        try:
            self._middle_button = Qt.MiddleButton
        except:
            self._middle_button = Qt.MidButton

    def mousePressEvent(self, event):
        if (event.button() == self._middle_button
                and not QApplication.keyboardModifiers() & Qt.ControlModifier):
            self._panning = True
            self.setDragMode(QGraphicsView.ScrollHandDrag)
            event = QMouseEvent(event.type(), event.pos(), Qt.LeftButton,
                                Qt.LeftButton, event.modifiers())

        QGraphicsView.mousePressEvent(self, event)

    def mouseReleaseEvent(self, event):
        QGraphicsView.mouseReleaseEvent(self, event)

        if not self._panning:
            return

        self._panning = False
        self.setDragMode(QGraphicsView.NoDrag)
        self.setCursor(QCursor(Qt.ArrowCursor))


class CanvasSplitterHandle(QSplitterHandle):
    def __init__(self, parent):
        QSplitterHandle.__init__(self, Qt.Horizontal, parent)
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

        QSplitterHandle.mouseMoveEvent(self, event)


class CanvasSplitter(QSplitter):
    def __init__(self, parent):
        QSplitter.__init__(self, parent)

    def set_active(self, yesno: bool):
        handle = self.handle(1)
        if handle:
            handle.set_active(yesno)

    def createHandle(self):
        return CanvasSplitterHandle(self)


class ZoomSlider(QSlider):
    zoom_fit_asked = pyqtSignal()

    def __init__(self, parent):
        QSlider.__init__(self, parent)

    @staticmethod
    def map_float_to(x, min_a, max_a, min_b, max_b):
        if max_a == min_a:
            return min_b
        return min_b + ((x - min_a) / (max_a - min_a)) * (max_b - min_b)

    def _show_tool_tip(self):
        win = QApplication.activeWindow()
        if win and win.isFullScreen():
            return
        string = "  Zoom: %i%%  " % int(self.zoom_percent())
        QToolTip.showText(self.mapToGlobal(QPoint(0, 12)), string)

    def zoom_percent(self)->int:
        percent = 100.0
        if self.value() <= 500:
            percent = self.map_float_to(self.value(), 0, 500, 20, 100)
        else:
            percent = self.map_float_to(self.value(), 500, 1000, 100, 300)
        return percent

    def set_percent(self, percent: float):
        if 99.99999 < percent < 100.00001:
            self.setValue(500)
        elif percent < 100:
            self.setValue(self.map_float_to(percent, 20, 100, 0, 500))
        else:
            self.setValue(self.map_float_to(percent, 100, 300, 500, 1000))
        self._show_tool_tip()

    def mouseDoubleClickEvent(self, event):
        self.zoom_fit_asked.emit()

    def contextMenuEvent(self, event):
        self.setValue(500)
        self._show_tool_tip()

    def wheelEvent(self, event):
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


class ProgressBarDsp(QProgressBar):
    def __init__(self, parent):
        QProgressBar.__init__(self)

    def setValue(self, value):
        color_border = "rgba(%i%%, %i%%, 0, 55%%)" % (value, 100 - value)
        color_center = "rgba(%i%%, %i%%, 0, 45%%)" % (value, 100 - value)
        self.setStyleSheet(
            "QProgressBar:chunk{background-color: "
            + "qlineargradient(x1:0, y1:0, x2:0, y1:1, "
            + "stop:0 " + color_border + ','
            + "stop:0.5 " + color_center + ','
            + "stop:1 " + color_border + ',' + ')}')
        QProgressBar.setValue(self, value)


class StartupDialogButtonBox(QDialogButtonBox):
    key_event = pyqtSignal(object)

    def __init__(self, parent):
        QDialogButtonBox.__init__(self, parent)

    def keyPressEvent(self, event):
        if event.key in (Qt.Key_Up, Qt.Key_Down):
            self.key_event.emit(event)
            return

        QDialogButtonBox.keyPressEvent(self, event)

class StartupDialogPushButtonNew(QPushButton):
    focus_on_list = pyqtSignal()
    focus_on_open = pyqtSignal()

    def __init__(self, parent):
        QPushButton.__init__(self, parent)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Down, Qt.Key_Up):
            self.focus_on_open.emit()
            return

        if event.key() in (Qt.Key_Left, Qt.Key_Right):
            self.focus_on_list.emit()
            return

        QPushButton.keyPressEvent(self, event)


class StartupDialogPushButtonOpen(StartupDialogPushButtonNew):
    focus_on_new = pyqtSignal()

    def __init__(self, parent):
        StartupDialogPushButtonNew.__init__(self, parent)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Down, Qt.Key_Up):
            self.focus_on_new.emit()
            return

        StartupDialogPushButtonNew.keyPressEvent(self, event)
