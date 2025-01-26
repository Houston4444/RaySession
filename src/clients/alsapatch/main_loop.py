
# Imports from standard library
import os
import signal
import sys
import logging
from typing import Union, Callable

# Imports from src/shared
from nsm_client import NsmServer, Address

# Local imports
from patcher.bases import EventHandler
from patcher.patcher import Patcher

from .engine import Engine

_logger = logging.getLogger(__name__)


def internal_prepare(
        *func_args: str, nsm_url='') -> Union[int, tuple[Callable, Callable]]:
    '''Prepare the client, return a int in case of error,
    otherwise the start_func and the stop_func.'''
    # set log level with exec arguments
    if len(func_args) > 0:
        read_log_level = False
        log_level = logging.WARNING

        for func_arg in func_args:
            if func_arg in ('-log', '--log'):
                read_log_level = True
                log_level = logging.DEBUG

            elif read_log_level:
                if func_arg.isdigit():
                    log_level = int(func_arg)
                else:
                    uarg = func_arg.upper()
                    if (uarg in logging.__dict__.keys()
                            and isinstance(logging.__dict__[uarg], int)):
                        log_level = logging.__dict__[uarg]
        _logger.parent.setLevel(log_level)

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
    patcher = Patcher(engine, nsm_server)
    return patcher.run_loop, patcher.stop

def run():
    ret = internal_prepare(*sys.argv[1:], nsm_url=os.getenv('NSM_URL', ''))
    if isinstance(ret, int):
        sys.exit(ret)

    start_func, stop_func = ret

    signal.signal(signal.SIGINT, stop_func)
    signal.signal(signal.SIGTERM, stop_func)
    start_func()
    print('c fini')
