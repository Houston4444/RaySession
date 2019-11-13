#!/usr/bin/python3 -u

import argparse
import liblo
import os
import signal
import sys
import time
import subprocess

from PyQt5.QtCore import (QCoreApplication, QTimer, pyqtSignal,
                          QObject, QProcess, QSettings, pyqtSlot)

import ray
from multi_daemon_file import MultiDaemonFile

OPERATION_TYPE_NULL = 0
OPERATION_TYPE_CONTROL = 1
OPERATION_TYPE_SERVER = 2
OPERATION_TYPE_SESSION = 3
OPERATION_TYPE_CLIENT = 4

control_operations = ('start', 'stop', 'list_daemons', 'get_root', 
                      'get_port', 'get_pid', 'get_session_path')

server_operations = (
    'quit', 'change_root', 'list_session_templates', 
    'list_user_client_templates', 'list_factory_client_templates', 
    'remove_client_template', 'list_sessions', 'new_session',
    'open_session', 'open_session_off', 'save_session_template',
    'rename_session')

session_operations = ('save', 'save_as_template', 'take_snapshot',
                      'close', 'abort', 'duplicate', 'open_snapshot',
                      'rename', 'add_executable', 'add_proxy',
                      'add_client_template', 'list_snapshots',
                      'list_clients')

#client_operations = ('stop', 'kill', 'trash', 'resume', 'save',
                     #'save_as_template', 'show_optional_gui',
                     #'hide_optional_gui', 'update_properties',
                     #'list_snapshots', 'open_snapshot')

def signalHandler(sig, frame):
    if sig in (signal.SIGINT, signal.SIGTERM):
        QCoreApplication.quit()


class Signaler(QObject):
    done = pyqtSignal(int)
    daemon_started = pyqtSignal()
    daemon_no_announce = pyqtSignal()
    message = pyqtSignal(str)
    

class OscServerThread(liblo.ServerThread):
    def __init__(self):
        liblo.ServerThread.__init__(self)
        self.m_daemon_address = None
    
    @liblo.make_method('/reply', None)
    def replyNone(self, path, args, types, src_addr):
        if not ray.areTheyAllString(args):
            return
        
        if len(args) >= 1:
            reply_path = args[0]
        else:
            return
        
        if reply_path != osc_order_path:
            sys.stdout.write('bug: reply for a wrong path:%s instead of %s\n'
                             % (ray.highlightText(reply_path), 
                                ray.highlightText(osc_order_path)))
            return
        
        if reply_path in ('/ray/server/list_sessions',
                          '/ray/server/list_session_templates',
                          '/ray/session/list_clients'):
            if len(args) >= 2:
                sessions = args[1:]
                out_message = ""
                for session in sessions:
                    out_message += "%s\n" % session
                sys.stdout.write(out_message)
                return
            else:
                signaler.done.emit(0)
                
        elif reply_path in ('/ray/server/list_factory_client_templates',
                            '/ray/server/list_user_client_templates'):
            if len(args) >= 2:
                templates = args[1:]
                out_message = ""
                for template_and_icon in templates:
                    template, slash, icon = template_and_icon.partition('/')
                    out_message += "%s\n" % template
                sys.stdout.write(out_message)
                return
            else:
                signaler.done.emit(0)
                
        elif reply_path == '/ray/session/list_snapshots':
            if len(args) >= 2:
                snapshots = args[1:]
                out_message = ""
                for snapshot_and_info in snapshots:
                    snapshot, slash, info = snapshot_and_info.partition(':')
                    out_message += "%s\n" % snapshot
                sys.stdout.write(out_message)
                return
            else:
                signaler.done.emit(0)
            
        elif len(args) == 2:
            reply_path, message = args
            if os.path.basename(reply_path).startswith(('list_', 'add_')):
                sys.stdout.write("%s\n" % message)
            signaler.done.emit(0)
    
    @liblo.make_method('/error', 'sis')
    def errorMessage(self, path, args, types, src_addr):
        error_path, err, message = args
        
        if error_path != osc_order_path:
            sys.stdout.write('bug: error for a wrong path:%s instead of %s\n'
                             % (ray.highlightText(error_path), 
                                ray.highlightText(osc_order_path)))
            return
        
        sys.stdout.write('%s\n' % message)
        
        signaler.done.emit(- err)
    
    @liblo.make_method('/minor_error', 'sis')
    def minorErrorMessage(self, path, args, types, src_addr):
        error_path, err, message = args
        sys.stdout.write('\033[31m%s\033[0m\n' % message)
        if err == ray.Err.UNKNOWN_MESSAGE:
            signaler.done.emit(- err)
    
    @liblo.make_method('/ray/control/message', 's')
    def rayControlMessage(self, path, args, types, src_addr):
        message = args[0]
        signaler.message.emit(message)
        #sys.stdout.write('%s\n' % message)
        
    @liblo.make_method('/ray/control/server/announce', 'siisi')
    def rayControlServerAnnounce(self, path, args, types, src_addr):
        self.m_daemon_address = src_addr
        signaler.daemon_started.emit()
    
    #@liblo.make_method(None, None)
    #def noneMethod(self, path, args, types, src_addr):
        #types_str = ''
        #for t in types:
            #types_str += t
    
    def setDaemonAddress(self, daemon_port):
        self.m_daemon_address = liblo.Address(daemon_port)
        self.toDaemon('/ray/server/controller_announce')
    
    def toDaemon(self, *args):
        self.send(self.m_daemon_address, *args)

