# Imports from standard library
import logging
from typing import TYPE_CHECKING, Callable

# Imports from src/shared
import ray
import osc_paths
import osc_paths.ray.gui as rg
from osclib import OscPack

if TYPE_CHECKING:
    from session import Session


_logger = logging.getLogger(__name__)


class SessionOp:
    '''Session operation that may contains many functions to run
    in the order of its `routine`. Theses functions can be separated
    in time execution, if wait for clients replies, file copy or other
    is required.
    '''
    def __init__(
            self, session: 'Session', osp: OscPack | None =None):
        '''if `osp` is set, replies and errors will be sent
        to the osp.src_addr, otherwise, they will be sent to the
        session.steps_osp.src_addr'''
        self.session = session
        self.osp = osp
        self.routine = list[Callable]()
        self.func_n = 0
        self.script_step: str = ''
        self.script_osp: OscPack | None = None
    
    @property
    def class_name(self) -> str:
        return self.__class__.__name__.rpartition('.')[2]
    
    def _sub_step_name(self, index: int) -> str:
        return f'{self.class_name}.{self.routine[index].__name__}'
    
    def _clean_up_session_ops(self):
        if self.osp is not None:
            return

        session = self.session

        session.steps_osp = None
        session.session_ops.clear()
        session.cur_session_op = None

        if session.path is None:
            session.canvas_saver.unload_session()
            session.set_server_status(ray.ServerStatus.OFF)
            session.send_gui(rg.session.NAME, '', '')
            session.send_gui(rg.session.NOTES, '')
            session.send_gui(rg.session.NOTES_HIDDEN)
        else:
            session.set_server_status(ray.ServerStatus.READY)

    def start(self):
        _logger.debug(f'Start step {self._sub_step_name(0)}')
        self.func_n = 0
        self.routine[0]()
    
    def start_from_script(self, script_osp: OscPack):
        self.script_osp = script_osp
        self.start()

    def next(self, wait_for=ray.WaitFor.NONE,
             timeout: int | None =None, redondant=False):
        '''Once `wait_for` is not pertinent anymore or if `timeout`
        has past, execute the next function of self.routine.'''
        self.func_n += 1
        
        if wait_for is ray.WaitFor.NONE:
            if self.func_n >= len(self.routine):
                self.session.next_session_op()
            else:
                self.routine[self.func_n]
            return
        
        self.session.wait_and_go_to(
            self, wait_for, timeout, redondant=redondant)

    def run_next(self):
        if self.func_n >= len(self.routine):
            _logger.error(
                f'{self.__class__.__name__}.run_step called '
                'while its job is completed')
            return
        
        _logger.debug(f'Start step {self._sub_step_name(self.func_n)}')
        self.routine[self.func_n]()

    def reply(self, msg: str):
        '''send final reply of the operation
        and cleanup session attributes.'''
        if self.osp is not None:
            self.session.send_even_dummy(*self.osp.reply(), msg)
            return

        if self.session.steps_osp is not None:        
            self.session.send_even_dummy(
                *self.session.steps_osp.reply(), msg)
        
        self._clean_up_session_ops()
        
    def error(self, err: ray.Err, msg: str):
        '''reply an error to the operation asker, and abort the operation'''
        _logger.error(
            f'{self.__class__.__name__} error Err.{err.name}\n{msg}')
        if self.osp is not None:
            self.session.send_even_dummy(*self.osp.error(), err, msg)
            return

        if self.session.steps_osp is not None:
            self.session.send_even_dummy(
            *self.session.steps_osp.error(), err, msg)
            
        self._clean_up_session_ops()

    def minor_error(self, err: ray.Err, msg: str):
        '''post a minor error to the operation asker'''
        osp = self.session.steps_osp
        if self.osp is not None:
            osp = self.osp
        
        if osp is None:
            return
        
        self.session.send_even_dummy(
            osp.src_addr, osp.path, osc_paths.MINOR_ERROR, err, msg)    