 # -*- coding: utf-8 -*-

from PyQt5.QtWidgets import QLineEdit
from PyQt5.QtGui     import QPalette, QColor
from PyQt5.QtCore    import QTimer

class StatusBar(QLineEdit):
    def __init__(self, parent):
        QLineEdit.__init__(self)
        self.next_texts = []
        self.timer = QTimer()
        self.timer.setInterval(350)
        self.timer.timeout.connect(self.showNextText)
        
        palette = self.palette()
        base = palette.base()
        text = palette.text()
        palette.setBrush(QPalette.Base, text)
        palette.setBrush(QPalette.WindowText, base)
        palette.setBrush(QPalette.Text, base)
        
        win_bg_color = self.palette().window().color()        
        self.setPalette(palette)
        
    def showNextText(self):
        if self.next_texts:
            next_text = self.next_texts[0]
            self.next_texts.__delitem__(0)
            self.setText(next_text, True)
        else:
            self.timer.stop()
        
    def setText(self, text, from_timer=False):
        if not from_timer:
            if self.timer.isActive():
                self.next_texts.append(text)
                return
            self.timer.start()
        if len(text) > 6:
            self.setStyleSheet('QLineEdit{font-size: 8px; font-weight: bold}')
        else:
            self.setStyleSheet('QLineEdit{font-size: 10px; font-weight: bold}')
        QLineEdit.setText(self, text)
        
    def paintEvent(self, event):
        
        QLineEdit.paintEvent(self, event)
        
        