def printHelp(stdout=False):
    message="""control RaySession daemons
opions are
    start
        starts a daemon if there is no daemon started
    stop
        stops the default daemon
    list_daemons
        list running daemon osc ports
    get_port
        get daemon osc port
    get_root
        get daemon root directory for sessions
    get_pid
        get deamon pid

    new_session NEW_SESSION_NAME [SESSION_TEMPLATE]
        Creates and loads NEW_SESSION_NAME, optionnally with SESSION_TEMPLATE
    open_session SESSION_NAME [SESSION_TEMPLATE]
        Loads SESSION_NAME (create it if it does not exists
                            optionnally with SESSION_TEMPLATE)
    list_sessions
        Lists available sessions in sessions root directory
    quit
        Aborts current session (if any) and stop the daemon
    change_root NEW_ROOT_FOLDER
        Changes root directory for the sessions to NEW_ROOT_FOLDER
    list_session_templates
        Lists session templates
    list_user_client_templates
        Lists user client templates
    list_factory_client_templates
        Lists factory client templates
    remove_client_template CLIENT_TEMPLATE
        Removes user CLIENT_TEMPLATE
        
    save
        Saves the current session
    save_as_template SESSION_TEMPLATE_NAME
        Saves the current session as template
    take_snapshot SNAPSHOT_NAME
        Takes a snapshot of the current session
    close
        Saves and Closes the current session
    abort
        Aborts current session
    duplicate NEW_SESSION_NAME
        Saves, duplicates the current session and load the new one
    open_snapshot SNAPSHOT
        Saves, close the session, back to SNAPSHOT and re-open it
    rename NEW_SESSION_NAME
        renames the current session to NEW_SESSION_NAME
    add_executable EXECUTABLE
        Adds a client to the current session
    add_proxy
        Adds a proxy client to the current session
    add_client_template CLIENT_TEMPLATE
        Adds a client to the current session from CLIENT_TEMPLATE
    list_snapshots
        Lists all snapshots of the current session
"""
    if stdout:
        sys.stdout.write(message)
    else:
        sys.stderr.write(message)

def printMessage(message):
    sys.stdout.write("%s\n" % message)

@pyqtSlot()
def finished(err_code):
    global exit_code, exit_initiated
    if not exit_initiated:
        exit_initiated = True
        exit_code = err_code
        
        osc_server.toDaemon('/ray/server/controller_disannounce')
        time.sleep(0.010) # prevent impossibility to stop liblo server
        QCoreApplication.quit()

def daemonStarted():
    global daemon_announced
    daemon_announced = True
    
    #print('zoefk', osc_order_path, *arg_list)
    osc_server.toDaemon(osc_order_path, *arg_list)

def daemonNoAnnounce():
    if daemon_announced:
        return
    
    sys.stderr.write("daemon didn't announce and will be killed\n")
    sys.exit(1)

def getDefaultPort():
    for daemon in daemon_list:
        if (daemon.user == os.environ['USER']
                and not daemon.not_default):
            return daemon.port
    return 0

def autoTypeString(string):
    if string.isdigit():
        return int(string)
    elif string.replace('.', '', 1).isdigit():
        return float(string)
    return string
    
    
