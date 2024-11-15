#!/usr/bin/python3 -u

import os
from pathlib import Path
import signal
import sys
import logging

from qt_api import QT_API
os.environ['QT_API'] = QT_API

from qtpy.QtCore import (
    QCoreApplication, QTimer, QLocale, QTranslator)

import ray
from daemon_tools import (get_code_root, init_daemon_tools, RS,
                          CommandLineArgs, ArgParser, Terminal)
from osc_server_thread import OscServerThread
from multi_daemon_file import MultiDaemonFile
from session_signaled import SignaledSession


_logger = logging.getLogger(__name__)
_log_handler = logging.StreamHandler()
_log_handler.setFormatter(logging.Formatter(
    f"%(name)s - %(levelname)s - %(message)s"))
_logger.setLevel(logging.DEBUG)
_logger.addHandler(_log_handler)


def signal_handler(sig, frame):
    if sig in (signal.SIGINT, signal.SIGTERM):
        session.terminate()


if __name__ == '__main__':
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

    # manage session_root
    session_root = CommandLineArgs.session_root
    if not session_root:
        session_root = str(Path(os.getenv('HOME'))
                           / _translate('daemon', 'Ray Network Sessions'))

    session_root_path = Path(session_root)
    # make session_root folder if needed
    if not session_root_path.is_dir():
        if session_root_path.exists():
            sys.stderr.write(
                "%s exists and is not a dir, please choose another path !\n"
                % session_root_path)
            sys.exit(1)

        try:
            session_root_path.mkdir(parents=True)
        except:
            sys.stderr.write("impossible to make dir %s , aborted !\n"
                             % session_root_path)
            sys.exit(1)


    # create session
    session = SignaledSession(session_root_path)

    # create and start server
    if CommandLineArgs.findfreeport:
        server = OscServerThread(session,
                                 ray.get_free_osc_port(
                                     CommandLineArgs.osc_port))
    else:
        if ray.is_osc_port_free(CommandLineArgs.osc_port):
            server = OscServerThread(session, CommandLineArgs.osc_port)
        else:
            sys.stderr.write(
                _translate('daemon',
                           'port %i is not free, try another one\n')
                % CommandLineArgs.osc_port)
            sys.exit()
    server.start()

    if CommandLineArgs.hidden:
        server.not_default = True

    # announce server to GUI
    if CommandLineArgs.gui_url:
        server.announce_gui(CommandLineArgs.gui_url.url,
                            gui_pid=CommandLineArgs.gui_pid)
    elif CommandLineArgs.gui_port:
        server.announce_gui(CommandLineArgs.gui_port.url,
                            gui_pid=CommandLineArgs.gui_pid)

    # announce to ray_control if launched from it.
    if CommandLineArgs.control_url:
        server.announce_controller(CommandLineArgs.control_url)

    # print server url
    Terminal.message('URL : %s' % ray.get_net_url(server.port))
    Terminal.message('      %s' % server.url)
    Terminal.message('ROOT: %s' % CommandLineArgs.session_root)

    # create or update multi_daemon_file in /tmp
    multi_daemon_file = MultiDaemonFile(session, server)
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

    # start app
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
    
    # save sessions infos in cache
    session.save_folder_sizes_cache_file()

    RS.settings.sync()

    # stop the server
    server.stop()

    del server
    del session
    del app
