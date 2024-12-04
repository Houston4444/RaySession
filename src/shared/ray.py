

from dataclasses import dataclass
from enum import Enum, IntEnum, Flag
import os
import shlex
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from qtpy.QtCore import QSettings


VERSION = "0.16.0"
APP_TITLE = 'RaySession'
DEFAULT_SESSION_ROOT = Path.home() / 'Ray Sessions'
SCRIPTS_DIR = 'ray-scripts'
NOTES_PATH = 'ray-notes'
FACTORY_SESSION_TEMPLATES = (
    'with_jack_patch', 'with_jack_config', 'scripted')
RAYNET_BIN = 'ray-network'
GIT_IGNORED_EXTENSIONS = ".wav .flac .ogg .mp3 .mp4 .avi .mkv .peak .m4a .pdf"


class PrefixMode(Enum):
    CUSTOM = 0
    CLIENT_NAME = 1
    SESSION_NAME = 2
    
    @classmethod
    def _missing_(cls, value: object) -> 'PrefixMode':
        if isinstance(value, str):
            if value.lower() == 'client_name':
                return PrefixMode.CLIENT_NAME
            if value.lower() == 'session_name':
                return PrefixMode.SESSION_NAME
            if value.lower() == 'custom':
                return PrefixMode.CUSTOM
        return PrefixMode.CLIENT_NAME


class JackNaming(Enum):
    SHORT = 0
    LONG = 1
    
    @classmethod
    def _missing_(cls, value: object) -> 'JackNaming':
        return JackNaming.LONG


class ClientStatus(Enum):    
    INVALID = -1
    '''This status should never appears. It is the defaut value
    from an int non existing in other values.'''
    
    STOPPED = 0
    LAUNCH = 1
    OPEN = 2
    READY = 3
    PRECOPY = 4
    COPY = 5
    SAVE = 6
    SWITCH = 7
    QUIT = 8
    NOOP = 9
    ERROR = 10
    REMOVED = 11
    UNDEF = 12
    SCRIPT = 13
    LOSE = 14

    @classmethod
    def _missing_(cls, value) -> 'ClientStatus':
        return ClientStatus.INVALID
        

class ServerStatus(Enum):
    INVALID = -1
    '''This status should never appears. It is the defaut value
    from an int non existing in other values.'''
    
    OFF = 0
    NEW = 1
    OPEN = 2
    CLEAR = 3
    SWITCH = 4
    LAUNCH = 5
    PRECOPY = 6
    COPY = 7
    READY = 8
    SAVE = 9
    CLOSE = 10
    SNAPSHOT = 11
    REWIND = 12
    WAIT_USER = 13
    OUT_SAVE = 14
    OUT_SNAPSHOT = 15
    SCRIPT = 16
    
    @classmethod
    def _missing_(cls, value) -> 'ServerStatus':
        return ServerStatus.INVALID


class Protocol(Enum):
    NSM = 0
    RAY_HACK = 1
    RAY_NET = 2
    
    @classmethod
    def _missing_(cls, value) -> 'Protocol':
        return Protocol.NSM
    
    def to_string(self) -> str:
        if self is self.RAY_HACK:
            return "Ray-Hack"
        if self is self.RAY_NET:
            return "Ray-Net"
        return "NSM"
    
    @staticmethod
    def from_string(string: str) -> 'Protocol':
        if string.lower() in ('ray_hack', 'ray-hack'):
            return Protocol.RAY_HACK
        if string.lower() in ('ray_net', 'ray-net'):
            return Protocol.RAY_NET
        return Protocol.NSM


class Option(Flag):
    NONE = 0x00
    NSM_LOCKED = 0x001
    SAVE_FROM_CLIENT = 0x002 #DEPRECATED
    BOOKMARK_SESSION = 0x004
    HAS_WMCTRL = 0x008
    DESKTOPS_MEMORY = 0x010
    HAS_GIT = 0x020
    SNAPSHOTS = 0x040
    SESSION_SCRIPTS = 0x080
    GUI_STATES = 0x100
    
    @classmethod
    def _missing_(cls, value) -> 'Option':
        try:
            return super()._missing_(value)
        except:
            return Option.NONE 


