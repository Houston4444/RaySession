from typing import TYPE_CHECKING

from qtpy.QtCore import QCoreApplication

import ray

from .session_op import SessionOp

if TYPE_CHECKING:
    from session_operating import OperatingSession


_translate = QCoreApplication.translate


class SessionOpSaveSnapshot(SessionOp):
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
        self.routine = [self.snapshot, self.snapshot_substep1]

    def snapshot(self):
        session = self.session
        
        if not self.force:
            if not (session.has_server_option(ray.Option.SNAPSHOTS)
                    and not session.snapshoter.is_auto_snapshot_prevented()
                    and session.snapshoter.has_changes()):
                session.next_function()
                return

        if self.outing:
            session.set_server_status(ray.ServerStatus.OUT_SNAPSHOT)
        else:
            session.set_server_status(ray.ServerStatus.SNAPSHOT)

        session.send_gui_message(_translate('GUIMSG', "snapshot started..."))
        session.snapshoter.save(self.snapshot_name, self.rewind_snapshot,
            self.snapshot_substep1, self.snapshot_error)

    def snapshot_substep1(self, aborted=False):
        session = self.session
        if aborted:
            session.message('Snapshot aborted')
            session.send_gui_message(_translate('GUIMSG', 'Snapshot aborted!'))

        session.send_gui_message(_translate('GUIMSG', '...Snapshot finished.'))
        session.next_function()

    def snapshot_error(self, err_snapshot: ray.Err, info_str='', exit_code=0):
        session = self.session
        
        m = _translate('Snapshot Error', "Unknown error")
        match err_snapshot:
            case ray.Err.SUBPROCESS_UNTERMINATED:
                m = _translate(
                    'Snapshot Error',
                    "git didn't stop normally.\n%s") % info_str
            case ray.Err.SUBPROCESS_CRASH:
                m = _translate(
                    'Snapshot Error',
                    "git crashes.\n%s") % info_str
            case ray.Err.SUBPROCESS_EXITCODE:
                m = _translate(
                    'Snapshot Error',
                    "git exit with the error code %i.\n%s") % (
                        exit_code, info_str)
        session.message(m)
        session.send_gui_message(m)

        if self.error_is_minor:
            session._send_minor_error(err_snapshot, m)
            session.next_function()
        else:
            self.error(err_snapshot, m)
