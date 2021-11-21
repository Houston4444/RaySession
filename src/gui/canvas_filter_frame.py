
from PyQt5.QtWidgets import QFrame
from PyQt5.QtCore import pyqtSignal, Qt

import patchbay_manager

import ui.filter_frame


class CanvasFilterFrame(QFrame):
    def __init__(self, parent):
        QFrame.__init__(self, parent)
        self.ui = ui.filter_frame.Ui_Frame()
        self.ui.setupUi(self)

        self.patchbay_manager = None
        
        self.ui.lineEditGroupFilter.textEdited.connect(self._text_changed)
        self.ui.lineEditGroupFilter.up_down_pressed.connect(self._up_down_pressed)
        self.ui.toolButtonUp.clicked.connect(self._up_pressed)
        self.ui.toolButtonDown.clicked.connect(self._down_pressed)
        self.ui.checkBoxAudioFilter.stateChanged.connect(
            self._check_box_audio_checked)
        self.ui.checkBoxMidiFilter.stateChanged.connect(
            self._check_box_midi_checked)
        self.ui.toolButtonCloseFilterBar.clicked.connect(
            self.hide)
        
        self._n_selected = 0
        self._n_boxes = 0
    
    def _filter_groups(self):
        if self.patchbay_manager is None:
            return
        
        filter_text = self.ui.lineEditGroupFilter.text()
        
        self.ui.labelBoxes.setText('')
        
        self._n_boxes = self.patchbay_manager.filter_groups(
            filter_text, self._n_selected)

        if self._n_boxes:
            self.ui.lineEditGroupFilter.setStyleSheet('')
            
            if filter_text:
                self.ui.labelBoxes.setText(
                    '%i / %i' % (self._n_selected, self._n_boxes))
        else:
            self.ui.lineEditGroupFilter.setStyleSheet(
                'QLineEdit{background-color:#800000}')
            

        self.ui.toolButtonUp.setEnabled(self._n_boxes >= 2)
        self.ui.toolButtonDown.setEnabled(self._n_boxes >= 2)

    def _text_changed(self, text: str):
        if text:
            self._n_selected = 1
        else:
            self._n_selected = 0
        self._filter_groups()

    def _up_pressed(self):
        self._n_selected += 1
        if self._n_selected > self._n_boxes:
            self._n_selected = 1
        self._filter_groups()
    
    def _down_pressed(self):
        self._n_selected -= 1
        if self._n_selected < 1:
            self._n_selected = self._n_boxes

        self._filter_groups()

    def _up_down_pressed(self, key: int):
        if not self.ui.toolButtonUp.isEnabled():
            # could be toolButtonDown
            # they both are enable/disable together
            return
        
        if key == Qt.Key_Up:
            self._up_pressed()
        elif key == Qt.Key_Down:
            self._down_pressed()

    def _change_port_types_view(self):
        if self.patchbay_manager is None:
            return
        
        port_types_view = (
            int(self.ui.checkBoxAudioFilter.isChecked())
                * patchbay_manager.PORT_TYPE_AUDIO
            + int(self.ui.checkBoxMidiFilter.isChecked())
                  * patchbay_manager.PORT_TYPE_MIDI)
        
        self.patchbay_manager.change_port_types_view(port_types_view)
        self._filter_groups()
    
    def _check_box_audio_checked(self, state: int):
        if not state:
            self.ui.checkBoxMidiFilter.setChecked(True)
            
        self._change_port_types_view()

    def _check_box_midi_checked(self, state: int):
        if not state:
            self.ui.checkBoxAudioFilter.setChecked(True)
            
        self._change_port_types_view()
    
    def showEvent(self, event):
        self.ui.lineEditGroupFilter.setFocus()
        self.ui.toolButtonDown.setEnabled(False)
        self.ui.toolButtonUp.setEnabled(False)
        self.ui.labelBoxes.setText('')
        
    def hideEvent(self, event):
        self.ui.lineEditGroupFilter.setText('')
        self._n_selected = 0
        self._filter_groups()
        
    def set_patchbay_manager(self, patchbay_manager):
        self.patchbay_manager = patchbay_manager
        
