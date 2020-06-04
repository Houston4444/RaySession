

import argparse
import liblo
import os
import shlex
import socket
import subprocess
import sys
from liblo import Server, Address
from PyQt5.QtCore import QLocale, QTranslator, QT_VERSION_STR, QFile
from PyQt5.QtGui import QIcon, QPalette

# get qt version in list of ints
QT_VERSION = []
for strdigit in QT_VERSION_STR.split('.'):
    QT_VERSION.append(int(strdigit))

QT_VERSION = tuple(QT_VERSION)

if QT_VERSION < (5, 6):
    sys.stderr.write(
        "WARNING: You are using a version of QT older than 5.6.\n"
        + "You won't be warned if a process can't be launch.\n")
    
VERSION = "0.9.0"

APP_TITLE = 'RaySession'
DEFAULT_SESSION_ROOT = "%s/Ray Sessions" % os.getenv('HOME')
SCRIPTS_DIR = 'ray-scripts'
NOTES_PATH = 'ray-notes'
factory_session_templates = (
    'with_jack_patch', 'with_jack_config', 'scripted')

class PrefixMode:
    CUSTOM = 0
    CLIENT_NAME = 1
    SESSION_NAME = 2


class ClientStatus:
    STOPPED =  0
    LAUNCH  =  1
    OPEN    =  2
    READY   =  3
    PRECOPY =  4
    COPY    =  5
    SAVE    =  6
    SWITCH  =  7
    QUIT    =  8
    NOOP    =  9
    ERROR   = 10
    REMOVED = 11
    UNDEF   = 12
    SCRIPT  = 13


class ServerStatus:
    OFF      =  0
    NEW      =  1
    OPEN     =  2
    CLEAR    =  3
    SWITCH   =  4
    LAUNCH   =  5
    PRECOPY  =  6
    COPY     =  7
    READY    =  8
    SAVE     =  9
    CLOSE    = 10
    SNAPSHOT = 11
    REWIND   = 12
    WAIT_USER = 13
    OUT_SAVE  = 14
    OUT_SNAPSHOT = 15
    SCRIPT = 16


class NSMMode:
    NO_NSM  = 0
    CHILD   = 1
    NETWORK = 2


class Protocol:
    NSM = 0
    RAY_HACK = 1
    NET_SESSION = 2


class Option:
    NSM_LOCKED       = 0x001
    SAVE_FROM_CLIENT = 0x002 #DEPRECATED
    BOOKMARK_SESSION = 0x004
    HAS_WMCTRL       = 0x008
    DESKTOPS_MEMORY  = 0x010
    HAS_GIT          = 0x020
    SNAPSHOTS        = 0x040
    SESSION_SCRIPTS  = 0x080


class Err:
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


class Command:
    NONE = 0
    START = 1
    OPEN = 2
    SAVE = 3
    STOP = 4


class WaitFor:
    NONE = 0
    QUIT = 1
    STOP_ONE = 2
    ANNOUNCE = 3
    REPLY = 4
    DUPLICATE_START = 5
    DUPLICATE_FINISH = 6
    SCRIPT_QUIT = 7


class Template:
    NONE = 0
    RENAME = 1
    SESSION_SAVE = 2
    SESSION_SAVE_NET = 3
    SESSION_LOAD = 4
    SESSION_LOAD_NET = 5
    CLIENT_SAVE = 6
    CLIENT_LOAD = 7

class SwitchState:
    NONE = 0
    RESERVED = 1
    NEEDED = 2
    DONE = 3

class WindowManager:
    NONE = 0
    X = 1
    WAYLAND = 2


class Favorite():
    def __init__(self, name, icon, factory):
        self.name = name
        self.icon = icon
        self.factory = factory


debug = False


def ifDebug(string):
    if debug:
        sys.stderr.write("%s\n" % string)

def setDebug(bool):
    global debug
    debug = bool

def versionToTuple(version_str):
    version_list = []
    for c in version_str.split('.'):
        if not c.isdigit():
            return ()
        version_list.append(int(c))
        
    return tuple(version_list)

def addSelfBinToPath():
    # Add raysession/src/bin to $PATH to can use ray executables after make
    # Warning, will works only if link to this file is in RaySession/*/*/*.py
    this_path = os.path.realpath(os.path.dirname(os.path.realpath(__file__)))
    bin_path = "%s/bin" % os.path.dirname(this_path)
    if not os.environ['PATH'].startswith("%s:" % bin_path):
        os.environ['PATH'] = "%s:%s" % (bin_path, os.environ['PATH'])


