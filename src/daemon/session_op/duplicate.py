from typing import TYPE_CHECKING

from qtpy.QtCore import QCoreApplication

import ray
from osclib import Address, is_valid_osc_url
import osc_paths.nsm as nsm
import osc_paths.ray as r
import osc_paths.ray.gui as rg

from daemon_tools import highlight_text, NoSessionPath
import multi_daemon_file

from .session_op import SessionOp

if TYPE_CHECKING:
    from session_operating import OperatingSession


_translate = QCoreApplication.translate


class Duplicate(SessionOp):
    def __init__(self, session: 'OperatingSession', new_session_name: str):
        super().__init__(session)
        self.new_session_name = new_session_name
        self.routine = [self.start_network_sessions_copy,
                        self.copy_session_folder,
                        self.wait_network_sessions_copy,
                        self.rename_files]

    def start_network_sessions_copy(self):
        session = self.session
        
        if session._clients_have_errors():
            self.error(
                ray.Err.GENERAL_ERROR,
                _translate('error', "Some clients could not save"))
            return

        session.send_gui(rg.trash.CLEAR)
        session.send_gui_message(
            _translate('GUIMSG', '-- Duplicating session %s to %s --')
            % (highlight_text(session.short_path_name),
               highlight_text(self.new_session_name)))

        for client in session.clients:
            if client.is_ray_net:
                client.ray_net.duplicate_state = -1.0
                if (client.ray_net.daemon_url
                        and is_valid_osc_url(client.ray_net.daemon_url)):
                    session.send(
                        Address(client.ray_net.daemon_url),
                        r.session.DUPLICATE_ONLY,
                        session.short_path_name,
                        self.new_session_name,
                        client.ray_net.session_root)

                session.expected_clients.append(client)

        if session.expected_clients:
            session.send_gui_message(
                _translate(
                    'GUIMSG',
                    'waiting for network daemons to start duplicate...'))

        self.next(ray.WaitFor.DUPLICATE_START, timeout=2000)

    def copy_session_folder(self):
        session = self.session        
        if session.path is None:
            raise NoSessionPath
        
        spath = session.root / self.new_session_name
        session.set_server_status(ray.ServerStatus.COPY)
        session.send_gui_message(
            _translate('GUIMSG', 'start session copy...'))

        # lock the directory of the new session created
        multi_daemon_file.add_locked_path(spath)

        err = session.file_copier.start_session_copy(session.path, spath)
        if err is not ray.Err.OK:
            multi_daemon_file.unlock_path(spath)
            self.error(
                err, 
                _translate(
                    'Session Copy',
                    'Failed to start copy from %s to %s') % (
                        session.path, spath))
            return
        
        self.next(ray.WaitFor.FILE_COPY)

    def wait_network_sessions_copy(self):
        session = self.session
        
        if session.file_copier.aborted:
            # unlock the directory of the aborted session
            multi_daemon_file.unlock_path(
                session.root / self.new_session_name)

            osp = session.steps_osp
            if osp is not None:
                session.send(
                    osp.src_addr, r.net_daemon.DUPLICATE_STATE, 1.0)

            if osp is not None and osp.path == nsm.server.DUPLICATE:
                # for nsm server control API compatibility
                # abort duplication is not possible in Non/New NSM
                # so, send the only known error
                self.error(ray.Err.NO_SUCH_FILE, 'No such file.')
                return
            
            self.error(
                ray.Err.COPY_ABORTED,
                _translate('error', 'Copy was aborted by user'))
            return
        
        session.clean_expected()
        session.send_gui_message(
            _translate('GUIMSG', '...session copy finished.'))

        for client in session.clients:
            if (client.is_ray_net
                    and 0 <= client.ray_net.duplicate_state < 1):
                session.expected_clients.append(client)

        if session.expected_clients:
            session.send_gui_message(
                _translate('GUIMSG',
                           'waiting for network daemons to finish duplicate'))

        self.next(ray.WaitFor.DUPLICATE_FINISH) # 1 Hour

    def rename_files(self):
        session = self.session
        session.adjust_files_after_copy(
            self.new_session_name, ray.Template.NONE)

        # unlock the directory of the new session created
        multi_daemon_file.unlock_path(session.root / self.new_session_name)
        
        if session.steps_osp is not None:
            session.send(
                session.steps_osp.src_addr, r.net_daemon.DUPLICATE_STATE, 1.0)
        
        self.next()

        