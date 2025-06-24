#!/usr/bin/python3 -u

# Imports from standard library
import logging
import os
import signal
import sys
from typing import TYPE_CHECKING, Callable
from pathlib import Path
from enum import Enum, auto
import time
import shutil


# Imports from src/shared
from osclib import Address
from proc_name import set_proc_name
from nsm_client import NsmCallback

from .sl_server import SlServer
from .main_object import MainObject

if TYPE_CHECKING:
    import jack


_logger = logging.getLogger(__name__)


class ArgRead(Enum):
    NONE = auto()
    LOG = auto()
    OSC_PORT = auto()


def run():
    set_proc_name('ray-sooploop')

    if not shutil.which('sooperlooper'):
        _logger.critical('SooperLooper is not installed.')
        sys.exit(1)

    main = MainObject()
    transport_wk = False

    # set log level and other parameters with exec arguments
    if len(sys.argv) > 1:
        arg_read = ArgRead.NONE
        log_level = logging.WARNING

        for arg in sys.argv[1:]:
            match arg: 
                case '-log'|'--log':
                    arg_read = ArgRead.LOG
                    log_level = logging.DEBUG

                case '-osc-port'|'--osc-port':
                    arg_read = ArgRead.OSC_PORT

                case '--transport_workaround':
                    transport_wk = True
                    arg_read = ArgRead.NONE

                case '--follow-jack-naming':
                    main.follow_jack_naming = True
                    arg_read = ArgRead.NONE

                case _:
                    if arg_read is ArgRead.LOG:
                        if arg.isdigit():
                            log_level = int(uarg)
                        else:
                            uarg = arg.upper()
                            if (uarg in logging.__dict__.keys()
                                    and isinstance(
                                        logging.__dict__[uarg], int)):
                                log_level = logging.__dict__[uarg]
                    
                    elif arg_read is ArgRead.OSC_PORT:
                        if arg.isdigit():
                            main.wanted_osc_port = int(arg)

                    arg_read = ArgRead.NONE

        _logger.setLevel(log_level)
    
    nsm_url = os.getenv('NSM_URL')
    if not nsm_url:
        _logger.error('Could not register as NSM client.')
        sys.exit(1)
    
    try:
        daemon_address = Address(nsm_url)
    except:
        _logger.error('NSM_URL seems to be invalid.')
        sys.exit(1)
        
    nsm_server = SlServer(daemon_address)
    main.nsm_server = nsm_server
    nsm_server.set_callback(NsmCallback.OPEN, main.open_file)
    nsm_server.set_callback(NsmCallback.SAVE, main.save_file)
    nsm_server.set_callback(NsmCallback.SHOW_OPTIONAL_GUI, main.show_optional_gui)
    nsm_server.set_callback(NsmCallback.HIDE_OPTIONAL_GUI, main.hide_optional_gui)
    nsm_server.announce(
        'SooperLooper', ':optional-gui:switch:', Path(sys.argv[0]).name)
    
    # connect program interruption signals
    signal.signal(signal.SIGINT, main.signal_handler)
    signal.signal(signal.SIGTERM, main.signal_handler)

    if transport_wk:
        global jack
        import jack
        try:
            jack_client = jack.Client("sooper_ray_wk", no_start_server=True)
        except:
            jack_client = None
            _logger.error(
                'Failed to add a jack client for transport check, '
                'transport check will be ignored')
            transport_wk = False
        main.jack_client = jack_client

    loop_time = 2 if transport_wk else 50 # ms

    # main loop
    while True:
        if main.leaving:
            break

        nsm_server.recv(loop_time)
        
        if transport_wk:
            main.check_transport()
        
        if main.last_gui_state is not main.gui_running:
            main.last_gui_state = main.gui_running
            nsm_server.send_gui_state(main.last_gui_state)

        if not main.not_started_yet:
            if not main.sl_running:
                break

    # QUIT
    
    # stop GUI
    if main.gui_running:
        main.gui_process.terminate()

    # stop sooperlooper
    if main.sl_running:
        nsm_server.send_sl('/quit')  
        for i in range(1000):
            time.sleep(0.0010)
            if not main.sl_running:
                break
        
        if main.sl_running:
            main.sl_process.terminate()
            for i in range(1000):
                time.sleep(0.0010)
                if not main.sl_running:
                    break

            if main.sl_running:
                main.sl_process.kill()

    sys.exit(0)

