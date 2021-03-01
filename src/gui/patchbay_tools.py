
from PyQt5.QtWidgets import QWidget, QComboBox
from PyQt5.QtCore import pyqtSignal, QTimer

import ui.patchbay_tools

class PatchbayToolsWidget(QWidget):
    buffer_size_changed = pyqtSignal(int)
    
    def __init__(self):
        QWidget.__init__(self)
        self.ui = ui.patchbay_tools.Ui_Form()
        self.ui.setupUi(self)
        
        self.ui.pushButtonXruns.clicked.connect(
            self.reset_xruns)
        self.ui.comboBoxBuffer.currentTextChanged.connect(
            self.change_buffersize)
        
        self.current_buffer_size = 1024
        self.buffer_sizes = [16, 32, 64, 128, 256, 512,
                             1024, 2048, 4096, 8192]
        
        for size in self.buffer_sizes:
            self.ui.comboBoxBuffer.addItem(str(size), size)
        
        self._waiting_buffer_change = False
        
        self.xruns_counter = 0
        
    def set_samplerate(self, samplerate: int):
        k_samplerate = samplerate / 1000.0
        self.ui.labelSamplerate.setText("%.3f" % k_samplerate)
        
    def set_buffer_size(self, buffer_size: int):
        self._waiting_buffer_change = False
        index = self.ui.comboBoxBuffer.findData(buffer_size)
        
        # manage exotic buffer sizes
        if index < 0:
            index = 0
            for size in self.buffer_sizes:
                if size > buffer_size:
                    break
                index += 1
            
            self.buffer_sizes.insert(index, buffer_size)
            self.ui.comboBoxBuffer.insertItem(
                index, str(buffer_size), buffer_size)
        
        self.ui.comboBoxBuffer.setCurrentIndex(index)
        self.ui.comboBoxBuffer.setEnabled(True)
        self.current_buffer_size = buffer_size
    
    def update_xruns(self):
        self.ui.pushButtonXruns.setText("%i Xruns" % self.xruns_counter)
    
    def add_xrun(self):
        self.xruns_counter += 1
        self.update_xruns()
    
    def reset_xruns(self):
        self.xruns_counter = 0
        self.update_xruns()
    
    def set_dsp_load(self, dsp_load: int):
        self.ui.progressBarDsp.setValue(dsp_load)
    
    def change_buffersize(self, buffer_string: str):
        if not buffer_string.isdigit():
            return
        self.ui.comboBoxBuffer.setEnabled(False)
        self._waiting_buffer_change = True
        self.buffer_size_changed.emit(int(buffer_string))
        QTimer.singleShot(10000, self.re_enable_buffer_combobox)
        
    def re_enable_buffer_combobox(self):
        if self._waiting_buffer_change:
            self.set_buffer_size(self.current_buffer_size)
    
        
        
