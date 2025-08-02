
from typing import TYPE_CHECKING
from patshared import TransportPosition

import osc_paths.ray as r
import osc_paths.ray.patchbay.monitor as rpm
from osclib import Address

from patch_engine import PatchEngine

if TYPE_CHECKING:
    from osc_server import PatchbayDaemonServer


class RayPatchEngine(PatchEngine):
    def __init__(self, osc_server: 'PatchbayDaemonServer'):
        super().__init__()
        self.osc_server = osc_server
    
    def send_gui(self, *args):
        self.osc_server.send_gui(*args)
    
    def associate_client_name_and_uuid(self, client_name: str, uuid: int):
        self.send_gui(rpm.CLIENT_NAME_AND_UUID, client_name, uuid)

    def port_added(self, pname: str, ptype: int, pflags: int, puuid: int):
        self.send_gui(rpm.PORT_ADDED, pname, ptype, pflags, puuid) 

    def port_renamed(self, ex_name: str, new_name: str, uuid=0):
        if uuid:
            self.send_gui(rpm.PORT_RENAMED, ex_name, new_name, uuid)
        else:
            self.send_gui(rpm.PORT_RENAMED, ex_name, new_name)
    
    def port_removed(self, port_name: str):
        self.send_gui(rpm.PORT_REMOVED, port_name)
    
    def metadata_updated(self, uuid: int, key: str, value: str):
        self.send_gui(rpm.METADATA_UPDATED, uuid, key, value)
    
    def connection_added(self, connection: tuple[str, str]):
        self.send_gui(rpm.CONNECTION_ADDED, connection[0], connection[1])

    def connection_removed(self, connection: tuple[str, str]):
        self.send_gui(rpm.CONNECTION_REMOVED, connection[0], connection[1])
    
    def server_stopped(self):
        # here server is JACK (or Pipewire JACK)
        self.send_gui(rpm.SERVER_STOPPED)
    
    def send_transport_position(self, tpos: 'TransportPosition'):
        self.send_gui(rpm.TRANSPORT_POSITION,
                      tpos.frame, int(tpos.rolling), int(tpos.valid_bbt),
                      tpos.bar, tpos.beat, tpos.tick, tpos.beats_per_minutes)
    
    def send_dsp_load(self, dsp_load: int):
        self.send_gui(rpm.DSP_LOAD, dsp_load)
    
    def send_one_xrun(self):
        self.send_gui(rpm.ADD_XRUN)
    
    def send_buffersize(self):
        self.send_gui(rpm.BUFFER_SIZE, self.main_object.buffer_size)
    
    def send_samplerate(self):
        self.send_gui(rpm.SAMPLE_RATE, self.main_object.samplerate)

    def send_pretty_names_locked(self, locked: bool):
        self.send_gui(rpm.PRETTY_NAMES_LOCKED, int(locked))
    
    def send_server_lose(self):
        self.send_gui(rpm.SERVER_LOSE)

        # In the case server is not responding
        # and gui has not yet been added to gui_list
        # but gui url stocked in self._tmp_gui_url
        if not self.gui_list and self._tmp_gui_url:
            try:
                addr = Address(self._tmp_gui_url)
            except:
                return

        self.send(addr, rpm.SERVER_LOSE)

    def make_one_shot_act(self, one_shot_act: str):
        match one_shot_act:
            case r.patchbay.EXPORT_ALL_PRETTY_NAMES:
                self.main_object.export_all_pretty_names_to_jack_now()
            case r.patchbay.IMPORT_ALL_PRETTY_NAMES:
                self._import_all_pretty_names()
            case r.patchbay.CLEAR_ALL_PRETTY_NAMES:
                self.main_object.clear_all_pretty_names_from_jack()