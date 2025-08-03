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
from osc_server import PatchbayDaemonServer
from ray_patch_engine import RayPatchEngine


IS_INTERNAL = not Path(sys.path[0]).name == __name__
if IS_INTERNAL:
    _logger = logging.getLogger(__name__)
else:
    _logger = logging.getLogger()
    _log_handler = logging.StreamHandler()
    _log_handler.setFormatter(logging.Formatter(
        f"%(levelname)s:%(name)s - %(message)s"))
    _logger.addHandler(_log_handler)


def main_loop(args):
    mo: MainObject
    osc_server: PatchbayDaemonServer
    mo, osc_server = args

    mo.start(RayPatchEngine(osc_server, mo.daemon_port))
    osc_server.add_gui(osc_server._tmp_gui_url)
    
    n = 0

    while True:
        osc_server.recv(50)
        
        if mo.can_leave:
            break

        if mo.jack_running:
            if n % 4 == 0:
                mo.remember_dsp_load()
                if mo.dsp_wanted and n % 20 == 0:
                    mo.send_dsp_load()
            
            mo.process_patch_events()
            mo.check_pretty_names_export()
            mo.send_transport_pos()

            if mo.pretty_names_ready and mo.one_shot_act:
                mo.pbe.make_one_shot_act(mo.one_shot_act)
                mo.one_shot_act = ''
                if mo.can_leave:
                    break
        else:
            if n % 10 == 0:
                if mo.client is not None:
                    _logger.debug(
                        'deactivate JACK client after server shutdown')
                    mo.client.deactivate()
                    _logger.debug('close JACK client after server shutdown')
                    mo.client.close()
                    _logger.debug('close JACK client done')
                    mo.client = None
                _logger.debug('try to start JACK')
                mo.start_jack_client()

        n += 1
        
        # for faster modulos
        if n == 20:
            n = 0

    mo.exit()

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
    auto_export_pretty_names = True
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
        auto_export_pretty_names = not bool(pns.lower() in ('0', 'false'))
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
    
    main_object = MainObject(daemon_port)
    main_object.auto_export_pretty_names = auto_export_pretty_names
    main_object.one_shot_act = one_shot_act
    osc_server = PatchbayDaemonServer(main_object)
    osc_server.set_tmp_gui_url(gui_url)
    main_loop((main_object, osc_server))

def internal_prepare(
        daemon_port: str, gui_url: str, pretty_names_active: str,
        one_shot_act: str, nsm_url=''):
    main_object = MainObject(int(daemon_port))
    main_object.auto_export_pretty_names = not bool(
        pretty_names_active.lower() in ('0', 'false'))
    main_object.one_shot_act = one_shot_act

    osc_server = PatchbayDaemonServer(main_object)
    osc_server.set_tmp_gui_url(gui_url)

    return (main_loop, main_object.internal_stop,
            (main_object, osc_server), None)
