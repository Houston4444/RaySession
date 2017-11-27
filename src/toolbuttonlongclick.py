# -*- coding: utf-8 -*-
from PyQt5.QtWidgets import QToolButton
from PyQt5.QtCore    import QTimer, pyqtSignal

class ToolButtonLongClick(QToolButton):
    longclicked = pyqtSignal()
    
    def __init__(self, parent):
        QToolButton.__init__(self)
        self.timer_click = QTimer()
        self.timer_click.setInterval(1000)
        self.timer_click.setSingleShot(True)
        self.timer_click.timeout.connect(self.longclicked.emit)
    
    def mousePressEvent(self, event):
        self.timer_click.start()
        QToolButton.mousePressEvent(self, event)
        
    def mouseReleaseEvent(self, event):
        self.timer_click.stop()
        QToolButton.mouseReleaseEvent(self, event)
        
    def mouseMoveEvent(self, event):
        print(event.pos().x(), self.size().width())
        if (not event.pos().x() in range(self.size().width()) or
            not event.pos().y() in range(self.size().height()) ):
            self.timer_click.stop()
        QToolButton.mouseMoveEvent(self, event)
    
