#!/usr/bin/python3 -u


import logging
import os
import signal
import sys
from typing import Optional
import xml.etree.ElementTree as ET
from pathlib import Path
from enum import Enum, auto
import time
import subprocess
import shutil

from nsm_client.osclib import Address, get_free_osc_port, is_osc_port_free
from nsm_client import NsmServer, NsmCallback, Err
from xml_tools import XmlElement
import jacklib


_logger = logging.getLogger(__name__)


def signal_handler(sig, frame):
    if sig in (signal.SIGINT, signal.SIGTERM):
        # general_object.leave()
        main.leaving = True


class SlState(Enum):
    NOT_STARTED_YET = auto()
    STARTED = auto()
    OSC_READY = auto()
    SESSION_LOADED = auto()


class ArgRead(Enum):
    NONE = auto()
    LOG = auto()
    OSC_PORT = auto()


class SlServer(NsmServer):
    def __init__(self, daemon_address: Address):
        super().__init__(daemon_address)
        
        self.wait_pong = False
        self.save_error = False
        self.load_error = False
        
        self.sl_addr = Address(9951)

        self.add_method('/sl_pong', 'ssi', self.sl_pong)
        self.add_method('/sl_save_error', None, self.sl_save_error)
        self.add_method('/sl_load_error', None, self.sl_load_error)

    def sl_pong(self, path: str, args: list, types: str, src_adrr: Address):
        if main.sl_state is SlState.STARTED:
            main.sl_state = SlState.OSC_READY
        
        self.wait_pong = False

    def sl_save_error(
            self, path: str, args: list, types: str, src_adrr: Address):
        self.save_error = True
        
    def sl_load_error(
            self, path: str, args: list, types: str, src_adrr: Address):
        self.load_error = True

    def set_sl_port(self, port: int):
        self.sl_addr = Address(port)
        
    def send_sl(self, *args):
        self.send(self.sl_addr, *args)

class MainObject:
    def __init__(self):
        self.project_path = Path()
        self.full_client_id = 'SooperLooper'
        self.session_file = Path()
        self.session_bak = Path()
        self.midi_bindings_file = Path()
        
        self.jack_follow_naming = False
        self.wanted_osc_port: Optional[int] = None
        
        # self.gui_process = QProcess()
        self.gui_process: Optional[subprocess.Popen] = None

        self.sl_process: Optional[subprocess.Popen] = None
        self.sl_port = 9951
        self.sl_addr = Address(self.sl_port)
        self.sl_state = SlState.NOT_STARTED_YET
        self.not_started_yet = True
        
        self.last_gui_state = False
        self.leaving = False
        
    def sl_running(self) -> bool:
        'return True if sooperlooper process is running, else False'
        if self.sl_process is None:
            return False
        
        return self.sl_process.poll() is None

    def gui_running(self) -> bool:
        'return True if slgui process is running, else False'
        if self.gui_process is None:
            return False
        
        return self.gui_process.poll() is None
    
    def set_sl_port(self, port: int):
        self.sl_port = port
        self.sl_addr = Address(self.sl_port)

main = MainObject()


# class SlOSCThread(NSMThread):
#     def __init__(self, name, signaler, daemon_address, debug):
#         NSMThread.__init__(self, name, signaler, daemon_address, debug)
#         self.sl_is_ready = False

#     @make_method('/pongSL', 'ssi')
#     def pong(self, path, args):
#         self.sl_is_ready = True

#         if general_object.wait_for_load:
#             general_object.sl_ready.emit()


# class GeneralObject(QObject):
#     sl_ready = Signal()

#     def __init__(self, sl_port=None):
#         QObject.__init__(self)

#         self.sl_process = QProcess()
#         self.sl_process.setProcessChannelMode(
#             QProcess.ProcessChannelMode.ForwardedChannels)
#         self.sl_process.finished.connect(self.slProcessFinished)

#         if sl_port is not None:
#             self.sl_port = sl_port
#         else:
#             self.sl_port = ray.get_free_osc_port(9951)

#         self.sl_url = Address(self.sl_port)

#         self.gui_process = QProcess()
#         self.gui_process.setProcessChannelMode(
#             QProcess.ProcessChannelMode.ForwardedChannels)
#         self.gui_process.started.connect(self.guiProcessStarted)
#         self.gui_process.finished.connect(self.guiProcessFinished)

#         self.project_path = Path()
#         self.full_client_id = ''
#         self.session_file = Path()
#         self.session_bak = Path()
#         self.midi_bindings_file = Path()

