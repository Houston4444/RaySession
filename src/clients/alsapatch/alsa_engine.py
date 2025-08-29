
# imports from shared
from patcher.bases import EventHandler, ProtoEngine

# Local imports
from .alsa_thread import AlsaManager


class AlsaEngine(ProtoEngine):
    def __init__(self, event_handler: EventHandler):
        super().__init__(event_handler)
        self._alsa_mng: AlsaManager = None # type:ignore
        
    def init(self) -> bool:
        self._alsa_mng = AlsaManager(self.ev_handler)
        return True

    def connect_ports(self, port_out: str, port_in: str):
        self._alsa_mng.connect_ports(port_out, port_in)

    def disconnect_ports(self, port_out: str, port_in: str):
        self._alsa_mng.connect_ports(port_out, port_in, disconnect=True)
        
    def quit(self):
        self._alsa_mng.stop()

