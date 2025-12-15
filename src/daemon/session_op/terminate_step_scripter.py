from typing import TYPE_CHECKING

import ray

from .session_op import SessionOp

if TYPE_CHECKING:
    from session_operating import OperatingSession


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

        self.next(ray.WaitFor.SCRIPT_QUIT, timeout=5000)

    def kill_step_scripter(self):
        session = self.session
        if session.step_scripter.is_running():
            session.step_scripter.kill()

        self.next(ray.WaitFor.SCRIPT_QUIT, timeout=1000)

    def go_to_next(self):
        self.session.next_function()
