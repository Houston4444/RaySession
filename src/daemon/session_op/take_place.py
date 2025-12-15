import time
from typing import TYPE_CHECKING

import osc_paths.ray.gui as rg
import ray

from daemon_tools import NoSessionPath

from .session_op import SessionOp

if TYPE_CHECKING:
    from session_operating import OperatingSession


class TakePlace(SessionOp):
    def __init__(self, session: 'OperatingSession'):
        super().__init__(session)
        self.routine = [self.take_place]

    def take_place(self):
        session = self.session
        session._set_path(
            session.future_session_path,
            session.future_session_name)

        if session.path is None:
            raise NoSessionPath

        if session.name and session.name != session.path.name:
            # session folder has been renamed
            # so rename session to it
            for client in (session.future_clients
                           + session.future_trashed_clients):
                client.adjust_files_after_copy(
                    str(session.path), ray.Template.RENAME)
            session._set_path(session.future_session_path)
            
            # session has been renamed and client files have been moved
            # save session file is required here, else clients could not
            # find their files at reload (after session abort).
            session._save_session_file()

        session.send_gui(rg.session.NAME, session.name, str(session.path))
        session.trashed_clients.clear()

        session.notes = session.future_notes
        session.send_gui(rg.session.NOTES, session.notes)
        session.notes_shown = session.future_notes_shown
        if session.notes_shown:
            session.send_gui(rg.session.NOTES_SHOWN)
        else:
            session.send_gui(rg.session.NOTES_HIDDEN)

        session.canvas_saver.send_session_group_positions()
        session.load_locked = True

        session._time_at_open = time.time()

        session.next_function()
