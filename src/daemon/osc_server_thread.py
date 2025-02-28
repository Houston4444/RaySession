
# Imports from standard library
import logging
import os
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
    Address, BunServerThread, MegaSend, get_net_url, make_method, Message, OscPack,
    are_on_same_machine, are_same_osc_port, send, TCP, verified_address)
import ray
from xml_tools import XmlElement
import osc_paths as p
import osc_paths.nsm as NSM
import osc_paths.ray as R
import osc_paths.ray.gui as RG
import osc_paths.ray.gui.patchbay as RGP
import osc_paths.ray.patchbay as RP

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


def _path_is_valid(path: str) -> bool:
    if path.startswith(('./', '../')):
        return False

    for forbidden in ('//', '/./', '/../'):
        if forbidden in path:
            return False

    if path.endswith(('/.', '/..')):
        return False
    return True

def osp_method(path: str, types: str):
    def decorated(func: Callable):
        @make_method(path, types)
        def wrapper(*args, **kwargs):
            t_thread, t_path, t_args, t_types, src_addr, rest = args
            _logger.debug(
                '\033[94mOSC::daemon_receives\033[0m '
                f'{t_path}, {t_types}, {t_args}, %{src_addr.url}'
            )

            osp = OscPack(t_path, t_args, t_types, src_addr)
            response = func(t_thread, osp, **kwargs)

            if response != False:
                signaler.osc_recv.emit(osp)

            return response
        return wrapper
    return decorated


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

    @osp_method(p.osc.PING, '')
    def oscPing(self, osp: OscPack):
        self.send(*osp.reply())

    @osp_method(p.REPLY, None)
    def reply(self, osp: OscPack):
        if not osp.strings_only:
            self._unknown_message(osp)

        if not len(osp.args) >= 1:
            self._unknown_message(osp)
            return False

        reply_path = osp.args[0]

        if reply_path == R.server.LIST_SESSIONS:
            # this reply is only used here for reply from net_daemon
            # it directly resend its infos
            # to the last addr that asked session list
            if self._list_asker_addr:
                self.send(self._list_asker_addr, osp.path, *osp.args)
            return False

        if reply_path == RG.SCRIPT_USER_ACTION:
            self.send_gui(RG.HIDE_SCRIPT_USER_ACTION)
            for controller in self.controller_list:
                self.send(controller.addr, p.REPLY,
                          R.server.SCRIPT_USER_ACTION,
                          'User action dialog validate')
            return False

        if not len(osp.args) == 2:
            # assume this is a normal client, not a net_daemon
            self._unknown_message(osp)
            return False

    @osp_method(p.ERROR, 'sis')
    def error(self, osp: OscPack):
        error_path, error_code, error_string = osp.args

        if error_path == RG.SCRIPT_USER_ACTION:
            self.send_gui(RG.HIDE_SCRIPT_USER_ACTION)

            for controller in self.controller_list:
                self.send(controller.addr, p.ERROR,
                          R.server.SCRIPT_USER_ACTION, -1,
                          'User action dialog aborted !')
            return False

    @osp_method(p.MINOR_ERROR, 'sis')
    def minor_error(self, osp: OscPack):
        # prevent minor_error to minor_error loop in daemon <-> daemon communication
        pass

    # SERVER_CONTROL messages
    # following messages only for :server-control: capability
    @osp_method(NSM.server.ADD, 's')
    def nsmServerAdd(self, osp: OscPack):
        executable_path = osp.args[0]

        if self.session.path is None:
            self.send(*osp.error(), ray.Err.NO_SESSION_OPEN,
                      "Cannot add to session because no session is loaded.")
            return False

        if '/' in executable_path:
            self.send(*osp.error(), ray.Err.LAUNCH_FAILED,
                "Absolute paths are not permitted. Clients must be in $PATH")
            return False

    @osp_method(NSM.server.SAVE, '')
    def nsmServerSave(self, osp: OscPack):
        if self.session.path is None:
            self.send(*osp.error(), ray.Err.NO_SESSION_OPEN,
                      "No session to save.")
            return False

    @osp_method(NSM.server.OPEN, 's')
    def nsmServerOpen(self, osp: OscPack):
        pass

    @osp_method(NSM.server.NEW, 's')
    def nsmServerNew(self, osp: OscPack):
        if self.is_nsm_locked:
            return False

        if not _path_is_valid(osp.args[0]):
            self.send(*osp.error(), ray.Err.CREATE_FAILED,
                      "Invalid session name.")
            return False

    @osp_method(NSM.server.DUPLICATE, 's')
    def nsmServerDuplicate(self, osp: OscPack):
        if self.is_nsm_locked or self.session.path is None:
            self.send(*osp.error(), ray.Err.NO_SESSION_OPEN,
                      "No session to duplicate.")
            return False

        if not _path_is_valid(osp.args[0]):
            self.send(*osp.error(), ray.Err.CREATE_FAILED,
                      "Invalid session name.")
            return False

    @osp_method(NSM.server.CLOSE, '')
    def nsmServerClose(self, osp: OscPack):
        if self.session.path is None:
            self.send(*osp.error(), ray.Err.NO_SESSION_OPEN,
                      "No session to close.")
            return False

    @osp_method(NSM.server.ABORT, '')
    def nsmServerAbort(self, osp: OscPack):
        if self.session.path is None:
            self.send(*osp.error(), ray.Err.NO_SESSION_OPEN,
                      "No session to abort.")
            return False

    @osp_method(NSM.server.QUIT, '')
    def nsmServerQuit(self, osp: OscPack):
        pass

    @osp_method(NSM.server.LIST, '')
    def nsmServerList(self, osp: OscPack):
        pass

    # END OF SERVER_CONTROL messages

    @osp_method(NSM.server.ANNOUNCE, 'sssiii')
    def nsmServerAnnounce(self, osp: OscPack):
        if self.session.path is None:
            self.send(*osp.error(), ray.Err.NO_SESSION_OPEN,
                      "Sorry, but there's no session open "
                      "for this application to join.")
            return False

    @osp_method(NSM.server.BROADCAST, None)
    def nsmServerBroadcast(self, osp: OscPack):
        if not osp.args:
            return False

        if not isinstance(osp.args[0], str):
            return False

        #don't allow clients to broadcast NSM commands
        follow_path = osp.args[0]
        if not isinstance(follow_path, str):
            return False
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

    @osp_method(NSM.server.MONITOR_RESET, '')
    def nsmServerGetAllStates(self, osp: OscPack):
        self.send(*osp.reply(), 'monitor reset')
        self.session.send_initial_monitor(osp.src_addr, monitor_is_client=True)

    @osp_method(NSM.client.PROGRESS, 'f')
    def nsmClientProgress(self, osp: OscPack):
        client = self.session.get_client_by_address(osp.src_addr)
        if not client:
            return False

        client.progress = osp.args[0]
        self.send_gui(RG.client.PROGRESS, client.client_id,
                      client.progress)

    @osp_method(NSM.client.IS_DIRTY, '')
    def nsmClientIs_dirty(self, osp: OscPack):
        client = self.session.get_client_by_address(osp.src_addr)
        if not client:
            return False

        Terminal.message("%s sends dirty" % client.client_id)

        client.dirty = 1
        client.last_dirty = time.time()

        self.send_gui(RG.client.DIRTY, client.client_id, client.dirty)

    @osp_method(NSM.client.IS_CLEAN, '')
    def nsmClientIs_clean(self, osp: OscPack):
        client = self.session.get_client_by_address(osp.src_addr)
        if not client:
            return False

        Terminal.message("%s sends clean" % client.client_id)

        client.dirty = 0

        self.send_gui(RG.client.DIRTY, client.client_id, client.dirty)
        return False

    @osp_method(NSM.client.MESSAGE, 'is')
    def nsmClientMessage(self, osp: OscPack):
        client = self.session.get_client_by_address(osp.src_addr)
        if not client:
            return False

        self.send_gui(RG.client.MESSAGE,
                      client.client_id, osp.args[0], osp.args[1])

    @osp_method(NSM.client.GUI_IS_HIDDEN, '')
    def nsmClientGui_is_hidden(self, osp: OscPack):
        client = self.session.get_client_by_address(osp.src_addr)
        if not client:
            return False

        Terminal.message("Client '%s' sends gui hidden" % client.client_id)

        client.gui_visible = False

        self.send_gui(RG.client.GUI_VISIBLE, client.client_id,
                     int(client.gui_visible))

    @osp_method(NSM.client.GUI_IS_SHOWN, '')
    def nsmClientGui_is_shown(self, osp: OscPack):
        client = self.session.get_client_by_address(osp.src_addr)
        if not client:
            return False

        Terminal.message("Client '%s' sends gui shown" % client.client_id)

        client.gui_visible = True
        client.gui_has_been_visible = True

        self.send_gui(RG.client.GUI_VISIBLE, client.client_id,
                     int(client.gui_visible))

    @osp_method(NSM.client.LABEL, 's')
    def nsmClientLabel(self, osp: OscPack):
        pass

    @osp_method(NSM.client.NETWORK_PROPERTIES, 'ss')
    def nsmClientNetworkProperties(self, osp: OscPack):
        pass

    def _unknown_message(self, osp: OscPack):
        self.send(osp.src_addr, p.MINOR_ERROR, osp.path,
                  ray.Err.UNKNOWN_MESSAGE,
                  "unknown osc message: %s %s" % (osp.path, osp.types))

    def send_gui(self, *args):
        # should be overclassed
        pass


