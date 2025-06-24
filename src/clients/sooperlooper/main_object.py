from pathlib import Path
from typing import TYPE_CHECKING, Optional
import subprocess
import xml.etree.ElementTree as ET
import logging
import time
import os
import signal

from xml_tools import XmlElement
from nsm_client import Err
from osclib import is_osc_port_free, get_free_osc_port

if TYPE_CHECKING:
    import jack
    from .sl_server import SlServer

_logger = logging.getLogger(__name__)


class MainObject:
    def __init__(self):
        self.jack_client: 'Optional[jack.Client]' = None
        self.nsm_server: 'Optional[SlServer]' = None
        
        self.project_path = Path()
        self.full_client_id = 'SooperLooper'
        self.session_file = Path()
        self.session_bak = Path()
        self.midi_bindings_file = Path()
        
        self.follow_jack_naming = False
        self.wanted_osc_port: Optional[int] = None
        
        self.gui_process: Optional[subprocess.Popen] = None
        self.sl_process: Optional[subprocess.Popen] = None
        self.sl_port = 9951
        self.not_started_yet = True
        
        self.last_gui_state = False
        self.leaving = False
        
        # for transport workaround
        self.transport_wk = False
        self.transport_playing = False
        self.will_trig = False
    
    @property
    def sl_running(self) -> bool:
        'Is True if sooperlooper process is running, else False'
        if self.sl_process is None:
            return False
        
        return self.sl_process.poll() is None

    @property
    def gui_running(self) -> bool:
        'Is True if slgui process is running, else False'
        if self.gui_process is None:
            return False
        
        return self.gui_process.poll() is None

    def check_transport(self):
        if self.jack_client is None:
            return

        # if this method is called, it means jack is already imported.
        if TYPE_CHECKING:
            import jack

        state, pos_dict = self.jack_client.transport_query()

        try:
            assert pos_dict.get('beat') is not None
        except:
            return

        if self.will_trig:
            if pos_dict['beat'] == pos_dict['beats_per_bar']:
                if (pos_dict['ticks_per_beat'] - pos_dict['tick']) <= 4:
                    # we are at 4 ticks or less from next bar (arbitrary)
                    # so we send a trig message to sooperlooper.
                    self.nsm_server.send_sl('/sl/-1/hit', 'trigger')
                    self.will_trig = False
                    return

        if (self.transport_playing and state == jack.STOPPED):
            if self.will_trig:
                self.will_trig = False
            else:
                self.nsm_server.send_sl('/sl/-1/hit', 'pause_on')

            self.transport_playing = False

        elif (not self.transport_playing and state == jack.ROLLING):
            if pos_dict['beat'] == 1 and pos_dict['tick'] == 0:
                self.nsm_server.send_sl('/sl/-1/hit', 'trigger')

            else:
                self.will_trig = True

            self.transport_playing = True

    def xml_correction(self):
        '''Rewrite the sooperlooper session file to include audio files'''
        try:
            tree = ET.parse(self.session_file)
            root = tree.getroot()
        except:
            _logger.warning(f'Failed to modify XML file {self.session_file}')
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
                if self.project_path in audio_file_name.parents:
                    xc_child.set_str(
                        'loop_audio',
                        audio_file_name.relative_to(self.project_path))
                    
        try:
            tree.write(self.session_file)
        except:
            _logger.warning(
                f'Failed to save audio files in {self.session_file}')

    def open_file(
            self, project_path: str, session_name: str,
            full_client_id: str) -> tuple[Err, str]:
        self.project_path = Path(project_path)
        self.session_file = self.project_path / 'session.slsess'
        self.session_bak = self.project_path / 'session.slsess.bak'
        self.midi_bindings_file = self.project_path / 'session.slb'

        if not self.follow_jack_naming:
            full_client_id = 'sooperlooper'

        self.full_client_id = full_client_id

        # STOP GUI
        if self.gui_running:
            self.gui_process.terminate()
        
        # STOP sooperlooper
        if self.sl_running:
            self.nsm_server.send_sl('/quit')
            
            for i in range(100):
                time.sleep(0.050)
                if self.sl_process.poll() is not None:
                    break
                
                if self.leaving:
                    break
                
            if self.sl_process.poll() is None:
                self.sl_process.terminate()
                for i in range(100):
                    time.sleep(0.050)
                    if self.sl_process.poll() is not None:
                        break
                    
                    if self.leaving:
                        break
        
        # create project folder and go inside
        # it is required to save audio files correctly
        try:
            self.project_path.mkdir(parents=True, exist_ok=True)
            os.chdir(self.project_path)
        except:
            return Err.CREATE_FAILED, f'Impossible to create {self.project_path}'
        
        if self.wanted_osc_port is not None:
            if is_osc_port_free(self.wanted_osc_port):
                self.nsm_server.set_sl_port(self.wanted_osc_port)
            else:
                self.leaving = True
                return (Err.LAUNCH_FAILED,
                        f'Wanted OSC port {self.wanted_osc_port} is busy')

        else:
            self.nsm_server.set_sl_port(get_free_osc_port(self.sl_port))
        
        # START sooperlooper
        try:
            self.sl_process = subprocess.Popen(
                ['sooperlooper',
                '-p', str(self.nsm_server.sl_addr.port), '-j', self.full_client_id])
        except BaseException as e:
            return Err.LAUNCH_FAILED, 'failed to start sooperlooper'
        
        # PING sooperlooper until it is ready to communicate
        pong_ok = False
        self.nsm_server.wait_pong = True

        for i in range(1000):
            self.nsm_server.send_sl('/ping', self.nsm_server.url, '/sl_pong')
            self.nsm_server.recv(10)
            
            if not self.nsm_server.wait_pong:
                pong_ok = True
                break
            
            if not self.sl_running:
                break
            
            if self.leaving:
                break

        if not pong_ok:
            return (
                Err.LAUNCH_FAILED,
                'Failed to launch sooperlooper, or fail to communicate with it')

        # LOAD midi bindings
        if self.midi_bindings_file.exists():
            self.nsm_server.send_sl(
                '/load_midi_bindings', str(self.midi_bindings_file), '')

        # LOAD project
        if self.session_file.exists():
            self.nsm_server.load_error = False
            self.nsm_server.send_sl(
                '/load_session', str(self.session_file),
                self.nsm_server.url, '/sl_load_error')
            
            # Wait 500ms for an error loading project
            # Unfortunately, sooperlooper replies only if there is an error.
            for i in range(10):
                self.nsm_server.recv(50)
                if self.nsm_server.load_error:
                    return Err.BAD_PROJECT, 'Session Failed to load'
                
                if self.leaving:
                    return Err.LAUNCH_FAILED, 'leaving process'

        # if jack_client:
        #     self.transport_timer.start()
        self.not_started_yet = False
            
        return Err.OK, f'Session {self.session_file} loaded'

    def save_file(self):
        self.session_bak.unlink(missing_ok=True)

        if self.session_file.exists():
            self.session_file.rename(self.session_bak)

        self.nsm_server.send_sl(
            '/save_midi_bindings', str(self.midi_bindings_file), '')

        self.nsm_server.save_error = False
        self.nsm_server.send_sl(
            '/save_session', str(self.session_file),
            self.nsm_server.url, '/sl_save_error', 1)
        
        for i in range(200):
            self.nsm_server.recv(50)
            if self.nsm_server.save_error:
                return Err.BAD_PROJECT, f'Failed to save {self.session_file}'
            
            if self.session_file.exists():
                break
            
            if self.leaving:
                return Err.CREATE_FAILED, 'Quitting program'

        if not self.session_file.exists():
            return Err.BAD_PROJECT, f'{self.session_file} has not been saved'

        self.xml_correction()

        return (Err.OK, f'Session {self.session_file} saved')

    def show_optional_gui(self):
        if not self.gui_running:
            self.gui_process = subprocess.Popen(
                ['slgui', '-P', str(self.nsm_server.sl_addr.port)])
        self.nsm_server.send_gui_state(True)
        
    def hide_optional_gui(self):
        if self.gui_running:
            self.gui_process.terminate()
        self.nsm_server.send_gui_state(False)
        
    def signal_handler(self, sig, frame):
        if sig in (signal.SIGINT, signal.SIGTERM):
            self.leaving = True