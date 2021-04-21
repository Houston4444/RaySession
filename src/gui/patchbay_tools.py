
from PyQt5.QtCore import pyqtSignal, QTimer
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QWidget, QComboBox, QMenu, QApplication

import patchcanvas

import ui.canvas_port_info
import ui.patchbay_tools

GROUP_CONTEXT_AUDIO = 0x01
GROUP_CONTEXT_MIDI = 0x02

_translate = QApplication.translate


class PatchbayToolsWidget(QWidget):
    buffer_size_change_order = pyqtSignal(int)

    def __init__(self):
        QWidget.__init__(self)
        self.ui = ui.patchbay_tools.Ui_Form()
        self.ui.setupUi(self)

        self._waiting_buffer_change = False
        self._buffer_change_from_osc = False

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

    def set_samplerate(self, samplerate: int):
        str_sr = str(samplerate)
        str_samplerate = str_sr
        if len(str_sr) > 3:
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


class CanvasMenu(QMenu):
    def __init__(self, patchbay_manager):
        QMenu.__init__(self, _translate('patchbay', 'Patchbay'))
        self.patchbay_manager = patchbay_manager
        
        self.action_fullscreen = self.addAction(
            _translate('patchbay', "Toggle Full Screen"))
        self.action_fullscreen.setIcon(QIcon.fromTheme('view-fullscreen'))
        self.action_fullscreen.triggered.connect(
            patchbay_manager.toggle_full_screen)

        port_types_view = patchbay_manager.port_types_view & (
            GROUP_CONTEXT_AUDIO | GROUP_CONTEXT_MIDI)

        self.port_types_menu = QMenu(_translate('patchbay', 'Type filter'))
        self.port_types_menu.setIcon(QIcon.fromTheme('view-filter'))
        self.action_audio_midi = self.port_types_menu.addAction(
            _translate('patchbay', 'Audio + Midi'))
        self.action_audio_midi.setCheckable(True)
        self.action_audio_midi.setChecked(
            bool(port_types_view == (GROUP_CONTEXT_AUDIO
                                     | GROUP_CONTEXT_MIDI)))
        self.action_audio_midi.triggered.connect(
            self.port_types_view_audio_midi_choice)
        
        self.action_audio = self.port_types_menu.addAction(
            _translate('patchbay', 'Audio only'))
        self.action_audio.setCheckable(True)
        self.action_audio.setChecked(port_types_view == GROUP_CONTEXT_AUDIO)
        self.action_audio.triggered.connect(
            self.port_types_view_audio_choice)

        self.action_midi = self.port_types_menu.addAction(
            _translate('patchbay', 'MIDI only'))
        self.action_midi.setCheckable(True)
        self.action_midi.setChecked(port_types_view == GROUP_CONTEXT_MIDI)
        self.action_midi.triggered.connect(
            self.port_types_view_midi_choice)

        self.addMenu(self.port_types_menu)

        self.zoom_menu = QMenu(_translate('patchbay', 'Zoom'))
        self.zoom_menu.setIcon(QIcon.fromTheme('zoom'))

        self.autofit = self.zoom_menu.addAction(
            _translate('patchbay', 'auto-fit'))
        self.autofit.setIcon(QIcon.fromTheme('zoom-select-fit'))
        self.autofit.setShortcut('Home')
        self.autofit.triggered.connect(patchcanvas.canvas.scene.zoom_fit)

        self.zoom_in = self.zoom_menu.addAction(
            _translate('patchbay', 'Zoom +'))
        self.zoom_in.setIcon(QIcon.fromTheme('zoom-in'))
        self.zoom_in.setShortcut('Ctrl++')
        self.zoom_in.triggered.connect(patchcanvas.canvas.scene.zoom_in)

        self.zoom_out = self.zoom_menu.addAction(
            _translate('patchbay', 'Zoom -'))
        self.zoom_out.setIcon(QIcon.fromTheme('zoom-out'))
        self.zoom_out.setShortcut('Ctrl+-')
        self.zoom_out.triggered.connect(patchcanvas.canvas.scene.zoom_out)

        self.zoom_orig = self.zoom_menu.addAction(
            _translate('patchbay', 'Zoom 100%'))
        self.zoom_orig.setIcon(QIcon.fromTheme('zoom'))
        self.zoom_orig.setShortcut('Ctrl+1')
        self.zoom_orig.triggered.connect(patchcanvas.canvas.scene.zoom_reset)

        self.addMenu(self.zoom_menu)

        self.action_refresh = self.addAction(
            _translate('patchbay', "Refresh the canvas"))
        self.action_refresh.setIcon(QIcon.fromTheme('view-refresh'))
        self.action_refresh.triggered.connect(patchbay_manager.refresh)

        self.action_options = self.addAction(
            _translate('patchbay', "Canvas options"))
        self.action_options.setIcon(QIcon.fromTheme("configure"))
        self.action_options.triggered.connect(
            patchbay_manager.show_options_dialog)

    def port_types_view_audio_midi_choice(self):
        self.action_audio_midi.setChecked(True)
        self.action_audio.setChecked(False)
        self.action_midi.setChecked(False)
        
        self.patchbay_manager.change_port_types_view(
            GROUP_CONTEXT_AUDIO | GROUP_CONTEXT_MIDI)
    
    def port_types_view_audio_choice(self):
        self.action_audio_midi.setChecked(False)
        self.action_audio.setChecked(True)
        self.action_midi.setChecked(False)
        self.patchbay_manager.change_port_types_view(
            GROUP_CONTEXT_AUDIO)
    
    def port_types_view_midi_choice(self):
        self.action_audio_midi.setChecked(False)
        self.action_audio.setChecked(False)
        self.action_midi.setChecked(True)
        self.patchbay_manager.change_port_types_view(
            GROUP_CONTEXT_MIDI)

        #act_sel = menu.exec(QCursor.pos())

        #if act_sel == action_fullscreen:
            #self.toggle_full_screen()
        #elif act_sel == action_audio_midi:
            #self.change_port_types_view(
                #GROUP_CONTEXT_AUDIO | GROUP_CONTEXT_MIDI)
        #elif act_sel == action_audio:
            #self.change_port_types_view(GROUP_CONTEXT_AUDIO)
        #elif act_sel == action_midi:
            #self.change_port_types_view(GROUP_CONTEXT_MIDI)
        #elif act_sel == autofit:
            #patchcanvas.canvas.scene.zoom_fit()
        #elif act_sel == zoom_in:
            #patchcanvas.canvas.scene.zoom_in()
        #elif act_sel == zoom_out:
            #patchcanvas.canvas.scene.zoom_out()
        #elif act_sel == zoom_orig:
            #patchcanvas.canvas.scene.zoom_reset()
        #elif act_sel == action_refresh:
            #self.refresh()
        #elif act_sel == action_options:
            #self.show_options_dialog()
