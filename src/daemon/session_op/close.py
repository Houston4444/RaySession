import time
from typing import TYPE_CHECKING

from qtpy.QtCore import QCoreApplication

import ray
import osc_paths.ray.gui as rg

from client import Client
from .session_op import SessionOp

if TYPE_CHECKING:
    from session_operating import OperatingSession


_translate = QCoreApplication.translate


class SessionOpClose(SessionOp):
    def __init__(self, session: 'OperatingSession',
                 clear_all_clients=False):
        super().__init__(session)
        self.clear_all_clients = clear_all_clients
        self.routine = [
            self.close, self.close_substep1, self.close_substep2]

    def start_from_script(self, arguments: list[str]):
        if 'close_all' in arguments:
            self.clear_all_clients = True
        self.start()
            
    def close(self):
        session = self.session
        session.expected_clients.clear()

        if session.path is None:
            session.next_function()
            return

        # clients we will keep alive
        keep_client_list = list[Client]()

        # stopped clients we will remove immediately
        byebye_client_list = list[Client]()

        if not self.clear_all_clients:
            for future_client in session.future_clients:
                if not future_client.auto_start:
                    continue

                for client in session.clients:
                    if client in keep_client_list:
                        continue

                    if client.can_switch_with(future_client):
                        client.switch_state = ray.SwitchState.RESERVED
                        keep_client_list.append(client)
                        break

        for client in session.clients:
            if client not in keep_client_list:
                # client is not capable of switch, or is not wanted
                # in the new session
                if client.is_running:
                    session.expected_clients.append(client)
                else:
                    byebye_client_list.append(client)

        if keep_client_list:
            session.set_server_status(ray.ServerStatus.CLEAR)
        else:
            session.set_server_status(ray.ServerStatus.CLOSE)

        for client in byebye_client_list:
            if client in session.clients:
                session._remove_client(client)
            else:
                raise NameError(f'no client {client.client_id} to remove')

        if session.expected_clients:
            if len(session.expected_clients) == 1:
                session.send_gui_message(
                    _translate('GUIMSG',
                               'waiting for %s to quit...')
                        % session.expected_clients[0].gui_msg_style)
            else:
                session.send_gui_message(
                    _translate('GUIMSG',
                               'waiting for %i clients to quit...')
                        % len(session.expected_clients))

            for client in session.expected_clients.__reversed__():
                session.clients_to_quit.append(client)
            session.timer_quit.start()

        session.trashed_clients.clear()
        session.send_gui(rg.trash.CLEAR)

        self.next(30000, ray.WaitFor.QUIT)

    def close_substep1(self):
        session = self.session
        for client in session.expected_clients:
            client.kill()

        self.next(1000, ray.WaitFor.QUIT)

    def close_substep2(self):
        session = self.session
        session._clean_expected()

        # remember in recent sessions
        # only if session has been open at least 30 seconds
        # to prevent remember when session is open just for a little script
        if time.time() - session._time_at_open > 30:
            session.remember_as_recent()

        if self.clear_all_clients:
            session._set_path(None)
            
        session.next_function()