#         self.file_timer = QTimer()
#         self.file_timer.setInterval(100)
#         self.file_timer.timeout.connect(self.checkFile)
#         self.n_file_timer = 0

#         signaler.server_sends_open.connect(self.initialize)
#         signaler.server_sends_save.connect(self.saveSlSession)
#         signaler.show_optional_gui.connect(self.showOptionalGui)
#         signaler.hide_optional_gui.connect(self.hideOptionalGui)

#         self.sl_ready.connect(self.loadSession)

#         self._switching = False
#         self.leaving = False
#         self.wait_for_load = False

#         self.ping_timer = QTimer()
#         self.ping_timer.setInterval(100)
#         self.ping_timer.timeout.connect(self.pingSL)
#         self.ping_timer.start()

#         self.transport_timer = QTimer()
#         self.transport_timer.setInterval(2)
#         self.transport_timer.timeout.connect(self.checkTransport)

#         self.transport_playing = False
#         self.will_trig = False
        
#         self.jack_follow_naming = False

#     def JackShutdownCallback(self, arg=None):
#         self.transport_timer.stop()
#         return 0

#     def checkTransport(self):
#         pos = jacklib.jack_position_t()
#         pos.valid = 0

#         state = jacklib.transport_query(jack_client, jacklib.pointer(pos))

#         if self.will_trig:
#             if pos.beat == pos.beats_per_bar:
#                 if (pos.ticks_per_beat - pos.tick) <= 4:
#                     # we are at 4 ticks or less from next bar (arbitrary)
#                     # so we send a trig message to sooperlooper.
#                     server.send(self.sl_url, '/sl/-1/hit', 'trigger')
#                     self.will_trig = False
#                     return

#         if (self.transport_playing
#                 and state == jacklib.JackTransportStopped):
#             if self.will_trig:
#                 self.will_trig = False
#             else:
#                 server.send(self.sl_url, '/sl/-1/hit', 'pause_on')

#             self.transport_playing = False

#         elif (not self.transport_playing
#               and state == jacklib.JackTransportRolling):
#             if pos.beat == 1 and pos.tick == 0:
#                 server.send(self.sl_url, '/sl/-1/hit', 'trigger')

#             else:
#                 self.will_trig = True

#             self.transport_playing = True

#     def pingSL(self):
#         if server.sl_is_ready:
#             self.ping_timer.stop()
#         else:
#             server.send(self.sl_url, '/ping', server.url, '/pongSL')

#     def leave(self):
#         self.leaving = True
        
#         if QT5:
#             if self.gui_process.state():
#                 self.gui_process.terminate()
#             else:
#                 if self.sl_process.state():
#                     server.send(self.sl_url, '/quit')
#                 else:
#                     app.quit()
#             return

#         if self.gui_process.state() is QProcess.ProcessState.NotRunning:
#             if self.sl_process.state() is QProcess.ProcessState.NotRunning:
#                 app.quit()
#             else:
#                 server.send(self.sl_url, '/quit')
#         else:
#             self.gui_process.terminate()

#     def isGuiShown(self):
#         return bool(self.sl_process.state() == QProcess.ProcessState.Running)

#     def slProcessFinished(self, exit_code):
#         if not self._switching:
#             app.quit()

#     def guiProcessStarted(self):
#         server.sendGuiState(True)

#     def guiProcessFinished(self, exit_code):
#         if self.leaving:
#             if self.sl_process.state():
#                 server.send(self.sl_url, '/quit')
#             else:
#                 app.quit()

#         server.sendGuiState(False)

#     def startFileChecker(self):
#         self.n_file_timer = 0

#         if self.session_file.exists():
#             self.stopFileChecker()
#             return

#         self.file_timer.start()

#     def stopFileChecker(self):
#         self.n_file_timer = 0
#         self.file_timer.stop()

#         self.xml_correction()

#         server.saveReply()

#     def checkFile(self):
#         if self.n_file_timer > 200: #more than 20 second
#             self.stopFileChecker()
#             return

#         if self.session_file.exists():
#             self.stopFileChecker()
#             return

#         self.n_file_timer += 1

#     def xml_correction(self):
#         try:
#             tree = ET.parse(self.session_file)
#             root = tree.getroot()
#         except:
#             _logger.warning(f'Failed to modify XML file {self.session_file}')
#             return
        
#         if root.tag != 'SLSession':
#             return
        
#         for child in root:
#             if child.tag != 'Loopers':
#                 continue
            
#             for c_child in child:
#                 if c_child.tag != 'Looper':
#                     continue
                
