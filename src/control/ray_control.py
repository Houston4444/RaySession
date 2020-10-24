#!/usr/bin/python3 -u

import os
import signal
import sys
import xml.etree.ElementTree as ET
import warnings
# import subprocess and osc_server (local file) conditionnally
# in order to answer faster in many cases.

OPERATION_TYPE_NULL = 0
OPERATION_TYPE_CONTROL = 1
OPERATION_TYPE_SERVER = 2
OPERATION_TYPE_SESSION = 3
OPERATION_TYPE_CLIENT = 4
OPERATION_TYPE_TRASHED_CLIENT = 5
OPERATION_TYPE_ALL = 6 # for help message

control_operations = ('start', 'start_new', 'start_new_hidden', 'stop',
                      'list_daemons',
                      'get_root', 'get_port', 'get_port_gui_free',
                      'get_pid', 'get_session_path',
                      'has_local_gui', 'has_gui')

server_operations = (
    'quit', 'change_root', 'list_session_templates',
    'list_user_client_templates', 'list_factory_client_templates',
    'remove_client_template', 'list_sessions', 'new_session',
    'open_session', 'open_session_off', 'save_session_template',
    'rename_session', 'set_options', 'has_option',
    'script_info', 'hide_script_info', 'script_user_action')

session_operations = ('save', 'save_as_template', 'take_snapshot',
                      'close', 'abort', 'duplicate', 'open_snapshot',
                      'rename', 'set_notes', 'get_notes',
                      'add_executable', 'add_proxy',
                      'add_factory_client_template',
                      'add_user_client_template',
                      'add_client_template', 'list_snapshots',
                      'list_clients', 'list_trashed_clients',
                      'reorder_clients',
                      'get_session_name', 'run_step', 'clear_clients')


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

def pidExists(pid: int)->bool:
    if isinstance(pid, str):
        pid = int(pid)

    try:
        os.kill(pid, 0)
    except OSError:
        return False
    else:
        return True

def pidIsStopped(pid: int)->bool:
    proc_file_path = '/proc/%i/status' % pid
    if os.path.exists(proc_file_path):
        proc_file = open(proc_file_path)
        for line in proc_file.readlines():
            if line.startswith('State:	'):
                value = line.replace('State:	', '', 1)
                if value and value[0] == 'T':
                    return True
        return False
    return True

def getDaemonList():
    try:
        tree = ET.parse('/tmp/RaySession/multi-daemon.xml')
    except:
        return []

    l_daemon_list = []

    root = tree.getroot()
    for child in root:
        l_daemon = Daemon()

        for key in child.attrib.keys():
            if key == 'root':
                l_daemon.root = child.attrib[key]
            elif key == 'session_path':
                l_daemon.session_path = child.attrib[key]
            elif key == 'user':
                l_daemon.user = child.attrib[key]
            elif key == 'not_default':
                l_daemon.not_default = bool(child.attrib[key] == '1')
            elif key == 'net_daemon_id':
                net_daemon_id = child.attrib[key]
                if net_daemon_id.isdigit():
                   l_daemon.net_daemon_id = int(net_daemon_id)

            elif key == 'pid':
                pid = child.attrib[key]
                if pid.isdigit() and pidExists(pid):
                    l_daemon.pid = int(pid)

            elif key == 'port':
                l_port = child.attrib[key]
                if l_port.isdigit():
                    l_daemon.port = int(l_port)

            elif key == 'has_gui':
                l_daemon.has_local_gui = bool(child.attrib[key] == '3')
                l_daemon.has_gui = bool(child.attrib[key] == '1')
                
            elif key == 'local_gui_pids':
                gui_pids_str = child.attrib[key]
                for pid_str in gui_pids_str.split(':'):
                    if pid_str.isdigit():
                        l_daemon.local_gui_pids.append(int(pid_str))

        if not (l_daemon.net_daemon_id
                and l_daemon.pid
                and l_daemon.port):
            continue

        l_daemon_list.append(l_daemon)
    return l_daemon_list

class Daemon:
    net_daemon_id = 0
    root = ""
    session_path = ""
    pid = 0
    port = 0
    user = ""
    not_default = False
    has_gui = 0
    has_local_gui = 0
    
    def __init__(self):
        self.local_gui_pids = []


def printHelp(stdout=False, category=OPERATION_TYPE_NULL):
    script_dir = os.path.dirname(os.path.realpath(sys.argv[0]))
    lang_file = "help_en_US"

    if os.getenv('LANG').startswith('fr_'):
        lang_file = "help_fr_FR"

    help_path = "%s/%s" % (script_dir, lang_file)

    try:
        help_file = open(help_path, 'r')
        full_message = help_file.read()
    except:
        sys.stderr.write('error: help_file %s is missing\n' % help_path)
        sys.exit(101)

    message = ''
    stars = 0

    if category == OPERATION_TYPE_ALL:
        message = full_message
    else:
        for line in full_message.split('\n'):
            if line.startswith('* '):
                stars += 1

            if (stars == 0
                    or (stars == 1 and category == OPERATION_TYPE_CONTROL)
                    or (stars == 2 and category == OPERATION_TYPE_SERVER)
                    or (stars == 3 and category == OPERATION_TYPE_SESSION)
                    or (stars >= 4 and category == OPERATION_TYPE_CLIENT)):
                message += "%s\n" % line

    if stdout:
        sys.stdout.write(message)
    else:
        sys.stderr.write(message)

