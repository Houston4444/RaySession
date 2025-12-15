from typing import TYPE_CHECKING

from .session_op import SessionOp

if TYPE_CHECKING:
    from session_operating import OperatingSession


class Success(SessionOp):
    def __init__(self, session: 'OperatingSession', msg='Done', gui_msg=''):
        super().__init__(session)
        self.msg = msg
        self.gui_msg = gui_msg
        self.routine = [self.success]

    def success(self):
        if self.msg:
            self.session.message(self.msg)
        if self.gui_msg:
            self.session.send_gui_message(self.gui_msg)
        
        self.reply(self.msg)