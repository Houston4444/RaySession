
# Imports from standard library
import logging
import os
from pickletools import optimize
import shlex
import random
import shutil
import subprocess
import time
from typing import TYPE_CHECKING, Callable, Optional
from pathlib import Path
import xml.etree.ElementTree as ET

# third party imports
from qtpy.QtCore import QCoreApplication

# Imports from HoustonPatchbay
from patshared import GroupPos

# Imports from src/shared
from osclib import (
    Address, BunServerThread, MegaSend, get_net_url, Message,
    OscPack, are_on_same_machine, are_same_osc_port, send, TCP,
    verified_address, OscMulTypes)
import ray
from xml_tools import XmlElement
import osc_paths
import osc_paths.ray as r
import osc_paths.ray.gui as rg
import osc_paths.nsm as nsm

# Local imports
from signaler import Signaler
import multi_daemon_file
from daemon_tools import (
    TemplateRoots, CommandLineArgs,
    Terminal, RS, get_code_root)
from terminal_starter import which_terminal

if TYPE_CHECKING:
    from session_signaled import SignaledSession


instance = None
signaler = Signaler.instance()
_translate = QCoreApplication.translate
_logger = logging.getLogger(__name__)

_validators = dict[str, Callable[[OscPack], bool]]()
_validators_types = dict[str, str]()


def _path_is_valid(path: str) -> bool:
    if path.startswith(('./', '../')):
        return False

    for forbidden in ('//', '/./', '/../'):
        if forbidden in path:
            return False

    if path.endswith(('/.', '/..')):
        return False
    return True


def validator(path: str, multypes: OscMulTypes, no_sess='', directos=False):
    '''With this decorator, the OSC path method will continue
    its work in the main thread (in session_signaled module),
    except if the function returns False.
    
    `path`: OSC str path

    `full_types`: str containing all accepted arg types
    separated with '|'. It also accepts special characters:
    - '.' for any arg type
    - '*' for any number of args of type specified by the previous
    character
    
    `no_sess`: string message to send if no session is open 
    '''
    def decorated(func: Callable):
        def wrapper(*args, **kwargs):
            if no_sess:
                server: 'OscServerThread' = args[0]
                osp: OscPack = args[1]

                if server.session.path is None:
                    server.send(
                        *osp.error(), ray.Err.NO_SESSION_OPEN, no_sess)
                    return False

            response = func(*args, **kwargs)
            if directos or response is False:
                return False
            return True
    
        _validators[path] = wrapper
        _validators_types[path] = multypes

        return wrapper
    return decorated

def directos(path: str, multypes: OscMulTypes, no_sess=''):
    '''This OSC path method decorated with this 
    does all its job directly in the thread of the server.
    No work will have to be done in the main thread.
    see `validator` doc.'''
    return validator(path, multypes, no_sess=no_sess, directos=True)


class Controller:
    addr: Optional[Address] = None
    pid = 0


class Gui:
    def __init__(self, url: str):
        self.addr = Address(url)
        self.tcp_addr: Optional[Address] = None
        self.pid = 0


# Osc server thread is splitted in several classes for confort.


