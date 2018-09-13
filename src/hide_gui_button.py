from PyQt5.QtWidgets import QToolButton
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtGui  import QPalette

class HideGuiButton(QToolButton):
    toggleGui = pyqtSignal()
    
    def __init__(self, parent):
        QToolButton.__init__(self, parent)
        
        basecolor   = self.palette().base().color().name()
        textcolor   = self.palette().buttonText().color().name()
        textdbcolor = self.palette().brush(QPalette.Disabled, QPalette.WindowText).color().name()
        
        style = "QToolButton{border-radius: 2px ;border-left: 1px solid " + \
                "qlineargradient(spread:pad, x1:0, y1:0, x2:0, y2:1, stop:0 " + textcolor + \
                ", stop:0.35 " + basecolor + ", stop:0.75 " + basecolor + ", stop:1 " + textcolor + ")" + \
                ";border-right: 1px solid " + "qlineargradient(spread:pad, x1:0, y1:0, x2:0, y2:1, stop:0 " + textcolor + \
                ", stop:0.25 " + basecolor + ", stop:0.75 " + basecolor + ", stop:1 " + textcolor + ")" + \
                ";border-top: 1px solid " + textcolor + ";border-bottom : 1px solid " + textcolor +  \
                "; background-color: " + basecolor + "; font-size: 11px" + "}" + \
                "QToolButton::checked{background-color: " + \
                "qlineargradient(spread:pad, x1:0, y1:0, x2:0, y2:1, stop:0 " + textcolor + \
                ", stop:0.25 " + basecolor + ", stop:0.85 " + basecolor + ", stop:1 " + textcolor + ")" + \
                "; margin-top: 0px; margin-left: 0px " + "}" + \
                "QToolButton::disabled{;border-left: 1px solid " + \
                "qlineargradient(spread:pad, x1:0, y1:0, x2:0, y2:1, stop:0 " + textdbcolor + \
                ", stop:0.25 " + basecolor + ", stop:0.75 " + basecolor + ", stop:1 " + textdbcolor + ")" + \
                ";border-right: 1px solid " + \
                "qlineargradient(spread:pad, x1:0, y1:0, x2:0, y2:1, stop:0 " + textdbcolor + \
                ", stop:0.25 " + basecolor + ", stop:0.75 " + basecolor + ", stop:1 " + textdbcolor + ")" + \
                ";border-top: 1px solid " + textdbcolor + ";border-bottom : 1px solid " + textdbcolor + \
                "; background-color: " + basecolor + "}"
            
        self.setStyleSheet(style)
        
        
    def mousePressEvent(self, event):
        self.toggleGui.emit()
        #and not toggle button, the client will emit a gui state that will toggle this button
