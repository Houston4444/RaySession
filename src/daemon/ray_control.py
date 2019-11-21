#!/usr/bin/python3 -u

import liblo
import os
import signal
import sys
import time
import subprocess
import xml.etree.ElementTree as ET

OPERATION_TYPE_NULL = 0
OPERATION_TYPE_CONTROL = 1
OPERATION_TYPE_SERVER = 2
OPERATION_TYPE_SESSION = 3
OPERATION_TYPE_CLIENT = 4

# !!! we don't load ray.py to win import duration
# if change in ray.Err numbers, this has to be changed too !!!
ERR_UNKNOWN_MESSAGE = -18

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
                      'list_clients', 'get_session_name')

#client_operations = ('stop', 'kill', 'trash', 'resume', 'save',
                     #'save_as_template', 'show_optional_gui',
                     #'hide_optional_gui', 'update_properties',
                     #'list_snapshots', 'open_snapshot')

def signalHandler(sig, frame):
    if sig in (signal.SIGINT, signal.SIGTERM):
        global terminate
        terminate = True

def addSelfBinToPath():
    # Add raysession/src/bin to $PATH to can use ray executables after make
    # Warning, will works only if link to this file is in RaySession/*/*/*.py
    this_path = os.path.realpath(os.path.dirname(os.path.realpath(__file__)))
    bin_path = "%s/bin" % os.path.dirname(this_path)
    if not os.environ['PATH'].startswith("%s:" % bin_path):
        os.environ['PATH'] = "%s:%s" % (bin_path, os.environ['PATH'])

def areTheyAllString(args):
    for arg in args:
        if type(arg) != str:
            return False
    return True

def highlightText(string):
    if "'" in string:
        return '"%s"' % string
    else:
        return "'%s'" % string

def pidExists(pid):
        if type(pid) == str:
            pid = int(pid)
        
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        else:
            return True

def getDaemonList():
    daemon_list = []
    has_dirty_pid = False
    
    try:
        tree = ET.parse('/tmp/RaySession/multi-daemon.xml')
    except:
        return []
    
    root = tree.getroot()
    for child in root:
        daemon_dict = child.attrib
        keys = daemon_dict.keys()
        
        daemon = Daemon()
        if 'root' in keys:
            daemon.root = child.attrib['root']
        if 'session_path' in keys:
            daemon.session_path = child.attrib['session_path']
        if 'user' in keys:
            daemon.user = child.attrib['user']
            
            
        for key in keys:
            if key == 'root':
                daemon.root = child.attrib[key]
            elif key == 'session_path':
                daemon.session_path = child.attrib[key]
            elif key == 'user':
                daemon.user = child.attrib[key]
            elif key == 'not_default':
                daemon.not_default = bool(child.attrib[key] == 'true')
            elif key == 'net_daemon_id':
                net_daemon_id = child.attrib[key]
                if net_daemon_id.isdigit():
                    daemon.net_daemon_id = net_daemon_id
            elif key == 'pid':
                pid = child.attrib[key]
                if pid.isdigit():
                    daemon.pid = pid
            elif key == 'port':
                port = child.attrib[key]
                if port.isdigit():
                    daemon.port = port
        
        if not (daemon.net_daemon_id
                and daemon.pid
                and daemon.port):
            continue
        
        daemon_list.append(daemon)
    return daemon_list

class Daemon:
    net_daemon_id = 0
    root = ""
    session_path = ""
    pid = 0
    port = 0
    user = ""
    not_default = False

class OscServer(liblo.Server):
    def __init__(self):
        liblo.Server.__init__(self)
        self.m_daemon_address = None
        self.add_method('/reply', None, self.replyMessage)
        self.add_method('/error', 'sis', self.errorMessage)
        self.add_method('/minor_error', 'sis', self.minorErrorMessage)
        self.add_method('/ray/control/message', 's', self.rayControlMessage)
        self.add_method('/ray/control/server/announce', 'siisi',
                        self.rayControlServerAnnounce)
        self._final_err = -1

    def replyMessage(self, path, args, types, src_addr):
        if not areTheyAllString(args):
            return
        
        if len(args) >= 1:
            reply_path = args[0]
        else:
            return
        
        if reply_path != osc_order_path:
            sys.stdout.write('bug: reply for a wrong path:%s instead of %s\n'
                             % (highlightText(reply_path), 
                                highlightText(osc_order_path)))
            return
        
        if reply_path in ('/ray/server/list_factory_client_templates',
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
                self._final_err = 0
                
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
                self._final_err = 0
        
        elif os.path.basename(reply_path).startswith(('list_', 'get_')):
            if len(args) >= 2:
                sessions = args[1:]
                out_message = ""
                for session in sessions:
                    out_message += "%s\n" % session
                sys.stdout.write(out_message)
                return
            else:
                self._final_err = 0
        
        elif len(args) == 2:
            reply_path, message = args
            if os.path.basename(reply_path).startswith(('list_', 'add_')):
                sys.stdout.write("%s\n" % message)
            self._final_err = 0
    
    def errorMessage(self, path, args, types, src_addr):
        error_path, err, message = args
        
        if error_path != osc_order_path:
            sys.stdout.write('bug: error for a wrong path:%s instead of %s\n'
                             % (highlightText(error_path), 
                                highlightText(osc_order_path)))
            return
        
        sys.stderr.write('%s\n' % message)
        
        self._final_err = - err
    
    def minorErrorMessage(self, path, args, types, src_addr):
        error_path, err, message = args
        sys.stdout.write('\033[31m%s\033[0m\n' % message)
        if err == ERR_UNKNOWN_MESSAGE:
            #signaler.done.emit(- err)
            self._final_err = -err
    
    def rayControlMessage(self, path, args, types, src_addr):
        message = args[0]
        printMessage(message)
        
    def rayControlServerAnnounce(self, path, args, types, src_addr):
        self.m_daemon_address = src_addr
        daemonStarted()
    
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
    addSelfBinToPath()
    
    if len(sys.argv) <= 1:
        printHelp()
        sys.exit(100)
    
    terminate = False
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
    
    daemon_list = getDaemonList()
    
    osc_server = OscServer()
    
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
        daemonStarted()
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
        
        #TODO
        session_root = "%s/Ray Sessions" % os.getenv('HOME')
        try:
            settings_file = open("%s/.config/RaySession/RaySession.conf", 'r')
            contents = settings_file.read()
            for line in contents.split('\n'):
                if line.startswith('default_session_root='):
                    session_root = line.replace('default_session_root', '', 1)
                    break
        except:
            pass
        
        # start a daemon because no one is running
        #daemon_process = subprocess.Popen(
            #['ray-daemon', '--control-url', str(osc_server.url),
             #'--session-root', session_root])
        daemon_process = subprocess.Popen(
            ['ray-daemon', '--control-url', str(osc_server.url),
             '--session-root', session_root],
            -1, None, None, subprocess.DEVNULL, subprocess.DEVNULL)
    
    #connect SIGINT and SIGTERM
    signal.signal(signal.SIGINT,  signalHandler)
    signal.signal(signal.SIGTERM, signalHandler)
    
    exit_code = -1
    
    if not(operation_type == OPERATION_TYPE_CONTROL and operation == 'start'):
        while True:
            osc_server.recv(50)
            
            if terminate:
                break
            
            exit_code = osc_server._final_err
            if exit_code >= 0:
                break
    
    sys.exit(exit_code)
