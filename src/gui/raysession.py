#!/usr/bin/python3 -u

#libs
import signal
import sys
import time
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QIcon, QFontDatabase
from PyQt5.QtCore import QLocale, QTranslator, QTimer, QLibraryInfo

#local imports
from gui_tools import ArgParser, CommandLineArgs, initGuiTools, getCodeRoot
from gui_server_thread import GUIServerThread
from gui_session import SignaledSession
import ray


def signalHandler(sig, frame):
    if sig in (signal.SIGINT, signal.SIGTERM):
        if session._daemon_manager.launched_before:
            if (CommandLineArgs.under_nsm
                    and session.server_status != ray.ServerStatus.OFF):
                session._main_win.terminate_request = True

                l_server = GUIServerThread.instance()
                if l_server:
                    l_server.abortSession()
            else:
                session._daemon_manager.stop()
            return

        session._main_win.terminate_request = True
        session._daemon_manager.stop()

if __name__ == '__main__':
    #set Qt Application
    app = QApplication(sys.argv)
    app.setApplicationName("RaySession")
    app.setApplicationVersion(ray.VERSION)
    app.setOrganizationName("RaySession")
    app.setWindowIcon(QIcon(':/scalable/raysession.svg'))
    app.setQuitOnLastWindowClosed(False)
    app.setDesktopFileName('raysession')

    ### Translation process
    locale = QLocale.system().name()
    appTranslator = QTranslator()
    if appTranslator.load("%s/locale/raysession_%s" % (getCodeRoot(), locale)):
        app.installTranslator(appTranslator)

    sysTranslator = QTranslator()
    pathSysTranslations = QLibraryInfo.location(QLibraryInfo.TranslationsPath)
    sysTranslator.load("%s/qt_%s" % (pathSysTranslations, locale))
    
    QFontDatabase.addApplicationFont(":/fonts/Ubuntu-R.ttf")
    QFontDatabase.addApplicationFont(":fonts/Ubuntu-C.ttf")

    #get arguments
    parser = ArgParser()

    initGuiTools()

    #Add raysession/src/bin to $PATH to can use raysession after make, whitout install
    ray.addSelfBinToPath()

    #connect signals
    signal.signal(signal.SIGINT, signalHandler)
    signal.signal(signal.SIGTERM, signalHandler)

    #needed for signals SIGINT, SIGTERM
    timer = QTimer()
    timer.start(200)
    timer.timeout.connect(lambda: None)

    #build session
    server = GUIServerThread()
    session = SignaledSession()

    app.exec()

    # TODO find something better, sometimes program never ends without.
    time.sleep(0.002)

    server.stop()
    session.quit()
    del session
    del app
