import argparse
import os
import sys
from PyQt5.QtCore import QCoreApplication, QStandardPaths, QSettings

import ray

settings = QSettings()
#non_active_clients = []

def dirname(*args):
    return os.path.dirname(*args)

def getAppConfigPath():
    return "%s/%s" % (
            QStandardPaths.writableLocation(QStandardPaths.ConfigLocation),
            QCoreApplication.organizationName())

def getCodeRoot():
    return dirname(dirname(dirname(os.path.realpath(__file__))))

def initDaemonTools():
    #global non_active_clients
    #del non_active_clients
    
    if CommandLineArgs.config_dir:
        settings = QSettings(CommandLineArgs.config_dir)
    else:
        settings = QSettings()
        
    RS.setSettings(settings)
    
    RS.setNonActiveClients(ray.getListInSettings(settings, 
                                                 'daemon/non_active_list'))
    RS.setFavorites(ray.getListInSettings(settings, 'daemon/favorites'))
    TemplateRoots.initConfig()

def getGitDefaultUnAndIgnored(executable):
    ignored = []
    unignored = []
        
    if executable in ('luppp', 'sooperlooper', 'sooperlooper_nsm'):
        unignored.append('.wav')
            
    elif executable == 'samplv1_jack':
        unignored = ['.wav', '.flac', '.ogg', '.mp3']
        
    return (ignored, unignored)
    
class RS:
    settings = QSettings()
    non_active_clients = []
    favorites = []
    
    @classmethod
    def setSettings(cls, settings):
        del cls.settings
        cls.settings = settings
        
    @classmethod
    def setNonActiveClients(cls, nalist):
        del cls.non_active_clients
        cls.non_active_clients = nalist
        
    @classmethod
    def setFavorites(cls, favorites):
        cls.favorites = favorites

class TemplateRoots:
    net_session_name = ".ray-net-session-templates"
    factory_sessions = "%s/session_templates" % getCodeRoot()
    factory_clients  = "%s/client_templates"  % getCodeRoot()
    
    @classmethod
    def initConfig(cls):
        if CommandLineArgs.config_dir:
            app_config_path = CommandLineArgs.config_dir
        else:
            app_config_path = getAppConfigPath()
            
        cls.user_sessions = "%s/session_templates" % app_config_path
        cls.user_clients  = "%s/client_templates"  % app_config_path


class Terminal:
    _last_client_name = ''
    
    @classmethod
    def message(cls, string):
        if cls._last_client_name and cls._last_client_name != 'daemon':
            sys.stderr.write('\n')
        
        sys.stderr.write('[\033[90mray-daemon\033[0m]\033[92m%s\033[0m\n'
                            % string)
        
        cls._last_client_name = 'daemon'
        
    @classmethod
    def snapshoterMessage(cls, byte_string, command=''):
        snapshoter_str = "snapshoter:.%s" % command
        
        if cls._last_client_name != snapshoter_str:
            sys.stderr.write('\n[\033[90mray-daemon-git%s\033[0m]\n'
                             % command)
        sys.stderr.buffer.write(byte_string)
        
        cls._last_client_name = snapshoter_str

    @classmethod
    def clientMessage(cls, byte_string, client_name, client_id):
        client_str = "%s.%s" % (client_name, client_id)
        
        if not CommandLineArgs.debug_only:
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
    osc_port     = 0
    findfreeport = True
    gui_url      = None
    config_dir   = ''
    debug        = False
    debug_only   = False
    session      = ''
    
    @classmethod
    def eatAttributes(cls, parsed_args):
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
        
        default_root = "%s/%s" % (os.getenv('HOME'), 
                                  _translate('daemon', 
                                             'Ray Network Sessions'))
        
        self.add_argument('--session-root', '-r', type=str, default=default_root,
                          help='set root folder for sessions')
        self.add_argument('--session', '-s', type=str, default='',
                          help='session to load at startup')
        self.add_argument('--osc-port', '-p', 
                          type=int, default=0, 
                          help='select OSC port for the daemon')
        self.add_argument('--findfreeport', action='store_true', 
                          help='find another port if port is not free')
        self.add_argument('--gui-url', type=ray.getLibloAddress, 
                          help=argparse.SUPPRESS)
        self.add_argument('--config-dir', '-c', type=str, default='', 
                          help='use a custom config dir')
        self.add_argument('--debug','-d',  action='store_true', 
                          help='see all OSC messages')
        self.add_argument('--debug-only', '-do', action='store_true', 
                          help='debug without client messages')
        
        self.add_argument('-v', '--version', action='version',
                          version=ray.VERSION)
        
        parsed_args = argparse.ArgumentParser.parse_args(self)
        CommandLineArgs.eatAttributes(parsed_args)
        
        
