# Imports from standard library
import math
from typing import TYPE_CHECKING

# third party imports
from qtpy.QtCore import QCoreApplication

# Imports from src/shared
import ray

# Local imports
from .session_op import SessionOp

if TYPE_CHECKING:
    from session import Session


_translate = QCoreApplication.translate


class CloseNoSaveClients(SessionOp):
    def __init__(self, session: 'Session'):
        super().__init__(session)
        self.routine = [
            self.close_gracefully_windows,
            self.wait_user_to_close_clients,
            self.go_to_next_function]

    def close_gracefully_windows(self):
        session = self.session
        session.clean_expected()

        if session.has_server_option(ray.Option.HAS_WMCTRL):
            has_nosave_clients = False
            for client in session.clients:
                if client.is_running and client.relevant_no_save_level() == 2:
                    has_nosave_clients = True
                    break

            if has_nosave_clients:
                session.desktops_memory.set_active_window_list()
                for client in session.clients:
                    if (client.is_running
                            and client.relevant_no_save_level() == 2):
                        session.expected_clients.append(client)
                        session.desktops_memory.find_and_close(client.pid)

        if session.expected_clients:
            session.send_gui_message(
                _translate(
                    'GUIMSG',
                    'waiting for no saveable clients '
                    'to be closed gracefully...'))

        duration = int(1000 * math.sqrt(len(session.expected_clients)))
        self.next(ray.WaitFor.QUIT, timeout=duration)

    def wait_user_to_close_clients(self):
        session = self.session
        session.clean_expected()
        has_nosave_clients = False

        for client in session.clients:
            if (client.is_running and client.relevant_no_save_level()):
                session.expected_clients.append(client)
                has_nosave_clients = True

        if has_nosave_clients:
            session.set_server_status(ray.ServerStatus.WAIT_USER)
            session.timer_wu_progress_n = 0
            session.timer_waituser_progress.start()
            session.send_gui_message(_translate('GUIMSG',
                'waiting you to close yourself unsaveable clients...'))

        # Timer (2mn) is restarted if an expected client has been closed
        self.next(ray.WaitFor.QUIT, timeout=120000, redondant=True)
        
    def go_to_next_function(self):
        self.next()