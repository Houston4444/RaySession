import importlib
from threading import Thread
from types import ModuleType
from typing import Optional, Callable
import logging

_logger = logging.getLogger(__name__)


class InternalClient:
    def __init__(
            self, name: str, args: tuple[str, ...], nsm_url: str):
        self.name = name
        self.args = args
        self.nsm_url = nsm_url
        self._lib: Optional[ModuleType] = None
        self._thread: Optional[Thread] = None
        self._start_func: Optional[Callable] = None
        self._stop_func: Optional[Callable] = None

    def main_loop(self):
        'target of the _thread attribute'

        module_name = self.name.replace('ray-', '')

        # import the client module
        try:
            self._lib = importlib.import_module(module_name)
        except BaseException as e:
            _logger.warning(f'Failed to import module {module_name} '
                            f'for internal client {self.name}\n'
                            + str(e))
            return

        # run the internal_prepare function
        try:
            funcs = self._lib.internal_prepare(
                *self.args, nsm_url=self.nsm_url)
        except BaseException as e:
            _logger.warning(
                'Failed to load internal_prepare function of '
                f'the internal client {self.name}\n'
                + str(e))
            return
        
        # check if internal_prepare success 
        if len(funcs) == 2:
            funcs: tuple[Callable, Callable]
            self._start_func, self._stop_func = funcs
        else:
            return
        
        # run 
        self._start_func()
    
    def start(self):
        if self.running:
            return
        
        self._thread = Thread(target=self.main_loop)
        self._thread.daemon = True
        self._thread.start()
    
    def stop(self):
        if not self.running:
            return
        
        if self._stop_func is None:
            _logger.error(f'Impossible to stop Internal Client {self.name},'
                          'stop_func is not defined')
            return

        self._stop_func()

    def kill(self):
        '''Does not really kill the thread,
        it makes the 'running' property lying'''
        if not self.running:
            return
        
        self._thread = None

    @property
    def running(self) -> bool:
        if self._thread is None:
            return False
        return self._thread.is_alive()