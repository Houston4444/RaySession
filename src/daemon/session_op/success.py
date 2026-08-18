# Imports from standard library
from typing import TYPE_CHECKING

# Local imports
from .session_op import SessionOp

if TYPE_CHECKING:
    from session import Session


class Success(SessionOp):
    def __init__(self, session: 'Session', msg='Done'):
        super().__init__(session)
        self.msg = msg
        self.routine = [self.success]

    def success(self):
        if self.msg:
            self.session.message(self.msg)
        self.reply(self.msg)