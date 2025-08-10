#!/usr/bin/python3 -u

# standard lib imports
import signal
import sys
import warnings
from pathlib import Path
import logging

# imports from shared/
from proc_name import set_proc_name

# imports from HoustonPatchbay
from patch_engine import PatchEngine

# local imports
from osc_server import PatchbayDaemonServer
from ray_patch_engine_outer import RayPatchEngineOuter


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
    pe: PatchEngine
    osc_server: PatchbayDaemonServer
    pe, osc_server = args

    pe.start(RayPatchEngineOuter(osc_server))
    if osc_server._tmp_gui_url:
        osc_server.add_gui(osc_server._tmp_gui_url)

    n = 0

    while True:
        osc_server.recv(50)
        
        if pe.can_leave:
            break

        if pe.jack_running:
            if n % 4 == 0:
                pe.remember_dsp_load()
                if pe.dsp_wanted and n % 20 == 0:
                    pe.send_dsp_load()
            
            pe.process_patch_events()
            pe.check_pretty_names_export()
            pe.send_transport_pos()

            if pe.custom_names_ready and pe.one_shot_act:
                pe.peo.make_one_shot_act(pe.one_shot_act)
                pe.one_shot_act = ''
                if pe.can_leave:
                    break
        else:
            if n % 10 == 0:
                if pe.client is not None:
                    _logger.debug(
                        'deactivate JACK client after server shutdown')
                    pe.client.deactivate()
                    _logger.debug('close JACK client after server shutdown')
                    pe.client.close()
                    _logger.debug('close JACK client done')
                    pe.client = None
                _logger.debug('try to start JACK')
                pe.start_jack_client()

        n += 1
        
        # for faster modulos
        if n == 20:
            n = 0

    pe.exit()

def start():
    '''launch the process when it is a process (not internal).'''
    set_proc_name('ray-patch_dmn')
    
    # prevent deprecation warnings python messages
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    
    signal.signal(signal.SIGINT, PatchEngine.signal_handler)
    signal.signal(signal.SIGTERM, PatchEngine.signal_handler)
    
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
    
    pretty_tmp_path = (Path('/tmp/RaySession/')
                       / f'pretty_names.{daemon_port}.json')

    patch_engine = PatchEngine('ray-patch_dmn', pretty_tmp_path,
                               auto_export_pretty_names)
    patch_engine.mdata_locker_value = daemon_port_str
    patch_engine.one_shot_act = one_shot_act
    osc_server = PatchbayDaemonServer(patch_engine, daemon_port)
    osc_server.set_tmp_gui_url(gui_url)
    main_loop((patch_engine, osc_server))

def internal_prepare(
        daemon_port: str, gui_url: str, pretty_names_active: str,
        one_shot_act: str, nsm_url=''):
    pretty_tmp_path = (Path('/tmp/RaySession/')
                       / f'pretty_names.{daemon_port}.json')
    auto_export_pretty_names = not bool(
        pretty_names_active.lower() in ('0', 'false'))
    patch_engine = PatchEngine('ray-patch_dmn', pretty_tmp_path,
                               auto_export_pretty_names)
    patch_engine.mdata_locker_value = daemon_port
    patch_engine.one_shot_act = one_shot_act

    osc_server = PatchbayDaemonServer(patch_engine, int(daemon_port))
    osc_server.set_tmp_gui_url(gui_url)

    return (main_loop, patch_engine.internal_stop,
            (patch_engine, osc_server), None)
