 # -*- coding: utf-8 -*-

from PyQt5.QtWidgets import QLineEdit
from PyQt5.QtGui     import QPalette, QColor, QFont, QFontDatabase, QFontMetrics
from PyQt5.QtCore    import QTimer, pyqtSignal

class StatusBar(QLineEdit):
    copyAborted = pyqtSignal()
    
    def __init__(self, parent):
        QLineEdit.__init__(self)
        self.next_texts = []
        self.timer = QTimer()
        self.timer.setInterval(350)
        self.timer.timeout.connect(self.showNextText)
        
        self.ubuntu_font      = QFont(QFontDatabase.applicationFontFamilies(0)[0], 8)
        self.ubuntu_font_cond = QFont(QFontDatabase.applicationFontFamilies(1)[0], 8)
        self.ubuntu_font.setBold(True)
        self.ubuntu_font_cond.setBold(True)
        
        self.basecolor = self.palette().base().color().name()
        self.bluecolor = self.palette().highlight().color().name()
        
    def showNextText(self):
        if self.next_texts:
            next_text = self.next_texts[0]
            self.next_texts.__delitem__(0)
            self.setText(next_text, True)
        else:
            self.timer.stop()
        
    def setText(self, text, from_timer=False):
        if text and not from_timer:
            if self.timer.isActive():
                self.next_texts.append(text)
                return
            self.timer.start()
        
        if not text:
            self.next_texts.clear()
        
        if QFontMetrics(self.ubuntu_font).width(text) > (self.width() - 10):
            self.setFont(self.ubuntu_font_cond)
        else:
            self.setFont(self.ubuntu_font)
            
        self.setStyleSheet('')
        
        QLineEdit.setText(self, text)
        
    def setProgress(self, progress):
        if not 0.0 <= progress <= 1.0:
            return
        
        pre_progress = progress - 0.03
        if pre_progress < 0:
            pre_progress = 0
        
        style = "QLineEdit{background-color: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0,stop:0 %s, stop:%f %s, stop:%f %s, stop:1 %s)}" % (self.bluecolor, pre_progress, self.bluecolor, progress, self.basecolor, self.basecolor)
        
        self.setStyleSheet(style)
        
    def mousePressEvent(self, event):
        event.ignore()
        
class StatusBarNegativ(StatusBar):
    def __init__(self, parent):
        StatusBar.__init__(self, parent)
        
    def mousePressEvent(self, event):
        self.copyAborted.emit()
        
    
