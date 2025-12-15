from typing import TYPE_CHECKING

from qtpy.QtCore import QCoreApplication

import ray

from daemon_tools import highlight_text

from .session_op import SessionOp

if TYPE_CHECKING:
    from session_operating import OperatingSession


_translate = QCoreApplication.translate


class Save(SessionOp):
    def __init__(self, session: 'OperatingSession',
                 outing=False, save_clients=True):
        super().__init__(session)
        self.script_step = 'save'
        self.outing = outing
        self.save_clients = save_clients
        self.routine = [self.save_the_clients, self.save_the_session]

    def start_from_script(self, arguments: list[str]):
        if 'without_clients' in arguments:
            self.outing = False
            self.save_clients = False
        self.start()

    def save_the_clients(self):
        session = self.session

        if session.path is None:
            session.next_function()
            return

        if self.outing:
            session.set_server_status(ray.ServerStatus.OUT_SAVE)
        else:
            session.set_server_status(ray.ServerStatus.SAVE)

        session.send_gui_message(
            _translate('GUIMSG', '-- Saving session %s --')
                % highlight_text(session.short_path_name))

        if self.save_clients:
            for client in session.clients:
                if client.can_save_now():
                    session.expected_clients.append(client)
                client.save()

            if session.expected_clients:
                if len(session.expected_clients) == 1:
                    session.send_gui_message(
                        _translate('GUIMSG', 'waiting for %s to save...')
                            % session.expected_clients[0].gui_msg_style)
                else:
                    session.send_gui_message(
                        _translate('GUIMSG',
                                   'waiting for %i clients to save...')
                            % len(session.expected_clients))

        self.next(10000, ray.WaitFor.REPLY)

    def save_the_session(self):
        session = self.session
        session._clean_expected()

        if self.save_clients and self.outing:
            for client in session.clients:
                if client.has_error():
                    self.error(ray.Err.GENERAL_ERROR,
                               'Some clients could not save')
                    return

        if session.path is None:
            session.next_function()
            return

        err = session._save_session_file()
        if err:
            self.save_error(ray.Err.CREATE_FAILED)
            return

        session.canvas_saver.save_json_session_canvas(session.path)

        full_notes_path = session.path / ray.NOTES_PATH

        if session.notes:
            try:
                with open(full_notes_path, 'w') as notes_file:
                    notes_file.write(session.notes)
            except:
                session.message(f'unable to save notes in {full_notes_path}')

        elif full_notes_path.is_file():
            try:
                full_notes_path.unlink()
            except:
                session.message(f'unable to remove {full_notes_path}')

        session.send_gui_message(
            _translate('GUIMSG', "Session '%s' saved.")
                % session.short_path_name)
        session.message(f'Session {session.short_path_name} saved.')

        session.next_function()

    def save_error(self, err_saving: ray.Err):
        session = self.session
        session.message("Failed")
        m = _translate('Load Error', "Unknown error")

        if err_saving is ray.Err.CREATE_FAILED:
            m = _translate(
                'GUIMSG', "Can't save session, session file is unwriteable !")

        session.message(m)
        session.send_gui_message(m)
        session.set_server_status(ray.ServerStatus.READY)
        
        self.error(ray.Err.CREATE_FAILED, m)
        