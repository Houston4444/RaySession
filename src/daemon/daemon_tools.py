
# Imports from standard library
import argparse
import os
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional, Union, Callable
from pathlib import Path
import logging

# third party imports
from qtpy.QtCore import (
    QCoreApplication, QStandardPaths, QSettings, QDateTime, QLocale)

# Imports from src/shared
from osclib import (
    Address, verified_address, verified_address_from_port)
import ray

if TYPE_CHECKING:
    from client import Client


_logger = logging.getLogger(__name__)
settings = QSettings()

# remember here associated desktop files for executables
# key: executable, value: desktop_file name
exec_and_desktops = dict[str, str]()

def get_app_config_path() -> Path:
    return (Path(
        QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.ConfigLocation))
        / QCoreApplication.organizationName())

def get_code_root() -> Path:
    return Path(__file__).parents[2]

def is_pid_child_of(child_pid: int, parent_pid: int) -> bool:
    if child_pid < parent_pid:
        return False

    ppid = child_pid

    while ppid > parent_pid:
        try:
            proc_file = open('/proc/%i/status' % ppid, 'r')
            proc_contents = proc_file.read()
        except BaseException:
            return False

        for line in proc_contents.splitlines():
            if line.startswith('PPid:'):
                ppid_str = line.rpartition('\t')[2]
                if ppid_str.isdigit():
                    ppid = int(ppid_str)
                    break
        else:
            return False

    if ppid == parent_pid:
        return True

    return False

def highlight_text(string: Union[str, Path]) -> str:
    string = str(string)

    if "'" in string:
        return f'"{string}"'
    return f"'{string}'"

def init_daemon_tools():
    if CommandLineArgs.config_dir:
        l_settings = QSettings(CommandLineArgs.config_dir)
    else:
        l_settings = QSettings()

    RS.set_settings(l_settings)

    RS.set_non_active_clients(
        ray.get_list_in_settings(l_settings, 'daemon/non_active_list'))
    RS.set_favorites(ray.get_list_in_settings(
        l_settings, 'daemon/favorites'))
    TemplateRoots.init_config()

def get_git_default_un_and_ignored(
        executable:str) -> tuple[list[str], list[str]]:
    ignored = list[str]()
    unignored = list[str]()

    if executable in ('luppp', 'sooperlooper', 'sooperlooper_nsm'):
        unignored.append('.wav')

    elif executable == 'samplv1_jack':
        unignored = ['.wav', '.flac', '.ogg', '.mp3']

    return (ignored, unignored)


@dataclass
class AppTemplate:
    template_name: str
    template_client: 'Client'
    display_name: str
    templates_root: Path


class RS:
    settings = QSettings()
    non_active_clients = []
    favorites = list[ray.Favorite]()

    @classmethod
    def set_settings(cls, settings):
        del cls.settings
        cls.settings = settings

    @classmethod
    def set_non_active_clients(cls, nalist):
        del cls.non_active_clients
        cls.non_active_clients = nalist

    @classmethod
    def set_favorites(cls, favorites: list[ray.Favorite]):
        cls.favorites.clear()
        
        for fav in favorites:
            fav_dict = fav.__dict__
            if (isinstance(fav_dict.get('name'), str)
                    and isinstance(fav_dict.get('factory'), bool)
                    and isinstance(fav_dict.get('icon'), str)):
                display_name = fav_dict.get('display_name')
                if not isinstance(display_name, str):
                    display_name = ''
                
                if not display_name:
                    display_name = fav_dict.get('name')
                cls.favorites.append(ray.Favorite(
                    fav_dict.get('name'),
                    fav_dict.get('icon'),
                    fav_dict.get('factory'),
                    display_name))

class TemplateRoots:
    net_session_name = ".ray-net-session-templates"
    factory_sessions = get_code_root() / 'session_templates'
    factory_clients = get_code_root() / 'client_templates'    
    factory_clients_xdg = Path('/etc/xdg/raysession/client_templates')

    @classmethod
    def init_config(cls):
        if CommandLineArgs.config_dir:
            app_config_path = Path(CommandLineArgs.config_dir)
        else:
            app_config_path = get_app_config_path()

        cls.user_sessions = app_config_path / 'session_templates'
        cls.user_clients = app_config_path / 'client_templates'


