 # -*- coding: utf-8 -*-

from PyQt5.QtWidgets import QStackedWidget, QLabel, QLineEdit
from PyQt5.QtCore import Qt, pyqtSignal

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

class StackedSessionName(QStackedWidget):
    name_changed = pyqtSignal(str)
    
    def __init__(self, parent):
        QStackedWidget.__init__(self)
        self.is_editable = True
        
        self.label_widget = QLabel()
        self.label_widget.setAlignment(Qt.AlignHCenter |Qt.AlignVCenter)
        self.label_widget.setStyleSheet("QLabel {font-weight : bold}")
        
        self.line_edit_widget = CustomLineEdit(self)
        self.line_edit_widget.setAlignment(Qt.AlignHCenter)
        
        self.addWidget(self.label_widget)
        self.addWidget(self.line_edit_widget)
        
        self.setCurrentIndex(0)
        
    def mouseDoubleClickEvent(self, event):
        if self.currentIndex() == 1:
            self.setCurrentIndex(0)
            self.name_changed.emit(self.line_edit_widget.text())
            return
        
        elif self.currentIndex() == 0 and self.is_editable:
            self.setCurrentIndex(1)
            return
        
        QStackedWidget.mouseDoubleClickEvent(self, event)
    
    def setEditable(self, editable):
        self.is_editable = editable
        
        if not editable:
            self.setCurrentIndex(0)
            
    def setText(self, text):
        self.label_widget.setText(text)
        self.line_edit_widget.setText(text)
            
    
            