def autoTypeString(string):
    if string.isdigit():
        return int(string)
    if string.replace('.', '', 1).isdigit():
        return float(string)

    return string


if __name__ == '__main__':
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    addSelfBinToPath()

    if len(sys.argv) <= 1:
        printHelp()
        sys.exit(100)

    terminate = False
    operation_type = OPERATION_TYPE_NULL
    client_id = ''

    args = sys.argv[1:]

    wanted_port = 0
    detach = False

    dport = os.getenv('RAY_CONTROL_PORT')
    if dport and dport.isdigit():
        wanted_port = int(dport)

    while args and args[0].startswith('--'):
        option = args.pop(0)

        if option.startswith('--help'):
            if option == '--help':
                printHelp(True, OPERATION_TYPE_NULL)
            elif option == '--help-all':
                printHelp(True, OPERATION_TYPE_ALL)
            elif option == '--help-control':
                printHelp(True, OPERATION_TYPE_CONTROL)
            elif option == '--help-server':
                printHelp(True, OPERATION_TYPE_SERVER)
            elif option == '--help-session':
                printHelp(True, OPERATION_TYPE_SESSION)
            elif option in ('--help-client', '--help-clients'):
                printHelp(True, OPERATION_TYPE_CLIENT)
            else:
                printHelp()
                sys.exit(100)
            sys.exit(0)

        elif option == '--port':
            if not args:
                printHelp()
                sys.exit(100)
            port = args.pop(0)
            if not port.isdigit():
                sys.stderr.write('Invalid value for port: %s . Use digits !'
                                 % port)
                sys.exit(100)
            wanted_port = int(port)

        elif option == '--detach':
            detach = True
        else:
            printHelp()
            sys.exit(100)

    operation = args.pop(0)
    if operation in ('client', 'trashed_client'):
        if len(args) < 2:
            printHelp(False, OPERATION_TYPE_CLIENT)
            sys.exit(100)

        operation_type = OPERATION_TYPE_CLIENT
        if operation == 'trashed_client':
            operation_type = OPERATION_TYPE_TRASHED_CLIENT

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
            sys.stderr.write("Unknown operation: %s\n" % operation)
            printHelp()
            sys.exit(100)

    arg_list = [autoTypeString(s) for s in args]
    if operation_type in (OPERATION_TYPE_CLIENT,
                          OPERATION_TYPE_TRASHED_CLIENT):
        arg_list.insert(0, client_id)

    if operation in ('new_session', 'open_session', 'change_root',
                     'save_as_template', 'take_snapshot', 'duplicate',
                     'open_snapshot', 'rename', 'add_executable',
                     'add_client_template', 'script_info'):
        if not arg_list:
            sys.stderr.write('operation %s needs argument(s).\n' % operation)
            sys.exit(100)

    exit_code = 0
    daemon_announced = False

    daemon_list = getDaemonList()
    daemon_port = 0
    daemon_started = True

    for daemon in daemon_list:
        if ((daemon.user == os.environ['USER']
                    and not wanted_port and not daemon.not_default)
                or (wanted_port == daemon.port)):
            daemon_port = daemon.port
            break
    else:
        daemon_started = False

    if operation_type == OPERATION_TYPE_CONTROL:
        if operation == 'start':
            if daemon_started:
                sys.stderr.write('server already started.\n')
                sys.exit(0)

        elif operation in ('start_new', 'start_new_hidden'):
            pass

        elif operation == 'stop':
            if not daemon_started:
                sys.stderr.write('No server started.\n')
                sys.exit(0)

        elif operation == 'list_daemons':
            for daemon in daemon_list:
                if daemon.not_default:
                    continue
                sys.stdout.write('%s\n' % str(daemon.port))
            sys.exit(0)

        else:
            if not daemon_started:
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

            elif operation == 'get_port_gui_free':
                wanted_session_root = ''
                if args:
                    wanted_session_root = args[0]

                for daemon in daemon_list:
                    if (daemon.user == os.environ['USER']
                            and (daemon.root == wanted_session_root
                                 or not wanted_session_root)
                            and not daemon.not_default):
                        if not daemon.has_local_gui:
                            sys.stdout.write('%s\n' % daemon.port)
                            break

                        for pid in daemon.local_gui_pids:
                            if pid == 0:
                                # This means we don't know the pid of the local GUI
                                # So consider this daemon has already a GUI
                                break

                            if pidExists(pid) and not pidIsStopped(pid):
                                break
                        else:
                            sys.stdout.write('%s\n' % daemon.port)
                            break

                sys.exit(0)

            elif operation == 'get_root':
                for daemon in daemon_list:
                    if daemon.port == daemon_port:
                        sys.stdout.write('%s\n' % daemon.root)
                        sys.exit(0)

            elif operation == 'get_session_path':
                for daemon in daemon_list:
                    if daemon.port == daemon_port:
                        if not daemon.session_path:
                            sys.exit(1)
                        sys.stdout.write('%s\n' % daemon.session_path)
                        sys.exit(0)

            elif operation == 'has_local_gui':
                for daemon in daemon_list:
                    if daemon.port == daemon_port:
                        if daemon.has_local_gui:
                            sys.exit(0)
                sys.exit(1)

            elif operation == 'has_gui':
                for daemon in daemon_list:
                    if daemon.port == daemon_port:
                        if daemon.has_gui:
                            sys.exit(0)
                sys.exit(1)

    elif not daemon_started:
        at_port = ''
        if daemon_port:
            at_port = "at port %i" % daemon_port

        if operation_type == OPERATION_TYPE_SERVER:
            if operation == 'quit':
                sys.stderr.write('No server %s to quit !\n' % at_port)
                sys.exit(0)

        elif operation_type == OPERATION_TYPE_SESSION:
            sys.stderr.write("No server started %s. So no session to %s\n"
                                 % (at_port, operation))
            sys.exit(100)
        elif operation_type == OPERATION_TYPE_CLIENT:
            sys.stderr.write("No server started %s. So no client to %s\n"
                                 % (at_port, operation))
            sys.exit(100)
        elif operation_type == OPERATION_TYPE_CLIENT:
            sys.stderr.write(
                "No server started %s. So no trashed client to %s\n"
                                 % (at_port, operation))
            sys.exit(100)
        else:
            printHelp()
            sys.exit(100)

    osc_order_path = '/ray/'
    if operation_type == OPERATION_TYPE_CLIENT:
        osc_order_path += 'client/'
    elif operation_type == OPERATION_TYPE_TRASHED_CLIENT:
        osc_order_path += 'trashed_client/'
    elif operation_type == OPERATION_TYPE_SERVER:
        osc_order_path += 'server/'
    elif operation_type == OPERATION_TYPE_SESSION:
        osc_order_path += 'session/'

    osc_order_path += operation

    if operation_type == OPERATION_TYPE_CONTROL and operation == 'stop':
        osc_order_path = '/ray/server/quit'

    import osc_server  # see top of the file
    server = osc_server.OscServer(detach)
    server.setOrderPathArgs(osc_order_path, arg_list)
    daemon_process = None

    if (daemon_started
            and not (operation_type == OPERATION_TYPE_CONTROL
                     and operation in ('start_new', 'start_new_hidden'))):
        if (operation_type == OPERATION_TYPE_CONTROL
                and operation == 'stop'):
            daemon_port_list = []

            if wanted_port:
                daemon_port_list.append(wanted_port)
            else:
                for daemon in daemon_list:
                    if (daemon.user == os.getenv('USER')
                            and not daemon.not_default):
                        daemon_port_list.append(daemon.port)

            server.stopDaemons(daemon_port_list)
        else:
            server.setDaemonAddress(daemon_port)
            server.sendOrderMessage()

        if detach:
            sys.exit(0)
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
        process_args = ['ray-daemon', '--control-url', str(server.url),
                        '--session-root', session_root]

        if wanted_port:
            process_args.append('--osc-port')
            process_args.append(str(wanted_port))

        if (operation_type == OPERATION_TYPE_CONTROL
                and operation == 'start_new_hidden'):
            process_args.append('--hidden')
            process_args.append('--no-options')

        daemon_process = subprocess.Popen(process_args, -1, None, None,
                                          subprocess.DEVNULL,
                                          subprocess.DEVNULL)

        server.waitForStart()

        if (operation_type == OPERATION_TYPE_CONTROL
                and operation in ('start', 'start_new', 'start_new_hidden')):
            server.waitForStartOnly()

    #connect SIGINT and SIGTERM
    signal.signal(signal.SIGINT, signalHandler)
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

        if daemon_process and not daemon_process.poll() is None:
            sys.stderr.write('daemon terminates, sorry\n')
            exit_code = 104
            break

    if (operation_type == OPERATION_TYPE_CONTROL
            and operation in ('start_new', 'start_new_hidden')
            and exit_code == 0):
        daemon_port = server.getDaemonPort()
        if daemon_port:
            sys.stdout.write("%i\n" % daemon_port)

    server.disannounceToDaemon()

    sys.exit(exit_code)
