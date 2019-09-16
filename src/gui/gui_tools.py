import argparse
import os
import sys
from PyQt5.QtCore import QSettings, QSize
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QIcon, QPixmap, QPalette

import ray



g_settings = QSettings()
default_session_root = "%s/Ray Sessions" % (os.getenv('HOME'))

def _translate(*args):
    return QApplication.translate(*args)

def setDefaultSessionRoot(path):
    global default_session_root
    default_session_root = path
    
def getDefaultSessionRoot():
    return default_session_root

class RS:
    settings = QSettings()
    
    @classmethod
    def setSettings(cls, settings):
        del cls.settings
        cls.settings = settings

def initGuiTools():
    if CommandLineArgs.under_nsm:
        settings = QSettings('%s/child_sessions'
                             % QApplication.organizationName())
    elif CommandLineArgs.config_dir:
        settings = QSettings(CommandLineArgs.config_dir)
    else:
        settings = QSettings()
       
    RS.setSettings(settings)
    
    CommandLineArgs.changeSessionRoot(
        settings.value('default_session_root',
                       "%s/Ray Sessions" % (os.getenv('HOME')),
                        type=str))

def isDarkTheme(widget):
    return bool(
        widget.palette().brush(2, QPalette.WindowText).color().lightness()
        > 128)

def dirname(*args):
    return os.path.dirname(*args)

def getCodeRoot():
    return dirname(dirname(dirname(os.path.realpath(__file__))))

def serverStatusString(server_status):
    server_status_strings = {
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
        ray.ServerStatus.WAIT_USER : _translate('server_status', "waiting"),
        ray.ServerStatus.OUT_SAVE: _translate('server_status', "save"),
        ray.ServerStatus.OUT_SNAPSHOT: _translate('server_status', "snapshot")}

    if not 0 <= server_status < len(server_status_strings):
        return _translate('server status', "invalid")

    return server_status_strings[server_status]


def clientStatusString(client_status):
    client_status_strings = {
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
        ray.ClientStatus.UNDEF  : _translate('client_status', "")}

    if not 0 <= client_status < len(client_status_strings):
        return _translate('client_status', 'invalid')

    return client_status_strings[client_status]


class ErrDaemon:
    # for use on network session under NSM
    NO_ERROR = 0
    NO_ANNOUNCE = -1
    NOT_OFF = -2
    WRONG_ROOT = -3
    FORBIDDEN_ROOT = -4
    NOT_NSM_LOCKED = -5
    WRONG_VERSION = -6


class RayIcon(QIcon):
    def __init__(self, icon_name, dark=False):
        QIcon.__init__(self)
        breeze = 'breeze-dark' if dark else 'breeze'
        self.addFile(':scalable/%s/%s' % (breeze, icon_name), QSize(22, 22))
        self.addPixmap(
            QPixmap(
                ':scalable/%s/disabled/%s' %
                (breeze, icon_name)), QIcon.Disabled, QIcon.Off)
    

class CommandLineArgs(argparse.Namespace):
    daemon_url = None
    out_daemon = False
    config_dir = ''
    debug = False
    debug_only = False
    net_session_root = ''
    net_daemon_id = 0
    under_nsm = False
    NSM_URL = ''
    session_root = ''
    session = ''

    @classmethod
    def eatAttributes(cls, parsed_args):
        for attr_name in dir(parsed_args):
            if not attr_name.startswith('_'):
                setattr(cls, attr_name, getattr(parsed_args, attr_name))

        if cls.debug_only:
            cls.debug = True

        if cls.config_dir and not os.access(cls.config_dir, os.W_OK):
            sys.stderr.write(
                '%s is not a writable config dir, try another one\n'
                % cls.config_dir)
            sys.exit(1)

        if os.getenv('NSM_URL'):
            try:
                cls.NSM_URL = ray.getLibloAddress(os.getenv('NSM_URL'))
            except BaseException:
                sys.stderr.write('%s is not a valid NSM_URL\n'
                                 % os.getenv('NSM_URL'))
                sys.exit(1)

            cls.under_nsm = True
        
        if not cls.session_root:
            cls.session_root = RS.settings.value(
                                    'default_session_root',
                                    '%s/Ray Sessions' % os.getenv('HOME'))
        
        if cls.session_root.endswith('/'):
            cls.session_root = cls.session_root[:-1]
            
    @classmethod
    def changeSessionRoot(cls, path):
        cls.session_root = path


class ArgParser(argparse.ArgumentParser):
    def __init__(self):
        argparse.ArgumentParser.__init__(
            self,
            description=_translate(
                'help',
                'A session manager based on the Non-Session-Manager API '
                + 'for sound applications.'))
        self.add_argument('--daemon-url', '-u', type=ray.getLibloAddress,
                          help=_translate('help',
                                          'connect to this daemon url'))
        self.add_argument('--out-daemon', action='store_true',
                          help=argparse.SUPPRESS)
        self.add_argument('--session-root', '-r', type=str,
                          help=_translate(
                              'help', 'Use this folder as root for sessions'))
        self.add_argument('--session', '-s', type=str,
                          help=_translate('help', 
                                          'Open this session at startup'))
        self.add_argument('--config-dir', '-c', type=str, default='',
                          help=_translate('help', 'use a custom config dir'))
        self.add_argument('--debug', '-d', action='store_true',
                          help=_translate('help', 'display OSC messages'))
        self.add_argument('--debug-only', '-do', action='store_true',
                          help=_translate('help',
                                          'debug without client messages'))
        self.add_argument('--net-session-root', type=str, default='',
                          help=argparse.SUPPRESS)
        self.add_argument('--net-daemon-id', type=int, default=0,
                          help=argparse.SUPPRESS)
        self.add_argument('-v', '--version', action='version',
                          version=ray.VERSION)

        parsed_args = argparse.ArgumentParser.parse_args(self)
        CommandLineArgs.eatAttributes(parsed_args)
