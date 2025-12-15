import logging
from typing import TYPE_CHECKING

from qtpy.QtCore import QCoreApplication

import osc_paths.ray.gui as rg
import ray

from .session_op import SessionOp

if TYPE_CHECKING:
    from session_operating import OperatingSession


_logger = logging.getLogger(__name__)
_translate = QCoreApplication.translate


class ExitNow(SessionOp):
    def __init__(self, session: 'OperatingSession'):
        super().__init__(session)
        self.routine = [self.wait_patchbay, self.quit_app]

    def wait_patchbay(self):
        self.next(1000, ray.WaitFor.PATCHBAY_QUIT)
        
    def quit_app(self):
        session = self.session
        session.set_server_status(ray.ServerStatus.OFF)
        session._set_path(None)
        session.message("Bye Bye...")
        session._send_reply("Bye Bye...")
        session.send_gui(rg.server.DISANNOUNCE)
        QCoreApplication.quit()