#                 xc_child = XmlElement(c_child)
#                 audio_file_name = Path(xc_child.str('loop_audio'))
#                 if audio_file_name.is_relative_to(self.project_path):
#                     xc_child.set_str(
#                         'loop_audio',
#                         audio_file_name.relative_to(self.project_path))
                    
#         try:
#             tree.write(self.session_file)
#         except:
#             _logger.warning(
#                 f'Failed to save audio files in {self.session_file}')

#     def initialize(
#             self, project_path: str, session_name: str, full_client_id: str):
#         self.project_path = Path(project_path)
#         self.session_file = self.project_path / 'session.slsess'
#         self.session_bak = self.project_path / 'session.slsess.bak'
#         self.midi_bindings_file = self.project_path / 'session.slb'

#         if not self.jack_follow_naming:
#             full_client_id = 'sooperlooper'

#         if full_client_id != self.full_client_id:
#             self.full_client_id = full_client_id

#             if self.gui_process.state():
#                 self.gui_process.terminate()
#                 self.gui_process.waitForFinished(500)
#             else:
#                 server.sendGuiState(False)
            
#             self._switching = True
            
#             if self.sl_process.state():
#                 self.sl_process.terminate()
#                 self.sl_process.waitForFinished(500)
            
#             self._switching = False
            
#             self.sl_process.start(
#                 'sooperlooper',
#                 ['-p', str(self.sl_port), '-j', self.full_client_id])

#         self.project_path.mkdir(parents=True, exist_ok=True)

#         os.chdir(self.project_path)

#         if server.sl_is_ready:
#             self.loadSession()
            
#         else:
#             self.wait_for_load = True

#         if jack_client:
#             self.transport_timer.start()

#     def loadSession(self):
#         #self.sl_process.start('sooperlooper', ['-p', str(self.sl_port)])
#         self.wait_for_load = False
#         server.send(
#             self.sl_url, '/load_session', str(self.session_file),
#             server.url, '/re-load')
#         server.send(
#             self.sl_url, '/load_midi_bindings',
#             str(self.midi_bindings_file), '')

#         if jack_client is not None:
#             server.send(self.sl_url, '/set', 'sync_source', -1.0)
#             server.send(self.sl_url, '/set', 'eighth_per_cycle', 8.0)
#             server.send(self.sl_url, '/sl/0/set,' 'quantize', 1.0)
#         server.openReply()

#     def saveSlSession(self):
#         self.session_bak.unlink(missing_ok=True)

#         if self.session_file.exists():
#             self.session_file.rename(self.session_bak)

#         server.send(self.sl_url, '/save_session', str(self.session_file),
#                     server.url, '/re-save', 1)

#         server.send(self.sl_url, '/save_midi_bindings',
#                     str(self.midi_bindings_file), '')

#         self.startFileChecker()

#     def showOptionalGui(self):
#         if QT5:
#             if not self.gui_process.state():
#                 self.gui_process.start('slgui', ['-P', str(self.sl_port)])
#         else:
#             if self.gui_process.state() is QProcess.ProcessState.NotRunning:
#                 self.gui_process.start('slgui', ['-P', str(self.sl_port)]) 

#     def hideOptionalGui(self):
#         if QT5:
#             if self.gui_process.state():
#                 self.gui_process.terminate()
#         else:
#             if (self.gui_process.state()
#                     is not QProcess.ProcessState.NotRunning):
#                 self.gui_process.terminate()




def xml_correction():
    try:
        tree = ET.parse(main.session_file)
        root = tree.getroot()
    except:
        _logger.warning(f'Failed to modify XML file {main.session_file}')
        return
    
    if root.tag != 'SLSession':
        return
    
    for child in root:
        if child.tag != 'Loopers':
            continue
        
        for c_child in child:
            if c_child.tag != 'Looper':
                continue
            
            xc_child = XmlElement(c_child)
            audio_file_name = Path(xc_child.str('loop_audio'))
            if main.project_path in audio_file_name.parents:
                xc_child.set_str(
                    'loop_audio',
                    audio_file_name.relative_to(main.project_path))
                
    try:
        tree.write(main.session_file)
    except:
        _logger.warning(
            f'Failed to save audio files in {main.session_file}')



