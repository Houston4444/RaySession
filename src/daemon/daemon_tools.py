import argparse
import os
import sys
from PyQt5.QtCore import (QCoreApplication, QStandardPaths, QSettings,
                          QDateTime, QLocale)

import ray

settings = QSettings()

def dirname(*args)->str:
    return os.path.dirname(*args)

def basename(*args)->str:
    return os.path.basename(*args)

def get_app_config_path()->str:
    return "%s/%s" % (
            QStandardPaths.writableLocation(QStandardPaths.ConfigLocation),
            QCoreApplication.organizationName())

def get_code_root()->str:
    return dirname(dirname(dirname(os.path.realpath(__file__))))

def is_pid_child_of(child_pid, parent_pid)->bool:
    if child_pid < parent_pid:
        return False

    ppid = child_pid

    while ppid > parent_pid:
        try:
            proc_file = open('/proc/%i/status' % ppid, 'r')
            proc_contents = proc_file.read()
        except BaseException:
            return False

        for line in proc_contents.split('\n'):
            if line.startswith('PPid:'):
                ppid_str = line.rpartition('\t')[2]
                if ppid_str.isdigit():
                    ppid = int(ppid_str)
                    break
        else:
            return False

    #while ppid != parent_pid and ppid > 1 and ppid != this_pid:
        #try:
            #ppid = int(subprocess.check_output(
                #['ps', '-o', 'ppid=', '-p', str(ppid)]))
        #except BaseException:
            #return False

    if ppid == parent_pid:
        return True

    return False

def highlight_text(string)->str:
    if "'" in string:
        return '"%s"' % string
    return "'%s'" % string

def init_daemon_tools():
    if CommandLineArgs.config_dir:
        l_settings = QSettings(CommandLineArgs.config_dir)
    else:
        l_settings = QSettings()

    RS.set_settings(l_settings)

    RS.set_non_active_clients(
        ray.get_list_in_settings(l_settings, 'daemon/non_active_list'))
    RS.set_favorites(ray.get_list_in_settings(l_settings, 'daemon/favorites'))
    TemplateRoots.init_config()

def get_git_default_un_and_ignored(executable:str)->tuple:
    ignored = []
    unignored = []

    if executable in ('luppp', 'sooperlooper', 'sooperlooper_nsm'):
        unignored.append('.wav')

    elif executable == 'samplv1_jack':
        unignored = ['.wav', '.flac', '.ogg', '.mp3']

    return (ignored, unignored)

def get_nsm_capable_execs_from_desktop_files()->list:
    ''' returns a list of tuples 
        {'executable': str, 'desktop_file': str, nsm_capable: bool} '''
    desk_path_list = (
        '%s/.local' % os.getenv('HOME'),
        '/usr/local',
        '/usr')

    application_dicts = []

    for desk_path in desk_path_list:
        full_desk_path = "%s/share/applications" % desk_path

        if not os.path.isdir(full_desk_path):
            # applications folder doesn't exists
            continue

        if not os.access(full_desk_path, os.R_OK):
            # no permission to read this applications folder
            continue

        for root, dirs, files in os.walk(full_desk_path):
            for f in files:
                if not f.endswith('.desktop'):
                    continue

                if f in [apd['desktop_file'] for apd in application_dicts]:
                    # desktop file already seen in a prior desk_path
                    continue

                full_desk_file = os.path.join(root, f)
                
                try:
                    file = open(full_desk_file, 'r')
                    contents = file.read()
                except:
                    continue

                executable = ''
                has_nsm_mention = False
                nsm_capable = True
                name = ''
                
                for line in contents.splitlines():
                    if line.startswith('Exec='):
                        executable_and_args = line.partition('=')[2]
                        executable = executable_and_args.partition(' ')[0]
                    
                    elif line.lower().startswith('x-nsm-capable='):
                        has_nsm_mention = True
                        value = line.partition('=')[2]
                        nsm_capable = bool(value.strip().lower() == 'true')
                        
                    elif line.startswith('Name='):
                        name = line.partition('=')[2].strip()

                if has_nsm_mention and executable:
                    application_dicts.append(
                        {'executable': executable,
                         'name': '/' + name if name else '/' + executable,
                         'desktop_file': f,
                         'nsm_capable': nsm_capable,
                         'skipped': False})
                    print('ff', application_dicts[-1])
    
    return [a for a in application_dicts if a['nsm_capable']]


class RS:
    settings = QSettings()
    non_active_clients = []
    favorites = []

    @classmethod
    def set_settings(cls, settings):
        del cls.settings
        cls.settings = settings

    @classmethod
    def set_non_active_clients(cls, nalist):
        del cls.non_active_clients
        cls.non_active_clients = nalist

    @classmethod
    def set_favorites(cls, favorites):
        cls.favorites = favorites


class TemplateRoots:
    net_session_name = ".ray-net-session-templates"
    factory_sessions = "%s/session_templates" % get_code_root()
    factory_clients = "%s/client_templates"  % get_code_root()
    factory_clients_xdg = "/etc/xdg/raysession/client_templates"

    @classmethod
    def init_config(cls):
        if CommandLineArgs.config_dir:
            app_config_path = CommandLineArgs.config_dir
        else:
            app_config_path = get_app_config_path()

        cls.user_sessions = "%s/session_templates" % app_config_path
        cls.user_clients = "%s/client_templates"  % app_config_path