class ClientCommunicating(BunServerThread):
    '''Contains NSM protocol.
    OSC paths have to be never changed.'''
    
    def __init__(self, session: 'SignaledSession', osc_num=0, tcp_port=0):
        BunServerThread.__init__(self, osc_num)
        self.session = session
        self.tcp_port = tcp_port
        'the port number of the tcp_server.'

        self._nsm_locker_url = ''
        self._net_master_daemon_url = ''
        self._list_asker_addr = None

        self.gui_list = list[Gui]()
        self.controller_list = list[Controller]()
        self.monitor_list = list[Address]()
        self.server_status = ray.ServerStatus.OFF
        self.is_nsm_locked = False
        self.not_default = False

        self.net_daemon_id = random.randint(1, 999999999)
        self.options = 0

    @directos(osc_paths.osc.PING, '')
    def _osc_ping(self, osp: OscPack):
        self.send(*osp.reply())

    @validator(osc_paths.REPLY, 'ss*')
    def reply(self, osp: OscPack):
        reply_path: str = osp.args[0]

        if reply_path == r.server.LIST_SESSIONS:
            # this reply is only used here for reply from net_daemon
            # it directly resend its infos
            # to the last addr that asked session list
            if self._list_asker_addr:
                self.send(self._list_asker_addr, osp.path, *osp.args)
            return False

        if reply_path == rg.SCRIPT_USER_ACTION:
            self.send_gui(rg.HIDE_SCRIPT_USER_ACTION)
            for controller in self.controller_list:
                self.send(controller.addr, osc_paths.REPLY,
                          r.server.SCRIPT_USER_ACTION,
                          'User action dialog validate')
            return False

        if not len(osp.args) == 2:
            # assume this is a normal client, not a net_daemon
            self._unknown_message(osp)
            return False

    @validator(osc_paths.ERROR, 'sis')
    def error(self, osp: OscPack):
        error_path, error_code, error_string = osp.args

        if error_path == rg.SCRIPT_USER_ACTION:
            self.send_gui(rg.HIDE_SCRIPT_USER_ACTION)

            for controller in self.controller_list:
                self.send(controller.addr, osc_paths.ERROR,
                          r.server.SCRIPT_USER_ACTION, -1,
                          'User action dialog aborted !')
            return False

    @validator(osc_paths.MINOR_ERROR, 'sis')
    def minor_error(self, osp: OscPack):
        # prevent minor_error to minor_error loop 
        # in daemon <-> daemon communication
        pass

    # SERVER_CONTROL messages
    # following messages only for :server-control: capability
    @validator(nsm.server.ADD, 's',
               no_sess="Cannot add to session because no session is loaded.")
    def _nsm_server_add(self, osp: OscPack):
        executable_path: str = osp.args[0]

        if '/' in executable_path:
            self.send(*osp.error(), ray.Err.LAUNCH_FAILED,
                "Absolute paths are not permitted. Clients must be in $PATH")
            return False

    @validator(nsm.server.SAVE, '', no_sess="No session to save.")
    def _nsm_server_save(self, osp: OscPack):
        ...

    @validator(nsm.server.OPEN, 's')
    def _nsm_server_open(self, osp: OscPack):
        ...

    @validator(nsm.server.NEW, 's')
    def _nsm_server_new(self, osp: OscPack):
        if self.is_nsm_locked:
            return False

        new_session_name: str = osp.args[0]

        if not _path_is_valid(new_session_name):
            self.send(*osp.error(), ray.Err.CREATE_FAILED,
                      "Invalid session name.")
            return False

    @validator(nsm.server.DUPLICATE, 's')
    def _nsm_server_duplicate(self, osp: OscPack):
        if self.is_nsm_locked or self.session.path is None:
            self.send(*osp.error(), ray.Err.NO_SESSION_OPEN,
                      "No session to duplicate.")
            return False

        if not _path_is_valid(osp.args[0]):
            self.send(*osp.error(), ray.Err.CREATE_FAILED,
                      "Invalid session name.")
            return False

    @validator(nsm.server.CLOSE, '', no_sess='No session to close.')
    def _nsm_server_close(self, osp: OscPack):
        ...

    @validator(nsm.server.ABORT, '', no_sess='No session to abort.')
    def _nsm_server_abort(self, osp: OscPack):
        ...

    @validator(nsm.server.QUIT, '')
    def _nsm_server_quit(self, osp: OscPack):
        ...

    @validator(nsm.server.LIST, '')
    def _nsm_server_list(self, osp: OscPack):
        ...

    # END OF SERVER_CONTROL messages

    @validator(nsm.server.ANNOUNCE, 'sssiii',
               no_sess="Sorry, but there's no session open "
                       "for this application to join.")
    def _nsm_server_announce(self, osp: OscPack):
        ...

    @validator(nsm.server.BROADCAST, 's.*')
    def _nsm_server_broadcast(self, osp: OscPack):
        # don't allow clients to broadcast NSM commands
        follow_path: str = osp.args[0]
        if follow_path.startswith(('/nsm/', '/ray/')):
            return False

        for client in self.session.clients:
            if not client.addr:
                continue

            if not are_same_osc_port(client.addr.url, osp.src_addr.url):
                self.send(client.addr, Message(*osp.args))

            # TODO broadcast to slave daemons
            #for gui_addr in self.gui_list:
                ##also relay to attached GUI so that the broadcast can be
                ##propagated to another NSMD instance
                #if gui_addr.url != osp.src_addr.url:
                    #self.send(gui_addr, Message(*osp.args))

    @validator(nsm.server.MONITOR_RESET, '')
    def _nsm_server_monitor_reset(self, osp: OscPack):
        self.send(*osp.reply(), 'monitor reset')
        self.session.send_initial_monitor(
            osp.src_addr, monitor_is_client=True)

    @validator(nsm.client.PROGRESS, 'f')
    def _nsm_client_progress(self, osp: OscPack):
        client = self.session.get_client_by_address(osp.src_addr)
        if not client:
            return False

        progress: float = osp.args[0]
        client.progress = progress
        self.send_gui(rg.client.PROGRESS, client.client_id,
                      client.progress)

    @validator(nsm.client.IS_DIRTY, '')
    def _nsm_client_is_dirty(self, osp: OscPack):
        client = self.session.get_client_by_address(osp.src_addr)
        if not client:
            return False

        Terminal.message("%s sends dirty" % client.client_id)

        client.dirty = 1
        client.last_dirty = time.time()

        self.send_gui(rg.client.DIRTY, client.client_id, client.dirty)

    @validator(nsm.client.IS_CLEAN, '')
    def _nsm_client_is_clean(self, osp: OscPack):
        client = self.session.get_client_by_address(osp.src_addr)
        if not client:
            return False

        Terminal.message("%s sends clean" % client.client_id)

        client.dirty = 0

        self.send_gui(rg.client.DIRTY, client.client_id, client.dirty)
        return False

    @validator(nsm.client.MESSAGE, 'is')
    def _nsm_client_message(self, osp: OscPack):
        client = self.session.get_client_by_address(osp.src_addr)
        if not client:
            return False

        self.send_gui(rg.client.MESSAGE,
                      client.client_id, osp.args[0], osp.args[1])

    @validator(nsm.client.GUI_IS_HIDDEN, '')
    def _nsm_client_gui_is_hidden(self, osp: OscPack):
        client = self.session.get_client_by_address(osp.src_addr)
        if not client:
            return False

        Terminal.message("Client '%s' sends gui hidden" % client.client_id)

        client.gui_visible = False

        self.send_gui(rg.client.GUI_VISIBLE, client.client_id,
                      int(client.gui_visible))

    @validator(nsm.client.GUI_IS_SHOWN, '')
    def _nsm_client_gui_is_shown(self, osp: OscPack):
        client = self.session.get_client_by_address(osp.src_addr)
        if not client:
            return False

        Terminal.message("Client '%s' sends gui shown" % client.client_id)

        client.gui_visible = True
        client.gui_has_been_visible = True

        self.send_gui(rg.client.GUI_VISIBLE, client.client_id,
                      int(client.gui_visible))

    @validator(nsm.client.LABEL, 's')
    def _nsm_client_label(self, osp: OscPack):
        ...

    @validator(nsm.client.NETWORK_PROPERTIES, 'ss')
    def _nsm_client_network_properties(self, osp: OscPack):
        ...

    def _unknown_message(self, osp: OscPack):
        self.send(osp.src_addr, osc_paths.MINOR_ERROR, osp.path,
                  ray.Err.UNKNOWN_MESSAGE,
                  "unknown osc message: %s %s" % (osp.path, osp.types))

    def send_gui(self, *args):
        # should be overclassed
        ...


