from typing import TYPE_CHECKING

from qtpy.QtCore import QCoreApplication

import ray

from client import Client

from .session_op import SessionOp

if TYPE_CHECKING:
    from session_operating import OperatingSession


_translate = QCoreApplication.translate


class LoadSnapshot(SessionOp):
    def __init__(self, session: 'OperatingSession',
                 snapshot_name: str, client_id=''):
        super().__init__(session)
        self.snapshot_name = snapshot_name
        self.client_id = client_id
        self.routine = [self.close_client,
                        self.kill_client,
                        self.load_snapshot]

        self.client: Client | None = None
        self._client_was_running = False

    def close_client(self):
        if self.client_id:
            session = self.session            
            for client in session.clients:
                if client.client_id == self.client_id:
                    self.client = client
                    break

            if self.client is not None and self.client.is_running:
                self._client_was_running = True
                session.set_server_status(ray.ServerStatus.READY)
                session.expected_clients.append(self.client)
                self.client.stop()

        self.next(30000, ray.WaitFor.STOP_ONE)
        
    def kill_client(self):
        if self.client is not None and self.client.is_running:
            self.client.kill()
            
        self.next(1000, ray.WaitFor.STOP_ONE)

    def load_snapshot(self):
        session = self.session
        session.clean_expected()
        if self.session.path is None:
            session.next_function()
            return
        
        session.set_server_status(ray.ServerStatus.REWIND)

        if self.client_id:
            err = session.snapshoter.load_client_exclusive(
                self.client_id, self.snapshot_name)        
        else:
            err = session.snapshoter.load(
                self.session.path, self.snapshot_name)
            
        if err is ray.Err.OK:
            if self.client is not None:
                session.set_server_status(ray.ServerStatus.READY)
                if self._client_was_running:
                    self.client.start()
            session.next_function()
            return
        
        m = _translate('Snapshot Error', "Snapshot error")
        if err is ray.Err.GIT_ERROR:
            err, command, exit_code = session.snapshoter.last_git_error
            match err:
                case ray.Err.SUBPROCESS_UNTERMINATED:
                    m = _translate(
                        'Snapshot Error',
                        "command didn't stop normally:\n%s") % command
                case ray.Err.SUBPROCESS_CRASH:
                    m = _translate(
                        'Snapshot Error',
                        "command crashes:\n%s") % command
                case ray.Err.SUBPROCESS_EXITCODE:
                    m = _translate(
                        'Snapshot Error',
                        "command exit with the error code %i:\n%s") % (
                            exit_code, command)

        elif err is ray.Err.NO_SUCH_FILE:
            m = _translate(
                'Snapshot Error',
                "error reading file:\n%s") % session.snapshoter.history_file
        
        session.message(m)
        session.send_gui_message(m)
        session.set_server_status(ray.ServerStatus.OFF)
        self.error(err, m)
