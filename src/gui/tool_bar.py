
from enum import IntFlag
from PyQt5.QtWidgets import (
    QWidget, QSizePolicy, QToolBar, QLabel, QMenu,
    QApplication, QAction)
from PyQt5.QtGui import QMouseEvent
from PyQt5.QtCore import pyqtSignal, Qt, QPoint

_translate = QApplication.translate


class ToolDisplayed(IntFlag):
    TRANSPORT = 0x01
    ZOOM_SLIDER = 0x02


class SpacerWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.MinimumExpanding,
                           QSizePolicy.MinimumExpanding)


class RayToolBar(QToolBar):
    displayed_widgets_changed = pyqtSignal(int)
    
    def __init__(self, parent):
        super().__init__(parent)
        
        self._displayed_widgets = ToolDisplayed.ZOOM_SLIDER
        
    def mousePressEvent(self, event: QMouseEvent) -> None:
        child_widget = self.childAt(event.pos())
        super().mousePressEvent(event)
        if (event.button() != Qt.RightButton
                or not isinstance(child_widget, (QLabel, SpacerWidget))):
            return

        menu = QMenu()
        menu.addSection(_translate('tool_bar', 'Displayed tools'))
        
        tool_actions = {
            ToolDisplayed.TRANSPORT:
                QAction(_translate('tool_bar', 'JACK Transport')),
            ToolDisplayed.ZOOM_SLIDER:
                QAction(_translate('tool_bar', 'Zoom slider'))}
        
        for key, act in tool_actions.items():
            act.setCheckable(True)
            act.setChecked(bool(self._displayed_widgets & key))
            menu.addAction(act)
        
        # execute the menu, exit if no action
        point = event.screenPos().toPoint()
        point.setY(self.mapToGlobal(QPoint(0, self.height())).y())
        if menu.exec(point) is None:
            return

        for key, act in tool_actions.items():
            if act.isChecked():
                self._displayed_widgets |= key
            else:
                self._displayed_widgets &= ~key

        self.displayed_widgets_changed.emit(int(self._displayed_widgets))