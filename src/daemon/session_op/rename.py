# Imports from standard library
import logging
import subprocess
from typing import TYPE_CHECKING

# third party imports
from qtpy.QtCore import QCoreApplication

# Imports from src/shared
import ray

# Local imports
from daemon_tools import NoSessionPath

from .session_op import SessionOp

if TYPE_CHECKING:
    from session import Session


_logger = logging.getLogger(__name__)
_translate = QCoreApplication.translate


class Rename(SessionOp):
    def __init__(self, session: 'Session', new_session_name: str):
        super().__init__(session)
        self.new_session_name = new_session_name
        self.routine = [self.rename]

    def rename(self):
        session = self.session
        if session.path is None:
            raise NoSessionPath

        old_name = session.name

        spath = session.path.parent / self.new_session_name
        if spath.exists():
            self.error(
                ray.Err.CREATE_FAILED,
                _translate(
                    'rename',
                    "Folder %s already exists,\n"
                    "Impossible to rename session.")
                        % self.new_session_name)
            return
        
        try:
            subprocess.run(['mv', session.path, spath])
        except:
            self.error(
                ray.Err.GENERAL_ERROR,
                "failed to rename session")
            return
        
        session.set_path(spath)
        session.send_gui_message(
            _translate('GUIMSG', 'Session %s has been renamed to %s .')
            % (old_name, self.new_session_name))
        session.send_gui_message(
            _translate('GUIMSG', 'Session directory is now: %s')
                % session.path)
        
        for client in session.clients + session.trashed_clients:
            client.adjust_files_after_copy(
                self.new_session_name, ray.Template.RENAME)

        self.next()