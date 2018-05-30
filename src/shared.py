from liblo import Server, Address
import argparse
import liblo, socket
import sys, os, shlex
from PyQt5.QtCore import QLocale, QTranslator, QT_VERSION_STR

#get qt version in list of ints
QT_VERSION = []
for strdigit in QT_VERSION_STR.split('.'):
    QT_VERSION.append(int(strdigit))

QT_VERSION = tuple(QT_VERSION)

if QT_VERSION < (5, 6):
    sys.stderr.write("WARNING: You are using a version of QT older than 5.6.\nYou won't be able to know if a process can't be launch.\n")

#Ray Session version
VERSION = "0.6.0"

APP_TITLE = 'Ray Session'

PREFIX_MODE_UNDEF        = 0
PREFIX_MODE_CLIENT_NAME  = 1
PREFIX_MODE_SESSION_NAME = 2

CLIENT_STATUS_STOPPED =  0
CLIENT_STATUS_LAUNCH  =  1
CLIENT_STATUS_OPEN    =  2
CLIENT_STATUS_READY   =  3
CLIENT_STATUS_PRECOPY =  4
CLIENT_STATUS_COPY    =  5
CLIENT_STATUS_SAVE    =  6
CLIENT_STATUS_SWITCH  =  7
CLIENT_STATUS_QUIT    =  8
CLIENT_STATUS_NOOP    =  9
CLIENT_STATUS_ERROR   = 10
CLIENT_STATUS_REMOVED = 11

SERVER_STATUS_OFF       =  0
SERVER_STATUS_NEW       =  1
SERVER_STATUS_OPEN      =  2
SERVER_STATUS_CLEAR     =  3
SERVER_STATUS_SWITCH    =  4
SERVER_STATUS_LAUNCH    =  5
SERVER_STATUS_PRECOPY   =  6
SERVER_STATUS_COPY      =  7
SERVER_STATUS_READY     =  8
SERVER_STATUS_SAVE      =  9
SERVER_STATUS_CLOSE     = 10


def ifDebug(string):
    if debug:
        print(string, file=sys.stderr)

def setDebug(bool):
    global debug
    debug = bool

def isOscPortFree(port):
    try:
        testport = Server(port)
    except:
        return False
    
    del testport
    return True

def getFreeOscPort(default=16187):
    #get a free OSC port for daemon, start from default
    
    if default >= 65536:
        default=16187
    
    daemon_port = default
    UsedPort    = True
    testport    = None

    while UsedPort:
        try:
            testport = Server(daemon_port)
            UsedPort = False
        except:
            daemon_port += 1
            UsedPort = True

    del testport
    return daemon_port

def getLibloAddress(url):
    valid_url = False
    try:
        address = liblo.Address(url)
        valid_url = True
    except:
        valid_url = False
        msg = "%r is not a valid osc url" % url
        raise argparse.ArgumentTypeError(msg)
    
    if valid_url:
        try:
            liblo.send(address, '/ping')
            return address
        except:
            msg = "%r is an unknown osc url" % url
            raise argparse.ArgumentTypeError(msg)

def areSameOscPort(url1, url2):
    if url1 == url2:
        return True
    #print('areSameOscPort')
    try:
        address1 = Address(url1)
        address2 = Address(url2)
    except:
        return False
    
    #print('zef')
    
    if address1.port != address2.port:
        return False
    
    if areOnSameMachine(url1, url2):
        return True
    
    return False
    
    ##print('zmelf')
    #if address1.hostname == address2.hostname:
        #return True
    
    ##print('zemofk')
    #try:
        #if socket.gethostbyaddr(address1.hostname) == socket.gethostbyaddr(address2.hostname):
            #return True
    #except:
        #return False
    
    ##print('mzokef')
    #return False
    