class Err(IntEnum):
    OK = 0
    GENERAL_ERROR = -1
    INCOMPATIBLE_API = -2
    BLACKLISTED = -3
    LAUNCH_FAILED = -4
    NO_SUCH_FILE = -5
    NO_SESSION_OPEN = -6
    UNSAVED_CHANGES = -7
    NOT_NOW = -8
    BAD_PROJECT = -9
    CREATE_FAILED = -10
    SESSION_LOCKED = -11
    OPERATION_PENDING = -12
    COPY_RUNNING = -13
    NET_ROOT_RUNNING = -14
    SUBPROCESS_UNTERMINATED = -15
    SUBPROCESS_CRASH = -16
    SUBPROCESS_EXITCODE = -17
    UNKNOWN_MESSAGE = -18
    ABORT_ORDERED = -19
    COPY_ABORTED = -20
    SESSION_IN_SESSION_DIR = -21
    # check control/osc_server.py in case of changes !!!


class Command(Enum):
    NONE = 0
    START = 1
    OPEN = 2
    SAVE = 3
    STOP = 4


class WaitFor(Enum):
    NONE = 0
    QUIT = 1
    STOP_ONE = 2
    ANNOUNCE = 3
    REPLY = 4
    DUPLICATE_START = 5
    DUPLICATE_FINISH = 6
    SCRIPT_QUIT = 7


class Template(Enum):
    NONE = 0
    RENAME = 1
    SESSION_SAVE = 2
    SESSION_SAVE_NET = 3
    SESSION_LOAD = 4
    SESSION_LOAD_NET = 5
    CLIENT_SAVE = 6
    CLIENT_LOAD = 7


class SwitchState(Enum):
    NONE = 0
    RESERVED = 1
    NEEDED = 2
    DONE = 3


class WindowManager(Enum):
    NONE = 0
    X = 1
    WAYLAND = 2


class Systray(Enum):
    OFF = 0
    SESSION_ONLY = 1
    ALWAYS = 2


class ScriptFile(Flag):
    PREVENT = 0x0
    PARENT = 0x1
    LOAD = 0x2
    SAVE = 0x4
    CLOSE = 0x8
    

@dataclass
class Favorite:
    name: str
    icon: str
    factory: bool
    display_name: str


def version_to_tuple(version_str: str) -> tuple[int, int, int]:
    version_list = []
    for c in version_str.split('.'):
        if not c.isdigit():
            return (0, 0, 0)
        version_list.append(int(c))

    return tuple(version_list)

def add_self_bin_to_path():
    # Add RaySession/src/bin to $PATH to can use ray executables after make
    # Warning, will works only if link to this file is in RaySession/*/*/*.py
    bin_path = Path(__file__).parent.parent / 'bin'
    path_env = os.getenv('PATH')
    if path_env is None:
        # if it happens, very few chances that system works correctly
        os.environ['PATH'] = f'{bin_path}'
        return
    
    if str(bin_path) not in path_env.split(':'):
        os.environ['PATH'] = f'{bin_path}:{path_env}'

def get_list_in_settings(settings: 'QSettings', path: str) -> list:
    '''getting a QSettings value of list type seems to not works
    the same way on all machines'''

    try:
        settings_list = settings.value(path, [], type=list)
    except BaseException:
        try:
            settings_list = settings.value(path, [])
        except BaseException:
            settings_list = []

    if isinstance(settings_list, list):
        return settings_list
    return []

def is_git_taggable(string: str) -> bool:
    '''Know if a string can be a git tag, not used currently'''
    if not string:
        return False

    if string.startswith('/'):
        return False

    if string.endswith('/'):
        return False

    if string.endswith('.'):
        return False

    for forbidden in (' ', '~', '^', ':', '?', '*',
                      '[', '..', '@{', '\\', '//', ','):
        if forbidden in string:
            return False

    if string == "@":
        return False

    return True

def is_valid_full_path(path: str) -> bool:
    if not path.startswith('/'):
        return False

    for forbidden in ('//', '/./', '/../'):
        if forbidden in path:
            return False

    if path.endswith(('/.', '/..')):
        return False
    return True

def shell_line_to_args(string: str) -> Optional[list[str]]:
    try:
        args = shlex.split(string)
    except BaseException:
        return None

    return args

def types_are_all_strings(types: str) -> bool:
    for char in types:
        if char != 's':
            return False
    return True

def get_window_manager() -> WindowManager:
    if os.getenv('WAYLAND_DISPLAY'):
        return WindowManager.WAYLAND

    if os.getenv('DISPLAY'):
        return WindowManager.X

    return WindowManager.NONE


