
from PyQt5.QtWidgets import QWidget, QComboBox
from PyQt5.QtCore import pyqtSignal, QTimer

import ui.canvas_port_info
import ui.patchbay_tools

CONTEXT_AUDIO = 0x01
CONTEXT_MIDI = 0x02


class PatchbayToolsWidget(QWidget):
    buffer_size_change_order = pyqtSignal(int)
    audio_midi_change_order = pyqtSignal(int)
    
    def __init__(self):
        QWidget.__init__(self)
        self.ui = ui.patchbay_tools.Ui_Form()
        self.ui.setupUi(self)
        
        self._waiting_buffer_change = False
        self._buffer_change_from_osc = False
        
        self._current_audio_midi = 3
        
        self.ui.checkBoxAudio.stateChanged.connect(
            self.audio_button_checked)
        self.ui.checkBoxMidi.stateChanged.connect(
            self.midi_button_checked)
        self.ui.pushButtonXruns.clicked.connect(
            self.reset_xruns)
        self.ui.comboBoxBuffer.currentIndexChanged.connect(
            self.change_buffersize)
        
        self.buffer_sizes = [16, 32, 64, 128, 256, 512,
                             1024, 2048, 4096, 8192]
        
        for size in self.buffer_sizes:
            self.ui.comboBoxBuffer.addItem(str(size), size)
        
        self.current_buffer_size = self.ui.comboBoxBuffer.currentData()
        
        self.xruns_counter = 0
    
    def audio_button_checked(self, yesno: int):
        if yesno:
            self._current_audio_midi |= CONTEXT_AUDIO
        else:
            self._current_audio_midi &= ~CONTEXT_AUDIO
            if not self._current_audio_midi & CONTEXT_MIDI:
                self.ui.checkBoxMidi.setChecked(True)
                return
        
        self.audio_midi_change_order.emit(self._current_audio_midi)
        
    def midi_button_checked(self, yesno: int):
        if yesno:
            self._current_audio_midi |= CONTEXT_MIDI
        else:
            self._current_audio_midi &= ~CONTEXT_MIDI
            if not self._current_audio_midi & CONTEXT_AUDIO:
                self.ui.checkBoxAudio.setChecked(True)
                return

        self.audio_midi_change_order.emit(self._current_audio_midi)
    
    def set_samplerate(self, samplerate: int):
        #k_samplerate = samplerate / 1000.0
        str_sr = str(samplerate)
        str_samplerate = str_sr[:-3] + ' ' + str_sr[-3:]
        
        self.ui.labelSamplerate.setText(str_samplerate)
        
    def set_buffer_size(self, buffer_size: int):
        self._waiting_buffer_change = False
        self.ui.comboBoxBuffer.setEnabled(True)

        if self.ui.comboBoxBuffer.currentData() == buffer_size:
            return
        
        self._buffer_change_from_osc = True
        
        index = self.ui.comboBoxBuffer.findData(buffer_size)
        
        # manage exotic buffer sizes
        # findData returns -1 if buffer_size is not in combo box values
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
    
    def change_buffersize(self, index: int):
        # prevent loop of buffer size change
        if self._buffer_change_from_osc:
            # change_buffersize not called by user
            # but ensure next time it could be
            self._buffer_change_from_osc = False
            return
        
        
        self.ui.comboBoxBuffer.setEnabled(False)
        self._waiting_buffer_change = True
        self.buffer_size_change_order.emit(
            self.ui.comboBoxBuffer.currentData())
        
        # only in the case no set_buffer_size message come back
        QTimer.singleShot(10000, self.re_enable_buffer_combobox)
        
    def re_enable_buffer_combobox(self):
        if self._waiting_buffer_change:
            self.set_buffer_size(self.current_buffer_size)
            
    def set_jack_running(self, yesno: bool):
        for widget in (
                self.ui.checkBoxAudio,
                self.ui.checkBoxMidi,
                self.ui.labelSamplerateTitle,
                self.ui.labelSamplerate,
                self.ui.labelSamplerateUnits,
                self.ui.labelBuffer,
                self.ui.comboBoxBuffer,
                self.ui.pushButtonXruns,
                self.ui.labelDsp,
                self.ui.progressBarDsp,
                self.ui.lineSep1,
                self.ui.lineSep2,
                self.ui.lineSep3):
            widget.setVisible(yesno)
        
        self.ui.labelJackNotStarted.setVisible(not yesno)
        
