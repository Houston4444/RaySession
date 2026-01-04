# Imports from standard library
import time
from typing import TYPE_CHECKING

# Imports from src/shared
import osc_paths.ray.gui as rg
import ray

# Local imports
from daemon_tools import NoSessionPath

from .session_op import SessionOp

if TYPE_CHECKING:
    from session import Session


class TakePlace(SessionOp):
    def __init__(self, session: 'Session'):
        super().__init__(session)
        self.routine = [self.take_place]

    def take_place(self):
        session = self.session
        session.set_path(
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
            session.set_path(session.future_session_path)
            
            # session has been renamed and client files have been moved
            # save session file is required here, else clients could not
            # find their files at reload (after session abort).
            session.save_session_file()

        session.send_gui(rg.session.NAME, session.name, str(session.path))
        session.trashed_clients.clear()
        
        session.alternative_groups.clear()
        alter_list = list[str]()
        for alter_group in session.future_alternative_groups:
            session.alternative_groups.append(alter_group)
            alter_list += list(alter_group)
            alter_list.append('')
        session.send_gui(rg.session.ALTERNATIVE_GROUPS, *alter_list)

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

        self.next()