class ClientData:
    client_id = ''
    protocol = Protocol.NSM
    executable_path = ''
    arguments = ''
    pre_env = ''
    name = ''
    prefix_mode = PrefixMode.SESSION_NAME
    custom_prefix = ''
    desktop_file = ''
    label = ''
    description = ''
    icon = ''
    capabilities = ''
    check_last_save = True
    ignored_extensions = GIT_IGNORED_EXTENSIONS
    template_origin = ''
    jack_client_name = ''
    jack_naming = JackNaming.SHORT
    in_terminal = False
    ray_hack: 'RayHack'
    ray_net: 'RayNet'

    @staticmethod
    def sisi():
        return 'sissssissssssisssii'

    @staticmethod
    def new_from(*args):
        client_data = ClientData()
        client_data.update(*args)
        return client_data

    @staticmethod
    def spread_client(client: 'ClientData') -> tuple:
        return (client.client_id, client.protocol.value,
                client.executable_path, client.arguments, client.pre_env,
                client.name, client.prefix_mode.value, client.custom_prefix,
                client.desktop_file, client.label, client.description,
                client.icon,
                client.capabilities, int(client.check_last_save),
                client.ignored_extensions,
                client.template_origin,
                client.jack_client_name, client.jack_naming.value,
                int(client.in_terminal))

    def set_ray_hack(self, ray_hack: 'RayHack'):
        self.ray_hack = ray_hack

    def set_ray_net(self, ray_net: 'RayNet'):
        self.ray_net = ray_net

    def update(self, client_id, protocol,
               executable, arguments, pre_env,
               name, prefix_mode, custom_prefix,
               desktop_file, label, description,
               icon,
               capabilities, check_last_save,
               ignored_extensions,
               template_origin,
               jack_client_name, jack_naming,
               in_terminal,
               secure=False):
        self.executable_path = str(executable)
        self.arguments = str(arguments)
        self.pre_env = str(pre_env)

        self.desktop_file = str(desktop_file)
        self.label = str(label)
        self.description = str(description)
        self.icon = str(icon)

        self.check_last_save = bool(check_last_save)
        self.ignored_extensions = str(ignored_extensions)
        self.template_origin = template_origin
        self.jack_naming = JackNaming(jack_naming)
        self.in_terminal = bool(in_terminal)

        if secure:
            return

        # Now, if message is 'unsecure' only.
        # change things that can't be changed normally
        self.client_id = str(client_id)
        self.protocol = Protocol(protocol)
        if name:
            self.name = str(name)
        else:
            self.name = os.path.basename(self.executable_path)
        self.prefix_mode = PrefixMode(prefix_mode)

        if self.prefix_mode is PrefixMode.CUSTOM:
            if custom_prefix:
                self.custom_prefix = str(custom_prefix)
            else:
                self.prefix_mode = PrefixMode.SESSION_NAME

        self.capabilities = str(capabilities)
        self.jack_client_name = jack_client_name

    def update_secure(self, *args):
        self.update(*args, secure=True)

    def spread(self) -> tuple:
        return ClientData.spread_client(self)
    
    def prettier_name(self) -> str:
        if self.label:
            return self.label
        if (self.protocol is not Protocol.RAY_HACK
                and self.name):
            return self.name
        return self.executable_path


class RayHack:
    config_file = ""
    save_sig = 0
    stop_sig = 15
    wait_win = False
    no_save_level = 0
    useless_str = ''
    useless_int = 0

    @staticmethod
    def sisi():
        # the first 's' is for client_id, not stocked in RayHack
        return 'siiiisi'

    @staticmethod
    def new_from(*args):
        ray_hack = RayHack()
        ray_hack.update(*args)
        return ray_hack

    def saveable(self) -> bool:
        return bool(self.config_file and self.save_sig)

    def relevant_no_save_level(self) -> int:
        if self.config_file and self.save_sig == 0:
            return self.no_save_level
        return 0

    def update(self, config_file,
               save_sig, stop_sig,
               wait_win, no_save_level,
               useless_str, useless_int):
        self.config_file = str(config_file)
        self.save_sig = int(save_sig)
        self.stop_sig = int(stop_sig)
        self.wait_win = bool(wait_win)
        self.no_save_level = int(no_save_level)

    def spread(self) -> tuple:
        return (self.config_file, self.save_sig, self.stop_sig,
                int(self.wait_win), self.no_save_level,
                self.useless_str, self.useless_int)


class RayNet:
    daemon_url = ''
    session_root = ''
    session_template = ''
    duplicate_state = -1
    running_daemon_url = ''
    running_session_root =''

    @staticmethod
    def sisi():
        return 'sss'

    @staticmethod
    def new_from(*args):
        ray_net = RayNet()
        ray_net.update(*args)
        return ray_net

    def update(self, daemon_url, session_root, session_template):
        self.daemon_url = daemon_url
        self.session_root = session_root
        self.session_template = session_template

    def spread(self)->tuple:
        return (self.daemon_url, self.session_root, self.session_template)

