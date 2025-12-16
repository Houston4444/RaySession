# Imports from standard library
import logging
from typing import TYPE_CHECKING

# third party imports
from qtpy.QtCore import QCoreApplication

# Imports from src/shared
import osc_paths.ray.gui as rg
import ray

# Local imports
from daemon_tools import highlight_text

from .session_op import SessionOp

if TYPE_CHECKING:
    from session_operating import OperatingSession


_logger = logging.getLogger(__name__)
_translate = QCoreApplication.translate


class New(SessionOp):
    def __init__(self, session: 'OperatingSession', session_name: str):
        super().__init__(session)
        self.session_name = session_name
        self.routine = [self.new]

    def new(self):
        session = self.session
        session.send_gui_message(
            _translate('GUIMSG', "Creating new session %s")
                % highlight_text(self.session_name))
        spath = session.root / self.session_name

        if session._is_path_in_a_session_dir(spath):
            self.error(
                ray.Err.SESSION_IN_SESSION_DIR,
                "Can't create session in a dir containing a session "
                "for better organization.")
            return

        try:
            spath.mkdir(parents=True)
        except:
            self.error(ray.Err.CREATE_FAILED,
                       "Could not create the session directory")
            return

        session.set_server_status(ray.ServerStatus.NEW)
        session._set_path(spath)
        session.send_gui(
            rg.session.NAME, session.name, str(session.path))
        self.next()