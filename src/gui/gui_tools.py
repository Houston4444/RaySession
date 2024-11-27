
# Imports from standard library
import argparse
import os
from pathlib import Path
import sys
from typing import TYPE_CHECKING

# third party imports
from qtpy.QtCore import QSettings, QSize, QFile
from qtpy.QtWidgets import QApplication, QWidget
from qtpy.QtGui import QIcon, QPixmap, QPalette

# Imports from src/shared
from osclib import Address, verified_address, verified_address_from_port
import ray

if TYPE_CHECKING:
    from gui_signaler import Signaler


_translate = QApplication.translate

_RAY_ICONS_CACHE_LIGHT = {}
_RAY_ICONS_CACHE_DARK = {}
_APP_ICONS_CACHE_LIGHT = {}
_APP_ICONS_CACHE_DARK = {}

class RS:
    settings = QSettings()

    # HD for Hideable dialog
    # we can add elements here but never change 
    # the existing ones, because they are used in user config files
    HD_Donations = 0x001
    HD_OpenNsmSession = 0x002
    HD_SnapshotsInfo = 0x004
    HD_WaitCloseUser = 0x008
    HD_JackConfigScript = 0x010
    HD_SessionScripts = 0x020
    HD_SystrayClose = 0x040
    HD_StartupRecentSessions = 0x080
    HD_ArdourConversion = 0x100
    
    _signaler: 'Signaler' = None
    
    @classmethod
    def set_settings(cls, settings):
        del cls.settings
        cls.settings = settings

    @classmethod
    def is_hidden(cls, hideable_dialog: int) -> bool:
        hidden_dialogs = cls.settings.value('hidden_dialogs', 0, type=int)
        return bool(hidden_dialogs & hideable_dialog)

    @classmethod
    def set_hidden(cls, hiddeable_dialog: int, hide=True):
        hidden_dialogs = cls.settings.value('hidden_dialogs', 0, type=int)

        if hide:
            hidden_dialogs |= hiddeable_dialog
        else:
            hidden_dialogs &= ~hiddeable_dialog

        cls.settings.setValue('hidden_dialogs', hidden_dialogs)
        
        if cls._signaler is not None:
            cls._signaler.hiddens_changed.emit(hidden_dialogs)

    @classmethod
    def reset_hiddens(cls):
        cls.settings.setValue('hidden_dialogs', 0x00)
        if cls._signaler is not None:
            cls._signaler.hiddens_changed.emit(0)
        
    @classmethod
    def set_signaler(cls, signaler: 'Signaler'):
        cls._signaler = signaler


class ErrDaemon:
    # for use on network session under NSM
    NO_ERROR = 0
    NO_ANNOUNCE = -1
    NOT_OFF = -2
    WRONG_ROOT = -3
    FORBIDDEN_ROOT = -4
    NOT_NSM_LOCKED = -5
    WRONG_VERSION = -6


class RayAbstractIcon(QIcon):
    def __init__(self, icon_name: str, dark=False):
        QIcon.__init__(self)
        breeze = 'breeze-dark' if dark else 'breeze'
        self.addFile(':scalable/%s/%s' % (breeze, icon_name), QSize(22, 22))
        self.addPixmap(
            QPixmap(
                ':scalable/%s/disabled/%s' %
                (breeze, icon_name)), QIcon.Mode.Disabled, QIcon.State.Off)


def RayIcon(icon_name: str, dark=False) -> RayAbstractIcon:
    if dark and icon_name in _RAY_ICONS_CACHE_DARK.keys():
        return _RAY_ICONS_CACHE_DARK[icon_name]
    if not dark and icon_name in _RAY_ICONS_CACHE_LIGHT.keys():
        return _RAY_ICONS_CACHE_LIGHT[icon_name]
    
    icon = RayAbstractIcon(icon_name, dark)
    if dark:
        _RAY_ICONS_CACHE_DARK[icon_name] = icon
    else:
        _RAY_ICONS_CACHE_LIGHT[icon_name] = icon
    
    return icon


def verified_address_arg(arg: str) -> Address:
    addr_or_msg = verified_address(arg)
    if isinstance(addr_or_msg, Address):
        return addr_or_msg
    raise argparse.ArgumentTypeError(addr_or_msg)

def verified_address_from_port_arg(arg: str) -> Address:
    addr_or_msg = verified_address_from_port(arg)
    if isinstance(addr_or_msg, Address):
        return addr_or_msg
    raise argparse.ArgumentTypeError(addr_or_msg)


