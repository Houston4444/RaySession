# Imports from standard library
from typing import TYPE_CHECKING

# Imports from src/shared
import ray

# Local imports
from .session_op import SessionOp

if TYPE_CHECKING:
    from session import Session


class AbortCopy(SessionOp):
    def __init__(self, session: 'Session'):
        super().__init__(session)
        self.routine = [self.abort_copy, self.abort_copy_done]

    def abort_copy(self):
        if self.session.file_copier.is_active():
            self.session.file_copier.abort()
            
        self.next(ray.WaitFor.FILE_COPY)
        
    def abort_copy_done(self):
        self.next()