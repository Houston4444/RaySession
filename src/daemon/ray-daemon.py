#!/usr/bin/python3 -u

import os
import signal
import sys

from PyQt5.QtCore import (QCoreApplication, QTimer,
                          QLocale, QTranslator)

import ray
from daemon_tools import (init_daemon_tools, RS, get_code_root,
                          CommandLineArgs, ArgParser, Terminal)
from osc_server_thread import OscServerThread
from multi_daemon_file import MultiDaemonFile
from session_signaled import SignaledSession

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

    if appTranslator.load("%s/locale/raysession_%s"
                          % (get_code_root(), locale)):
        app.installTranslator(appTranslator)

    _translate = app.translate

    # check arguments
    parser = ArgParser()

    # manage session_root
    session_root = CommandLineArgs.session_root
    if not session_root:
        session_root = "%s/%s" % (os.getenv('HOME'),
                                  _translate('daemon',
                                             'Ray Network Sessions'))

    # make session_root folder if needed
    if not os.path.isdir(session_root):
        if os.path.exists(session_root):
            sys.stderr.write(
                "%s exists and is not a dir, please choose another path !\n"
                % session_root)
            sys.exit(1)

        try:
            os.makedirs(session_root)
        except:
            sys.stderr.write("impossible to make dir %s , aborted !\n"
                             % session_root)
            sys.exit(1)


    # create session
    session = SignaledSession(session_root)

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
    RS.settings.setValue('daemon/recent_sessions', session.recent_sessions)
    if not CommandLineArgs.no_options:
        RS.settings.setValue('daemon/options', server.options)

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
