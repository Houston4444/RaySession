# Imports from standard library
import logging
from typing import TYPE_CHECKING

# third party imports
from qtpy.QtCore import QCoreApplication

# Imports from src/shared
import osc_paths.ray.gui as rg
import ray

# Local imports
from .session_op import SessionOp

if TYPE_CHECKING:
    from session import Session


_logger = logging.getLogger(__name__)
_translate = QCoreApplication.translate


class ExitNow(SessionOp):
    def __init__(self, session: 'Session'):
        super().__init__(session)
        self.routine = [self.wait_patchbay, self.quit_app]

    def wait_patchbay(self):
        self.next(ray.WaitFor.PATCHBAY_QUIT, timeout=1000)
        
    def quit_app(self):
        session = self.session
        session.set_server_status(ray.ServerStatus.OFF)
        session.set_path(None)
        session.message("Bye Bye...")
        session._send_reply("Bye Bye...")
        session.send_gui(rg.server.DISANNOUNCE)
        QCoreApplication.quit()
