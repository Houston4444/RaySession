from typing import TYPE_CHECKING

import ray

from .session_op import SessionOp

if TYPE_CHECKING:
    from session_operating import OperatingSession


class AbortCopy(SessionOp):
    def __init__(self, session: 'OperatingSession'):
        super().__init__(session)
        self.routine = [self.abort_copy, self.abort_copy_done]

    def abort_copy(self):
        if self.session.file_copier.is_active():
            self.session.file_copier.abort()
            
        self.next(ray.WaitFor.FILE_COPY)
        
    def abort_copy_done(self):
        self.next()
