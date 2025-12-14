import logging
from typing import TYPE_CHECKING, Callable

import ray
from osclib import OscPack

if TYPE_CHECKING:
    from session_operating import OperatingSession


_logger = logging.getLogger(__name__)


class SessionOp:
    '''Session operation that may contains many functions to run
    in the order of its `routine`. Theses functions can be separated
    in time execution, if wait for clients replies, file copy or other
    is required.
    '''
    def __init__(
            self, session: 'OperatingSession', osp: OscPack | None =None):
        '''if `osp` is set, replies and errors will be sent
        to the osp.src_addr, otherwise, they will be sent to the
        session.steps_osp.src_addr'''
        self.session = session
        self.osp = osp
        self.routine = list[Callable]()
        self.func_n = 0
        self.script_step: str = ''
    
    @property
    def class_name(self) -> str:
        return self.__class__.__name__.rpartition('.')[2]
    
    def _sub_step_name(self, index: int) -> str:
        return f'{self.class_name}.{self.routine[index].__name__}'
    
    def _clean_up_session_ops(self):
        if self.osp is not None:
            return
        
        self.session.steps_osp = None
        self.session.steps_order.clear()
        if self.session.path is None:
            self.session.set_server_status(ray.ServerStatus.OFF)
        else:
            self.session.set_server_status(ray.ServerStatus.READY)

    def start(self):
        _logger.debug(f'Start step {self._sub_step_name(0)}')
        self.func_n = 0
        self.routine[0]()
    
    def start_from_script(self, arguments: list[str]):
        self.start()
    
    def next(self, duration: int, wait_for: ray.WaitFor, redondant=False):
        '''Once `wait_for` is not pertinent anymore or if `duration`
        has past, execute the next function of self.routine.
        
        If `duration` is negative, there is no timeout.'''
        _logger.debug(
            f'{self.class_name}.{self.routine[self.func_n].__name__} finished')

        self.func_n += 1
        self.session._wait_and_go_to(
            duration, self.routine[self.func_n],
            wait_for, redondant=redondant)

    def reply(self, msg: str):
        '''Final reply of the operation.'''
        if self.osp is not None:
            self.session.send_even_dummy(*self.osp.reply(), msg)
            return

        if self.session.steps_osp is not None:        
            self.session.send_even_dummy(
                *self.session.steps_osp.reply(), msg)
        
        self._clean_up_session_ops()
        
    def error(self, err: ray.Err, msg: str):
        '''reply an error to the operation asker'''
        if self.osp is not None:
            self.session.send_even_dummy(*self.osp.error(), err, msg)
            return

        if self.session.steps_osp is not None:
            self.session.send_even_dummy(
            *self.session.steps_osp.error(), err, msg)
            
        self._clean_up_session_ops()

