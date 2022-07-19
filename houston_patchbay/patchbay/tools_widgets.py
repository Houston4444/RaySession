
import os
from typing import TYPE_CHECKING

from PyQt5.QtCore import pyqtSignal, QTimer, QLocale, QUrl
from PyQt5.QtGui import QIcon, QDesktopServices, QPalette
from PyQt5.QtWidgets import QWidget, QMenu, QApplication, QDialog

from .patchcanvas import patchcanvas
from .base_elements import JackPortFlag, Port, PortType

from .ui.canvas_port_info import Ui_CanvasPortInfo as PortInfoUiDialog
from .ui.patchbay_tools import Ui_Form as PatchbayToolsUiForm

if TYPE_CHECKING:
    from .patchbay_manager import PatchbayManager


# Port Type
PORT_TYPE_NULL = 0
PORT_TYPE_AUDIO = 1
PORT_TYPE_MIDI = 2

_translate = QApplication.translate

def is_dark_theme(widget: QWidget) -> bool:
    return bool(
        widget.palette().brush(
            QPalette.Active, QPalette.WindowText).color().lightness()
        > 128)

def get_code_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.realpath(__file__))))


class PatchbayToolsWidget(QWidget):
    buffer_size_change_order = pyqtSignal(int)

    def __init__(self):
        QWidget.__init__(self)
        self.ui = PatchbayToolsUiForm()
        self.ui.setupUi(self)

        if is_dark_theme(self):
            self.ui.sliderZoom.setStyleSheet(
                self.ui.sliderZoom.styleSheet().replace('/breeze/', '/breeze-dark/'))

        self._waiting_buffer_change = False
        self._buffer_change_from_osc = False

        self.ui.sliderZoom.valueChanged.connect(self.set_zoom)

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

    def zoom_changed_from_canvas(self, ratio):
        self.ui.sliderZoom.set_percent(ratio * 100)

    def set_zoom(self, value):
        percent = self.ui.sliderZoom.zoom_percent()
        patchcanvas.canvas.scene.zoom_ratio(percent)

    def set_samplerate(self, samplerate: int):
        str_sr = str(samplerate)
        str_samplerate = str_sr
        
        # separate the three last digits from begin with a space
        # 48000 -> 48 000
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
        QTimer.singleShot(10000, self._re_enable_buffer_combobox)

    def _re_enable_buffer_combobox(self):
        if self._waiting_buffer_change:
            self.set_buffer_size(self.current_buffer_size)

    def set_jack_running(self, yesno: bool):
        for widget in (
                self.ui.sliderZoom,
                self.ui.labelSamplerate,
                self.ui.labelSamplerateUnits,
                self.ui.labelBuffer,
                self.ui.comboBoxBuffer,
                self.ui.pushButtonXruns,
                self.ui.progressBarDsp,
                self.ui.lineSep1,
                self.ui.lineSep2,
                self.ui.lineSep3):
            widget.setVisible(yesno)

        self.ui.labelJackNotStarted.setVisible(not yesno)
        if yesno:
            patchcanvas.canvas.scene.scale_changed.connect(
                self.zoom_changed_from_canvas)
            self.ui.sliderZoom.zoom_fit_asked.connect(
                patchcanvas.canvas.scene.zoom_fit)


