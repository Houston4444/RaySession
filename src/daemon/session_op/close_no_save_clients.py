import math
from typing import TYPE_CHECKING

from qtpy.QtCore import QCoreApplication

import ray

from .session_op import SessionOp

if TYPE_CHECKING:
    from session_operating import OperatingSession


_translate = QCoreApplication.translate


class SessionOpCloseNoSaveClients(SessionOp):
    def __init__(self, session: 'OperatingSession'):
        super().__init__(session)
        self.routine = [
            self.close_no_save_clients,
            self.close_no_save_clients_substep1,
            self.close_no_save_clients_substep2]

    def close_no_save_clients(self):
        session = self.session
        session._clean_expected()

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
                    'waiting for no saveable clients to be closed gracefully...'))

        duration = int(1000 * math.sqrt(len(session.expected_clients)))
        self.next(duration, ray.WaitFor.QUIT)

    def close_no_save_clients_substep1(self):
        session = self.session
        session._clean_expected()
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
        self.next(120000, ray.WaitFor.QUIT, redondant=True)
        
    def close_no_save_clients_substep2(self):
        self.session.next_function()