def areOnSameMachine(url1, url2):
    if url1 == url2:
        return True
    
    try:
        address1 = Address(url1)
        address2 = Address(url2)
    except:
        return False
    
    if address1.hostname == address2.hostname:
        return True
    
    try:
        if socket.gethostbyaddr(address1.hostname) == socket.gethostbyaddr(address2.hostname):
            return True
    except:
        return False
    
    #print('mzokef')
    return False
    
    
def shellLineToArgs(string):
    try:
        args = shlex.split(string)
    except:
        return None
    
    return args

def areTheyAllString(args):
    for arg in args:
        if type(arg) != str:
            return False
    return True

class ClientData(object):
    client_id       = ''
    executable_path = ''
    arguments       = ''
    name            = ''
    prefix_mode     = 2
    project_path    = ''
    label           = ''
    icon            = ''
    capabilities    = ''
    check_last_save = True
    
    def __init__(self, client_id, 
                 executable,
                 arguments="",
                 name='', 
                 prefix_mode=PREFIX_MODE_SESSION_NAME, 
                 project_path='', 
                 label='', 
                 icon='', 
                 capabilities='',
                 check_last_save=True):
        self.client_id       = str(client_id)
        self.executable_path = str(executable)
        self.arguments       = str(arguments)
        self.prefix_mode     = int(prefix_mode)
        self.label           = str(label)
        self.capabilities    = str(capabilities)
        self.check_last_save = bool(check_last_save)
        
        self.name  = str(name) if name else os.path.basename(self.executable_path)
        self.icon  = str(icon) if icon else self.name.lower().replace('_', '-')
        
        if self.prefix_mode == 0:
            if self.project_path:
                self.project_path = str(project_path)
            else:
                self.prefix_mode = 2

def clientStatusString(status):
    if not 0 <= status < len(client_status_strings):
        return _translate('client status', "invalid")
        
    return client_status_strings[status]

def serverStatusString(server_status):
    if not 0 <= server_status < len(server_status_strings):
        return _translate('server status', "invalid")
    
    return server_status_strings[server_status]

def init_translation(_translate):    
    global client_status_strings
    client_status_strings = {CLIENT_STATUS_STOPPED: _translate('client status', "stopped"),
                             CLIENT_STATUS_LAUNCH : _translate('client status', "launch"),
                             CLIENT_STATUS_OPEN   : _translate('client status', "open"),
                             CLIENT_STATUS_READY  : _translate('client status', "ready"),
                             CLIENT_STATUS_PRECOPY: _translate('client status', "copy"),
                             CLIENT_STATUS_COPY   : _translate('client status', "copy"),
                             CLIENT_STATUS_SAVE   : _translate('client status', "save"),
                             CLIENT_STATUS_SWITCH : _translate('client status', "switch"),
                             CLIENT_STATUS_QUIT   : _translate('client status', "quit"),
                             CLIENT_STATUS_NOOP   : _translate('client status', "noop"),
                             CLIENT_STATUS_ERROR  : _translate('client status', "error"),
                             CLIENT_STATUS_REMOVED: _translate('client status', "removed") }
    
    global server_status_strings
    server_status_strings = {SERVER_STATUS_OFF      : _translate('server status', "off"),
                             SERVER_STATUS_NEW      : _translate('server status', "new"),
                             SERVER_STATUS_OPEN     : _translate('server status', "open"),
                             SERVER_STATUS_CLEAR    : _translate('server status', "clear"),
                             SERVER_STATUS_SWITCH   : _translate('server status', "switch"),
                             SERVER_STATUS_LAUNCH   : _translate('server status', "launch"),
                             SERVER_STATUS_PRECOPY  : _translate('server status', "copy"),
                             SERVER_STATUS_COPY     : _translate('server status', "copy"),
                             SERVER_STATUS_READY    : _translate('server status', "ready"),
                             SERVER_STATUS_SAVE     : _translate('server status', "save"),
                             SERVER_STATUS_CLOSE    : _translate('server status', "close") }

        
