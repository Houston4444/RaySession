from liblo import Server
import argparse
import liblo
import sys, os

VERSION = "0.2.0"

APP_TITLE = 'Ray Session'

PREFIX_MODE_UNDEF        = 0
PREFIX_MODE_CLIENT_NAME  = 1
PREFIX_MODE_SESSION_NAME = 2

#NOT IMPLEMENTED YET
CLIENT_STATUS_STOPPED = 0
CLIENT_STATUS_LAUNCH  = 1
CLIENT_STATUS_OPEN    = 2
CLIENT_STATUS_READY   = 3
CLIENT_STATUS_SWITCH  = 4
CLIENT_STATUS_CLOSE   = 5
CLIENT_STATUS_NOOP    = 6
CLIENT_STATUS_ERROR   = 7


def ifDebug(string):
    if debug:
        #qDebug(remove_accents(string))
        print(string, file=sys.stderr)

def setDebug(bool):
    global debug
    debug = bool

def getFreeOscPort(default=16187):
    #get a free OSC port for deamon, start from default
    
    if default == 65536:
        default=16187
    
    deamon_port = default
    UsedPort    = True
    testport    = None

    while UsedPort:
        try:
            testport = Server(deamon_port)
            UsedPort = False
        except:
            deamon_port += 1
            UsedPort = True

    del testport
    return deamon_port

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
        
class ClientData(object):
    client_id       = ''
    executable_path = ''
    name            = ''
    prefix_mode     = 2
    project_path    = ''
    label           = ''
    icon            = ''
    capabilities    = ''
    
    def __init__(self, client_id, 
                 executable, 
                 name='', 
                 prefix_mode=PREFIX_MODE_SESSION_NAME, 
                 project_path='', 
                 label='', 
                 icon='', 
                 capabilities=''):
        self.client_id       = str(client_id)
        self.executable_path = str(executable)
        self.prefix_mode     = int(prefix_mode)
        self.label           = str(label)
        self.capabilities    = str(capabilities)
        
        self.name  = str(name)  if name  else os.path.basename(self.executable_path)
        self.icon  = str(icon)  if icon  else self.name.lower().replace('_', '-')
        
        if self.prefix_mode == 0:
            self.project_path = str(project_path)
        
