#!/usr/bin/python3

import argparse
import liblo
import os
import signal
import sys
import time

from PyQt5.QtCore import (QCoreApplication, QTimer, pyqtSignal,
                          QObject, QProcess, QSettings)

import ray
from multi_daemon_file import MultiDaemonFile

def signalHandler(sig, frame):
    if sig in (signal.SIGINT, signal.SIGTERM):
        QCoreApplication.quit()

class Signaler(QObject):
    done = pyqtSignal(int)
    daemon_started = pyqtSignal()


class OscServerThread(liblo.ServerThread):
    def __init__(self):
        liblo.ServerThread.__init__(self)
        self.m_daemon_address = None
    
    @liblo.make_method('/reply', None)
    def replyNone(self, path, args, types, src_addr):
        if len(args) >= 1:
            reply_path = args[0]
        else:
            return
        
        if reply_path == '/ray/server/list_sessions':
            if len(args) >= 2:
                sessions = args[1:]
                out_message = ""
                for session in sessions:
                    out_message += "%s\n" % session
                sys.stdout.write(out_message)
                return
            else:
                signaler.done.emit(0)
            
        if len(args) == 2:
            reply_path, message = args
            sys.stdout.write("%s\n" % message)
            
            if reply_path != '/nsm/server/list':
                signaler.done.emit(0)
        elif len(args) == 3:
            reply_path, err, message = args
            sys.stdout.write("%s\n" % message)
            
            signaler.done.emit(- err)
    
    @liblo.make_method('/error', 'sis')
    def errorMessage(self, path, args, types, src_addr):
        error_path, err, message = args
        sys.stdout.write('%s\n' % message)
        
        signaler.done.emit(- err)
    
    # this is very strange
    # nsmd sends a /nsm/server/list err Ok message when list is done.
    @liblo.make_method('/nsm/server/list', 'is')
    def nsmServerList(self, path, args, types, src_addr):
        signaler.done.emit(0)
        
    @liblo.make_method('/ray/gui/server/announce', 'siisi')
    def rayGuiServerAnnounce(self, path, args, types, src_addr):
        self.m_daemon_address = src_addr
        signaler.daemon_started.emit()
        
    def setDaemonAddress(self, daemon_port):
        self.m_daemon_address = liblo.Address(daemon_port)
    
    def toDaemon(self, *args):
        self.send(self.m_daemon_address, *args)

def printHelp():
    sys.stdout.write(
        """control NSM server,
opions are
    add executable_name
        Adds a client to the current session.
    save
        Saves the current session.
    open project_name
        Saves the current session and loads a new session.
    new project_name
        Saves the current session and creates a new session.
    duplicate new_project
        Saves and closes the current session, makes a copy, and opens it.
    close
        Saves and closes the current session.
    abort
        Closes the current session *WITHOUT SAVING*  
    quit
        Saves and closes the current session and terminates the server.
    list 
        Lists available projects.
""")
    sys.exit(0)

#class finisher(QObject):
    #def finished(self, err_code):
        #global exit_code
        #exit_code = err_code
        #QCoreApplication.quit()
        
def finished(err_code):
    global exit_code, exit_initiated
    if not exit_initiated:
        exit_initiated = True
        exit_code = err_code
        QCoreApplication.quit()

def daemonStarted():
    if operation == 'list':
        osc_server.toDaemon('/ray/server/list_sessions', 0)
    else:
        osc_server.toDaemon('/nsm/server/%s' % operation, *arg_list)

def getDefaultPort():
    daemon_list = multi_daemon_file.getDaemonList()
    
    for daemon in daemon_list:
        if (daemon.user == os.environ['USER']
                and not daemon.not_default):
            return daemon.port
    return 0

if __name__ == '__main__':
    ray.addSelfBinToPath()
    
    if len(sys.argv) <= 1:
        printHelp()
        sys.exit(100)
    
    operation = sys.argv[1]
    if not operation in ('add', 'save', 'open', 'new', 'duplicate', 
                         'close', 'abort', 'quit', 'list'):
        printHelp()
        sys.exit(100)
    
    arg_list = []
    if len(sys.argv) >= 3:
        arg_list = sys.argv[2:]
    
    if operation in ('add', 'open', 'new', 'duplicate'):
        if not arg_list:
            sys.stderr.write('missing argument after "%s"\n' % operation)
            sys.exit(100)
    
    exit_code = 0
    exit_initiated = False
    
    multi_daemon_file = MultiDaemonFile(None, None)
    daemon_list = multi_daemon_file.getDaemonList()
    
    app = QCoreApplication(sys.argv)
    app.setApplicationName("RaySession")
    app.setOrganizationName("RaySession")
    settings = QSettings()
    
    signaler = Signaler()
    signaler.done.connect(finished)
    signaler.daemon_started.connect(daemonStarted)
    
    osc_server = OscServerThread()
    osc_server.start()
    daemon_port = getDefaultPort()
    
    if daemon_port:
        osc_server.setDaemonAddress(nsm_port)
        signaler.daemon_started.emit()
    else:
        session_root = settings.value('default_session_root',
                            '%s/Ray Sessions' % os.getenv('HOME'))
        
        # start a daemon because no one is running
        # fake to be a gui to get daemon announce
        QProcess.startDetached('ray-daemon',
            ['--gui-url', str(osc_server.url),
             '--session-root', session_root])
    
    #connect SIGINT and SIGTERM
    signal.signal(signal.SIGINT,  signalHandler)
    signal.signal(signal.SIGTERM, signalHandler)
    
    #needed for SIGINT and SIGTERM
    timer = QTimer()
    timer.setInterval(200)
    timer.timeout.connect(lambda: None)
    timer.start()
    
    ##time.sleep(0.201)
    #if nsm_port:
        #osc_server.toDaemon('/nsm/server/%s' % operation, *arg_list)
    
    app.exec()
    osc_server.stop()
        
    sys.exit(exit_code)
    
