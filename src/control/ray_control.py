#!/usr/bin/python3 -u

import os
import signal
import sys
import xml.etree.ElementTree as ET
# import subprocess and osc_server (local file) conditionnally
# in order to answer faster in many cases.

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
    try:
        tree = ET.parse('/tmp/RaySession/multi-daemon.xml')
    except:
        return []
    
    daemon_list = []
    has_dirty_pid = False
    
    root = tree.getroot()
    for child in root:
        daemon = Daemon()
        
        for key in child.attrib.keys():
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


def printHelp(stdout=False):
    script_dir = os.path.dirname(os.path.realpath(sys.argv[0]))
    lang_file = "help_en_US"
    help_path = "%s/%s" % (script_dir, lang_file)
    
    try:
        help_file = open(help_path, 'r')
        message = help_file.read()
    except:
        sys.stderr.write('error: help_file %s is missing\n' % help_path)
        sys.exit(101)
    
    if stdout:
        sys.stdout.write(message)
    else:
        sys.stderr.write(message)

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
    daemon_announced = False
    
    daemon_list = getDaemonList()
    
    daemon_port = 0
    for daemon in daemon_list:
        if (daemon.user == os.environ['USER']
                and not daemon.not_default):
            daemon_port = daemon.port
            break
    
    if operation_type == OPERATION_TYPE_CONTROL:
        if operation == 'start':
            if daemon_port:
                sys.stderr.write('server already started.\n')
                sys.exit(0)
        
        elif operation == 'stop':
            if not daemon_port:
                sys.stderr.write('No server started.\n')
                sys.exit(0)
        
        elif operation == 'list_daemons':
            for daemon in daemon_list:
                sys.stdout.write('%s\n' % str(daemon.port))
            sys.exit(0)
        
        else:
            if not daemon_port:
                sys.stderr.write(
                    'No server started. So impossible to %s\n' % operation)
                sys.exit(100)
                
            if operation == 'get_pid':
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
                        
    elif not daemon_port:
        if operation_type == OPERATION_TYPE_SERVER:
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
    
    import osc_server # see top of the file
    server = osc_server.OscServer()
    server.setOrderPathArgs(osc_order_path, arg_list)
    
    if daemon_port:
        server.setDaemonAddress(daemon_port)
        server.sendOrderMessage()
    else:        
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
        import subprocess # see top of the file
        daemon_process = subprocess.Popen(
            ['ray-daemon', '--control-url', str(server.url),
             '--session-root', session_root],
            -1, None, None, subprocess.DEVNULL, subprocess.DEVNULL)
        #daemon_process = subprocess.Popen(
            #['ray-daemon', '--control-url', '192.168.50.1',
             #'--session-root', session_root],
            #-1, None, None, subprocess.DEVNULL, subprocess.DEVNULL)
        
        server.waitForStart()
        
        if (operation_type == OPERATION_TYPE_CONTROL
                and operation == 'start'):
            server.waitForStartOnly()
    
    #connect SIGINT and SIGTERM
    signal.signal(signal.SIGINT,  signalHandler)
    signal.signal(signal.SIGTERM, signalHandler)
    
    exit_code = -1
    
    while True:
        server.recv(50)
        
        if terminate:
            break
        
        exit_code = server.finalError()
        if exit_code >= 0:
            break
        
        if server.isWaitingStartForALong():
            exit_code = 103
            break
    
    sys.exit(exit_code)
