#!/usr/bin/python3 -u

# Imports from standard library
import signal
import sys
import os
from pathlib import Path
import logging

root_path = Path(__file__).parents[2]

# allow libs to be imported from submodules and shared
sys.path.insert(1, str(root_path / 'HoustonPatchbay' / 'source'))
sys.path.insert(1, str(root_path / 'src' / 'shared'))

from qt_api import QT_API
os.environ['QT_API'] = QT_API

# third party imports
from qtpy.QtWidgets import QApplication
from qtpy.QtGui import QIcon, QFontDatabase
from qtpy.QtCore import QLocale, QTranslator, QTimer, QLibraryInfo

# Imports from src/shared
import ray
from proc_name import set_proc_name

# Local imports
from gui_tools import (ArgParser, CommandLineArgs,
                       init_gui_tools, get_code_root)
from gui_server_thread import GuiServerThread
from gui_session import SignaledSession

# prevent to not find icon at startup
import resources_rc

_logger = logging.getLogger()


def signal_handler(sig, frame):
    if sig in (signal.SIGINT, signal.SIGTERM):
        if session.daemon_manager.launched_before:
            if (CommandLineArgs.under_nsm
                    and session.server_status is not ray.ServerStatus.OFF):
                session.main_win.terminate_request = True

                l_server = GuiServerThread.instance()
                if l_server:
                    l_server.abort_session()
            else:
                session.daemon_manager.stop()
            return

        session.main_win.terminate_request = True
        session.daemon_manager.stop()
    global terminate
    terminate = True


if True:
    # set logger handlers
    _log_handler = logging.StreamHandler()
    _log_handler.setFormatter(logging.Formatter(
        f"%(levelname)s:%(name)s - %(message)s"))
    _logger.addHandler(_log_handler)
    
    set_proc_name(ray.APP_TITLE.lower())
    
    # set Qt Application
    app = QApplication(sys.argv)
    app.setApplicationName(ray.APP_TITLE)
    app.setApplicationVersion(ray.VERSION)
    app.setOrganizationName(ray.APP_TITLE)
    app.setWindowIcon(QIcon(
        f':main_icon/scalable/{ray.APP_TITLE.lower()}.svg'))
    app.setQuitOnLastWindowClosed(False)
    app.setDesktopFileName(ray.APP_TITLE.lower())

    # with some themes (GNOME fedora 34)
    # QGroupBox are not really visible
    app.setStyleSheet("QGroupBox{background-color: #15888888}")

    ### Translation process
    locale = QLocale.system().name()

    app_translator = QTranslator()
    if app_translator.load(QLocale(), ray.APP_TITLE.lower(),
                           '_', str(get_code_root() / 'locale')):
        app.installTranslator(app_translator)

    patchbay_translator = QTranslator()
    if patchbay_translator.load(
            QLocale(), 'patchbay',
            '_', str(get_code_root() / 'HoustonPatchbay' / 'locale')):
        app.installTranslator(patchbay_translator)

    sys_translator = QTranslator()
    path_sys_translations = QLibraryInfo.location(
        QLibraryInfo.TranslationsPath)
    if sys_translator.load(QLocale(), 'qt', '_', path_sys_translations):
        app.installTranslator(sys_translator)

    QFontDatabase.addApplicationFont(":/fonts/Ubuntu-R.ttf")
    QFontDatabase.addApplicationFont(":/fonts/Ubuntu-C.ttf")

    # get arguments
    parser = ArgParser()
    init_gui_tools()
    
    log_dict = {logging.INFO: CommandLineArgs.info,
                logging.DEBUG: CommandLineArgs.dbg}
    
    for log_level, multimodule in log_dict.items():
        for module in multimodule.split(':'):
            if not module:
                continue

            if module == 'raysession':
                _logger.setLevel(log_level)
                continue

            _mod_logger = logging.getLogger(module)
            _mod_logger.setLevel(log_level)

    # Add raysession/src/bin to $PATH
    # to can use raysession after make, without install
    ray.add_self_bin_to_path()

    #connect signals
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    #needed for signals SIGINT, SIGTERM
    timer = QTimer()
    timer.start(200)
    timer.timeout.connect(lambda: None)

    #build session
    server = GuiServerThread()
    session = SignaledSession()

    app.exec()

    server.stop()
    session.quit()