def open_file(
        project_path: str, session_name: str,
        full_client_id: str) -> tuple[Err, str]:
    main.project_path = Path(project_path)
    main.session_file = main.project_path / 'session.slsess'
    main.session_bak = main.project_path / 'session.slsess.bak'
    main.midi_bindings_file = main.project_path / 'session.slb'

    # if not main.jack_follow_naming:
    #     full_client_id = 'sooperlooper'

    main.full_client_id = full_client_id

    # STOP GUI
    if main.gui_running():
        main.gui_process.terminate()
    
    # STOP sooperlooper
    if main.sl_running():
        nsm_server.send_sl('/quit')
        
        for i in range(100):
            time.sleep(0.050)
            if main.sl_process.poll() is not None:
                break
            
            if main.leaving:
                break
            
        if main.sl_process.poll() is None:
            main.sl_process.terminate()
            for i in range(100):
                time.sleep(0.050)
                if main.sl_process.poll() is not None:
                    break
                
                if main.leaving:
                    break
    
    # create project folder and go inside
    # it is required to save audio files correctly
    try:
        main.project_path.mkdir(parents=True, exist_ok=True)
        os.chdir(main.project_path)
    except:
        return Err.CREATE_FAILED, f'Impossible to create {main.project_path}'
    
    if main.wanted_osc_port is not None:
        if is_osc_port_free(main.wanted_osc_port):
            main.set_sl_port(main.wanted_osc_port)
        else:
            main.leaving = True
            return (Err.LAUNCH_FAILED,
                    f'Wanted OSC port {main.wanted_osc_port} is busy')

    else:
        main.set_sl_port(get_free_osc_port(main.sl_port))
        nsm_server.set_sl_port(get_free_osc_port(main.sl_port))
    
    # START sooperlooper
    try:
        main.sl_process = subprocess.Popen(
            ['sooperlooper',
             '-p', str(main.sl_port), '-j', main.full_client_id])
    except BaseException as e:
        return Err.LAUNCH_FAILED, 'failed to start sooperlooper'
        
    main.sl_state = SlState.STARTED
    
    # PING sooperlooper until it is ready to communicate
    pong_ok = False
    nsm_server.wait_pong = True

    for i in range(1000):
        nsm_server.send_sl('/ping', nsm_server.url, '/sl_pong')
        nsm_server.recv(10)
        
        if not nsm_server.wait_pong:
            pong_ok = True
            break
        
        if not main.sl_running():
            break
        
        if main.leaving:
            break

    if not pong_ok:
        return (
            Err.LAUNCH_FAILED,
            'Failed to launch sooperlooper, or fail to communicate with it')

    # LOAD midi bindings
    if main.midi_bindings_file.exists():
        nsm_server.send_sl(
            '/load_midi_bindings', str(main.midi_bindings_file), '')

    # LOAD project
    if main.session_file.exists():
        nsm_server.load_error = False
        nsm_server.send_sl(
            '/load_session', str(main.session_file),
            nsm_server.url, '/sl_load_error')
        
        # Wait 500ms for an error loading project
        # Unfortunately, sooperlooper replies only if there is an error.
        for i in range(10):
            nsm_server.recv(50)
            if nsm_server.load_error:
                return Err.BAD_PROJECT, 'Session Failed to load'
            
            if main.leaving:
                return Err.LAUNCH_FAILED, 'leaving process'

    # if jack_client:
    #     self.transport_timer.start()
    main.not_started_yet = False
        
    return Err.OK, f'Session {main.session_file} loaded'

def save_file():
    main.session_bak.unlink(missing_ok=True)

    if main.session_file.exists():
        main.session_file.rename(main.session_bak)

    nsm_server.send_sl('/save_midi_bindings', str(main.midi_bindings_file), '')

    nsm_server.save_error = False
    nsm_server.send_sl(
        '/save_session', str(main.session_file),
        nsm_server.url, '/sl_save_error', 1)
    
    for i in range(200):
        nsm_server.recv(50)
        if nsm_server.save_error:
            return Err.BAD_PROJECT, f'Failed to save {main.session_file}'
        
        if main.session_file.exists():
            break
        
        if main.leaving:
            return Err.CREATE_FAILED, 'Quitting program'

    if not main.session_file.exists():
        return Err.BAD_PROJECT, f'{main.session_file} has not been saved'

    xml_correction()

    return (Err.OK, f'Session {main.session_file} saved')

def show_optional_gui():
    if not main.gui_running():
        main.gui_process = subprocess.Popen(
            ['slgui', '-P', str(main.sl_port)])
    nsm_server.send_gui_state(True)
    
def hide_optional_gui():
    if main.gui_running():
        main.gui_process.terminate()
    nsm_server.send_gui_state(False)

