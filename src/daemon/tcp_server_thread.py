import logging
from typing import TYPE_CHECKING, Optional

from qtpy.QtCore import QCoreApplication

from osclib import TCP, ServerThread, get_free_osc_port

from signaler import Signaler

if TYPE_CHECKING:
    from session_signaled import SignaledSession


_instance = None
signaler = Signaler.instance()
_translate = QCoreApplication.translate
_logger = logging.getLogger(__name__)


class TcpServerThread(ServerThread):
    def __init__(self, session: 'SignaledSession'):
        tcp_port = get_free_osc_port(default=3556, protocol=TCP)
        super().__init__(tcp_port, TCP)
        
        self.session = session
        
        global _instance
        _instance = self
        
    @staticmethod
    def instance() -> 'Optional[TcpServerThread]':
        return _instance
