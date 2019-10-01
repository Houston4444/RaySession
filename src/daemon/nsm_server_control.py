#!/usr/bin/python3

import argparse
import liblo
import os
import signal
import sys
import time

from PyQt5.QtCore import QCoreApplication, QTimer, pyqtSignal, QObject

import ray

def signalHandler(sig, frame):
    if sig in (signal.SIGINT, signal.SIGTERM):
        QCoreApplication.quit()


class Signaler(QObject):
    done = pyqtSignal(int)

class OscServerThread(liblo.ServerThread):
    def __init__(self, daemon_port):
        liblo.ServerThread.__init__(self)
        self._daemon_port = daemon_port
        
    #@liblo.make_method('/reply', 'ss')
    #def replyMessage(self, path, args, types, src_addr):
        #reply_path, message = args
        #print('fko', reply_path, message)
        #sys.stdout.write("%s\n" % message)
        
        #if reply_path != '/nsm/server/list':
            #signaler.done.emit(0)
    
    #@liblo.make_method('/reply', 'sis')
    #def replyMessage2(self, path, args, types, src_addr):
        #reply_path, err, message = args
        #sys.stdout.write("%s\n" % message)
        
        #signaler.done.emit(- err)
    
    @liblo.make_method('/reply', None)
    def replyNone(self, path, args, types, src_addr):
        #print('fkorf', args)
        
        if len(args) == 2:
            reply_path, message = args
            #print('fko', reply_path, message)
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
    
    def toDaemon(self, *args):
        self.send(liblo.Address(self._daemon_port), *args)

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
    global exit_code
    exit_code = err_code
    QCoreApplication.quit()

if __name__ == '__main__':
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
    
    nsm_port = 13555
    
    if ray.isOscPortFree(nsm_port):
        sys.stderr.write("No server at port %i\n" % nsm_port)
        sys.exit(100)
    
    exit_code = 0
    
    
    
    app = QCoreApplication(sys.argv)
    signaler = Signaler()
    signaler.done.connect(finished)
    
    osc_server = OscServerThread(nsm_port)
    osc_server.start()
    
    #connect SIGINT and SIGTERM
    signal.signal(signal.SIGINT,  signalHandler)
    signal.signal(signal.SIGTERM, signalHandler)
    
    #needed for SIGINT and SIGTERM
    timer = QTimer()
    timer.setInterval(200)
    timer.timeout.connect(lambda: None)
    timer.start()
    
    #time.sleep(0.201)
    osc_server.toDaemon('/nsm/server/%s' % operation, *arg_list)
    
    app.exec()
    osc_server.stop()
    
    sys.exit(exit_code)
    