class OscServerThread(ClientCommunicating):
    def __init__(self, session, osc_num=0, tcp_port=0):
        ClientCommunicating.__init__(
            self, session, osc_num=osc_num, tcp_port=tcp_port)

        self._OPTIONS_DICT = {
            'save_from_client': ray.Option.SAVE_FROM_CLIENT,
            'bookmark_session_folder': ray.Option.BOOKMARK_SESSION,
            'desktops_memory': ray.Option.DESKTOPS_MEMORY,
            'snapshots': ray.Option.SNAPSHOTS,
            'session_scripts': ray.Option.SESSION_SCRIPTS,
            'gui_states': ray.Option.GUI_STATES}

        default_options = (ray.Option.BOOKMARK_SESSION
                           | ray.Option.SNAPSHOTS
                           | ray.Option.SESSION_SCRIPTS)

        try:
            self.options = ray.Option(RS.settings.value(
                'daemon/options',
                default_options.value,
                type=int))
        except BaseException as e:
            _logger.warning(f'Unable to find config daemon options\n{str(e)}')
            self.options = default_options

        if CommandLineArgs.no_options:
            self.options = ray.Option.NONE

        if shutil.which('wmctrl'):
            self.options |= ray.Option.HAS_WMCTRL
        else:
            self.options &= ~ray.Option.HAS_WMCTRL

        if shutil.which('git'):
            self.options |= ray.Option.HAS_GIT
        else:
            self.options &= ~ray.Option.HAS_GIT

        self.client_templates_database = {
            'factory': [], 'user': []}

        self.session_to_preview = ''
        
        self._terminal_command_is_default = True
        self.terminal_command = RS.settings.value(
            'daemon/terminal_command', '', type=str)
        if self.terminal_command:
            self._terminal_command_is_default = False
        else:
            self.terminal_command = shlex.join(
                which_terminal(title='RAY_TERMINAL_TITLE'))
        
        self.patchbay_dmn_port: Optional[int] = None
        
        methods_dict = {
            r.server.ABORT_COPY: '',
            r.server.ABORT_PARRALLEL_COPY: 'i',
            r.server.ABORT_SNAPSHOT: '',
            r.server.LIST_FACTORY_CLIENT_TEMPLATES: 's*',
            r.server.LIST_USER_CLIENT_TEMPLATES: 's*',
            r.server.OPEN_SESSION: 's|si|sis',
            r.server.OPEN_SESSION_OFF: 's|si',
            r.server.QUIT: '',
            r.server.RENAME_SESSION: 'ss',
            r.server.patchbay.CLEAR_ABSENTS_IN_VIEW: 's',
            r.server.patchbay.SAVE_GROUP_PRETTY_NAME: 'sssi',
            r.server.patchbay.SAVE_PORT_PRETTY_NAME: 'sssi',
            r.server.patchbay.SAVE_PORTGROUP: 'siiiss*',
            r.server.patchbay.VIEW_NUMBER_CHANGED: 'ii',
            r.server.patchbay.VIEW_PTV_CHANGED: 'ii',
            r.server.patchbay.VIEWS_CHANGED: 's',
            r.net_daemon.DUPLICATE_STATE: 'f',
            r.session.ABORT: '',
            r.session.ADD_CLIENT_TEMPLATE: 'isss',
            r.session.ADD_FACTORY_CLIENT_TEMPLATE: 'ss*',
            r.session.ADD_OTHER_SESSION_CLIENT: 'ss',
            r.session.ADD_USER_CLIENT_TEMPLATE: 'ss*',
            r.session.CLEAR_CLIENTS: 's*',
            r.session.GET_NOTES: '',
            r.session.LIST_CLIENTS: 's*',
            r.session.LIST_SNAPSHOTS: '',
            r.session.LIST_TRASHED_CLIENTS: '',
            r.session.OPEN_SNAPSHOT: 's',
            r.session.REORDER_CLIENTS: 'ss*',
            r.session.RUN_STEP: 's*',
            r.session.SET_AUTO_SNAPSHOT: 'i',
            r.client.CHANGE_ADVANCED_PROPERTIES: 'ssisi',
            r.client.CHANGE_ID: 'ss',
            r.client.FULL_RENAME: 'ss',
            r.client.GET_CUSTOM_DATA: 'ss',
            r.client.GET_DESCRIPTION: 's',
            r.client.GET_PID: 's',
            r.client.GET_PROPERTIES: 's',
            r.client.GET_TMP_DATA: 'ss',
            r.client.HIDE_OPTIONAL_GUI: 's',
            r.client.IS_STARTED: 's',
            r.client.KILL: 's',
            r.client.LIST_FILES: 's',
            r.client.LIST_SNAPSHOTS: 's',
            r.client.OPEN: 's',
            r.client.OPEN_SNAPSHOT: 'ss',
            r.client.RESUME: 's',
            r.client.SAVE: 's',
            r.client.SAVE_AS_TEMPLATE: 'ss',
            r.client.SEND_SIGNAL: 'si',
            r.client.SET_CUSTOM_DATA: 'sss',
            r.client.SET_DESCRIPTION: 'ss',
            r.client.SET_PROPERTIES: 'sss*',
            r.client.SET_TMP_DATA: 'sss',
            r.client.SHOW_OPTIONAL_GUI: 's',
            r.client.START: 's',
            r.client.STOP: 's',
            r.client.TRASH: 's',
            r.client.UPDATE_PROPERTIES: ray.ClientData.sisi(),
            r.client.UPDATE_RAY_HACK_PROPERTIES: 's' + ray.RayHack.sisi(),
            r.client.UPDATE_RAY_NET_PROPERTIES: 's' + ray.RayNet.sisi(),
            r.trashed_client.REMOVE_DEFINITELY: 's',
            r.trashed_client.REMOVE_KEEP_FILES: 's',
            r.trashed_client.RESTORE: 's',
        }
        
        self.add_nice_methods(methods_dict, self.generic_method)
        self.add_nice_methods(_validators_types, self.generic_method)
        self.add_method(None, None, self.noneMethod)
        global instance
        instance = self

    @staticmethod
    def get_instance() -> 'Optional[OscServerThread]':
        return instance

    def generic_method(self, osp: OscPack):
        '''Except the unknown messages, all messages received
        go through here.'''
        
        # run the method decorated with @validator or @directos
        if osp.path in _validators:
            if not _validators[osp.path](self, osp):
                return

        # session_signaled will operate the message in the main thread
        signaler.osc_recv.emit(osp)

    @directos(r.server.GUI_ANNOUNCE, 'sisiis')
    def _srv_gui_announce(self, osp: OscPack):
        args: tuple[str, int, str, int, int, str] = osp.args
        (version, int_nsm_locked, net_master_daemon_url,
         gui_pid, net_daemon_id, tcp_url) = args

        nsm_locked = bool(int_nsm_locked)
        is_net_free = True

        if nsm_locked:
            self._net_master_daemon_url = net_master_daemon_url
            self.is_nsm_locked = True
            self._nsm_locker_url = osp.src_addr.url

            for gui in self.gui_list:
                if not are_same_osc_port(gui.addr.url, osp.src_addr.url):
                    self.send(gui.addr, rg.server.NSM_LOCKED, 1)

            self.net_daemon_id = net_daemon_id

            is_net_free = multi_daemon_file.is_free_for_root(
                self.net_daemon_id, self.session.root)

        tcp_addr = verified_address(tcp_url)
        if isinstance(tcp_addr, str):
            tcp_addr = None

        self.announce_gui(
            osp.src_addr.url, nsm_locked, is_net_free, gui_pid, tcp_addr)

    @directos(r.server.GUI_DISANNOUNCE, '')
    def _srv_gui_disannounce(self, osp: OscPack):
        for gui in self.gui_list:
            if are_same_osc_port(gui.addr.url, osp.src_addr.url):
                break
        else:
            return False

        self.gui_list.remove(gui)

        if osp.src_addr.url == self._nsm_locker_url:
            self.net_daemon_id = random.randint(1, 999999999)

            self.is_nsm_locked = False
            self._nsm_locker_url = ''
            self.send_gui(rg.server.NSM_LOCKED, 0)

        multi_daemon_file.update()

    @validator(r.server.ASK_FOR_PATCHBAY, 's')
    def _srv_ask_for_patchbay(self, osp: OscPack):
        gui_tcp_url: str = osp.args[0]
        patchbay_file = \
            Path('/tmp/RaySession/patchbay_daemons') / str(self.port)

        if not patchbay_file.exists():
            return True

        with open(patchbay_file, 'r') as file:
            contents = file.read()
            for line in contents.splitlines():
                if line.startswith('pid:'):
                    pid_str = line.rpartition(':')[2]
                    if pid_str.isdigit():
                        pid = int(pid_str)
                        try:
                            os.kill(pid, 0)
                        except OSError:
                            # go to main thread (session_signaled.py)
                            return True
                        else:
                            # pid is okay, let check the osc port next
                            continue
                    else:
                        return True

                if line.startswith('port:'):
                    port_str = line.rpartition(':')[2]
                    good_port = False

                    try:
                        patchbay_addr = Address(f'osc.tcp://localhost:{port_str}/')
                        good_port = True
                    except:
                        patchbay_addr = None
                        _logger.error(
                            f'port given for patchbay {port_str} '
                            'is not a valid osc TCP port')

                    if good_port:
                        send(patchbay_addr, r.patchbay.ADD_GUI,
                             gui_tcp_url)
                        return False
                    break

        # continue in main thread if patchbay_to_osc is not started yet
        # see session_signaled.py -> _ray_server_ask_for_patchbay

    @directos(r.server.CONTROLLER_ANNOUNCE, 'i')
    def _srv_controller_announce(self, osp: OscPack):
        controller = Controller()
        controller.addr = osp.src_addr
        controller.pid = osp.args[0]
        self.controller_list.append(controller)
        self.send(*osp.reply(), 'announced')

    @directos(r.server.CONTROLLER_DISANNOUNCE, '')
    def _srv_controller_disannonce(self, osp: OscPack):
        for controller in self.controller_list:
            if controller.addr.port == osp.src_addr.port:
                break
        else:
            return

        self.controller_list.remove(controller)
        self.send(*osp.reply(), 'disannounced')

    @directos(r.server.MONITOR_ANNOUNCE, '')
    def _srv_monitor_announce(self, osp: OscPack):
        monitor_addr = osp.src_addr
        self.monitor_list.append(monitor_addr)
        self.session.send_initial_monitor(
            osp.src_addr, monitor_is_client=False)
        self.send(*osp.reply(), 'announced')
    
    @directos(r.server.MONITOR_QUIT, '')
    def _srv_monitor_quit(self, osp: OscPack):
        for monitor_addr in self.monitor_list:
            if monitor_addr.url == osp.src_addr.url:
                break
        else:
            return
        
        self.monitor_list.remove(monitor_addr)
        self.send(*osp.reply(), 'monitor exit')

    @directos(r.server.SET_NSM_LOCKED, '')
    def _srv_set_nsm_locked(self, osp: OscPack):
        self.is_nsm_locked = True
        self._nsm_locker_url = osp.src_addr.url

        for gui in self.gui_list:
            if gui.addr.url != osp.src_addr.url:
                self.send(gui.addr, rg.server.NSM_LOCKED, 1)

    @validator(r.server.CHANGE_ROOT, 's')
    def _srv_change_root(self, osp: OscPack):
        new_root: str = osp.args[0]
        if not(new_root.startswith('/') and _path_is_valid(new_root)):
            self.send(*osp.error(), ray.Err.CREATE_FAILED,
                      "invalid session root !")
            return False

        if self._is_operation_pending(osp):
            self.send(*osp.error(), ray.Err.OPERATION_PENDING,
                      "Can't change session_root. Operation pending")
            return False

    @directos(r.server.SET_TERMINAL_COMMAND, 's')
    def _srv_set_terminal_command(self, osp: OscPack):
        if osp.args[0] != self.terminal_command:
            self.terminal_command = osp.args[0]
            if not self.terminal_command:
                self.terminal_command = shlex.join(
                    which_terminal(title='RAY_TERMINAL_TITLE'))
            self.send_gui(rg.server.TERMINAL_COMMAND,
                          self.terminal_command)
        self.send(*osp.reply(), 'terminal command set')

    @directos(r.server.LIST_PATH, '')
    def _srv_list_path(self, osp: OscPack):
        exec_set = set[str]()
        tmp_exec_list = list[str]()
        n = 0

        pathlist = os.getenv('PATH').split(':')
        for pathdir in pathlist:
            if os.path.isdir(pathdir):
                listexe = os.listdir(pathdir)
                for exe in listexe:
                    fullexe = pathdir + '/' + exe

                    if (exe not in exec_set
                            and os.path.isfile(fullexe)
                            and os.access(fullexe, os.X_OK)):
                        exec_set.add(exe)
                        tmp_exec_list.append(exe)
                        n += len(exe)

                        if n >= 20000:
                            self.send(*osp.reply(), *tmp_exec_list)
                            tmp_exec_list.clear()
                            n = 0

        if tmp_exec_list:
            self.send(*osp.reply(), *tmp_exec_list)

    @directos(r.server.LIST_SESSION_TEMPLATES, '')
    def _srv_list_session_templates(self, osp: OscPack):
        if not TemplateRoots.user_sessions.is_dir():
            self.send(*osp.reply())
            return False

        template_list = list[str]()

        for file in TemplateRoots.user_sessions.iterdir():
            if file.is_dir():
                template_list.append(file.name)
                
                if len(template_list) == 100:
                    self.send(*osp.reply(), *template_list)
                    template_list.clear()

        if template_list:
            self.send(*osp.reply(), *template_list)

        self.send(*osp.reply())

    @directos(r.server.REMOVE_CLIENT_TEMPLATE, 's')
    def _srv_remove_client_template(self, osp: OscPack):
        template_name: str = osp.args[0]
        templates_root = TemplateRoots.user_clients
        templates_file = templates_root / 'client_templates.xml'

        if not templates_file.is_file():
            self.send(*osp.error(), ray.Err.NO_SUCH_FILE,
                      "file %s is missing !" % templates_file)
            return False

        if not os.access(templates_file, os.W_OK):
            self.send(*osp.error(), ray.Err.NO_SUCH_FILE,
                      "file %s in unwriteable !" % templates_file)
            return False

        tree = ET.parse(templates_file)
        root = tree.getroot()

        if root.tag != 'RAY-CLIENT-TEMPLATES':
            self.send(*osp.error(), ray.Err.BAD_PROJECT,
                      "file %s is not write correctly !" % templates_file)
            return False

        xroot = XmlElement(root)

        for c in xroot.iter():
            if c.el.tag != 'Client-Template':
                continue
            
            if c.str('template-name') == template_name:
                break
        else:
            self.send(*osp.error(), ray.Err.NO_SUCH_FILE,
                      "No template \"%s\" to remove !" % template_name)
            return False
        
        root.remove(c.el)
        
        try:
            tree.write(templates_file)
        except BaseException as e:
            _logger.error(str(e))
            self.send(*osp.error(), ray.Err.CREATE_FAILED,
                      "Impossible to rewrite user client templates xml file")
            return False
        
        templates_dir = templates_root / template_name
        if templates_dir.is_dir():
            try:
                shutil.rmtree(templates_dir)
            except BaseException as e:
                _logger.error(str(e))
                self.send(*osp.error(), ray.Err.CREATE_FAILED,
                      "Failed to remove the folder %s" % str(templates_dir))
                return False

        self.send(*osp.reply(),
                  f'template "{template_name}" removed.')

    @validator(r.server.LIST_SESSIONS, '|i')
    def _srv_list_sessions(self, osp: OscPack):
        self._list_asker_addr = osp.src_addr

    @validator(r.server.NEW_SESSION, 's|ss')
    def _srv_new_session(self, osp: OscPack):
        if self.is_nsm_locked:
            return False

        if not _path_is_valid(osp.args[0]):
            self.send(*osp.error(), ray.Err.CREATE_FAILED,
                      "Invalid session name.")
            return False

    @validator(r.server.SAVE_SESSION_TEMPLATE, 'ss|sss')
    def _srv_save_session_template(self, osp: OscPack):
        session_name: str = osp.args[0]
        template_name: str = osp.args[1]

        #save as template an not loaded session
        if not _path_is_valid(session_name):
            self.send(*osp.error(), ray.Err.CREATE_FAILED,
                    "Invalid session name.")
            return False

        if '/' in template_name:
            self.send(*osp.error(), ray.Err.CREATE_FAILED,
                      "Invalid template name.")
            return False

    @validator(r.server.GET_SESSION_PREVIEW, 's')
    def _srv_get_session_preview(self, osp: OscPack):
        sess_prev: str = osp.args[0]
        self.session_to_preview = sess_prev
    
    @directos(r.server.SCRIPT_INFO, 's')
    def _srv_script_info(self, osp: OscPack):
        info: str = osp.args[0]
        self.send_gui(rg.SCRIPT_INFO, info)
        self.send(*osp.reply(), "Info sent")

    @directos(r.server.HIDE_SCRIPT_INFO, '')
    def _srv_hide_script_info(self, osp: OscPack):
        self.send_gui(rg.HIDE_SCRIPT_INFO)
        self.send(*osp.reply(), "Info hidden")

    @directos(r.server.SCRIPT_USER_ACTION, 's')
    def _srv_script_user_action(self, osp: OscPack):
        if not self.gui_list:
            self.send(*osp.error(), ray.Err.LAUNCH_FAILED,
                      "This server has no attached GUI")
            return
        user_act: str = osp.args[0]
        self.send_gui(rg.SCRIPT_USER_ACTION, user_act)

    @validator(r.server.SET_OPTION, 'i')
    def _srv_set_option(self, osp: OscPack):
        'set option from GUI'
        option_int: int = osp.args[0]
        try:
            option = ray.Option(abs(option_int))
        except:
            self.send(*osp.error(), ray.Err.BAD_PROJECT,
                      f"Option num {abs(option_int)} does not exists")
            return False

        if option_int >= 0:
            self.options |= option
        else:
            self.options &= ~option        

        for gui in self.gui_list:
            if not are_same_osc_port(gui.addr.url, osp.src_addr.url):
                self.send(gui.addr, rg.server.OPTIONS,
                          self.options.value)

    @directos(r.server.SET_OPTIONS, 'ss*')
    def _srv_set_options(self, osp: OscPack):
        'set options from ray_control'
        args: list[str] = osp.args

        for option_str in args:
            option_value = True
            if option_str.startswith('not_'):
                option_value = False
                option_str = option_str.replace('not_', '', 1)

            if option_str in self._OPTIONS_DICT:
                option = self._OPTIONS_DICT[option_str]
                if option_value:
                    if (option is ray.Option.DESKTOPS_MEMORY
                            and ray.Option.HAS_WMCTRL not in self.options):
                        self.send(osp.src_addr, osc_paths.MINOR_ERROR, osp.path,
                            "wmctrl is not present. "
                            "Impossible to activate 'desktops_memory' option")
                        continue

                    if (option is ray.Option.SNAPSHOTS
                            and ray.Option.HAS_GIT not in self.options):
                        self.send(osp.src_addr, osc_paths.MINOR_ERROR, osp.path,
                            "git is not present. "
                            "Impossible to activate 'snapshots' option")
                        continue

                if option_value:
                    self.options |= option
                else:
                    self.options &= ~option

        for gui in self.gui_list:
            if not are_same_osc_port(gui.addr.url, osp.src_addr.url):
                self.send(gui.addr, rg.server.OPTIONS,
                          self.options.value)

        self.send(*osp.reply(), 'Options set')

    @directos(r.server.HAS_OPTION, 's')
    def _srv_has_option(self, osp: OscPack):
        option_str = osp.args[0]

        if option_str not in self._OPTIONS_DICT:
            self.send(*osp.error(), ray.Err.GENERAL_ERROR,
                      "option \"%s\" doesn't exists" % option_str)
            return

        if self.options & self._OPTIONS_DICT[option_str]:
            self.send(*osp.reply(), 'Has option')
        else:
            self.send(*osp.error(), ray.Err.GENERAL_ERROR,
                      "Option %s is not currently used" % option_str)

    @directos(r.server.CLEAR_CLIENT_TEMPLATES_DATABASE, '')
    def _srv_clear_client_templates_database(self, osp: OscPack):
        self.client_templates_database['factory'].clear()
        self.client_templates_database['user'].clear()
        self.send(*osp.reply(), 'database cleared')

    @directos(r.server.OPEN_FILE_MANAGER_AT, 's')
    def _srv_open_file_manager_at(self, osp: OscPack):
        folder_path: str = osp.args[0]
        if os.path.isdir(folder_path):
            subprocess.Popen(['xdg-open', folder_path])
        self.send(*osp.reply(), '')

    @directos(r.server.EXOTIC_ACTION, 's')
    def _srv_exotic_action(self, osp: OscPack):
        action: str = osp.args[0]
        autostart_dir = Path.home() / '.config' / 'autostart'
        desk_file = "ray-jack_checker.desktop"
        dest_full_path = autostart_dir / desk_file

        if action == 'set_jack_checker_autostart':
            if not autostart_dir.exists():
                autostart_dir.mkdir(parents=True)

            src_full_file = (
                get_code_root()
                / 'data' / 'share' / 'applications' / desk_file)
            
            shutil.copyfile(src_full_file, dest_full_path)

        elif action == 'unset_jack_checker_autostart':
            dest_full_path.unlink(missing_ok=True)

    @validator(r.server.patchbay.SAVE_GROUP_POSITION,
               'i' + GroupPos.args_types())
    def _srv_patchbay_save_group_position(self, osp: OscPack):
        # here send to others GUI the new group position
        for gui in self.gui_list:
            if not are_same_osc_port(gui.addr.url, osp.src_addr.url):
                self.send(
                    gui.addr,
                    rg.patchbay.UPDATE_GROUP_POSITION,
                    *osp.args)

    @validator(r.session.SAVE, '', no_sess='No session to save.')
    def _sess_save(self, osp: OscPack):
        ...

    @validator(r.session.SAVE_AS_TEMPLATE, 's')
    def _sess_save_as_template(self, osp: OscPack):
        template_name: str = osp.args[0]
        if '/' in template_name or template_name == '.':
            self.send(*osp.error(), ray.Err.CREATE_FAILED,
                      "Invalid session template name.")
            return False

    @directos(r.session.GET_SESSION_NAME, '', no_sess='No session loaded.')
    def _sess_get_session_name(self, osp: OscPack):
        self.send(*osp.reply(), self.session.name)
        self.send(*osp.reply())

    @validator(r.session.TAKE_SNAPSHOT, 's|si')
    def _sess_take_snapshot(self, osp: OscPack):
        if ray.Option.HAS_GIT not in self.options:
            self.send(*osp.error(),
                      "snapshot impossible because git is not installed")
            return False

    @validator(r.session.CLOSE, '', no_sess='No session to close.')
    def _sess_close(self, osp: OscPack):
        ...

    @validator(r.session.CANCEL_CLOSE, '',
               no_sess='No session to cancel close.')
    def _sess_cancel_close(self, osp: OscPack):
        ...

    @validator(r.session.SKIP_WAIT_USER, '')
    def _sess_skip_wait_user(self, osp: OscPack):
        if self.server_status is not ray.ServerStatus.WAIT_USER:
            return False

    @validator(r.session.DUPLICATE, 's', no_sess='No session to duplicate.')
    def _sess_duplicate(self, osp: OscPack):
        if self.is_nsm_locked:
            return False

        new_name: str = osp.args[0]

        if not _path_is_valid(new_name):
            self.send(*osp.error(), ray.Err.CREATE_FAILED,
                      "Invalid session name.")
            return False

    @validator(r.session.DUPLICATE_ONLY, 'sss')
    def _sess_duplicate_only(self, osp: OscPack):
        self.send(osp.src_addr, r.net_daemon.DUPLICATE_STATE, 0)

    @validator(r.session.RENAME, 's', no_sess="No session to rename.")
    def _sess_rename(self, osp: OscPack):
        new_session_name: str = osp.args[0]

        #prevent rename session in network session
        if self._nsm_locker_url:
            NSM_URL = os.getenv('NSM_URL')
            if not NSM_URL:
                return False

            if not are_same_osc_port(self._nsm_locker_url, NSM_URL):
                return False

        if '/' in new_session_name:
            self.send(*osp.error(), ray.Err.CREATE_FAILED,
                      "Invalid session name.")
            return False

        if self._is_operation_pending(osp):
            return False

    @validator(r.session.SET_NOTES, 's')
    def _sess_set_notes(self, osp: OscPack):
        self.session.notes = osp.args[0]

        for gui in self.gui_list:
            if not are_same_osc_port(gui.addr.url, osp.src_addr.url):
                self.send(gui.addr, rg.session.NOTES,
                          self.session.notes)

    def _add_exec(self, osp: OscPack) -> Optional[bool]:
        # used because the same check exists for 2 differents paths.
        match osp.args:
            case 'siiissi':
                args: tuple[str, int, int, int, str, str, int] = osp.args
                executable_path, auto_start, protocol, \
                    prefix_mode, prefix_pattern, client_id, jack_naming = args
                    
                try:
                    protocol = ray.Protocol(protocol)
                except:
                    self.send(*osp.error(), ray.Err.CREATE_FAILED,
                            f"Invalid protocol number: {protocol}")
                    return False

            case _:
                args: tuple[str, ...] = osp.args
                executable_path = args[0]
                ray_hack = bool(len(args) > 1 and 'ray_hack' in args[1:])
                if ray_hack: protocol = ray.Protocol.RAY_HACK
                else: protocol = ray.Protocol.NSM

        if protocol is ray.Protocol.NSM and '/' in executable_path:
            self.send(*osp.error(), ray.Err.LAUNCH_FAILED,
                "Absolute paths are not permitted. Clients must be in $PATH")
            return False

    @validator(r.session.ADD_EXECUTABLE, 'siiissi|ss*',
               no_sess='Cannot add to session because no session is loaded.')
    def _sess_add_executable(self, osp: OscPack):
        # old method, kept because it can be still used in old scripts.
        # Only default values differs, see session_signaled module.'''
        return self._add_exec(osp)
    
    @validator(r.session.ADD_EXEC, 'siiissi|ss*',
               no_sess='Cannot add to session because no session is loaded.')
    def _sess_add_exec(self, osp: OscPack):
        return self._add_exec(osp)

    @directos(r.session.OPEN_FOLDER, '')
    def _sess_open_folder(self, osp: OscPack):
        if self.session.path:
            subprocess.Popen(['xdg-open', self.session.path])
        self.send(*osp.reply(), '')

    @directos(r.session.SHOW_NOTES, '', no_sess='No session to show notes')
    def _sess_show_notes(self, osp: OscPack):
        self.session.notes_shown = True
        self.send_gui(rg.session.NOTES_SHOWN)
        self.send(*osp.reply(), 'notes shown')

    @directos(r.session.HIDE_NOTES, '', no_sess='No session to hide notes')
    def _sess_hide_notes(self, osp: OscPack):
        self.session.notes_shown = False
        self.send_gui(rg.session.NOTES_HIDDEN)
        self.send(*osp.reply(), 'notes hidden')

    @validator(r.client.CHANGE_PREFIX, 'si|ss|sis|sss')
    def _ray_client_change_prefix(self, osp: OscPack):
        if osp.args[1] in (ray.PrefixMode.CUSTOM.value, 'custom'):
            if len(osp.args) < 3:
                self._unknown_message(osp)
                return False

    @directos(r.favorites.ADD, 'ssis')
    def _ray_favorites_add(self, osp: OscPack):
        args: tuple[str, str, int, str] = osp.args
        name, icon, int_factory, display_name = args

        for favorite in RS.favorites:
            if (favorite.name == name
                    and bool(int_factory) is favorite.factory):
                favorite.icon = icon
                favorite.display_name = display_name
                break
        else:
            RS.favorites.append(
                ray.Favorite(name, icon, bool(int_factory), display_name))

        self.send_gui(rg.favorites.ADDED, *osp.args)

    @directos(r.favorites.REMOVE, 'si')
    def _ray_favorites_remove(self, osp: OscPack):
        args: tuple[str, int] = osp.args
        name, int_factory = args

        for favorite in RS.favorites:
            if (favorite.name == name
                    and bool(int_factory) is favorite.factory):
                RS.favorites.remove(favorite)
                break

        self.send_gui(rg.favorites.REMOVED, *osp.args)

    @validator(r.server.ASK_FOR_PRETTY_NAMES, 'i')
    def _srv_ask_for_pretty_names(self, osp: OscPack):
        args: tuple[int] = osp.args
        self.patchbay_dmn_port = args[0]

    # cannot be decorated, else it is defined in priority to all methods
    # defined after
    def noneMethod(
            self, path: str, args: list, types: str, src_addr: Address):
        osp = OscPack(path, args, types, src_addr)
        self._unknown_message(osp)

    def _is_operation_pending(self, osp: OscPack) -> bool:
        if self.session.file_copier.is_active():
            self.send(*osp.error(), ray.Err.COPY_RUNNING,
                      "ray-daemon is copying files. "
                      "Wait copy finish or abort copy, "
                      "and restart operation !")
            return True

        if self.session.steps_order:
            self.send(*osp.error(), ray.Err.OPERATION_PENDING,
                      "An operation pending.")
            return True

        return False

    def send(self, *args):
        _logger.debug('\033[96mOSC::daemon sends\033[0m ' + str(args[1:]))        
        ClientCommunicating.send(self, *args)

    def send_gui(self, *args):
        for gui in self.gui_list:
            self.send(gui.addr, *args)

    def send_patchbay_dmn(self, *args):
        self.send(self.patchbay_dmn_port, *args)

    def mega_send_gui(self, mega_send: MegaSend):
        self.mega_send([gui.addr for gui in self.gui_list], mega_send)
        
    def mega_send_patchbay(self, mega_send: MegaSend):
        if self.patchbay_dmn_port is not None:
            self.mega_send(self.patchbay_dmn_port, mega_send)

    def set_server_status(self, server_status:ray.ServerStatus):
        self.server_status = server_status
        self.send_gui(rg.server.STATUS, server_status.value)

    def send_renameable(self, renameable:bool):
        if not renameable:
            self.send_gui(rg.session.RENAMEABLE, 0)
            return

        if self._nsm_locker_url:
            nsm_url = os.getenv('NSM_URL')
            if not nsm_url:
                return
            if not are_same_osc_port(self._nsm_locker_url, nsm_url):
                return

        self.send_gui(rg.session.RENAMEABLE, 1)

    def announce_gui(
            self, url: str, nsm_locked=False,
            is_net_free=True, gui_pid=0, tcp_addr: Optional[Address]=None):
        gui = Gui(url)
        gui.pid = gui_pid
        gui.tcp_addr = tcp_addr

        tcp_url = get_net_url(self.tcp_port, protocol=TCP)

        self.send(gui.addr, rg.server.ANNOUNCE, ray.VERSION,
                  self.server_status.value, self.options.value,
                  str(self.session.root), int(is_net_free), tcp_url)

        self.send(gui.addr, rg.server.STATUS,
                  self.server_status.value)

        if self.session.path is None:
            self.send(gui.addr, rg.session.NAME, '', '')
        else:
            self.send(gui.addr, rg.session.NAME,
                      self.session.name, str(self.session.path))

        self.send(gui.addr, rg.session.NOTES, self.session.notes)
        self.send(gui.addr, rg.server.TERMINAL_COMMAND,
                  self.terminal_command)

        self.session.canvas_saver.send_all_group_positions(gui)

        for favorite in RS.favorites:
            self.send(gui.addr, rg.favorites.ADDED,
                      favorite.name, favorite.icon, int(favorite.factory),
                      favorite.display_name)

        for client in self.session.clients:
            self.send(gui.addr,
                      rg.client.NEW,
                      *client.spread())

            if client.is_ray_hack:
                self.send(gui.addr,
                          rg.client.RAY_HACK_UPDATE,
                          client.client_id,
                          *client.ray_hack.spread())
            elif client.is_ray_net:
                self.send(gui.addr,
                          rg.client.RAY_NET_UPDATE,
                          client.client_id,
                          *client.ray_net.spread())

            self.send(gui.addr, rg.client.STATUS,
                      client.client_id, client.status.value)

            if client.is_capable_of(':optional-gui:'):
                self.send(gui.addr, rg.client.GUI_VISIBLE,
                          client.client_id, int(client.gui_visible))

            if client.is_capable_of(':dirty:'):
                self.send(gui.addr, rg.client.DIRTY,
                          client.client_id, client.dirty)

        for trashed_client in self.session.trashed_clients:
            self.send(gui.addr, rg.trash.ADD,
                      *trashed_client.spread())

            if trashed_client.is_ray_hack:
                self.send(gui.addr, rg.trash.RAY_HACK_UPDATE,
                          trashed_client.client_id,
                          *trashed_client.ray_hack.spread())
            elif trashed_client.is_ray_net:
                self.send(gui.addr, rg.trash.RAY_NET_UPDATE,
                          trashed_client.client_id,
                          *trashed_client.ray_net.spread())

        self.session.check_recent_sessions_existing()
        if self.session.root in self.session.recent_sessions.keys():
            self.send(gui.addr, rg.server.RECENT_SESSIONS,
                      *self.session.recent_sessions[self.session.root])

        self.send(gui.addr, rg.server.MESSAGE,
                  _translate('daemon', "daemon runs at %s") % self.url)

        self.gui_list.append(gui)

        multi_daemon_file.update()

        Terminal.message(f"GUI connected at {gui.addr.url}")

    def announce_controller(self, control_address: Address):
        controller = Controller()
        controller.addr = control_address
        self.controller_list.append(controller)
        self.send(control_address, r.control.server.ANNOUNCE,
                  ray.VERSION, self.server_status.value, self.options.value,
                  str(self.session.root), 1)

    def send_controller_message(self, message: str):
        for controller in self.controller_list:
            self.send(controller.addr, r.control.MESSAGE, message)

    def has_gui(self) -> int:
        has_gui = False

        for gui in self.gui_list:
            if are_on_same_machine(self.url, gui.addr.url):
                # we've got a local GUI
                return 3

            has_gui = True

        if has_gui:
            return 1

        return 0

    def get_local_gui_pid_list(self) -> str:
        pid_list = list[str]()
        for gui in self.gui_list:
            if are_on_same_machine(gui.addr.url, self.url):
                pid_list.append(str(gui.pid))
        return ':'.join(pid_list)

    def is_gui_address(self, addr: Address) -> bool:
        for gui in self.gui_list:
            if are_same_osc_port(gui.addr.url, addr.url):
                return True
        return False
