#!/usr/bin/python3 -u

# standard lib imports
import signal
import sys
import warnings
from pathlib import Path
import logging

# imports from shared/
from proc_name import set_proc_name

# local imports
from main_object import MainObject


IS_INTERNAL = not Path(sys.path[0]).name == __name__
if IS_INTERNAL:
    _logger = logging.getLogger(__name__)
else:
    _logger = logging.getLogger()
    _log_handler = logging.StreamHandler()
    _log_handler.setFormatter(logging.Formatter(
        f"%(levelname)s:%(name)s - %(message)s"))
    _logger.addHandler(_log_handler)


def main_process(daemon_port_str: str, gui_tcp_url: str,
                 pretty_names_active: bool):
    try:
        daemon_port = int(daemon_port_str)
    except:
        _logger.critical(
            f'daemon port must be an integer, not "{daemon_port_str}"')
        return
        
    main_object = MainObject(daemon_port, gui_tcp_url, pretty_names_active)
    main_object.osc_server.add_gui(gui_tcp_url)
    if main_object.osc_server.gui_list:
        main_object.start_loop()
    # main_object.exit()

def start():
    '''launch the process when it is a process (not internal).'''
    set_proc_name('ray-patch_dmn')
    
    # prevent deprecation warnings python messages
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    
    signal.signal(signal.SIGINT, MainObject.signal_handler)
    signal.signal(signal.SIGTERM, MainObject.signal_handler)
    
    args = sys.argv.copy()
    daemon_port_str = ''
    gui_url = ''
    pretty_names_active = True
    one_shot_act = ''
    log = ''
    dbg = ''

    args.pop(0)

    if args:
        daemon_port_str = args.pop(0)
    if args:
        gui_url = args.pop(0)
    if args:
        pns = args.pop(0)
        pretty_names_active = not bool(pns.lower() in ('0', 'false'))
        args.pop(0)
    if args:
        one_shot_act = args.pop(0)
    if args[0] == '--log':
        args.pop(0)
        log = args.pop(0)
    if args[0] == '--dbg':
        args.pop(0)
        dbg = args.pop(0)
    
    level = logging.INFO
    for lv_info in (log, dbg):
        for module_name in lv_info.split(':'):
            if module_name == 'patchbay_daemon':
                _logger.setLevel(level)
            elif module_name.startswith('patchbay_daemon.'):
                sh_mod_name = module_name.partition('.')[2]
                mod_logger = logging.getLogger(sh_mod_name)
                mod_logger.setLevel(level)

        level = logging.DEBUG
    
    try:
        daemon_port = int(daemon_port_str)
    except:
        _logger.critical(
            f'daemon port must be an integer, not "{daemon_port_str}"')
        return
    
    main_object = MainObject(
        daemon_port, gui_url, pretty_names_active, one_shot_act)

    if gui_url:
        main_object.osc_server.add_gui(gui_url)
    main_object.start_loop()
    
def internal_prepare(
        daemon_port: str, gui_url: str, pretty_names_active: str,
        one_shot_act: str, nsm_url=''):
    pretty_name_active_bool = not bool(
        pretty_names_active.lower() in ('0', 'false'))
    main_object = MainObject(
        int(daemon_port), gui_url, pretty_name_active_bool, one_shot_act)

    if gui_url:
        main_object.osc_server.add_gui(gui_url)
        if not main_object.osc_server.gui_list:
            return 1
    return main_object.start_loop, main_object.internal_stop
