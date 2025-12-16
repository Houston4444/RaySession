# Imports from standard library
from typing import TYPE_CHECKING

# Local imports
from .session_op import SessionOp

if TYPE_CHECKING:
    from session_operating import OperatingSession


class Success(SessionOp):
    def __init__(self, session: 'OperatingSession', msg='Done'):
        super().__init__(session)
        self.msg = msg
        self.routine = [self.success]

    def success(self):
        if self.msg:
            self.session.message(self.msg)
        self.reply(self.msg)