class Terminal:
    _last_client_name = ''

    @classmethod
    def message(cls, string, server_port=0):
        if cls._last_client_name and cls._last_client_name != 'daemon':
            sys.stderr.write('\n')

        sys.stderr.write('[\033[90mray-daemon\033[0m]\033[92m%s\033[0m\n'
                            % string)

        log_dir = "%s/logs" % get_app_config_path()
        if server_port:
            log_file_path = "%s/%i" % (log_dir, server_port)
        else:
            log_file_path = "%s/dummy" % log_dir

        if not os.path.exists(log_dir):
            os.makedirs(log_dir)

        log_file = open(log_file_path, 'a')

        date_time = QDateTime.currentDateTime()
        locale = QLocale(QLocale.English)
        date_format = locale.toString(date_time, "ddd MMM d hh:mm:ss yyyy")

        log_file.write("%s: %s\n" % (date_format, string))

        cls._last_client_name = 'daemon'

    @classmethod
    def snapshoter_message(cls, byte_string, command=''):
        snapshoter_str = "snapshoter:.%s" % command

        if cls._last_client_name != snapshoter_str:
            sys.stderr.write('\n[\033[90mray-daemon-git%s\033[0m]\n'
                             % command)
        sys.stderr.buffer.write(byte_string)

        cls._last_client_name = snapshoter_str

    @classmethod
    def scripter_message(cls, byte_string, command=''):
        scripter_str = "scripter:.%s" % command

        if cls._last_client_name != scripter_str:
            sys.stderr.write('\n[\033[90mray-daemon %s script\033[0m]\n'
                             % command)
        sys.stderr.buffer.write(byte_string)

        cls._last_client_name = scripter_str

    @classmethod
    def client_message(cls, byte_string, client_name, client_id):
        client_str = "%s.%s" % (client_name, client_id)

        if (not CommandLineArgs.debug_only
                and not CommandLineArgs.no_client_messages):
            if cls._last_client_name != client_str:
                sys.stderr.write('\n[\033[90m%s-%s\033[0m]\n'
                                    % (client_name, client_id))
            sys.stderr.buffer.write(byte_string)

        cls._last_client_name = client_str

    @classmethod
    def warning(cls, string):
        sys.stderr.write('[\033[90mray-daemon\033[0m]%s\033[0m\n' % string)
        cls._last_client_name = 'daemon'


class CommandLineArgs(argparse.Namespace):
    session_root = ''
    osc_port = 0
    findfreeport = True
    gui_url = None
    gui_port = 0
    gui_pid = 0
    config_dir = ''
    debug = False
    debug_only = False
    no_client_messages = False
    session = ''

    @classmethod
    def eat_attributes(cls, parsed_args):
        for attr_name in dir(parsed_args):
            if not attr_name.startswith('_'):
                setattr(cls, attr_name, getattr(parsed_args, attr_name))

        if cls.debug_only:
            cls.debug = True

        if cls.osc_port == 0:
            cls.osc_port = 16187
            cls.findfreeport = True

        if cls.config_dir and not os.access(cls.config_dir, os.W_OK):
            sys.stderr.write(
                '%s is not a writable config dir, try another one\n'
                    % cls.config_dir)
            sys.exit(1)

class ArgParser(argparse.ArgumentParser):
    def __init__(self):
        argparse.ArgumentParser.__init__(self)
        _translate = QCoreApplication.translate

        default_root = "%s/%s" % (
            os.getenv('HOME'),
            _translate('daemon', 'Ray Network Sessions'))

        self.add_argument('--session-root', '-r', type=str,
                          default=default_root,
                          help='set root folder for sessions')
        self.add_argument('--session', '-s', type=str, default='',
                          help='session to load at startup')
        self.add_argument('--osc-port', '-p',
                          type=int, default=0,
                          help='select OSC port for the daemon')
        self.add_argument('--findfreeport', action='store_true',
                          help='find another port if port is not free')
        self.add_argument('--gui-url', type=ray.get_liblo_address,
                          help=argparse.SUPPRESS)
        self.add_argument('--gui-port', type=ray.get_liblo_address_from_port,
                          help=argparse.SUPPRESS)
        self.add_argument('--gui-pid', type=int,
                          help=argparse.SUPPRESS)
        self.add_argument('--control-url', type=ray.get_liblo_address,
                          help=argparse.SUPPRESS)
        self.add_argument('--no-options', action='store_true',
            help='start without any option and do not save options at quit')
        self.add_argument('--hidden', action='store_true',
            help='hide for ray_control')
        self.add_argument('--config-dir', '-c', type=str, default='',
                          help='use a custom config dir')
        self.add_argument('--debug', '-d', action='store_true',
                          help='see all OSC messages')
        self.add_argument('--debug-only', '-do', action='store_true',
                          help='debug without client messages')
        self.add_argument('--no-client-messages', '-ncm', action='store_true',
                          help='do not print client messages')

        self.add_argument('-v', '--version', action='version',
                          version=ray.VERSION)

        parsed_args = argparse.ArgumentParser.parse_args(self)
        CommandLineArgs.eat_attributes(parsed_args)
