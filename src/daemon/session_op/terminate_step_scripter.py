import logging
from typing import TYPE_CHECKING

from qtpy.QtCore import QCoreApplication

import ray

from .session_op import SessionOp

if TYPE_CHECKING:
    from session_operating import OperatingSession


_logger = logging.getLogger(__name__)
_translate = QCoreApplication.translate


class TerminateStepScripter(SessionOp):
    def __init__(self, session: 'OperatingSession'):
        super().__init__(session)
        self.routine = [
            self.stop_step_scripter,
            self.kill_step_scripter,
            self.go_to_next]

    def stop_step_scripter(self):
        session = self.session
        if session.step_scripter.is_running():
            session.step_scripter.terminate()

        self.next(5000, ray.WaitFor.SCRIPT_QUIT)

    def kill_step_scripter(self):
        session = self.session
        if session.step_scripter.is_running():
            session.step_scripter.kill()

        self.next(1000, ray.WaitFor.SCRIPT_QUIT)

    def go_to_next(self):
        self.session.next_function()
