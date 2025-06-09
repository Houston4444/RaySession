import logging
from typing import Union, Callable
import os
import signal
import sys

from osclib import Address
from patcher.patcher import Patcher
from patcher.bases import EventHandler
from nsm_client import NsmServer

from .engine import Engine

_logger = logging.getLogger(__name__)
_log_handler = logging.StreamHandler()
_log_handler.setFormatter(logging.Formatter(
    f"%(name)s - %(levelname)s - %(message)s"))
_logger.setLevel(logging.WARNING)
_logger.addHandler(_log_handler)


def internal_prepare(
        *func_args: str, nsm_url='') -> Union[int, tuple[Callable, Callable]]:
    '''Prepare the client, return an integer in case of error,
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

        _logger.setLevel(log_level)

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

