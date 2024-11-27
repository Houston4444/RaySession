
# Imports from standard library
from typing import TYPE_CHECKING

# imports from jackpatch
if TYPE_CHECKING:
    from src.clients.jackpatch.bases import ProtoEngine
else:
    from bases import ProtoEngine

from alsa_thread import AlsaManager

class AlsaEngine(ProtoEngine):
    def __init__(self):
        super().__init__()
        self._alsa_mng: AlsaManager = None
        
    def init(self) -> bool:
        self._alsa_mng = AlsaManager()
        return True

    def connect_ports(self, port_out: str, port_in: str):
        self._alsa_mng.connect_ports(port_out, port_in)

    def disconnect_ports(self, port_out: str, port_in: str):
        self._alsa_mng.connect_ports(port_out, port_in, disconnect=True)

