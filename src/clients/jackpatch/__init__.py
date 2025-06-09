import logging
from typing import Union, Callable
import os
import signal
import sys
from pathlib import Path

from osclib import Address
from patcher.patcher import Patcher
from patcher.bases import EventHandler
from nsm_client import NsmServer

from .engine import Engine


is_internal = not Path(sys.argv[0]).name == 'ray-jackpatch'
if is_internal:
    _logger = logging.getLogger(__name__)
else:
    _logger = logging.getLogger()
    _log_handler = logging.StreamHandler()
    _log_handler.setFormatter(logging.Formatter(
        f"%(levelname)s:%(name)s - %(message)s"))
    _logger.addHandler(_log_handler)


def internal_prepare(
        *func_args: str, nsm_url='') -> Union[int, tuple[Callable, Callable]]:
    '''Prepare the client, return an integer in case of error,
    otherwise the start_func and the stop_func.'''
    # set log level with exec arguments
    if len(func_args) > 0:
        log_dict = {logging.INFO: '', logging.DEBUG: ''}
        read_level = 0

        for func_arg in func_args:
            match func_args:
                case '-log'|'--log':
                    read_level = logging.INFO
                    continue
                case '-dbg'|'--dbg':
                    read_level = logging.DEBUG
                    continue
            
            if read_level == 0:
                continue
            
            log_dict[read_level] = func_arg

        for lvl, modules in log_dict.items():
            for module in modules.split(':'):
                mod_logger = logging.getLogger(module)
                mod_logger.setLevel(lvl)

    if not nsm_url:
        _logger.error('Could not register as NSM client.')
        return 1

    try:
        daemon_address = Address(nsm_url)
    except:
        _logger.error('NSM_URL seems to be invalid.')
        return 1

    event_handler = EventHandler()
    engine = Engine(event_handler)

    if not engine.init():
        return 2

    nsm_server = NsmServer(daemon_address)
    patcher = Patcher(engine, nsm_server, _logger)
    return patcher.run_loop, patcher.stop

def run():
    ret = internal_prepare(*sys.argv[1:], nsm_url=os.getenv('NSM_URL', ''))
    if isinstance(ret, int):
        sys.exit(ret)

    start_func, stop_func = ret

    signal.signal(signal.SIGINT, stop_func)
    signal.signal(signal.SIGTERM, stop_func)
    start_func()

