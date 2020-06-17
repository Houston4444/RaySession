#!/usr/bin/python3 -u

#libs
import argparse
import os
import signal
import sys
import time
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QIcon, QFontDatabase
from PyQt5.QtCore import QLocale, QTranslator, QTimer

#local imports
from gui_signaler import Signaler
from daemon_manager import DaemonManager
from gui_tools import (
    ArgParser, CommandLineArgs, initGuiTools, default_session_root,
    ErrDaemon, _translate, getCodeRoot)
from gui_server_thread import GUIServerThread
from gui_session import SignaledSession
import nsm_client
import ray

#import UIs
import ui_raysession
import ui_client_slot

#import Qt resources
import resources_rc


def signalHandler(sig, frame):
    if sig in (signal.SIGINT, signal.SIGTERM):
        if session._daemon_manager.launched_before:
            if (CommandLineArgs.under_nsm
                    and session.server_status != ray.ServerStatus.OFF):
                session._main_win.terminate_request = True
                
                server = GUIServerThread.instance()
                if server:
                    server.abortSession()
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
    
    QFontDatabase.addApplicationFont(":/fonts/Ubuntu-R.ttf")
    QFontDatabase.addApplicationFont(":fonts/Ubuntu-C.ttf")
    
    initGuiTools()
    
    #Add raysession/src/bin to $PATH to can use raysession after make, whitout install
    ray.addSelfBinToPath()
    
    #get arguments
    parser = ArgParser()
    
    #connect signals
    signal.signal(signal.SIGINT , signalHandler)
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