def run():
    global nsm_server

    if not shutil.which('sooperlooper'):
        _logger.critical('SooperLooper is not installed.')
        sys.exit(1)

    # set log level and other parameters with exec arguments
    if len(sys.argv) > 1:
        arg_read = ArgRead.NONE
        log_level = logging.WARNING

        for arg in sys.argv[1:]:
            if arg in ('-log', '--log'):
                arg_read = ArgRead.LOG
                log_level = logging.DEBUG
            elif arg in ('-osc-port', '--osc-port'):
                arg_read = ArgRead.OSC_PORT
            else:
                if arg_read is ArgRead.LOG:
                    if arg.isdigit():
                        log_level = int(uarg)
                    else:
                        uarg = arg.upper()
                        if (uarg in logging.__dict__.keys()
                                and isinstance(logging.__dict__[uarg], int)):
                            log_level = logging.__dict__[uarg]
                
                elif arg_read is ArgRead.OSC_PORT:
                    if arg.isdigit():
                        main.wanted_osc_port = int(arg)

                arg_read = ArgRead.NONE

        _logger.setLevel(log_level)
    
    nsm_url = os.getenv('NSM_URL')
    if not nsm_url:
        _logger.error('Could not register as NSM client.')
        sys.exit(1)
    
    try:
        daemon_address = Address(nsm_url)
    except:
        _logger.error('NSM_URL seems to be invalid.')
        sys.exit(1)
        
    nsm_server = SlServer(daemon_address)
    nsm_server.set_callback(NsmCallback.OPEN, open_file)
    nsm_server.set_callback(NsmCallback.SAVE, save_file)
    nsm_server.set_callback(NsmCallback.SHOW_OPTIONAL_GUI, show_optional_gui)
    nsm_server.set_callback(NsmCallback.HIDE_OPTIONAL_GUI, hide_optional_gui)
    nsm_server.announce(
        'SooperLooper', ':optional-gui:switch:', Path(sys.argv[0]).name)
    
    # connect program interruption signals
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # main loop
    while True:
        if main.leaving:
            break

        nsm_server.recv(50)
        
        if main.last_gui_state is not main.gui_running():
            main.last_gui_state = main.gui_running()
            nsm_server.send_gui_state(main.last_gui_state)

        if not main.not_started_yet:
            if not main.sl_running():
                break

    # QUIT
    
    # stop GUI
    if main.gui_running():
        main.gui_process.terminate()

    # stop sooperlooper
    if main.sl_running():
        nsm_server.send_sl('/quit')  
        for i in range(1000):
            time.sleep(0.0010)
            if not main.sl_running():
                break
        
        if main.sl_running():
            main.sl_process.terminate()
            for i in range(1000):
                time.sleep(0.0010)
                if not main.sl_running():
                    break

            if main.sl_running():
                main.sl_process.kill()

    sys.exit(0)


if __name__ == '__main__':
    run()
    # NSM_URL = os.getenv('NSM_URL')
    # if not NSM_URL:
    #     sys.stderr.write('Could not register as NSM client.\n')
    #     sys.exit()

    # daemon_address = ray.get_liblo_address(NSM_URL)

    # signal.signal(signal.SIGINT, signal_handler)
    # signal.signal(signal.SIGTERM, signal_handler)

    # app = QCoreApplication(sys.argv)
    # app.setApplicationName("SooperLooperNSM")
    # app.setOrganizationName("SooperLooperNSM")

    # timer = QTimer()
    # timer.setInterval(200)
    # timer.timeout.connect(lambda: None)
    # timer.start()

    # signaler = NSMSignaler()

    # server = SlOSCThread('sooperlooper_nsm', signaler, daemon_address, False)

    # if len(sys.argv) > 1 and '--transport_workaround' in sys.argv[1:]:
    #     jack_client = jacklib.client_open(
    #         "sooper_ray_wk",
    #         jacklib.JackNoStartServer | jacklib.JackSessionID,
    #         None)
    # else:
    #     jack_client = None

    # sl_port = None
    # if len(sys.argv) > 1 and '--osc-port' in sys.argv[1:]:
    #     port_index = sys.argv.index('--osc-port')
    #     if len(sys.argv) > port_index + 1 and sys.argv[port_index + 1].isdigit():
    #         sl_port = int(sys.argv[port_index + 1])

    # general_object = GeneralObject(sl_port=sl_port)
    # if "--follow-jack-naming" in sys.argv[1:]:
    #     general_object.jack_follow_naming = True

    # server.start()
    
    # capabilities = ':optional-gui:switch:'
    # server.announce('SooperLooper', capabilities, 'sooperlooper_nsm')

    # app.exec()

    # server.stop()

    # del server
    # del app
