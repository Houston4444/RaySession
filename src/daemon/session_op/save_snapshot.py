import logging
from typing import TYPE_CHECKING

from qtpy.QtCore import QCoreApplication

import ray
import osc_paths
import osc_paths.ray as r

from snapshoter import full_ref_for_gui

from .session_op import SessionOp

if TYPE_CHECKING:
    from session_operating import OperatingSession


_logger = logging.getLogger(__name__)
_translate = QCoreApplication.translate


class SaveSnapshot(SessionOp):
    def __init__(self, session: 'OperatingSession',
                 snapshot_name='', rewind_snapshot='',
                 force=False, outing=False,
                 error_is_minor=True):
        super().__init__(session)
        self.snapshot_name = snapshot_name
        self.rewind_snapshot = rewind_snapshot
        self.force = force
        self.outing = outing
        self.error_is_minor = error_is_minor
        self.routine = [self.add_files, self.commit_files]

    def add_files(self):
        session = self.session
        
        if not self.force:
            if not (session.has_server_option(ray.Option.SNAPSHOTS)
                    and not session.snapshoter.is_auto_snapshot_prevented()
                    and session.snapshoter.has_changes()):
                _logger.info('No changes, no snapshot.')
                session.next_session_op()
                return

        if self.outing:
            session.set_server_status(ray.ServerStatus.OUT_SNAPSHOT)
        else:
            session.set_server_status(ray.ServerStatus.SNAPSHOT)

        session.send_gui_message(_translate('GUIMSG', "snapshot started..."))
        err = session.snapshoter.save()
        
        if err is not ray.Err.OK:
            match err:
                case ray.Err.GIT_ERROR:
                    err, command, exit_code = \
                        session.snapshoter.last_git_error
                    m = self._snapshot_error_msg(err, command, exit_code)
                case ray.Err.CREATE_FAILED:
                    m = _translate(
                        'Snapshot Error',
                        'Failed to write exclude file %s') % (
                            self.session.snapshoter.exclude_file)
                case _:
                    m = _translate('Snapshot Error', 'Unknown error')
            
            if self.error_is_minor:
                self.minor_error(err, m)
                session.next_session_op()
            else:
                self.error(err, m)
            return
        
        self.next(ray.WaitFor.SNAPSHOT_ADD)

    def commit_files(self):
        session = self.session
        
        if session.snapshoter.adder_aborted:
            session.message('Snapshot aborted')
            session.send_gui_message(
                _translate('GUIMSG', 'Snapshot aborted!'))
            
            if not self.error_is_minor:
                self.error(
                    ray.Err.COPY_ABORTED,
                    _translate('Snapshot Error',
                               'Snapshot has been aborted by user'))
                return

        err, ref = session.snapshoter.commit(
            self.snapshot_name, self.rewind_snapshot)
        
        command = ''
        exit_code = 0
        if err is ray.Err.GIT_ERROR:
            err, command, exit_code = session.snapshoter.last_git_error
        
        m = self._snapshot_error_msg(err, command, exit_code)
        
        if err is not ray.Err.OK:
            session.message(m)
            if self.error_is_minor:
                self.minor_error(err, m)
            else:
                self.error(err, m)
                return
        
        # not really a reply, not strong.
        if ref:
            self.session.send_gui(
                osc_paths.REPLY,
                r.session.LIST_SNAPSHOTS,
                full_ref_for_gui(
                    ref, self.snapshot_name, self.rewind_snapshot))

        session.send_gui_message(
            _translate('GUIMSG', '...Snapshot finished.'))
        self.next()

    def _snapshot_error_msg(
            self, err: ray.Err, command: str, exit_code: int) -> str:
        m = _translate('Snapshot Error', "Unknown error")
        match err:
            case ray.Err.SUBPROCESS_UNTERMINATED:
                m = _translate(
                    'Snapshot Error',
                    "git didn't stop normally.\n%s") % command
            case ray.Err.SUBPROCESS_CRASH:
                m = _translate(
                    'Snapshot Error',
                    "git crashes.\n%s") % command
            case ray.Err.SUBPROCESS_EXITCODE:
                m = _translate(
                    'Snapshot Error',
                    "git exit with the error code %i.\n%s") % (
                        exit_code, command)
                    
        return m