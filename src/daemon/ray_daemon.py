#!/usr/bin/python3 -u

# Standard lib imports
import os
import sys
from pathlib import Path
import logging
import signal

# set HoustonPatchbay/patchbay, src/shared/* and 
# modules usable as internal client as libs
sys.path.insert(1, str(Path(__file__).parents[2] / 'HoustonPatchbay/source'))
sys.path.insert(1, str(Path(__file__).parents[1] / 'patchbay_daemon'))
sys.path.insert(1, str(Path(__file__).parents[1] / 'clients'))
sys.path.insert(1, str(Path(__file__).parents[1] / 'shared'))

sys.path[0] = str(Path(__file__).parent)

# Set QT_API environment variable, to make qtpy knows
# if it should use Qt5 or Qt6
from qt_api import QT_API
os.environ['QT_API'] = QT_API

# third party imports
from qtpy.QtCore import (
    QCoreApplication, QTimer, QLocale, QTranslator)

# set logger
_logger = logging.getLogger()

# Imports from HoustonPatchbay
from patshared import Naming

# Imports from src/shared
from osclib import get_free_osc_port, is_osc_port_free, get_net_url, Address
import ray

# Local imports
from daemon_tools import (
    get_code_root, init_daemon_tools, RS,
    CommandLineArgs, ArgParser, LogStreamHandler)
from osc_server_thread import OscServerThread
import multi_daemon_file
from session_signaled import SignaledSession
import patchbay_dmn_mng


_terminate = False

def signal_handler(sig, frame):
    if sig in (signal.SIGINT, signal.SIGTERM):
        session.terminate()
        global _terminate
        _terminate = True


# if __name__ == '__main__':
if True:
    # set logger handlers
    _log_handler = LogStreamHandler()
    _log_handler.setFormatter(logging.Formatter(
        f"%(levelname)s:%(name)s - %(message)s"))
    _logger.addHandler(_log_handler)
    
    # add RaySession/src/bin to $PATH
    ray.add_self_bin_to_path()

    # create app
    app = QCoreApplication(sys.argv)
    app.setApplicationName("RaySession")
    app.setOrganizationName("RaySession")

    init_daemon_tools()
    
    # Translation process
    locale = QLocale.system().name()
    appTranslator = QTranslator()

    if appTranslator.load(
        str(get_code_root() / 'locale' / f'raysession_{locale}')):
        app.installTranslator(appTranslator)

    _translate = app.translate

    # check arguments
    parser = ArgParser()

    log_dict = {logging.INFO: CommandLineArgs.info,
                logging.DEBUG: CommandLineArgs.dbg}
    
    for log_level, multimodule in log_dict.items():
        for module in multimodule.split(':'):
            if not module:
                continue

            if module in ('ray_daemon', 'daemon'):
                _logger.setLevel(log_level)
                continue
            
            _mod_logger = logging.getLogger(module)
            _mod_logger.setLevel(log_level)

    # make session_root folder if needed
    if not CommandLineArgs.session_root.is_dir():
        if CommandLineArgs.session_root.exists():
            _logger.error(
                f'"{CommandLineArgs.session_root}" exists and is not a dir, '
                'please choose another path !')
            sys.exit(1)

        try:
            CommandLineArgs.session_root.mkdir(parents=True)
        except:
            _logger.error(
                f'impossible to make dir "{CommandLineArgs.session_root}", '
                'aborted !')
            sys.exit(1)

    # create session
    session = SignaledSession(CommandLineArgs.session_root)

    # create and start server
    if CommandLineArgs.findfreeport:
        server = OscServerThread(
            session,
            osc_num=get_free_osc_port(CommandLineArgs.osc_port))
    else:
        if is_osc_port_free(CommandLineArgs.osc_port):
            server = OscServerThread(
                session,
                osc_num=CommandLineArgs.osc_port)
        else:
            sys.stderr.write(
                _translate('daemon',
                           'port %i is not free, try another one\n')
                % CommandLineArgs.osc_port)
            sys.exit()

    patchbay_dmn_mng.set_daemon_server(server)
    server.start()

    # print server url
    session.message(f'URL : {get_net_url(server.port)}')
    session.message(f'      {server.url}')
    session.message(f'ROOT: {CommandLineArgs.session_root}')

    if CommandLineArgs.hidden:
        server.not_default = True

    # announce server to GUI
    if CommandLineArgs.gui_url:
        server.announce_gui(CommandLineArgs.gui_url.url,
                            gui_pid=CommandLineArgs.gui_pid,
                            tcp_addr=CommandLineArgs.gui_tcp_url)

    elif CommandLineArgs.gui_port:
        server.announce_gui(Address(CommandLineArgs.gui_port).url,
                            gui_pid=CommandLineArgs.gui_pid,
                            tcp_addr=CommandLineArgs.gui_tcp_url)        

    # announce to ray_control if launched from it.
    if CommandLineArgs.control_url:
        server.announce_controller(CommandLineArgs.control_url)

    if server.jack_export_naming & Naming.CUSTOM:
        patchbay_dmn_mng.start()

    # create or update multi_daemon_file in /tmp
    multi_daemon_file.init(session, server)    
    multi_daemon_file.update()

    # clean bookmarks created by crashed daemons
    session.bookmarker.clean(multi_daemon_file.get_all_session_paths())

    # load session asked from command line
    if CommandLineArgs.session:
        session.server_open_session_at_start(CommandLineArgs.session)

    # connect SIGINT and SIGTERM
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # needed for SIGINT and SIGTERM
    timer = QTimer()
    timer.setInterval(200)
    timer.timeout.connect(lambda: None)
    timer.start()

    # run main loop app
    app.exec()
    # app is stopped

    # update multi_daemon_file without this server
    multi_daemon_file.quit()

    # save RS.settings
    RS.settings.setValue('daemon/non_active_list', RS.non_active_clients)
    RS.settings.setValue('daemon/favorites', RS.favorites)

    recent_sessions = dict[str, list[str]]()
    for root_path, sessions in session.recent_sessions.items():
        recent_sessions[str(root_path)] = sessions

    RS.settings.setValue('daemon/recent_sessions', recent_sessions)
    if not CommandLineArgs.no_options:
        RS.settings.setValue('daemon/options', server.options.value)

    if server._terminal_command_is_default:
        RS.settings.setValue('daemon/terminal_command', '')
    else:
        RS.settings.setValue('daemon/terminal_command', server.terminal_command)

    # save JSON config group positions
    session.canvas_saver.save_config_file()
    patchbay_dmn_mng.daemon_exit()
    
    # save sessions infos in cache
    session.save_folder_sizes_cache_file()

    RS.settings.sync()

    # stop the server
    server.stop()