def internal_prepare(
        *func_args: str, nsm_url='') -> int | tuple[Callable, Callable]:
    if not shutil.which('sooperlooper'):
        _logger.critical('SooperLooper is not installed.')
        return 1

    main = MainObject()
    transport_wk = False

    # set log level and other parameters with exec arguments
    if func_args:
        arg_read = ArgRead.NONE
        log_level = logging.WARNING

        for arg in func_args:
            match arg: 
                case '-log'|'--log':
                    arg_read = ArgRead.LOG
                    log_level = logging.DEBUG

                case '-osc-port'|'--osc-port':
                    arg_read = ArgRead.OSC_PORT

                case '--transport_workaround':
                    transport_wk = True
                    arg_read = ArgRead.NONE

                case '--follow-jack-naming':
                    main.follow_jack_naming = True
                    arg_read = ArgRead.NONE

                case _:
                    if arg_read is ArgRead.LOG:
                        if arg.isdigit():
                            log_level = int(uarg)
                        else:
                            uarg = arg.upper()
                            if (uarg in logging.__dict__.keys()
                                    and isinstance(
                                        logging.__dict__[uarg], int)):
                                log_level = logging.__dict__[uarg]
                    
                    elif arg_read is ArgRead.OSC_PORT:
                        if arg.isdigit():
                            main.wanted_osc_port = int(arg)

                    arg_read = ArgRead.NONE

        _logger.setLevel(log_level)
    
    if not nsm_url:
        _logger.error('Could not register as NSM client.')
        return 1
    
    try:
        daemon_address = Address(nsm_url)
    except:
        _logger.error('NSM_URL seems to be invalid.')
        return 1
        
    nsm_server = SlServer(daemon_address)
    main.nsm_server = nsm_server
    nsm_server.set_callback(NsmCallback.OPEN, main.open_file)
    nsm_server.set_callback(NsmCallback.SAVE, main.save_file)
    nsm_server.set_callback(NsmCallback.SHOW_OPTIONAL_GUI, main.show_optional_gui)
    nsm_server.set_callback(NsmCallback.HIDE_OPTIONAL_GUI, main.hide_optional_gui)
    main.transport_wk = transport_wk
    
    return internal_start, internal_stop, main, main

def internal_start(data: MainObject):
    main = data
    main.nsm_server.announce(
        'SooperLooper', ':optional-gui:switch:', Path(sys.argv[0]).name)

    if main.transport_wk:
        global jack
        import jack
        try:
            jack_client = jack.Client("sooper_ray_wk", no_start_server=True)
        except:
            jack_client = None
            _logger.error(
                'Failed to add a jack client for transport check, '
                'transport check will be ignored')
            main.transport_wk = False
        main.jack_client = jack_client

    loop_time = 2 if main.transport_wk else 50 # ms

    # main loop
    while True:
        if main.leaving:
            break

        main.nsm_server.recv(loop_time)
        
        if main.transport_wk:
            main.check_transport()
        
        if main.last_gui_state is not main.gui_running:
            main.last_gui_state = main.gui_running
            main.nsm_server.send_gui_state(main.last_gui_state)

        if not main.not_started_yet:
            if not main.sl_running:
                break

    # QUIT
    
    # stop GUI
    if main.gui_running:
        main.gui_process.terminate()

    # stop sooperlooper
    if main.sl_running:
        main.nsm_server.send_sl('/quit')  
        for i in range(1000):
            time.sleep(0.0010)
            if not main.sl_running:
                break
        
        if main.sl_running:
            main.sl_process.terminate()
            for i in range(1000):
                time.sleep(0.0010)
                if not main.sl_running:
                    break

            if main.sl_running:
                main.sl_process.kill()
                
def internal_stop(data: MainObject):
    main = data
    main.leaving = True
