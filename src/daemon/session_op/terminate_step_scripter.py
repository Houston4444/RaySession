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
            self.terminate_step_scripter,
            self.terminate_step_scripter_substep2,
            self.terminate_step_scripter_substep3]

    def terminate_step_scripter(self):
        session = self.session
        if session.step_scripter.is_running():
            session.step_scripter.terminate()

        self.next(5000, ray.WaitFor.SCRIPT_QUIT)

    def terminate_step_scripter_substep2(self):
        session = self.session
        if session.step_scripter.is_running():
            session.step_scripter.kill()

        self.next(1000, ray.WaitFor.SCRIPT_QUIT)

    def terminate_step_scripter_substep3(self):
        self.session.next_function()
