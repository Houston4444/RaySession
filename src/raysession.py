#!/usr/bin/python3 -u

#libs
import signal
import sys
import time

from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QIcon, QFontDatabase
from PyQt5.QtCore import QLocale, QTranslator, QTimer, QLibraryInfo

#local imports
from gui.gui_tools import ArgParser, CommandLineArgs, init_gui_tools, get_code_root
from gui.gui_server_thread import GuiServerThread
from gui.gui_session import SignaledSession
import gui.ray as ray


def signal_handler(sig, frame):
    if sig in (signal.SIGINT, signal.SIGTERM):
        if session.daemon_manager.launched_before:
            if (CommandLineArgs.under_nsm
                    and session.server_status != ray.ServerStatus.OFF):
                session.main_win.terminate_request = True

                l_server = GuiServerThread.instance()
                if l_server:
                    l_server.abort_session()
            else:
                session.daemon_manager.stop()
            return

        session.main_win.terminate_request = True
        session.daemon_manager.stop()

if __name__ == '__main__':
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
                           '_', "%s/locale" % get_code_root()):
        app.installTranslator(app_translator)

    patchbay_translator = QTranslator()
    if patchbay_translator.load(QLocale(), 'patchbay',
                                '_', "%s/HoustonPatchbay/locale" % get_code_root()):
        app.installTranslator(patchbay_translator)

    sys_translator = QTranslator()
    path_sys_translations = QLibraryInfo.location(QLibraryInfo.TranslationsPath)
    if sys_translator.load(QLocale(), 'qt', '_', path_sys_translations):
        app.installTranslator(sys_translator)

    QFontDatabase.addApplicationFont(":/fonts/Ubuntu-R.ttf")
    QFontDatabase.addApplicationFont(":fonts/Ubuntu-C.ttf")

    # get arguments
    parser = ArgParser()

    init_gui_tools()

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

    # TODO find something better, sometimes program never ends without.
    time.sleep(0.002)

    server.stop()
    session.quit()
    del session
    del app