class OscServerThread(ClientCommunicating):
    _SIMPLE_OSC_PATHS: tuple[tuple[str, str]]
    'OSC paths directly running in session_signaled.py'
    
    _STRINGS_OSC_PATHS: dict[str, int]
    '''OSC paths needing an undeterminated number of strings as argument.
    key: OSC path
    value: minimum number of arguments'''
    
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

        self._SIMPLE_OSC_PATHS = {
            (R.server.QUIT, ''),
            (R.server.ABORT_COPY, ''),
            (R.server.ABORT_PARRALLEL_COPY, 'i'),
            (R.server.ABORT_SNAPSHOT, ''),
            (R.server.OPEN_SESSION, 's'),
            (R.server.OPEN_SESSION, 'si'),
            (R.server.OPEN_SESSION, 'sis'),
            (R.server.OPEN_SESSION_OFF, 's'),
            (R.server.OPEN_SESSION_OFF, 'si'),
            (R.server.RENAME_SESSION, 'ss'),
            (R.server.patchbay.VIEWS_CHANGED, 's'),
            (R.server.patchbay.CLEAR_ABSENTS_IN_VIEW, 's'),
            (R.server.patchbay.VIEW_NUMBER_CHANGED, 'ii'),
            (R.server.patchbay.VIEW_PTV_CHANGED, 'ii'),
            (R.server.patchbay.SAVE_GROUP_PRETTY_NAME, 'sssi'),
            (R.server.patchbay.SAVE_PORT_PRETTY_NAME, 'sssi'),
            (R.session.ABORT, ''),
            (R.session.OPEN_SNAPSHOT, 's'),
            (R.session.GET_NOTES, ''),
            (R.session.ADD_CLIENT_TEMPLATE, 'isss'),
            (R.session.ADD_OTHER_SESSION_CLIENT, 'ss'),
            (R.session.LIST_SNAPSHOTS, ''),
            (R.session.SET_AUTO_SNAPSHOT, 'i'),
            (R.session.LIST_TRASHED_CLIENTS, ''),
            (R.client.STOP, 's'),
            (R.client.KILL, 's'),
            (R.client.TRASH, 's'),
            (R.client.START, 's'),
            (R.client.RESUME, 's'),
            (R.client.OPEN, 's'),
            (R.client.SAVE, 's'),
            (R.client.SAVE_AS_TEMPLATE, 'ss'),
            (R.client.SHOW_OPTIONAL_GUI, 's'),
            (R.client.HIDE_OPTIONAL_GUI, 's'),
            (R.client.UPDATE_PROPERTIES, ray.ClientData.sisi()),
            (R.client.UPDATE_RAY_HACK_PROPERTIES, 's' + ray.RayHack.sisi()),
            (R.client.UPDATE_RAY_NET_PROPERTIES, 's' + ray.RayNet.sisi()),
            (R.client.GET_PROPERTIES, 's'),
            (R.client.CHANGE_ADVANCED_PROPERTIES, 'ssisi'),
            (R.client.FULL_RENAME, 'ss'),
            (R.client.CHANGE_ID, 'ss'),
            (R.client.SET_DESCRIPTION, 'ss'),
            (R.client.GET_DESCRIPTION, 's'),
            (R.client.GET_PID, 's'),
            (R.client.LIST_FILES, 's'),
            (R.client.LIST_SNAPSHOTS, 's'),
            (R.client.OPEN_SNAPSHOT, 'ss'),
            (R.client.IS_STARTED, 's'),
            (R.client.SET_CUSTOM_DATA, 'sss'),
            (R.client.GET_CUSTOM_DATA, 'ss'),
            (R.client.SET_TMP_DATA, 'sss'),
            (R.client.GET_TMP_DATA, 'ss'),
            (R.client.SEND_SIGNAL, 'si'),
            (R.trashed_client.RESTORE, 's'),
            (R.trashed_client.REMOVE_DEFINITELY, 's'),
            (R.trashed_client.REMOVE_KEEP_FILES, 's'),
            (R.net_daemon.DUPLICATE_STATE, 'f')
        }
        
        self._STRINGS_OSC_PATHS = {
            R.server.LIST_USER_CLIENT_TEMPLATES: 0,
            R.server.LIST_FACTORY_CLIENT_TEMPLATES: 0,
            R.session.RUN_STEP: 0,
            R.session.ADD_FACTORY_CLIENT_TEMPLATE: 1,
            R.session.ADD_USER_CLIENT_TEMPLATE: 1,
            R.session.REORDER_CLIENTS: 1,
            R.session.CLEAR_CLIENTS: 0,
            R.session.LIST_CLIENTS: 0,
            R.client.SET_PROPERTIES: 2,
        }

        self.add_method(None, None, self.noneMethod)

        global instance
        instance = self

    @staticmethod
    def get_instance() -> 'Optional[OscServerThread]':
        return instance

    @osp_method(R.server.GUI_ANNOUNCE, 'sisiis')
    def rayGuiGui_announce(self, osp: OscPack):
        (version, int_nsm_locked, net_master_daemon_url,
         gui_pid, net_daemon_id, tcp_url) = osp.args

        nsm_locked = bool(int_nsm_locked)
        is_net_free = True

        if nsm_locked:
            self._net_master_daemon_url = net_master_daemon_url
            self.is_nsm_locked = True
            self._nsm_locker_url = osp.src_addr.url

            for gui in self.gui_list:
                if not are_same_osc_port(gui.addr.url, osp.src_addr.url):
                    self.send(gui.addr, RG.server.NSM_LOCKED, 1)

            self.net_daemon_id = net_daemon_id

            is_net_free = multi_daemon_file.is_free_for_root(
                self.net_daemon_id, self.session.root)

        tcp_addr = verified_address(tcp_url)
        if isinstance(tcp_addr, str):
            tcp_addr = None

        self.announce_gui(
            osp.src_addr.url, nsm_locked, is_net_free, gui_pid, tcp_addr)

    @osp_method(R.server.GUI_DISANNOUNCE, '')
    def rayGuiGui_disannounce(self, osp: OscPack):
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
            self.send_gui(RG.server.NSM_LOCKED, 0)

        multi_daemon_file.update()

    @osp_method(R.server.ASK_FOR_PATCHBAY, 's')
    def rayServerAskForPatchbay(self, osp: OscPack):
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
                        send(patchbay_addr, RP.ADD_GUI,
                             gui_tcp_url)
                        return False
                    break

        # continue in main thread if patchbay_to_osc is not started yet
        # see session_signaled.py -> _ray_server_ask_for_patchbay

    @osp_method(R.server.CONTROLLER_ANNOUNCE, 'i')
    def rayServerControllerAnnounce(self, osp: OscPack):
        controller = Controller()
        controller.addr = osp.src_addr
        controller.pid = osp.args[0]
        self.controller_list.append(controller)
        self.send(*osp.reply(), 'announced')

    @osp_method(R.server.CONTROLLER_DISANNOUNCE, '')
    def rayServerControllerDisannounce(self, osp: OscPack):
        for controller in self.controller_list:
            if controller.addr.url == osp.src_addr.url:
                break
        else:
            return

        self.controller_list.remove(controller)
        self.send(*osp.reply(), 'disannounced')

    @osp_method(R.server.MONITOR_ANNOUNCE, '')
    def rayServerMonitorAnnounce(self, osp: OscPack):
        monitor_addr = osp.src_addr
        self.monitor_list.append(monitor_addr)
        self.session.send_initial_monitor(osp.src_addr, monitor_is_client=False)
        self.send(*osp.reply(), 'announced')
    
    @osp_method(R.server.MONITOR_QUIT, '')
    def rayServerMonitorDisannounce(self, osp: OscPack):
        for monitor_addr in self.monitor_list:
            if monitor_addr.url == osp.src_addr.url:
                break
        else:
            return
        
        self.monitor_list.remove(monitor_addr)
        self.send(*osp.reply(), 'monitor exit')

    @osp_method(R.server.SET_NSM_LOCKED, '')
    def rayServerSetNsmLocked(self, osp: OscPack):
        self.is_nsm_locked = True
        self._nsm_locker_url = osp.src_addr.url

        for gui in self.gui_list:
            if gui.addr.url != osp.src_addr.url:
                self.send(gui.addr, RG.server.NSM_LOCKED, 1)

    @osp_method(R.server.CHANGE_ROOT, 's')
    def rayServerChangeRoot(self, osp: OscPack):
        new_root: str = osp.args[0]
        if not(new_root.startswith('/') and _path_is_valid(new_root)):
            self.send(*osp.error(), ray.Err.CREATE_FAILED,
                      "invalid session root !")
            return False

        if self._is_operation_pending(osp):
            self.send(*osp.error(), ray.Err.OPERATION_PENDING,
                      "Can't change session_root. Operation pending")
            return False

    @osp_method(R.server.SET_TERMINAL_COMMAND, 's')
    def rayServerSetTerminalCommand(self, osp: OscPack):
        if osp.args[0] != self.terminal_command:
            self.terminal_command = osp.args[0]
            if not self.terminal_command:
                self.terminal_command = shlex.join(
                    which_terminal(title='RAY_TERMINAL_TITLE'))
            self.send_gui(RG.server.TERMINAL_COMMAND,
                          self.terminal_command)
        self.send(*osp.reply(), 'terminal command set')

    @osp_method(R.server.LIST_PATH, '')
    def rayServerListPath(self, osp: OscPack):
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
                            print('un reply path', tmp_exec_list)
                            self.send(osp.src_addr, p.REPLY,
                                      osp.path, *tmp_exec_list)
                            tmp_exec_list.clear()
                            n = 0

        if tmp_exec_list:
            self.send(*osp.reply(), *tmp_exec_list)

    @osp_method(R.server.LIST_SESSION_TEMPLATES, '')
    def rayServerListSessionTemplates(self, osp: OscPack):
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

    @osp_method(R.server.REMOVE_CLIENT_TEMPLATE, 's')
    def rayServerRemoveClientTemplate(self, osp: OscPack):
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

    @osp_method(R.server.LIST_SESSIONS, '')
    def rayServerListSessions(self, osp: OscPack):
        self._list_asker_addr = osp.src_addr

    @osp_method(R.server.LIST_SESSIONS, 'i')
    def rayServerListSessionsWithNet(self, osp: OscPack):
        self._list_asker_addr = osp.src_addr

    @osp_method(R.server.NEW_SESSION, None)
    def rayServerNewSession(self, osp: OscPack):
        if not osp.strings_only:
            self._unknown_message(osp)
            return False

        if self.is_nsm_locked:
            return False

        if not _path_is_valid(osp.args[0]):
            self.send(*osp.error(), ray.Err.CREATE_FAILED,
                      "Invalid session name.")
            return False

    @osp_method(R.server.SAVE_SESSION_TEMPLATE, 'ss')
    def rayServerSaveSessionTemplate(self, osp: OscPack):
        #save as template an not loaded session
        session_name, template_name = osp.args

        if not _path_is_valid(session_name):
            self.send(*osp.error(), ray.Err.CREATE_FAILED,
                    "Invalid session name.")
            return False

        if '/' in template_name:
            self.send(*osp.error(), ray.Err.CREATE_FAILED,
                      "Invalid template name.")
            return False

    @osp_method(R.server.SAVE_SESSION_TEMPLATE, 'sss')
    def rayServerSaveSessionTemplateWithRoot(self, osp: OscPack):
        #save as template an not loaded session
        session_name, template_name, sess_root = osp.args
        if not _path_is_valid(session_name):
            self.send(*osp.error(), ray.Err.CREATE_FAILED,
                    "Invalid template name.")
            return False

        if '/' in template_name:
            self.send(*osp.error(), ray.Err.CREATE_FAILED,
                      "Invalid session name.")
            return False

    @osp_method(R.server.GET_SESSION_PREVIEW, 's')
    def rayServerGetSessionPreview(self, osp: OscPack):
        sess_prev: str
        sess_prev = osp.args[0]
        self.session_to_preview = sess_prev
    
    @osp_method(R.server.SCRIPT_INFO, 's')
    def rayServerScriptInfo(self, osp: OscPack):
        self.send_gui(RG.SCRIPT_INFO, osp.args[0])
        self.send(*osp.reply(), "Info sent")

    @osp_method(R.server.HIDE_SCRIPT_INFO, '')
    def rayServerHideScriptInfo(self, osp: OscPack):
        self.send_gui(RG.HIDE_SCRIPT_INFO)
        self.send(*osp.reply(), "Info hidden")

    @osp_method(R.server.SCRIPT_USER_ACTION, 's')
    def rayServerScriptUserAction(self, osp: OscPack):
        if not self.gui_list:
            self.send(*osp.error(), ray.Err.LAUNCH_FAILED,
                      "This server has no attached GUI")
            return
        self.send_gui(RG.SCRIPT_USER_ACTION, osp.args[0])

    # set option from GUI
    @osp_method(R.server.SET_OPTION, 'i')
    def rayServerSetOption(self, osp: OscPack):
        option = ray.Option(abs(osp.args[0]))

        if osp.args[0] >= 0:
            self.options |= option
        else:
            self.options &= ~option        

        for gui in self.gui_list:
            if not are_same_osc_port(gui.addr.url, osp.src_addr.url):
                self.send(gui.addr, RG.server.OPTIONS,
                          self.options.value)

    # set options from ray_control
    @osp_method(R.server.SET_OPTIONS, None)
    def rayServerSetOptions(self, osp: OscPack):
        if not osp.strings_only:
            self._unknown_message(osp)
            return False

        if TYPE_CHECKING:
            assert isinstance(osp.args, list[str])

        for option_str in osp.args:
            option_value = True
            if option_str.startswith('not_'):
                option_value = False
                option_str = option_str.replace('not_', '', 1)

            if option_str in self._OPTIONS_DICT:
                option = self._OPTIONS_DICT[option_str]
                if option_value:
                    if (option is ray.Option.DESKTOPS_MEMORY
                            and ray.Option.HAS_WMCTRL not in self.options):
                        self.send(osp.src_addr, p.MINOR_ERROR, osp.path,
                            "wmctrl is not present. "
                            "Impossible to activate 'desktops_memory' option")
                        continue

                    if (option is ray.Option.SNAPSHOTS
                            and ray.Option.HAS_GIT not in self.options):
                        self.send(osp.src_addr, p.MINOR_ERROR, osp.path,
                            "git is not present. "
                            "Impossible to activate 'snapshots' option")
                        continue

                if option_value:
                    self.options |= option
                else:
                    self.options &= ~option

        for gui in self.gui_list:
            if not are_same_osc_port(gui.addr.url, osp.src_addr.url):
                self.send(gui.addr, RG.server.OPTIONS,
                          self.options.value)

        self.send(*osp.reply(), 'Options set')

    @osp_method(R.server.HAS_OPTION, 's')
    def rayServerHasOption(self, osp: OscPack):
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

    @osp_method(R.server.CLEAR_CLIENT_TEMPLATES_DATABASE, '')
    def rayServerClearClientTemplatesDatabase(self, osp: OscPack):
        self.client_templates_database['factory'].clear()
        self.client_templates_database['user'].clear()
        self.send(*osp.reply(), 'database cleared')

    @osp_method(R.server.OPEN_FILE_MANAGER_AT, 's')
    def rayServerOpenFileManagerAt(self, osp: OscPack):
        folder_path = osp.args[0]
        if os.path.isdir(folder_path):
            subprocess.Popen(['xdg-open', folder_path])
        self.send(*osp.reply(), '')

    @osp_method(R.server.EXOTIC_ACTION, 's')
    def rayServerExoticAction(self, osp: OscPack):
        action = osp.args[0]
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

    @osp_method(R.server.patchbay.SAVE_GROUP_POSITION,
                'i' + GroupPos.args_types())
    def rayServerPatchbaySaveCoordinates(self, osp: OscPack):
        # here send to others GUI the new group position
        for gui in self.gui_list:
            if not are_same_osc_port(gui.addr.url, osp.src_addr.url):
                self.send(
                    gui.addr,
                    RGP.UPDATE_GROUP_POSITION,
                    *osp.args)

    @osp_method(R.server.patchbay.SAVE_PORTGROUP, None)
    def rayServerPatchbaySavePortGroup(self, osp: OscPack):
        # osp.args must be group_name, port_type, port_mode, above_metadatas, *port_names
        # where port_names are all strings
        # so types must start with 'siiis' and may continue with strings only
        if not osp.types.startswith('siiis'):
            self._unknown_message(osp)
            return False

        other_types = osp.types.replace('siiis', '', 1)
        for t in other_types:
            if t != 's':
                self._unknown_message(osp)
                return False

    @osp_method(R.session.SAVE, '')
    def raySessionSave(self, osp: OscPack):
        if self.session.path is None:
            self.send(*osp.error(), ray.Err.NO_SESSION_OPEN,
                      "No session to save.")
            return False

    @osp_method(R.session.SAVE_AS_TEMPLATE, 's')
    def raySessionSaveAsTemplate(self, osp: OscPack):
        template_name = osp.args[0]
        if '/' in template_name or template_name == '.':
            self.send(*osp.error(), ray.Err.CREATE_FAILED,
                      "Invalid session template name.")
            return False

    @osp_method(R.session.GET_SESSION_NAME, '')
    def raySessionGetSessionName(self, osp: OscPack):
        if self.session.path is None:
            self.send(*osp.error(), ray.Err.NO_SESSION_OPEN,
                      "No session loaded.")
            return False

        self.send(*osp.reply(), self.session.name)
        self.send(*osp.reply())
        return False

    @osp_method(R.session.TAKE_SNAPSHOT, 's')
    def raySessionTakeSnapshotOnly(self, osp: OscPack):
        if ray.Option.HAS_GIT not in self.options:
            self.send(*osp.error(),
                      "snapshot impossible because git is not installed")
            return False

    @osp_method(R.session.TAKE_SNAPSHOT, 'si')
    def raySessionTakeSnapshot(self, osp: OscPack):
        if ray.Option.HAS_GIT not in self.options:
            self.send(*osp.error(),
                      "snapshot impossible because git is not installed")
            return False

    @osp_method(R.session.CLOSE, '')
    def raySessionClose(self, osp: OscPack):
        if self.session.path is None:
            self.send(*osp.error(), ray.Err.NO_SESSION_OPEN,
                      "No session to close.")
            return False

    @osp_method(R.session.CANCEL_CLOSE, '')
    def raySessionCancelClose(self, osp: OscPack):
        if self.session.path is None:
            self.send(*osp.error(), ray.Err.NO_SESSION_OPEN,
                      "No session to cancel close.")
            return False

    @osp_method(R.session.SKIP_WAIT_USER, '')
    def raySessionSkipWaitUser(self, osp: OscPack):
        if self.server_status is not ray.ServerStatus.WAIT_USER:
            return False

    @osp_method(R.session.DUPLICATE, 's')
    def raySessionDuplicate(self, osp: OscPack):
        if self.is_nsm_locked:
            return False

        if self.session.path is None:
            self.send(*osp.error(), ray.Err.NO_SESSION_OPEN,
                      "No session to duplicate.")
            return False

        if not _path_is_valid(osp.args[0]):
            self.send(*osp.error(), ray.Err.CREATE_FAILED,
                      "Invalid session name.")
            return False

    @osp_method(R.session.DUPLICATE_ONLY, 'sss')
    def nsmServerDuplicateOnly(self, osp: OscPack):
        self.send(osp.src_addr, R.net_daemon.DUPLICATE_STATE, 0)

    @osp_method(R.session.RENAME, 's')
    def rayServerRename(self, osp: OscPack):
        new_session_name = osp.args[0]

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

        if self.session.path is None:
            self.send(*osp.error(), ray.Err.NO_SESSION_OPEN,
                      "No session to rename.")
            return False

    @osp_method(R.session.SET_NOTES, 's')
    def raySessionSetNotes(self, osp: OscPack):
        self.session.notes = osp.args[0]

        for gui in self.gui_list:
            if not are_same_osc_port(gui.addr.url, osp.src_addr.url):
                self.send(gui.addr, RG.session.NOTES,
                          self.session.notes)

    @osp_method(R.session.ADD_EXECUTABLE, 'siiissi')
    def raySessionAddExecutableAdvanced(self, osp: OscPack):
        executable_path, auto_start, protocol, \
            prefix_mode, prefix_pattern, client_id, jack_naming = osp.args

        if self.session.path is None:
            self.send(*osp.error(), ray.Err.NO_SESSION_OPEN,
                      "Cannot add to session because no session is loaded.")
            return False

        if protocol is ray.Protocol.NSM and '/' in executable_path:
            self.send(*osp.error(), ray.Err.LAUNCH_FAILED,
                "Absolute paths are not permitted. Clients must be in $PATH")
            return False

    @osp_method(R.session.ADD_EXECUTABLE, None)
    def raySessionAddExecutableStrings(self, osp: OscPack):
        if not osp.strict_strings: 
            self._unknown_message(osp)
            return False

        if self.session.path is None:
            self.send(*osp.error(), ray.Err.NO_SESSION_OPEN,
                      "Cannot add to session because no session is loaded.")
            return False

        executable_path = osp.args[0]
        ray_hack = bool(len(osp.args) > 1 and 'ray_hack' in osp.args[1:])

        if '/' in executable_path and not ray_hack:
            self.send(*osp.error(), ray.Err.LAUNCH_FAILED,
                "Absolute paths are not permitted. Clients must be in $PATH")
            return False
        
    @osp_method(R.session.ADD_EXEC, 'siiissi')
    def raySessionAddExecAdvanced(self, osp: OscPack):
        executable_path, auto_start, protocol, \
            prefix_mode, prefix_pattern, client_id, jack_naming = osp.args

        if self.session.path is None:
            self.send(*osp.error(), ray.Err.NO_SESSION_OPEN,
                      "Cannot add to session because no session is loaded.")
            return False

        if protocol is ray.Protocol.NSM and '/' in executable_path:
            self.send(*osp.error(), ray.Err.LAUNCH_FAILED,
                "Absolute paths are not permitted. Clients must be in $PATH")
            return False

    @osp_method(R.session.ADD_EXEC, None)
    def raySessionAddExecStrings(self, osp: OscPack):
        if not osp.strict_strings:
            self._unknown_message(osp)
            return False

        if self.session.path is None:
            self.send(*osp.error(), ray.Err.NO_SESSION_OPEN,
                      "Cannot add to session because no session is loaded.")
            return False

        executable_path = osp.args[0]
        ray_hack = bool(len(osp.args) > 1 and 'ray_hack' in osp.args[1:])

        if '/' in executable_path and not ray_hack:
            self.send(*osp.error(), ray.Err.LAUNCH_FAILED,
                "Absolute paths are not permitted. Clients must be in $PATH")
            return False

    @osp_method(R.session.OPEN_FOLDER, '')
    def rayServerOpenFolder(self, osp: OscPack):
        if self.session.path:
            subprocess.Popen(['xdg-open', self.session.path])
        self.send(*osp.reply(), '')

    @osp_method(R.session.SHOW_NOTES, '')
    def raySessionShowNotes(self, osp: OscPack):
        if self.session.path is None:
            self.send(*osp.error(), ray.Err.NO_SESSION_OPEN,
                      "No session to show notes")
            return False

        self.session.notes_shown = True
        self.send_gui(RG.session.NOTES_SHOWN)
        self.send(*osp.reply(), 'notes shown')

    @osp_method(R.session.HIDE_NOTES, '')
    def raySessionHideNotes(self, osp: OscPack):
        if self.session.path is None:
            self.send(*osp.error(), ray.Err.NO_SESSION_OPEN,
                      "No session to hide notes")
            return False

        self.session.notes_shown = False
        self.send_gui(RG.session.NOTES_HIDDEN)
        self.send(*osp.reply(), 'notes hidden')

    @osp_method(R.client.CHANGE_PREFIX, None)
    def rayClientChangePrefix(self, osp: OscPack):
        # here message can be si, ss, sis, sss
        invalid = False

        if len(osp.args) < 2:
            invalid = True

        elif osp.args[1] in (ray.PrefixMode.CUSTOM.value, 'custom'):
            if len(osp.args) < 3:
                invalid = True

        if invalid:
            self._unknown_message(osp)
            return False

    @osp_method(R.favorites.ADD, 'ssis')
    def rayFavoriteAdd(self, osp: OscPack):
        name, icon, int_factory, display_name = osp.args

        for favorite in RS.favorites:
            if (favorite.name == name
                    and bool(int_factory) == favorite.factory):
                favorite.icon = icon
                favorite.display_name = display_name
                break
        else:
            RS.favorites.append(
                ray.Favorite(name, icon, bool(int_factory), display_name))

        self.send_gui(RG.favorites.ADDED, *osp.args)

    @osp_method(R.favorites.REMOVE, 'si')
    def rayFavoriteRemove(self, osp: OscPack):
        name, int_factory = osp.args

        for favorite in RS.favorites:
            if (favorite.name == name
                    and bool(int_factory) == favorite.factory):
                RS.favorites.remove(favorite)
                break

        self.send_gui(RG.favorites.REMOVED, *osp.args)

    @osp_method(R.server.ASK_FOR_PRETTY_NAMES, 'i')
    def askForPrettyNames(self, osp: OscPack):
        print('ask for pretty names received', osp.args)
        self.patchbay_dmn_port = osp.args[0]
        # signaler.osc_recv.emit(osp)
        return True

    # @osp_method(None, None)
    # cannot be decorated, else it is defined in priority to all methods
    # defined after
    def noneMethod(
            self, path: str, args: list, types: str, src_addr: Address):
        osp = OscPack(path, args, types, src_addr)
        if ((osp.path, osp.types)) in self._SIMPLE_OSC_PATHS:
            signaler.osc_recv.emit(osp)
            return
        
        if self._is_string_osc_path(osp):
            signaler.osc_recv.emit(osp)
            return

        self._unknown_message(osp)

    def _is_string_osc_path(self, osp: OscPack) -> bool:
        mini_strings = self._STRINGS_OSC_PATHS.get(osp.path)
        if mini_strings is None:
            return False
        
        if len(osp.args) < mini_strings:
            return False
        
        for c in osp.types:
            if c != 's':
                return False
            
        return True

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
        self.mega_send(self.patchbay_dmn_port, mega_send)

    def set_server_status(self, server_status:ray.ServerStatus):
        self.server_status = server_status
        self.send_gui(RG.server.STATUS, server_status.value)

    def send_renameable(self, renameable:bool):
        if not renameable:
            self.send_gui(RG.session.RENAMEABLE, 0)
            return

        if self._nsm_locker_url:
            nsm_url = os.getenv('NSM_URL')
            if not nsm_url:
                return
            if not are_same_osc_port(self._nsm_locker_url, nsm_url):
                return

        self.send_gui(RG.session.RENAMEABLE, 1)

    def announce_gui(
            self, url: str, nsm_locked=False,
            is_net_free=True, gui_pid=0, tcp_addr: Optional[Address]=None):
        gui = Gui(url)
        gui.pid = gui_pid
        gui.tcp_addr = tcp_addr

        tcp_url = get_net_url(self.tcp_port, protocol=TCP)

        self.send(gui.addr, RG.server.ANNOUNCE, ray.VERSION,
                  self.server_status.value, self.options.value,
                  str(self.session.root), int(is_net_free), tcp_url)

        self.send(gui.addr, RG.server.STATUS,
                  self.server_status.value)

        if self.session.path is None:
            self.send(gui.addr, RG.session.NAME, '')
        else:
            self.send(gui.addr, RG.session.NAME,
                      self.session.name, str(self.session.path))

        self.send(gui.addr, RG.session.NOTES, self.session.notes)
        self.send(gui.addr, RG.server.TERMINAL_COMMAND,
                  self.terminal_command)

        self.session.canvas_saver.send_all_group_positions(gui)

        for favorite in RS.favorites:
            self.send(gui.addr, RG.favorites.ADDED,
                      favorite.name, favorite.icon, int(favorite.factory),
                      favorite.display_name)

        for client in self.session.clients:
            self.send(gui.addr,
                      RG.client.NEW,
                      *client.spread())

            if client.is_ray_hack:
                self.send(gui.addr,
                          RG.client.RAY_HACK_UPDATE,
                          client.client_id,
                          *client.ray_hack.spread())
            elif client.is_ray_net:
                self.send(gui.addr,
                          RG.client.RAY_NET_UPDATE,
                          client.client_id,
                          *client.ray_net.spread())

            self.send(gui.addr, RG.client.STATUS,
                      client.client_id, client.status.value)

            if client.is_capable_of(':optional-gui:'):
                self.send(gui.addr, RG.client.GUI_VISIBLE,
                          client.client_id, int(client.gui_visible))

            if client.is_capable_of(':dirty:'):
                self.send(gui.addr, RG.client.DIRTY,
                          client.client_id, client.dirty)

        for trashed_client in self.session.trashed_clients:
            self.send(gui.addr, RG.trash.ADD,
                      *trashed_client.spread())

            if trashed_client.is_ray_hack:
                self.send(gui.addr, RG.trash.RAY_HACK_UPDATE,
                          trashed_client.client_id,
                          *trashed_client.ray_hack.spread())
            elif trashed_client.is_ray_net:
                self.send(gui.addr, RG.trash.RAY_NET_UPDATE,
                          trashed_client.client_id,
                          *trashed_client.ray_net.spread())

        self.session.check_recent_sessions_existing()
        if self.session.root in self.session.recent_sessions.keys():
            self.send(gui.addr, RG.server.RECENT_SESSIONS,
                      *self.session.recent_sessions[self.session.root])

        self.send(gui.addr, RG.server.MESSAGE,
                  _translate('daemon', "daemon runs at %s") % self.url)

        self.gui_list.append(gui)

        multi_daemon_file.update()

        Terminal.message(f"GUI connected at {gui.addr.url}")

    def announce_controller(self, control_address: Address):
        controller = Controller()
        controller.addr = control_address
        self.controller_list.append(controller)
        self.send(control_address, R.control.server.ANNOUNCE,
                  ray.VERSION, self.server_status.value, self.options.value,
                  str(self.session.root), 1)

    def send_controller_message(self, message: str):
        for controller in self.controller_list:
            self.send(controller.addr, R.control.MESSAGE, message)

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
        pid_list = []
        for gui in self.gui_list:
            if are_on_same_machine(gui.addr.url, self.url):
                pid_list.append(str(gui.pid))
        return ':'.join(pid_list)

    def is_gui_address(self, addr: Address) -> bool:
        for gui in self.gui_list:
            if are_same_osc_port(gui.addr.url, addr.url):
                return True
        return False