class CanvasMenu(QMenu):
    def __init__(self, patchbay_manager: 'PatchbayManager'):
        QMenu.__init__(self, _translate('patchbay', 'Patchbay'))
        self.patchbay_manager = patchbay_manager

        # fix wrong menu position with Wayland,
        # see https://community.kde.org/Guidelines_and_HOWTOs/Wayland_Porting_Notes
        self.winId()
        main_win = self.patchbay_manager.main_win
        main_win.winId()
        parent_window_handle = main_win.windowHandle()
        if not parent_window_handle:
            native_parent_widget = main_win.nativeParentWidget()
            if native_parent_widget:
                parent_window_handle = native_parent_widget.windowHandle()
        self.windowHandle().setTransientParent(parent_window_handle)

        self.patchbay_manager.sg.port_types_view_changed.connect(
            self._port_types_view_changed)

        self.action_fullscreen = self.addAction(
            _translate('patchbay', "Toggle Full Screen"))
        self.action_fullscreen.setIcon(QIcon.fromTheme('view-fullscreen'))
        self.action_fullscreen.triggered.connect(
            patchbay_manager.sg.full_screen_toggle_wanted.emit)

        port_types_view = patchbay_manager.port_types_view & (
            PortType.AUDIO_JACK | PortType.MIDI_JACK)

        self.action_find_box = self.addAction(
            _translate('patchbay', "Find a box...\tCtrl+F"))
        self.action_find_box.setIcon(QIcon.fromTheme('edit-find'))
        self.action_find_box.triggered.connect(
            patchbay_manager.sg.filters_bar_toggle_wanted.emit)

        self.port_types_menu = QMenu(_translate('patchbay', 'Type filter'), self)
        self.port_types_menu.setIcon(QIcon.fromTheme('view-filter'))
        self.action_audio_midi = self.port_types_menu.addAction(
            _translate('patchbay', 'Audio + Midi'))
        self.action_audio_midi.setCheckable(True)
        self.action_audio_midi.setChecked(
            bool(port_types_view == (PortType.AUDIO_JACK
                                     | PortType.MIDI_JACK)))
        self.action_audio_midi.triggered.connect(
            self.port_types_view_audio_midi_choice)

        self.action_audio = self.port_types_menu.addAction(
            _translate('patchbay', 'Audio only'))
        self.action_audio.setCheckable(True)
        self.action_audio.setChecked(port_types_view == PortType.AUDIO_JACK)
        self.action_audio.triggered.connect(
            self.port_types_view_audio_choice)

        self.action_midi = self.port_types_menu.addAction(
            _translate('patchbay', 'MIDI only'))
        self.action_midi.setCheckable(True)
        self.action_midi.setChecked(port_types_view == PortType.MIDI_JACK)
        self.action_midi.triggered.connect(
            self.port_types_view_midi_choice)

        self.addMenu(self.port_types_menu)

        self.zoom_menu = QMenu(_translate('patchbay', 'Zoom'), self)
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

        self.action_manual = self.addAction(
            _translate('patchbay', "Patchbay manual"))
        self.action_manual.setIcon(QIcon.fromTheme('system-help'))
        self.action_manual.triggered.connect(self.internal_manual)
        self.action_manual.setVisible(False)

        self.action_options = self.addAction(
            _translate('patchbay', "Canvas options"))
        self.action_options.setIcon(QIcon.fromTheme("configure"))
        self.action_options.triggered.connect(
            patchbay_manager.show_options_dialog)

    def _port_types_view_changed(self, port_types_view: int):
        self.action_audio_midi.setChecked(
            port_types_view == PortType.AUDIO_JACK | PortType.MIDI_JACK)
        self.action_audio.setChecked(
            port_types_view == PortType.AUDIO_JACK)
        self.action_midi.setChecked(
            port_types_view == PortType.MIDI_JACK)

    def port_types_view_audio_midi_choice(self):
        self.patchbay_manager.change_port_types_view(
            PortType.AUDIO_JACK | PortType.MIDI_JACK)

    def port_types_view_audio_choice(self):
        self.patchbay_manager.change_port_types_view(
            PortType.AUDIO_JACK)

    def port_types_view_midi_choice(self):
        self.patchbay_manager.change_port_types_view(
            PortType.MIDI_JACK)

    def internal_manual(self):
        pass


class CanvasPortInfoDialog(QDialog):
    def __init__(self, parent):
        QDialog.__init__(self, parent)
        self.ui = PortInfoUiDialog()
        self.ui.setupUi(self)

        self._port = None
        self.ui.toolButtonRefresh.clicked.connect(
            self.update_contents)

    def set_port(self, port: Port):
        self._port = port
        self.update_contents()

    def update_contents(self):
        if self._port is None:
            return

        port_type_str = _translate('patchbay', "Audio")
        if self._port.type == PORT_TYPE_MIDI:
            port_type_str = _translate('patchbay', "MIDI")

        flags_list = list[str]()

        dict_flag_str = {
            JackPortFlag.IS_INPUT: _translate('patchbay', 'Input'),
            JackPortFlag.IS_OUTPUT: _translate('patchbay', 'Output'),
            JackPortFlag.IS_PHYSICAL: _translate('patchbay', 'Physical'),
            JackPortFlag.CAN_MONITOR: _translate('patchbay', 'Monitor'),
            JackPortFlag.IS_TERMINAL: _translate('patchbay', 'Terminal'),
            JackPortFlag.IS_CONTROL_VOLTAGE: _translate('patchbay', 'Control Voltage')}

        for key in dict_flag_str.keys():
            if self._port.flags & key:
                flags_list.append(dict_flag_str[key])

        port_flags_str = ' | '.join(flags_list)

        self.ui.lineEditFullPortName.setText(self._port.full_name)
        self.ui.lineEditUuid.setText(str(self._port.uuid))
        self.ui.labelPortType.setText(port_type_str)
        self.ui.labelPortFlags.setText(port_flags_str)
        self.ui.labelPrettyName.setText(self._port.pretty_name)
        self.ui.labelPortOrder.setText(str(self._port.order))
        self.ui.labelPortGroup.setText(self._port.mdata_portgroup)

        self.ui.groupBoxMetadatas.setVisible(bool(
            self._port.pretty_name
            or self._port.order is not None
            or self._port.mdata_portgroup))