class Terminal:
    _last_client_name = ''

    @classmethod
    def message(cls, string: str, server_port=0):
        if cls._last_client_name and cls._last_client_name != 'daemon':
            sys.stderr.write('\n')

        sys.stderr.write(
            f'[\033[90mray-daemon\033[0m]\033[92m{string}\033[0m\n')

        log_dir = get_app_config_path() / 'logs'
        
        if server_port:
            log_file_path = log_dir / str(server_port)
        else:
            log_file_path = log_dir / 'dummy'

        log_dir.mkdir(exist_ok=True, parents=True)

        with open(log_file_path, 'a') as log_file:
            date_time = QDateTime.currentDateTime()

            locale = QLocale(
                QLocale.Language.English, QLocale.Country.UnitedStates)

            date_format = locale.toString(date_time, "ddd MMM d hh:mm:ss yyyy")

            log_file.write("%s: %s\n" % (date_format, string))

        cls._last_client_name = 'daemon'

    @classmethod
    def prepare_logging(cls):
        if cls._last_client_name != 'daemon':
            sys.stderr.write(f'\n[\033[90mray-daemon\033[0m]\n')
            cls._last_client_name = 'daemon'

    @classmethod
    def snapshoter_message(cls, byte_str: bytes, command=''):
        snapshoter_str = "snapshoter:.%s" % command

        if cls._last_client_name != snapshoter_str:
            sys.stderr.write(f'\n[\033[90mray-daemon-git{command}\033[0m]\n')
        sys.stderr.buffer.write(byte_str)

        cls._last_client_name = snapshoter_str

    @classmethod
    def scripter_message(cls, byte_str: bytes, command=''):
        scripter_str = f'scripter:.{command}'

        if cls._last_client_name != scripter_str:
            sys.stderr.write(
                f'\n[\033[90mray-daemon {command} script\033[0m]\n')
        sys.stderr.buffer.write(byte_str)

        cls._last_client_name = scripter_str

    @classmethod
    def client_message(
            cls, byte_str: bytes, client_name: str, client_id: str):
        client_str = f'{client_name}.{client_id}'

        if (not CommandLineArgs.debug_only
                and not CommandLineArgs.no_client_messages):
            if cls._last_client_name != client_str:
                sys.stderr.write(
                    f'\n[\033[90m{client_name}-{client_id}\033[0m]\n')
            sys.stderr.buffer.write(byte_str)

        cls._last_client_name = client_str

    @classmethod
    def warning(cls, string):
        sys.stderr.write(
            f'[\033[90mray-daemon\033[0m]{string}\033[0m\n')
        cls._last_client_name = 'daemon'


def verified_address_arg(arg: str) -> Address:
    addr_or_msg = verified_address(arg)
    if isinstance(addr_or_msg, Address):
        return addr_or_msg
    raise argparse.ArgumentTypeError(addr_or_msg)

def verified_address_from_port_arg(arg: str) -> Address:
    if not arg.isdigit():
        raise argparse.ArgumentTypeError(arg)
    
    addr_or_msg = verified_address_from_port(int(arg))
    if isinstance(addr_or_msg, Address):
        return addr_or_msg
    raise argparse.ArgumentTypeError(addr_or_msg)


class CommandLineArgs(argparse.Namespace):
    session_root = Path()
    hidden = False
    osc_port = 0
    findfreeport = True
    control_url: Optional[Address] = None
    gui_url: Optional[Address] = None
    gui_tcp_url: Optional[Address] = None
    gui_port = 0
    gui_pid = 0
    config_dir = ''
    debug = False
    debug_only = False
    no_client_messages = False
    session = ''
    no_options = False
    log = ''

    @classmethod
    def eat_attributes(cls, parsed_args: argparse.Namespace):
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
                f'{cls.config_dir} is not a writable config dir, '
                'try another one\n')
            sys.exit(1)
        
        if not cls.session_root.name:
            cls.session_root = Path(
                RS.settings.value('default_session_root', type=str))


class ArgParser(argparse.ArgumentParser):
    def __init__(self):
        argparse.ArgumentParser.__init__(self)
        _translate = QCoreApplication.translate

        default_root = \
            Path.home() / _translate('daemon', 'Ray Network Sessions')

        self.add_argument(
            '--session-root', '-r', type=Path, default=default_root,
            help='set root folder for sessions')
        self.add_argument(
            '--session', '-s', type=str, default='',
            help='session to load at startup')
        self.add_argument(
            '--osc-port', '-p',
            type=int, default=0,
            help='select OSC port for the daemon')
        self.add_argument(
            '--findfreeport', action='store_true',
            help='find another port if port is not free')
        self.add_argument(
            '--gui-url', type=verified_address_arg,
            help=argparse.SUPPRESS)
        self.add_argument(
            '--gui-port', type=verified_address_from_port_arg,
            help=argparse.SUPPRESS)
        self.add_argument(
            '--gui-tcp-url', type=verified_address_arg,
            help=argparse.SUPPRESS)
        self.add_argument(
            '--gui-pid', type=int, help=argparse.SUPPRESS)
        self.add_argument(
            '--control-url', type=verified_address_arg,
            help=argparse.SUPPRESS)
        self.add_argument(
            '--no-options', action='store_true',
            help='start without any option and do not save options at quit')
        self.add_argument(
            '--hidden', action='store_true', help='hide for ray_control')
        self.add_argument(
            '--config-dir', '-c', type=str, default='',
            help='use a custom config dir')
        self.add_argument(
            '--debug', '-d', action='store_true', help='see all OSC messages')
        self.add_argument(
            '--debug-only', '-do', action='store_true',
            help='debug without client messages')
        self.add_argument(
            '--no-client-messages', '-ncm', action='store_true',
            help='do not print client messages')
        self.add_argument(
            '-v', '--version', action='version', version=ray.VERSION)
        self.add_argument(
            '-log', '--log', type=str, default='',
            help='set the logs for specific modules')

        parsed_args = argparse.ArgumentParser.parse_args(self)
        CommandLineArgs.eat_attributes(parsed_args)


class LogStreamHandler(logging.StreamHandler):
    '''Allows to write `[ray-daemon]` before logging something
    if the previous message came from a client.'''
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def emit(self, record: logging.LogRecord):
        Terminal.prepare_logging()
        super().emit(record)