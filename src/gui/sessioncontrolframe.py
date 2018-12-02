 # -*- coding: utf-8 -*-

from PyQt5.QtWidgets import QFrame
from PyQt5.QtGui import QPalette

class SessionControlFrame(QFrame):
    def __init__(self, parent):
        QFrame.__init__(self)
        palette = self.palette()
        window_brush = palette.window()
        text_brush   = palette.text()
        palette.setBrush(QPalette.WindowText, window_brush)
        palette.setBrush(QPalette.Window, text_brush)
        self.setPalette(palette)
        self.setStyleSheet('QFrame{background-color:white}')
        
