# -*- coding: utf-8 -*-

from PyQt5.QtWidgets import QLineEdit
from PyQt5.QtCore    import Qt, pyqtSignal

class OpenSessionFilterBar(QLineEdit):
    updownpressed = pyqtSignal(int)
    
    def __init__(self, parent):
        QLineEdit.__init__(self)
        
    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Up, Qt.Key_Down):
            self.updownpressed.emit(event.key())
        QLineEdit.keyPressEvent(self, event)
        