def getListInSettings(settings, path):
    # getting a QSettings value of list type seems to not works the same way
    # on all machines
    try:
        settings_list = settings.value(path, [], type=list)
    except BaseException:
        try:
            settings_list = settings.value(path, [])
        except BaseException:
            settings_list = []

    return settings_list

def getGitIgnoredExtensions():
    return ".wav .flac .ogg .mp3 .mp4 .avi .mkv .peak .m4a .pdf"

def isPidChildOf(child_pid, parent_pid):
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

def isGitTaggable(string):
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

def highlightText(string):
    if "'" in string:
        return '"%s"' % string
    else:
        return "'%s'" % string

def isOscPortFree(port):
    try:
        testport = Server(port)
    except BaseException:
        return False

    del testport
    return True


def getFreeOscPort(default=16187):
    # get a free OSC port for daemon, start from default

    if default >= 65536:
        default = 16187

    daemon_port = default
    UsedPort = True
    testport = None

    while UsedPort:
        try:
            testport = Server(daemon_port)
            UsedPort = False
        except BaseException:
            daemon_port += 1
            UsedPort = True

    del testport
    return daemon_port


def isValidOscUrl(url):
    try:
        address = liblo.Address(url)
        return True
    except BaseException:
        return False


def getLibloAddress(url):
    valid_url = False
    try:
        address = liblo.Address(url)
        valid_url = True
    except BaseException:
        valid_url = False
        msg = "%r is not a valid osc url" % url
        raise argparse.ArgumentTypeError(msg)

    if valid_url:
        try:
            liblo.send(address, '/ping')
            return address
        except BaseException:
            msg = "%r is an unknown osc url" % url
            raise argparse.ArgumentTypeError(msg)

def getLibloAddressFromPort(port):
    try:
        port = int(port)
    except:
        msg = "%r port must be an int" % port
        raise argparse.ArgumentTypeError(msg)
    
    valid_port = False
    
    try:
        address = liblo.Address(port)
        valid_port = True
    except BaseException:
        valid_port = False
        msg = "%i is not a valid osc port" % port
        raise argparse.ArgumentTypeError(msg)

    if valid_port:
        try:
            liblo.send(address, '/ping')
            return address
        except BaseException:
            msg = "%i is an unknown osc port" % port
            raise argparse.ArgumentTypeError(msg)

def areSameOscPort(url1, url2):
    if url1 == url2:
        return True
    try:
        address1 = Address(url1)
        address2 = Address(url2)
    except BaseException:
        return False

    if address1.port != address2.port:
        return False

    if areOnSameMachine(url1, url2):
        return True

    return False


def areOnSameMachine(url1, url2):
    if url1 == url2:
        return True

    try:
        address1 = Address(url1)
        address2 = Address(url2)
    except BaseException:
        return False

    if address1.hostname == address2.hostname:
        return True

    try:
        if ((socket.gethostbyname(address1.hostname) in ('127.0.0.1', '127.0.1.1')) and (
                socket.gethostbyname(address2.hostname) in ('127.0.0.1', '127.0.1.1'))):
            return True

        if socket.gethostbyaddr(
                address1.hostname) == socket.gethostbyaddr(
                address2.hostname):
            return True
    except BaseException:
        try:
            ips = subprocess.check_output(['hostname', '-I']).decode()
            ip = ips.split(' ')[0]

            if ip.count('.') != 3:
                return False

            if ip not in (address1.hostname, address2.hostname):
                return False

            try:
                if socket.gethostbyname(
                        address1.hostname) in (
                        '127.0.0.1',
                        '127.0.1.1'):
                    if address2.hostname == ip:
                        return True
            except BaseException:
                if socket.gethostbyname(
                        address2.hostname) in (
                        '127.0.0.1',
                        '127.0.1.1'):
                    if address1.hostname == ip:
                        return True

        except BaseException:
            return False

        return False

    return False


def getUrl192(url):
    try:
        ips = subprocess.check_output(['hostname', '-I']).decode()
        ip = ips.split(' ')[0]
    except BaseException:
        return url

    if ip.count('.') != 3:
        return url

    suffix_port = url.rpartition(':')[2]
    return "osc.udp://%s:%s" % (ip, suffix_port)