class CommandLineArgs(argparse.Namespace):
    daemon_url: Address = None
    daemon_port: Address = None
    out_daemon = False
    session_root: str = ''
    config_dir = ''
    debug = False
    debug_only = False
    no_client_messages = False
    net_session_root = ''
    net_daemon_id = 0
    under_nsm = False
    NSM_URL = ''
    session_root = ''
    start_session = ''
    force_new_daemon = False

    @classmethod
    def eat_attributes(cls, parsed_args):
        for attr_name in dir(parsed_args):
            if not attr_name.startswith('_'):
                setattr(cls, attr_name, getattr(parsed_args, attr_name))

        if cls.debug_only:
            cls.debug = True

        if cls.debug or cls.no_client_messages:
            cls.force_new_daemon = True

        if cls.config_dir and not os.access(cls.config_dir, os.W_OK):
            sys.stderr.write(
                '%s is not a writable config dir, try another one\n'
                % cls.config_dir)
            sys.exit(1)

        if os.getenv('NSM_URL'):
            try:
                cls.NSM_URL = verified_address_arg(os.getenv('NSM_URL'))
            except BaseException:
                sys.stderr.write('%s is not a valid NSM_URL\n'
                                 % os.getenv('NSM_URL'))
                sys.exit(1)

            cls.under_nsm = True

        if (cls.session_root is not None
                and cls.session_root.endswith('/')):
            cls.session_root = cls.session_root[:-1]

    @classmethod
    def change_session_root(cls, path: str):
        cls.session_root = path


class ArgParser(argparse.ArgumentParser):
    def __init__(self):
        argparse.ArgumentParser.__init__(
            self,
            description=_translate(
                'help',
                'A session manager based on the Non-Session-Manager API '
                + 'for sound applications.'))
        self.add_argument('--daemon-url', '-u', type=verified_address_arg,
                          help=_translate('help',
                                          'connect to this daemon url'))
        self.add_argument('--daemon-port', '-p',
                          type=verified_address_from_port_arg,
                          help=_translate('help',
                                          'connect to this daemon port'))
        self.add_argument('--out-daemon', action='store_true',
                          help=argparse.SUPPRESS)
        self.add_argument('--session-root', '-r', type=str,
                          help=_translate(
                              'help', 'Use this folder as root for sessions'))
        self.add_argument('--start-session', '-s', type=str,
                          help=_translate('help',
                                          'Open this session at startup'))
        self.add_argument('--config-dir', '-c', type=str, default='',
                          help=_translate('help', 'use a custom config dir'))
        self.add_argument('--debug', '-d', action='store_true',
                          help=_translate('help', 'display OSC messages'))
        self.add_argument('--debug-only', '-do', action='store_true',
                          help=_translate('help',
                                          'debug without client messages'))
        self.add_argument('---no-client-messages', '-ncm', action='store_true',
                          help=_translate('help',
                                          'do not print client messages'))
        self.add_argument(
            '--force-new-daemon', '-fnd', action='store_true',
            help=_translate(
                'help', 'prevent to attach to an already running daemon'))
        self.add_argument('--net-session-root', type=str, default='',
                          help=argparse.SUPPRESS)
        self.add_argument('--net-daemon-id', type=int, default=0,
                          help=argparse.SUPPRESS)
        self.add_argument('-v', '--version', action='version',
                          version=ray.VERSION)

        parsed_args = argparse.ArgumentParser.parse_args(self)
        CommandLineArgs.eat_attributes(parsed_args)

def init_gui_tools():
    if CommandLineArgs.under_nsm:
        settings = QSettings('%s/child_sessions'
                             % QApplication.organizationName())
    elif CommandLineArgs.config_dir:
        settings = QSettings(CommandLineArgs.config_dir)
    else:
        settings = QSettings()

    RS.set_settings(settings)

    if not CommandLineArgs.session_root:
        CommandLineArgs.change_session_root(
            settings.value('default_session_root',
                           ray.DEFAULT_SESSION_ROOT,
                           type=str))

def is_dark_theme(widget: QWidget) -> bool:
    return bool(
        widget.palette().brush(
            QPalette.ColorGroup.Active,
            QPalette.ColorRole.WindowText).color().lightness()
        > 128)

def split_in_two(string: str) -> tuple[str, str]:
        middle = int(len(string)/2)
        sep_indexes = []
        last_was_digit = False

        for sep in (' ', '-', '_', 'capital'):
            for i in range(len(string)):
                c = string[i]
                if sep == 'capital':
                    if c.upper() == c:
                        if not c.isdigit() or not last_was_digit:
                            sep_indexes.append(i)
                        last_was_digit = c.isdigit()

                elif c == sep:
                    sep_indexes.append(i)

            if sep_indexes:
                break

        if not sep_indexes or sep_indexes == [0]:
            return (string, '')

        best_index = 0
        best_dif = middle

        for s in sep_indexes:
            dif = abs(middle - s)
            if dif < best_dif:
                best_index = s
                best_dif = dif

        if sep == ' ':
            return (string[:best_index], string[best_index+1:])
        return (string[:best_index], string[best_index:])

def dirname(*args) -> str:
    return os.path.dirname(*args)

def basename(*args) -> str:
    return os.path.basename(*args)

