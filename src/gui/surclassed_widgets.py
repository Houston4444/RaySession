
# Imports from standard library
import time
from typing import TYPE_CHECKING

from qtpy.QtWidgets import (
    QLineEdit, QStackedWidget, QLabel, QToolButton, QFrame,
    QSplitter, QSplitterHandle, QDialogButtonBox, QPushButton,
    QDialog, QApplication, QWidget)
from qtpy.QtGui import (QFont, QFontDatabase, QFontMetrics, QPalette,
                         QIcon, QKeyEvent, QMouseEvent)
from qtpy.QtCore import Qt, QTimer, Signal

from patchbay import filter_frame, tool_bar, PatchGraphicsView

if TYPE_CHECKING:
    from gui_session import Session


class RayHackButton(QToolButton):
    order_hack_visibility = Signal(bool)

    def __init__(self, parent):
        QToolButton.__init__(self, parent)

        basecolor = self.palette().base().color().name()
        textcolor = self.palette().buttonText().color().name()
        textdbcolor = self.palette().brush(
            QPalette.ColorGroup.Disabled,
            QPalette.ColorRole.WindowText).color().name()

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
    up_down_pressed = Signal(int)
    key_event = Signal(object)

    def __init__(self, parent):
        QLineEdit.__init__(self)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self.up_down_pressed.emit(event.key())
            self.key_event.emit(event)
        QLineEdit.keyPressEvent(self, event)


class CustomLineEdit(QLineEdit):
    def __init__(self, parent: 'StackedSessionName'):
        QLineEdit.__init__(self)
        self._parent = parent

    def mouseDoubleClickEvent(self, event):
        self._parent.mouseDoubleClickEvent(event)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key.Key_Enter, Qt.Key.Key_Return):
            self._parent.name_changed.emit(self.text())
            self._parent.setCurrentIndex(0)
            return

        QLineEdit.keyPressEvent(self, event)


class SessionFrame(QFrame):
    frame_resized = Signal()

    def __init__(self, parent):
        QFrame.__init__(self)

    def resizeEvent(self, event):
        QFrame.resizeEvent(self, event)
        self.frame_resized.emit()


class StackedSessionName(QStackedWidget):
    name_changed = Signal(str)

    def __init__(self, parent):
        QStackedWidget.__init__(self)
        self._is_editable = True

        self._label_widget = QLabel()
        self._label_widget.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        self._label_widget.setStyleSheet("QLabel {font-weight : bold}")

        self._line_edit_widget = CustomLineEdit(self)
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
            self._line_edit_widget.setFocus(Qt.FocusReason.OtherFocusReason)
        else:
            self.setCurrentIndex(0)

    def set_on_edit(self):
        if not self._is_editable:
            return

        self.setCurrentIndex(1)


class StatusBar(QLineEdit):
    status_pressed = Signal()

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
    def __init__(self, parent: QDialog):
        QToolButton.__init__(self, parent)
        self.setStyleSheet("QToolButton{border:none}")

    def mousePressEvent(self, event: QMouseEvent):
        parent = self.parent()
        if isinstance(parent, QWidget):
            parent.mousePressEvent(event)


class FavoriteToolButton(QToolButton):
    def __init__(self, parent):
        QToolButton.__init__(self, parent)
        self._template_name = ''
        self._template_icon = ''
        self._factory = True
        self._display_name = ''
        self._state = False
        self._favicon_not = QIcon(':scalable/breeze/draw-star.svg')
        self._favicon_yes = QIcon(':scalable/breeze/star-yellow.svg')

        self.session: Session = None

        self.setIcon(self._favicon_not)

    def set_dark_theme(self):
        self._favicon_not = QIcon(':scalable/breeze-dark/draw-star.svg')
        if not self._state:
            self.setIcon(self._favicon_not)

    def set_session(self, session: 'Session'):
        self.session = session

    def set_template(self, template_name: str, template_icon: str,
                     factory: bool, display_name: str):
        self._template_name = template_name
        self._template_icon = template_icon
        self._factory = factory
        self._display_name = display_name

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
                self._template_name, self._template_icon,
                self._factory, self._display_name)


class CanvasSplitterHandle(QSplitterHandle):
    def __init__(self, parent):
        QSplitterHandle.__init__(self, Qt.Orientation.Horizontal, parent)
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

    def handle(self, index: int) -> CanvasSplitterHandle:
        # just for output type redefinition
        return super().handle(index)

    def set_active(self, yesno: bool):
        handle = self.handle(1)
        if handle:
            handle.set_active(yesno)

    def createHandle(self):
        return CanvasSplitterHandle(self)


class StartupDialogButtonBox(QDialogButtonBox):
    key_event = Signal(object)

    def __init__(self, parent):
        QDialogButtonBox.__init__(self, parent)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self.key_event.emit(event)
            return

        QDialogButtonBox.keyPressEvent(self, event)


class StartupDialogPushButtonNew(QPushButton):
    focus_on_list = Signal()
    focus_on_open = Signal()

    def __init__(self, parent):
        QPushButton.__init__(self, parent)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            self.focus_on_open.emit()
            return

        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            self.focus_on_list.emit()
            return

        QPushButton.keyPressEvent(self, event)


class StartupDialogPushButtonOpen(StartupDialogPushButtonNew):
    focus_on_new = Signal()

    def __init__(self, parent):
        StartupDialogPushButtonNew.__init__(self, parent)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            self.focus_on_new.emit()
            return

        StartupDialogPushButtonNew.keyPressEvent(self, event)


class PreviewFrame(QFrame):
    def __init__(self, parent):
        QFrame.__init__(self, parent)


class CanvasGroupFilterFrame(filter_frame.FilterFrame):
    def __init__(self, parent):
        super().__init__(parent)
        

class RayToolBar(tool_bar.PatchbayToolBar):
    def __init__(self, parent):
        super().__init__(parent)
