
import logging
import os
from typing import TYPE_CHECKING
from pathlib import Path
import sys

from patch_engine import PatchEngineOuter
from patshared import TransportPosition, PortType

import osc_paths.ray.patchbay.monitor as rpm


if TYPE_CHECKING:
    from osc_server import PatchbayDaemonServer


_logger = logging.getLogger(__name__)

EXISTENCE_PATH = Path('/tmp/RaySession/patchbay_daemons')
JACK_CLIENT_NAME = 'ray-patch_dmn'


class RayPatchEngineOuter(PatchEngineOuter):
    def __init__(self, osc_server: 'PatchbayDaemonServer'):
        super().__init__()
        self.osc_server = osc_server
        self.daemon_port = osc_server.daemon_port
    
    @property
    def can_leave(self) -> bool:
        return self.osc_server.can_leave
    
    def write_existence_file(self):
        EXISTENCE_PATH.mkdir(parents=True, exist_ok=True)
        
        try:
            with open(EXISTENCE_PATH / str(self.daemon_port), 'w') as file:
                contents = f'pid:{os.getpid()}\nport:{self.osc_server.port}\n'
                file.write(contents)

        except PermissionError:
            _logger.critical('no permission for existence file')

    def remove_existence_file(self):
        existence_path = EXISTENCE_PATH / str(self.daemon_port)
        if not existence_path.exists():
            return 

        try:
            existence_path.unlink()
        except PermissionError:
            sys.stderr.write(
                f'{JACK_CLIENT_NAME}: Error, '
                f'unable to remove {existence_path}\n')
    
    def is_now_ready(self):
        self.osc_server.set_ready_for_daemon()
    
    def associate_client_name_and_uuid(self, client_name: str, uuid: int):
        self._send_gui(rpm.CLIENT_NAME_AND_UUID, client_name, uuid)

    def port_added(
            self, pname: str, ptype: PortType, pflags: int, puuid: int):
        self._send_gui(rpm.PORT_ADDED, pname, ptype.value, pflags, puuid) 

    def port_renamed(self, ex_name: str, new_name: str, uuid=0):
        if uuid:
            self._send_gui(rpm.PORT_RENAMED, ex_name, new_name, uuid)
        else:
            self._send_gui(rpm.PORT_RENAMED, ex_name, new_name)
    
    def port_removed(self, port_name: str):
        self._send_gui(rpm.PORT_REMOVED, port_name)
    
    def jack_client_added(self, client_name: str):
        self._send_gui(rpm.JACK_CLIENT_ADDED, client_name)
        
    def jack_client_removed(self, client_name: str):
        self._send_gui(rpm.JACK_CLIENT_REMOVED, client_name)
    
    def alsa_client_added(self, client_name: str):
        self._send_gui(rpm.ALSA_CLIENT_ADDED, client_name)
        
    def alsa_client_removed(self, client_name: str):
        self._send_gui(rpm.ALSA_CLIENT_REMOVED, client_name)
    
    def metadata_updated(self, uuid: int, key: str, value: str):
        self._send_gui(rpm.METADATA_UPDATED, uuid, key, value)
    
    def connection_added(self, connection: tuple[str, str]):
        self._send_gui(rpm.CONNECTION_ADDED, connection[0], connection[1])

    def connection_removed(self, connection: tuple[str, str]):
        self._send_gui(rpm.CONNECTION_REMOVED, connection[0], connection[1])
    
    def server_stopped(self):
        # here server is JACK (or Pipewire JACK)
        self._send_gui(rpm.SERVER_STOPPED)
    
    def server_restarted(self):
        self.osc_server.server_restarted()
    
    def send_transport_position(self, tpos: 'TransportPosition'):
        self._send_gui(rpm.TRANSPORT_POSITION,
                      tpos.frame, int(tpos.rolling), int(tpos.valid_bbt),
                      tpos.bar, tpos.beat, tpos.tick, tpos.beats_per_minutes)
    
    def send_dsp_load(self, dsp_load: int):
        self._send_gui(rpm.DSP_LOAD, dsp_load)
    
    def send_one_xrun(self):
        self._send_gui(rpm.ADD_XRUN)
    
    def send_buffersize(self, buffer_size: int):
        self._send_gui(rpm.BUFFER_SIZE, buffer_size)
    
    def send_samplerate(self, samplerate: int):
        self._send_gui(rpm.SAMPLE_RATE, samplerate)

    def send_pretty_names_locked(self, locked: bool):
        self._send_gui(rpm.PRETTY_NAMES_LOCKED, int(locked))
    
    def send_server_lose(self):
        self.osc_server.send_server_lose()

    def make_one_shot_act(self, one_shot_act: str):
        self.osc_server.make_one_shot_act(one_shot_act)
        
    def _send_gui(self, *args):
        self.osc_server.send_gui(*args)