def getThis192():
    global machine192

    if 'machine192' in globals():
        return machine192

    try:
        ips = subprocess.check_output(['hostname', '-I']).decode()
        ip = ips.split(' ')[0]
        machine192 = ip
        return ip
    except BaseException:
        return ''


def getMachine192(hostname=None):
    if hostname is None:
        return getThis192()
    else:
        if hostname in ('localhost', socket.gethostname()):
            return getThis192()

        return socket.gethostbyname(hostname)


def getMachine192ByUrl(url):
    try:
        addr = Address(url)
    except BaseException:
        return ''

    hostname = addr.hostname
    del addr

    return getMachine192(hostname)


def getNetUrl(port):
    try:
        ips = subprocess.check_output(['hostname', '-I']).decode()
        ip = ips.split(' ')[0]
    except BaseException:
        return ''

    if ip.count('.') != 3:
        return ''

    return "osc.udp://%s:%i/" % (ip, port)


def shellLineToArgs(string):
    try:
        args = shlex.split(string)
    except BaseException:
        return None

    return args

def areTheyAllString(args):
    for arg in args:
        if type(arg) != str:
            return False
    return True


def getAppIcon(icon_name, widget):
    dark = bool(
        widget.palette().brush(
            2, QPalette.WindowText).color().lightness() > 128)

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

    return icon

def getWindowManager():
    if os.getenv('WAYLAND_DISPLAY'):
        return WindowManager.WAYLAND
    
    if os.getenv('DISPLAY'):
        return WindowManager.X
    
    return WindowManager.NONE
    

def protocolToStr(protocol:int)->str:
    if protocol == Protocol.RAY_HACK:
        return "Ray-Hack"
    elif protocol == Protocol.NET_SESSION:
        return "Net-Session"
    return "NSM"

class ClientData:
    client_id = ''
    executable_path = ''
    arguments = ''
    name = ''
    prefix_mode = 2
    custom_prefix = ''
    desktop_file = ''
    label = ''
    description = ''
    icon = ''
    capabilities = ''
    check_last_save = True
    ignored_extensions = getGitIgnoredExtensions()
    protocol = Protocol.NSM
    ray_hack_config_file = ""
    ray_hack_save_sig = 0
    ray_hack_stop_sig = 15
    ray_hack_wait_win = False
    ray_hack_no_save_level = 0

    def __init__(self,
                 client_id,
                 executable,
                 arguments="",
                 name='',
                 prefix_mode=PrefixMode.SESSION_NAME,
                 custom_prefix='',
                 label='',
                 desktop_file='',
                 description='',
                 icon='',
                 capabilities='',
                 check_last_save=True,
                 ignored_extensions=getGitIgnoredExtensions(),
                 protocol=Protocol.NSM,
                 ray_hack_config_file="",
                 ray_hack_save_sig=0,
                 ray_hack_stop_sig=15,
                 ray_hack_wait_win=False,
                 ray_hack_no_save_level=0
                 ):
        self.client_id = str(client_id)
        self.executable_path = str(executable)
        self.arguments = str(arguments)
        self.prefix_mode = int(prefix_mode)
        self.desktop_file = str(desktop_file)
        self.label = str(label)
        self.description = str(description)
        self.capabilities = str(capabilities)
        self.check_last_save = bool(check_last_save)
        self.ignored_extensions = str(ignored_extensions)
        self.protocol = int(protocol)
        
        if self.protocol == Protocol.RAY_HACK:
            self.ray_hack_config_file = str(ray_hack_config_file)
            self.ray_hack_save_sig = int(ray_hack_save_sig)
            self.ray_hack_stop_sig = int(ray_hack_stop_sig)
            self.ray_hack_wait_win = bool(ray_hack_wait_win)
            self.ray_hack_no_save_level = int(ray_hack_no_save_level)

        self.name = str(name) if name else os.path.basename(
            self.executable_path)
        self.icon = str(icon) if icon else self.name.lower().replace('_', '-')

        if self.prefix_mode == PrefixMode.CUSTOM:
            if custom_prefix:
                self.custom_prefix = str(custom_prefix)
            else:
                self.prefix_mode = PrefixMode.SESSION_NAME