def get_code_root() -> Path:
    return Path(__file__).parent.parent.parent

def server_status_string(server_status: ray.ServerStatus) -> str:
    SERVER_STATUS_STRINGS = {
        ray.ServerStatus.INVALID : _translate('server status', "invalid"),
        ray.ServerStatus.OFF     : _translate('server status', "off"),
        ray.ServerStatus.NEW     : _translate('server status', "new"),
        ray.ServerStatus.OPEN    : _translate('server status', "open"),
        ray.ServerStatus.CLEAR   : _translate('server status', "clear"),
        ray.ServerStatus.SWITCH  : _translate('server status', "switch"),
        ray.ServerStatus.LAUNCH  : _translate('server status', "launch"),
        ray.ServerStatus.PRECOPY : _translate('server status', "copy"),
        ray.ServerStatus.COPY    : _translate('server status', "copy"),
        ray.ServerStatus.READY   : _translate('server status', "ready"),
        ray.ServerStatus.SAVE    : _translate('server status', "save"),
        ray.ServerStatus.CLOSE   : _translate('server status', "close"),
        ray.ServerStatus.SNAPSHOT: _translate('server_status', "snapshot"),
        ray.ServerStatus.REWIND  : _translate('server_status', "rewind"),
        ray.ServerStatus.WAIT_USER   : _translate('server_status', "waiting"),
        ray.ServerStatus.OUT_SAVE    : _translate('server_status', "save"),
        ray.ServerStatus.OUT_SNAPSHOT: _translate('server_status', "snapshot"),
        ray.ServerStatus.SCRIPT  : _translate('server_status', "script")}

    return SERVER_STATUS_STRINGS[server_status]

def client_status_string(client_status: ray.ClientStatus) -> str:
    CLIENT_STATUS_STRINGS = {
        ray.ClientStatus.INVALID: _translate('client_status', "invalid"),
        ray.ClientStatus.STOPPED: _translate('client status', "stopped"),
        ray.ClientStatus.LAUNCH : _translate('client status', "launch"),
        ray.ClientStatus.OPEN   : _translate('client status', "open"),
        ray.ClientStatus.READY  : _translate('client status', "ready"),
        ray.ClientStatus.PRECOPY: _translate('client status', "copy"),
        ray.ClientStatus.COPY   : _translate('client status', "copy"),
        ray.ClientStatus.SAVE   : _translate('client status', "save"),
        ray.ClientStatus.SWITCH : _translate('client status', "switch"),
        ray.ClientStatus.QUIT   : _translate('client status', "quit"),
        ray.ClientStatus.NOOP   : _translate('client status', "noop"),
        ray.ClientStatus.ERROR  : _translate('client status', "error"),
        ray.ClientStatus.REMOVED: _translate('client status', "removed"),
        ray.ClientStatus.UNDEF  : _translate('client_status', ""),
        ray.ClientStatus.SCRIPT : _translate('client_status', 'script'),
        ray.ClientStatus.LOSE   : _translate('client_status', "lose")}

    return CLIENT_STATUS_STRINGS[client_status]

def error_text(error: int) -> str:
    text = ''
    
    if error == ray.Err.SESSION_IN_SESSION_DIR:
        text = _translate(
            'guimsg', 
            "Can't create session in a dir containing a session "
            "for better organization.")
    
    return text

def get_app_icon(icon_name: str, widget: QWidget) -> QIcon:
    dark = bool(
        widget.palette().brush(
            QPalette.ColorGroup.Inactive,
            QPalette.ColorRole.WindowText).color().lightness() > 128)
    
    if dark and icon_name in _APP_ICONS_CACHE_DARK.keys():
        return _APP_ICONS_CACHE_DARK[icon_name]
    if not dark and icon_name in _APP_ICONS_CACHE_LIGHT.keys():
        return _APP_ICONS_CACHE_LIGHT[icon_name]
    
    icon = QIcon.fromTheme(icon_name)

    if icon.isNull():
        for ext in ('svg', 'svgz', 'png'):
            filename = ":app_icons/%s.%s" % (icon_name, ext)
            darkname = ":app_icons/dark/%s.%s" % (icon_name, ext)

            if dark and QFile.exists(darkname):
                filename = darkname

            if QFile.exists(filename):
                del icon
                icon = QIcon()
                icon.addFile(filename)
                break

    if icon.isNull():
        for path in ('/usr/local', '/usr', '%s/.local' % os.getenv('HOME')):
            for ext in ('png', 'svg', 'svgz', 'xpm'):
                filename = "%s/share/pixmaps/%s.%s" % (path, icon_name, ext)
                if QFile.exists(filename):
                    del icon
                    icon = QIcon()
                    icon.addFile(filename)
                    break

    if dark:
        _APP_ICONS_CACHE_DARK[icon_name] = icon
    else:
        _APP_ICONS_CACHE_LIGHT[icon_name] = icon

    return icon