if __name__ == '__main__':
    ray.addSelfBinToPath()
    
    if len(sys.argv) <= 1:
        printHelp()
        sys.exit(100)
    
    operation_type = OPERATION_TYPE_NULL
    client_id = ''
    
    args = sys.argv[1:]
    operation = args.pop(0)
    if operation == 'client':
        if len(args) < 2:
            printHelp()
            sys.exit(100)
        
        operation_type = OPERATION_TYPE_CLIENT
        client_id = args.pop(0)
        operation = args.pop(0)
    
    if not operation_type:
        if operation in control_operations:
            operation_type = OPERATION_TYPE_CONTROL
        elif operation in server_operations:
            operation_type = OPERATION_TYPE_SERVER
        elif operation in session_operations:
            operation_type = OPERATION_TYPE_SESSION
        else:
            printHelp()
            sys.exit(100)
        
    arg_list = [autoTypeString(s) for s in args]
    if operation_type == OPERATION_TYPE_CLIENT:
        arg_list.insert(0, client_id)
    
    if operation in ('new_session', 'open_session', 'change_root',
                     'save_as_template', 'take_snapshot', 'duplicate',
                     'open_snapshot', 'rename', 'add_executable',
                     'add_client_template'):
        if not arg_list:
            sys.stderr.write('operation %s needs argument(s).\n' % operation)
            sys.exit(100)
    
    exit_code = 0
    exit_initiated = False
    daemon_announced = False
    
    multi_daemon_file = MultiDaemonFile(None, None)
    daemon_list = multi_daemon_file.getDaemonList()
    
    app = QCoreApplication(sys.argv)
    app.setApplicationName(ray.APP_TITLE)
    app.setOrganizationName(ray.APP_TITLE)
    settings = QSettings()
    
    signaler = Signaler()
    signaler.done.connect(finished)
    signaler.daemon_started.connect(daemonStarted)
    signaler.message.connect(printMessage)
    
    osc_server = OscServerThread()
    osc_server.start()
    daemon_list = multi_daemon_file.getDaemonList()
    
    if operation == 'list_daemons':
        for daemon in daemon_list:
            sys.stdout.write('%s\n' % str(daemon.port))
        sys.exit(0)
    
    osc_order_path = '/ray/'
    if operation_type == OPERATION_TYPE_CLIENT:
        osc_order_path += 'client/'
    elif operation_type == OPERATION_TYPE_SERVER:
        osc_order_path += 'server/'
    elif operation_type == OPERATION_TYPE_SESSION:
        osc_order_path += 'session/'
        
    osc_order_path += operation
    
    if operation_type == OPERATION_TYPE_CONTROL and operation == 'stop':
        osc_order_path = '/ray/server/quit'
        
    daemon_port = getDefaultPort()
    
    if daemon_port:
        if operation_type == OPERATION_TYPE_CONTROL:
            if operation == 'start':
                sys.stderr.write('server already started.\n')
                sys.exit(0)
                
            elif operation == 'stop':
                operation = 'quit'
                
            elif operation == 'get_pid':
                for daemon in daemon_list:
                    if daemon.port == daemon_port:
                        sys.stdout.write('%s\n' % str(daemon.pid))
                        sys.exit(0)
                    
            elif operation == 'get_port':
                sys.stdout.write("%s\n" % str(daemon_port))
                sys.exit(0)
                
            elif operation == 'get_root':
                for daemon in daemon_list:
                    if daemon.port == daemon_port:
                        sys.stdout.write('%s\n' % daemon.root)
                        sys.exit(0)
                    
            elif operation == 'get_session_path':
                for daemon in daemon_list:
                    if daemon.port == daemon_port:
                        sys.stdout.write('%s\n' % daemon.session_path)
                        sys.exit(0)
        
        osc_server.setDaemonAddress(daemon_port)
        signaler.daemon_started.emit()
    else:
        if operation_type == OPERATION_TYPE_CONTROL:
            if operation == 'stop':
                sys.stderr.write('No server started.\n')
                sys.exit(0)
            elif operation == 'start':
                pass
            else:
                sys.stderr.write(
                    'No server started. So impossible to %s\n' % operation)
                sys.exit(100)
        
        elif operation_type == OPERATION_TYPE_SERVER:
            if operation == 'quit':
                sys.stderr.write('No server to quit !\n')
                sys.exit(0)
        
        elif operation_type == OPERATION_TYPE_SESSION:
            sys.stderr.write("No server started. So no session to %s\n"
                                 % operation)
            sys.exit(100)
        elif operation_type == OPERATION_TYPE_CLIENT:
            sys.stderr.write("No server started. So no client to %s\n"
                                 % operation)
            sys.exit(100)
        else:
            printHelp()
            sys.exit(100)
        
        session_root = settings.value('default_session_root',
                                      ray.DEFAULT_SESSION_ROOT)
        
        # start a daemon because no one is running
        #daemon_process = subprocess.Popen(
            #['ray-daemon', '--control-url', str(osc_server.url),
             #'--session-root', session_root])
        daemon_process = subprocess.Popen(
            ['ray-daemon', '--control-url', str(osc_server.url),
             '--session-root', session_root],
            -1, None, None, subprocess.DEVNULL, subprocess.DEVNULL)
        QTimer.singleShot(2000, daemonNoAnnounce)
    
    #connect SIGINT and SIGTERM
    signal.signal(signal.SIGINT,  signalHandler)
    signal.signal(signal.SIGTERM, signalHandler)
    
    #needed for SIGINT and SIGTERM
    timer = QTimer()
    timer.setInterval(200)
    timer.timeout.connect(lambda: None)
    timer.start()
    
    if not(operation_type == OPERATION_TYPE_CONTROL and operation == 'start'):
        app.exec()
        
    osc_server.stop()
    del osc_server
    del app
    
    sys.exit(exit_code)
