
# Imports from standard library
import logging
import os
import shlex
import sys
import random
import shutil
import subprocess
import time
from typing import TYPE_CHECKING, Callable
from pathlib import Path
import xml.etree.ElementTree as ET

# third party imports
from qtpy.QtCore import QCoreApplication

from patchbay.patchcanvas.patshared import GroupPos

# Imports from src/shared
from osclib import (
    Address, ServerThread, make_method, Message, OscPack,
    are_on_same_machine, are_same_osc_port)
import ray
from xml_tools import XmlElement

# Local imports
from signaler import Signaler
from multi_daemon_file import MultiDaemonFile
from daemon_tools import (
    TemplateRoots,
    CommandLineArgs,
    Terminal,
    RS,
    get_code_root)
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
            if CommandLineArgs.debug:
                sys.stderr.write(
                    '\033[94mOSC::daemon_receives\033[0m %s, %s, %s, %s\n'
                    % (t_path, t_types, t_args, src_addr.url))

            osp = OscPack(t_path, t_args, t_types, src_addr)
            response = func(t_thread, osp, **kwargs)

            if response != False:
                signaler.osc_recv.emit(osp)

            return response
        return wrapper
    return decorated


class Controller:
    addr: Address = None
    pid = 0


class GuiAdress(Address):
    gui_pid = 0


# Osc server thread separated in many classes for confort.


class ClientCommunicating(ServerThread):
    '''Contains NSM protocol.
    OSC paths have to be never changed.'''
    
    def __init__(self, session: 'SignaledSession', osc_num=0):
        ServerThread.__init__(self, osc_num)
        self.session = session

        self._nsm_locker_url = ''
        self._net_master_daemon_url = ''
        self._list_asker_addr = None

        self.gui_list = list[GuiAdress]()
        self.controller_list = list[Controller]()
        self.monitor_list = list[Address]()
        self.server_status = ray.ServerStatus.OFF
        self.is_nsm_locked = False
        self.not_default = False

        self.net_daemon_id = random.randint(1, 999999999)
        self.options = 0

    @osp_method('/osc/ping', '')
    def oscPing(self, osp: OscPack):
        self.send(*osp.reply())

    @osp_method('/reply', None)
    def reply(self, osp: OscPack):
        if not ray.types_are_all_strings(osp.types):
            self._unknown_message(osp)

        if not len(osp.args) >= 1:
            self._unknown_message(osp)
            return False

        reply_path = osp.args[0]

        if reply_path == '/ray/server/list_sessions':
            # this reply is only used here for reply from net_daemon
            # it directly resend its infos
            # to the last addr that asked session list
            if self._list_asker_addr:
                self.send(self._list_asker_addr, osp.path, *osp.args)
            return False

        if reply_path == '/ray/gui/script_user_action':
            self.send_gui('/ray/gui/hide_script_user_action')
            for controller in self.controller_list:
                self.send(controller.addr, '/reply',
                          '/ray/server/script_user_action',
                          'User action dialog validate')
            return False

        if not len(osp.args) == 2:
            # assume this is a normal client, not a net_daemon
            self._unknown_message(osp)
            return False

    @osp_method('/error', 'sis')
    def error(self, osp: OscPack):
        error_path, error_code, error_string = osp.args

        if error_path == '/ray/gui/script_user_action':
            self.send_gui('/ray/gui/hide_script_user_action')

            for controller in self.controller_list:
                self.send(controller.addr, '/error',
                          '/ray/server/script_user_action', -1,
                          'User action dialog aborted !')
            return False

    @osp_method('/minor_error', 'sis')
    def minor_error(self, osp: OscPack):
        # prevent minor_error to minor_error loop in daemon <-> daemon communication
        pass

    # SERVER_CONTROL messages
    # following messages only for :server-control: capability
    @osp_method('/nsm/server/add', 's')
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

    @osp_method('/nsm/server/save', '')
    def nsmServerSave(self, osp: OscPack):
        if self.session.path is None:
            self.send(*osp.error(), ray.Err.NO_SESSION_OPEN,
                      "No session to save.")
            return False

    @osp_method('/nsm/server/open', 's')
    def nsmServerOpen(self, osp: OscPack):
        pass

    @osp_method('/nsm/server/new', 's')
    def nsmServerNew(self, osp: OscPack):
        if self.is_nsm_locked:
            return False

        if not _path_is_valid(osp.args[0]):
            self.send(*osp.error(), ray.Err.CREATE_FAILED,
                      "Invalid session name.")
            return False

    @osp_method('/nsm/server/duplicate', 's')
    def nsmServerDuplicate(self, osp: OscPack):
        if self.is_nsm_locked or self.session.path is None:
            self.send(*osp.error(), ray.Err.NO_SESSION_OPEN,
                      "No session to duplicate.")
            return False

        if not _path_is_valid(osp.args[0]):
            self.send(*osp.error(), ray.Err.CREATE_FAILED,
                      "Invalid session name.")
            return False

    @osp_method('/nsm/server/close', '')
    def nsmServerClose(self, osp: OscPack):
        if self.session.path is None:
            self.send(*osp.error(), ray.Err.NO_SESSION_OPEN,
                      "No session to close.")
            return False

    @osp_method('/nsm/server/abort', '')
    def nsmServerAbort(self, osp: OscPack):
        if self.session.path is None:
            self.send(*osp.error(), ray.Err.NO_SESSION_OPEN,
                      "No session to abort.")
            return False

    @osp_method('/nsm/server/quit', '')
    def nsmServerQuit(self, osp: OscPack):
        pass

    @osp_method('/nsm/server/list', '')
    def nsmServerList(self, osp: OscPack):
        pass

    # END OF SERVER_CONTROL messages

    @osp_method('/nsm/server/announce', 'sssiii')
    def nsmServerAnnounce(self, osp: OscPack):
        if self.session.path is None:
            self.send(*osp.error(), ray.Err.NO_SESSION_OPEN,
                      "Sorry, but there's no session open "
                      "for this application to join.")
            return False

    @osp_method('/nsm/server/broadcast', None)
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

    @osp_method('/nsm/server/monitor_reset', '')
    def nsmServerGetAllStates(self, osp: OscPack):
        self.send(*osp.reply(), 'monitor reset')
        self.session.send_initial_monitor(osp.src_addr, monitor_is_client=True)

    @osp_method('/nsm/client/progress', 'f')
    def nsmClientProgress(self, osp: OscPack):
        client = self.session.get_client_by_address(osp.src_addr)
        if not client:
            return False

        client.progress = osp.args[0]
        self.send_gui("/ray/gui/client/progress", client.client_id,
                     client.progress)

    @osp_method('/nsm/client/is_dirty', '')
    def nsmClientIs_dirty(self, osp: OscPack):
        client = self.session.get_client_by_address(osp.src_addr)
        if not client:
            return False

        Terminal.message("%s sends dirty" % client.client_id)

        client.dirty = 1
        client.last_dirty = time.time()

        self.send_gui("/ray/gui/client/dirty", client.client_id, client.dirty)

    @osp_method('/nsm/client/is_clean', '')
    def nsmClientIs_clean(self, osp: OscPack):
        client = self.session.get_client_by_address(osp.src_addr)
        if not client:
            return False

        Terminal.message("%s sends clean" % client.client_id)

        client.dirty = 0

        self.send_gui("/ray/gui/client/dirty", client.client_id, client.dirty)
        return False

    @osp_method('/nsm/client/message', 'is')
    def nsmClientMessage(self, osp: OscPack):
        client = self.session.get_client_by_address(osp.src_addr)
        if not client:
            return False

        self.send_gui("/ray/gui/client/message",
                      client.client_id, osp.args[0], osp.args[1])

    @osp_method('/nsm/client/gui_is_hidden', '')
    def nsmClientGui_is_hidden(self, osp: OscPack):
        client = self.session.get_client_by_address(osp.src_addr)
        if not client:
            return False

        Terminal.message("Client '%s' sends gui hidden" % client.client_id)

        client.gui_visible = False

        self.send_gui("/ray/gui/client/gui_visible", client.client_id,
                     int(client.gui_visible))

    @osp_method('/nsm/client/gui_is_shown', '')
    def nsmClientGui_is_shown(self, osp: OscPack):
        client = self.session.get_client_by_address(osp.src_addr)
        if not client:
            return False

        Terminal.message("Client '%s' sends gui shown" % client.client_id)

        client.gui_visible = True
        client.gui_has_been_visible = True

        self.send_gui("/ray/gui/client/gui_visible", client.client_id,
                     int(client.gui_visible))

    @osp_method('/nsm/client/label', 's')
    def nsmClientLabel(self, osp: OscPack):
        pass

    @osp_method('/nsm/client/network_properties', 'ss')
    def nsmClientNetworkProperties(self, osp: OscPack):
        pass

    def _unknown_message(self, osp: OscPack):
        self.send(osp.src_addr, '/minor_error', osp.path,
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
    
    def __init__(self, session, osc_num=0):
        ClientCommunicating.__init__(self, session, osc_num)

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

        self._SIMPLE_OSC_PATHS = (
            ('/ray/server/quit', ''),
            ('/ray/server/abort_copy', ''),
            ('/ray/server/abort_parrallel_copy', 'i'),
            ('/ray/server/abort_snapshot', ''),
            ('/ray/server/open_session', 's'),
            ('/ray/server/open_session', 'si'),
            ('/ray/server/open_session', 'sis'),
            ('/ray/server/open_session_off', 's'),
            ('/ray/server/open_session_off', 'si'),
            ('/ray/server/rename_session', 'ss'),
            ('/ray/server/patchbay/views_changed', 's'),
            ('/ray/server/patchbay/clear_absents_in_view', 's'),
            ('/ray/server/patchbay/view_number_changed', 'ii'),
            ('/ray/server/patchbay/view_ptv_changed', 'ii'),
            ('/ray/session/abort', ''),
            ('/ray/session/open_snapshot', 's'),
            ('/ray/session/get_notes', ''),
            ('/ray/session/add_client_template', 'isss'),
            ('/ray/session/add_other_session_client', 'ss'),
            ('/ray/session/list_snapshots', ''),
            ('/ray/session/set_auto_snapshot', 'i'),
            ('/ray/session/list_trashed_clients', ''),
            ('/ray/client/stop', 's'),
            ('/ray/client/kill', 's'),
            ('/ray/client/trash', 's'),
            ('/ray/client/start', 's'),
            ('/ray/client/resume', 's'),
            ('/ray/client/open', 's'),
            ('/ray/client/save', 's'),
            ('/ray/client/save_as_template', 'ss'),
            ('/ray/client/show_optional_gui', 's'),
            ('/ray/client/hide_optional_gui', 's'),
            ('/ray/client/update_properties', ray.ClientData.sisi()),
            ('/ray/client/update_ray_hack_properties', 's' + ray.RayHack.sisi()),
            ('/ray/client/update_ray_net_properties', 's' + ray.RayNet.sisi()),
            ('/ray/client/get_properties', 's'),
            ('/ray/client/change_advanced_properties', 'ssisi'),
            ('/ray/client/full_rename', 'ss'),
            ('/ray/client/change_id', 'ss'),
            ('/ray/client/set_description', 'ss'),
            ('/ray/client/get_description', 's'),
            ('/ray/client/get_pid', 's'),
            ('/ray/client/list_files', 's'),
            ('/ray/client/list_snapshots', 's'),
            ('/ray/client/open_snapshot', 'ss'),
            ('/ray/client/is_started', 's'),
            ('/ray/client/set_custom_data', 'sss'),
            ('/ray/client/get_custom_data', 'ss'),
            ('/ray/client/set_tmp_data', 'sss'),
            ('/ray/client/get_tmp_data', 'ss'),
            ('/ray/client/send_signal', 'si'),
            ('/ray/trashed_client/restore', 's'),
            ('/ray/trashed_client/remove_definitely', 's'),
            ('/ray/trashed_client/remove_keep_files', 's'),
            ('/ray/net_daemon/duplicate_state', 'f')
        )
        
        self._STRINGS_OSC_PATHS = {
            '/ray/server/list_user_client_templates': 0,
            '/ray/server/list_factory_client_templates': 0,
            '/ray/session/run_step': 0,
            '/ray/session/add_factory_client_template': 1,
            '/ray/session/add_user_client_template': 1,
            '/ray/session/reorder_clients': 1,
            '/ray/session/clear_clients': 0,
            '/ray/session/list_clients': 0,
            '/ray/client/set_properties': 2,
        }

        global instance
        instance = self

    @staticmethod
    def get_instance() -> 'OscServerThread':
        return instance

    @osp_method('/ray/server/gui_announce', 'sisii')
    def rayGuiGui_announce(self, osp: OscPack):
        (version, int_nsm_locked, net_master_daemon_url,
         gui_pid, net_daemon_id) = osp.args

        nsm_locked = bool(int_nsm_locked)
        is_net_free = True

        if nsm_locked:
            self._net_master_daemon_url = net_master_daemon_url
            self.is_nsm_locked = True
            self._nsm_locker_url = osp.src_addr.url

            for gui_addr in self.gui_list:
                if not are_same_osc_port(gui_addr.url, osp.src_addr.url):
                    self.send(gui_addr, '/ray/gui/server/nsm_locked', 1)

            self.net_daemon_id = net_daemon_id

            multi_daemon_file = MultiDaemonFile.get_instance()
            if multi_daemon_file:
                is_net_free = multi_daemon_file.is_free_for_root(
                    self.net_daemon_id, self.session.root)

        self.announce_gui(osp.src_addr.url, nsm_locked, is_net_free, gui_pid)

    @osp_method('/ray/server/gui_disannounce', '')
    def rayGuiGui_disannounce(self, osp: OscPack):
        for addr in self.gui_list:
            if are_same_osc_port(addr.url, osp.src_addr.url):
                break
        else:
            return False

        self.gui_list.remove(addr)

        if osp.src_addr.url == self._nsm_locker_url:
            self.net_daemon_id = random.randint(1, 999999999)

            self.is_nsm_locked = False
            self._nsm_locker_url = ''
            self.send_gui('/ray/gui/server/nsm_locked', 0)

        multi_daemon_file = MultiDaemonFile.get_instance()
        if multi_daemon_file:
            multi_daemon_file.update()

    @osp_method('/ray/server/ask_for_patchbay', '')
    def rayServerGetPatchbayPort(self, osp: OscPack):
        patchbay_file = '/tmp/RaySession/patchbay_daemons/' + str(self.port)

        if not os.path.exists(patchbay_file):
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
                        patchbay_addr = Address(int(port_str))
                        good_port = True
                    except:
                        patchbay_addr = None
                        sys.stderr.write(
                            'port given for patchbay %s is not a valid osc port')

                    if good_port:
                        self.send(patchbay_addr, '/ray/patchbay/add_gui',
                                  osp.src_addr.url)
                        return False
                    break

        # continue in main thread if patchbay_to_osc is not started yet
        # see session_signaled.py -> _ray_server_ask_for_patchbay

    @osp_method('/ray/server/controller_announce', 'i')
    def rayServerControllerAnnounce(self, osp: OscPack):
        controller = Controller()
        controller.addr = osp.src_addr
        controller.pid = osp.args[0]
        self.controller_list.append(controller)
        self.send(*osp.reply(), 'announced')

    @osp_method('/ray/server/controller_disannounce', '')
    def rayServerControllerDisannounce(self, osp: OscPack):
        for controller in self.controller_list:
            if controller.addr.url == osp.src_addr.url:
                break
        else:
            return

        self.controller_list.remove(controller)
        self.send(*osp.reply(), 'disannounced')

    @osp_method('/ray/server/monitor_announce', '')
    def rayServerMonitorAnnounce(self, osp: OscPack):
        monitor_addr = osp.src_addr
        self.monitor_list.append(monitor_addr)
        self.session.send_initial_monitor(osp.src_addr, monitor_is_client=False)
        self.send(*osp.reply(), 'announced')
    
    @osp_method('/ray/server/monitor_quit', '')
    def rayServerMonitorDisannounce(self, osp: OscPack):
        for monitor_addr in self.monitor_list:
            if monitor_addr.url == osp.src_addr.url:
                break
        else:
            return
        
        self.monitor_list.remove(monitor_addr)
        self.send(*osp.reply(), 'monitor exit')

    @osp_method('/ray/server/set_nsm_locked', '')
    def rayServerSetNsmLocked(self, osp: OscPack):
        self.is_nsm_locked = True
        self._nsm_locker_url = osp.src_addr.url

        for gui_addr in self.gui_list:
            if gui_addr.url != osp.src_addr.url:
                self.send(gui_addr, '/ray/gui/server/nsm_locked', 1)

    @osp_method('/ray/server/change_root', 's')
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

    @osp_method('/ray/server/set_terminal_command', 's')
    def rayServerSetTerminalCommand(self, osp: OscPack):
        if osp.args[0] != self.terminal_command:
            self.terminal_command = osp.args[0]
            if not self.terminal_command:
                self.terminal_command = shlex.join(
                    which_terminal(title='RAY_TERMINAL_TITLE'))
            self.send_gui('/ray/gui/server/terminal_command',
                          self.terminal_command)
        self.send(*osp.reply(), 'terminal command set')

    @osp_method('/ray/server/list_path', '')
    def rayServerListPath(self, osp: OscPack):
        exec_list = list[str]()
        tmp_exec_list = list[str]()
        n = 0

        pathlist = os.getenv('PATH').split(':')
        for pathdir in pathlist:
            if os.path.isdir(pathdir):
                listexe = os.listdir(pathdir)
                for exe in listexe:
                    fullexe = pathdir + '/' + exe

                    if (os.path.isfile(fullexe)
                            and os.access(fullexe, os.X_OK)
                            and not exe in exec_list):
                        exec_list.append(exe)
                        tmp_exec_list.append(exe)
                        n += len(exe)

                        if n >= 20000:
                            self.send(osp.src_addr, '/reply',
                                      osp.path, *tmp_exec_list)
                            tmp_exec_list.clear()
                            n = 0

        if tmp_exec_list:
            self.send(*osp.reply(), *tmp_exec_list)

    @osp_method('/ray/server/list_session_templates', '')
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

    @osp_method('/ray/server/remove_client_template', 's')
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

    @osp_method('/ray/server/list_sessions', '')
    def rayServerListSessions(self, osp: OscPack):
        self._list_asker_addr = osp.src_addr

    @osp_method('/ray/server/list_sessions', 'i')
    def rayServerListSessionsWithNet(self, osp: OscPack):
        self._list_asker_addr = osp.src_addr

    @osp_method('/ray/server/new_session', None)
    def rayServerNewSession(self, osp: OscPack):
        if not ray.types_are_all_strings(osp.types):
            self._unknown_message(osp)
            return False

        if self.is_nsm_locked:
            return False

        if not _path_is_valid(osp.args[0]):
            self.send(*osp.error(), ray.Err.CREATE_FAILED,
                      "Invalid session name.")
            return False

    @osp_method('/ray/server/save_session_template', 'ss')
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

    @osp_method('/ray/server/save_session_template', 'sss')
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

    @osp_method('/ray/server/get_session_preview', 's')
    def rayServerGetSessionPreview(self, osp: OscPack):
        self.session_to_preview = osp.args[0]
    
    @osp_method('/ray/server/script_info', 's')
    def rayServerScriptInfo(self, osp: OscPack):
        self.send_gui('/ray/gui/script_info', osp.args[0])
        self.send(*osp.reply(), "Info sent")

    @osp_method('/ray/server/hide_script_info', '')
    def rayServerHideScriptInfo(self, osp: OscPack):
        self.send_gui('/ray/gui/hide_script_info')
        self.send(*osp.reply(), "Info hidden")

    @osp_method('/ray/server/script_user_action', 's')
    def rayServerScriptUserAction(self, osp: OscPack):
        if not self.gui_list:
            self.send(*osp.error(), ray.Err.LAUNCH_FAILED,
                      "This server has no attached GUI")
            return
        self.send_gui('/ray/gui/script_user_action', osp.args[0])

    # set option from GUI
    @osp_method('/ray/server/set_option', 'i')
    def rayServerSetOption(self, osp: OscPack):
        option = ray.Option(abs(osp.args[0]))

        if osp.args[0] >= 0:
            self.options |= option
        else:
            self.options &= ~option        

        for gui_addr in self.gui_list:
            if not are_same_osc_port(gui_addr.url, osp.src_addr.url):
                self.send(gui_addr, '/ray/gui/server/options',
                          self.options.value)

    # set options from ray_control
    @osp_method('/ray/server/set_options', None)
    def rayServerSetOptions(self, osp: OscPack):
        if not ray.types_are_all_strings(osp.types):
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
                        self.send(osp.src_addr, '/minor_error', osp.path,
                            "wmctrl is not present. "
                            "Impossible to activate 'desktops_memory' option")
                        continue

                    if (option is ray.Option.SNAPSHOTS
                            and ray.Option.HAS_GIT not in self.options):
                        self.send(osp.src_addr, '/minor_error', osp.path,
                            "git is not present. "
                            "Impossible to activate 'snapshots' option")
                        continue

                if option_value:
                    self.options |= option
                else:
                    self.options &= ~option

        for gui_addr in self.gui_list:
            if not are_same_osc_port(gui_addr.url, osp.src_addr.url):
                self.send(gui_addr, '/ray/gui/server/options',
                          self.options.value)

        self.send(*osp.reply(), 'Options set')

    @osp_method('/ray/server/has_option', 's')
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

    @osp_method('/ray/server/clear_client_templates_database', '')
    def rayServerClearClientTemplatesDatabase(self, osp: OscPack):
        self.client_templates_database['factory'].clear()
        self.client_templates_database['user'].clear()
        self.send(*osp.reply(), 'database cleared')

    @osp_method('/ray/server/open_file_manager_at', 's')
    def rayServerOpenFileManagerAt(self, osp: OscPack):
        folder_path = osp.args[0]
        if os.path.isdir(folder_path):
            subprocess.Popen(['xdg-open', folder_path])
        self.send(*osp.reply(), '')

    @osp_method('/ray/server/exotic_action', 's')
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

    @osp_method('/ray/server/patchbay/save_group_position',
                'i' + GroupPos.args_types())
    def rayServerPatchbaySaveCoordinates(self, osp: OscPack):
        # here send to others GUI the new group position
        for gui_addr in self.gui_list:
            if not are_same_osc_port(gui_addr.url, osp.src_addr.url):
                self.send(
                    gui_addr,
                    '/ray/gui/patchbay/update_group_position',
                    *osp.args)

    @osp_method('/ray/server/patchbay/save_portgroup', None)
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

    @osp_method('/ray/session/save', '')
    def raySessionSave(self, osp: OscPack):
        if self.session.path is None:
            self.send(*osp.error(), ray.Err.NO_SESSION_OPEN,
                      "No session to save.")
            return False

    @osp_method('/ray/session/save_as_template', 's')
    def raySessionSaveAsTemplate(self, osp: OscPack):
        template_name = osp.args[0]
        if '/' in template_name or template_name == '.':
            self.send(*osp.error(), ray.Err.CREATE_FAILED,
                      "Invalid session template name.")
            return False

    @osp_method('/ray/session/get_session_name', '')
    def raySessionGetSessionName(self, osp: OscPack):
        if self.session.path is None:
            self.send(*osp.error(), ray.Err.NO_SESSION_OPEN,
                      "No session loaded.")
            return False

        self.send(*osp.reply(), self.session.name)
        self.send(*osp.reply())
        return False

    @osp_method('/ray/session/take_snapshot', 's')
    def raySessionTakeSnapshotOnly(self, osp: OscPack):
        if ray.Option.HAS_GIT not in self.options:
            self.send(*osp.error(),
                      "snapshot impossible because git is not installed")
            return False

    @osp_method('/ray/session/take_snapshot', 'si')
    def raySessionTakeSnapshot(self, osp: OscPack):
        if ray.Option.HAS_GIT not in self.options:
            self.send(*osp.error(),
                      "snapshot impossible because git is not installed")
            return False

    @osp_method('/ray/session/close', '')
    def raySessionClose(self, osp: OscPack):
        if self.session.path is None:
            self.send(*osp.error(), ray.Err.NO_SESSION_OPEN,
                      "No session to close.")
            return False

    @osp_method('/ray/session/cancel_close', '')
    def raySessionCancelClose(self, osp: OscPack):
        if self.session.path is None:
            self.send(*osp.error(), ray.Err.NO_SESSION_OPEN,
                      "No session to cancel close.")
            return False

    @osp_method('/ray/session/skip_wait_user', '')
    def raySessionSkipWaitUser(self, osp: OscPack):
        if self.server_status is not ray.ServerStatus.WAIT_USER:
            return False

    @osp_method('/ray/session/duplicate', 's')
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

    @osp_method('/ray/session/duplicate_only', 'sss')
    def nsmServerDuplicateOnly(self, osp: OscPack):
        self.send(osp.src_addr, '/ray/net_daemon/duplicate_state', 0)

    @osp_method('/ray/session/rename', 's')
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

    @osp_method('/ray/session/set_notes', 's')
    def raySessionSetNotes(self, osp: OscPack):
        self.session.notes = osp.args[0]

        for gui_addr in self.gui_list:
            if not are_same_osc_port(gui_addr.url, osp.src_addr.url):
                self.send(gui_addr, '/ray/gui/session/notes',
                          self.session.notes)

    @osp_method('/ray/session/add_executable', 'siiissi')
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

    @osp_method('/ray/session/add_executable', None)
    def raySessionAddExecutableStrings(self, osp: OscPack):
        if not (osp.types and ray.types_are_all_strings(osp.types)):
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

    @osp_method('/ray/session/open_folder', '')
    def rayServerOpenFolder(self, osp: OscPack):
        if self.session.path:
            subprocess.Popen(['xdg-open', self.session.path])
        self.send(*osp.reply(), '')

    @osp_method('/ray/session/show_notes', '')
    def raySessionShowNotes(self, osp: OscPack):
        if self.session.path is None:
            self.send(*osp.error(), ray.Err.NO_SESSION_OPEN,
                      "No session to show notes")
            return False

        self.session.notes_shown = True
        self.send_gui('/ray/gui/session/notes_shown')
        self.send(*osp.reply(), 'notes shown')

    @osp_method('/ray/session/hide_notes', '')
    def raySessionHideNotes(self, osp: OscPack):
        if self.session.path is None:
            self.send(*osp.error(), ray.Err.NO_SESSION_OPEN,
                      "No session to hide notes")
            return False

        self.session.notes_shown = False
        self.send_gui('/ray/gui/session/notes_hidden')
        self.send(*osp.reply(), 'notes hidden')

    @osp_method('/ray/client/change_prefix', None)
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

    @osp_method('/ray/favorites/add', 'ssis')
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

        self.send_gui('/ray/gui/favorites/added', *osp.args)

    @osp_method('/ray/favorites/remove', 'si')
    def rayFavoriteRemove(self, osp: OscPack):
        name, int_factory = osp.args

        for favorite in RS.favorites:
            if (favorite.name == name
                    and bool(int_factory) == favorite.factory):
                RS.favorites.remove(favorite)
                break

        self.send_gui('/ray/gui/favorites/removed', *osp.args)

    @osp_method(None, None)
    def noneMethod(self, osp: OscPack):
        if ((osp.path, osp.types)) in self._SIMPLE_OSC_PATHS:
            return True
        
        if self._is_string_osc_path(osp):
            return True

        self._unknown_message(osp)
        return False

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
        if CommandLineArgs.debug:
            sys.stderr.write(
                '\033[96mOSC::daemon sends\033[0m ' + str(args[1:]) + '\n')

        ClientCommunicating.send(self, *args)

    def send_gui(self, *args):
        for gui_addr in self.gui_list:
            self.send(gui_addr, *args)

    def set_server_status(self, server_status:ray.ServerStatus):
        self.server_status = server_status
        self.send_gui('/ray/gui/server/status', server_status.value)

    def send_renameable(self, renameable:bool):
        if not renameable:
            self.send_gui('/ray/gui/session/renameable', 0)
            return

        if self._nsm_locker_url:
            nsm_url = os.getenv('NSM_URL')
            if not nsm_url:
                return
            if not are_same_osc_port(self._nsm_locker_url, nsm_url):
                return

        self.send_gui('/ray/gui/session/renameable', 1)

    def announce_gui(self, url, nsm_locked=False, is_net_free=True, gui_pid=0):
        gui_addr = GuiAdress(url)
        gui_addr.gui_pid = gui_pid

        self.send(gui_addr, "/ray/gui/server/announce", ray.VERSION,
                  self.server_status.value, self.options.value, str(self.session.root),
                  int(is_net_free))

        self.send(gui_addr, "/ray/gui/server/status", self.server_status.value)
        if self.session.path is None:
            self.send(gui_addr, "/ray/gui/session/name", "")
        else:
            self.send(gui_addr, "/ray/gui/session/name",
                      self.session.name, str(self.session.path))
        self.send(gui_addr, '/ray/gui/session/notes', self.session.notes)
        self.send(gui_addr, '/ray/gui/server/terminal_command',
                  self.terminal_command)

        self.session.canvas_saver.send_all_group_positions(gui_addr)

        for favorite in RS.favorites:
            self.send(gui_addr, "/ray/gui/favorites/added",
                      favorite.name, favorite.icon, int(favorite.factory),
                      favorite.display_name)

        for client in self.session.clients:
            self.send(gui_addr,
                      '/ray/gui/client/new',
                      *client.spread())

            if client.protocol is ray.Protocol.RAY_HACK:
                self.send(gui_addr,
                          '/ray/gui/client/ray_hack_update',
                          client.client_id,
                          *client.ray_hack.spread())
            elif client.protocol is ray.Protocol.RAY_NET:
                self.send(gui_addr,
                          '/ray/gui/client/ray_net_update',
                          client.client_id,
                          *client.ray_net.spread())

            self.send(gui_addr, "/ray/gui/client/status",
                      client.client_id, client.status.value)

            if client.is_capable_of(':optional-gui:'):
                self.send(gui_addr, '/ray/gui/client/gui_visible',
                          client.client_id, int(client.gui_visible))

            if client.is_capable_of(':dirty:'):
                self.send(gui_addr, '/ray/gui/client/dirty',
                          client.client_id, client.dirty)

        for trashed_client in self.session.trashed_clients:
            self.send(gui_addr, '/ray/gui/trash/add',
                      *trashed_client.spread())

            if trashed_client.protocol is ray.Protocol.RAY_HACK:
                self.send(gui_addr, '/ray/gui/trash/ray_hack_update',
                          trashed_client.client_id,
                          *trashed_client.ray_hack.spread())
            elif trashed_client.protocol is ray.Protocol.RAY_NET:
                self.send(gui_addr, '/ray/gui/trash/ray_net_update',
                          trashed_client.client_id,
                          *trashed_client.ray_net.spread())

        self.session.check_recent_sessions_existing()
        if self.session.root in self.session.recent_sessions.keys():
            self.send(gui_addr, '/ray/gui/server/recent_sessions',
                      *self.session.recent_sessions[self.session.root])

        self.send(gui_addr, '/ray/gui/server/message',
                  _translate('daemon', "daemon runs at %s") % self.url)

        self.gui_list.append(gui_addr)

        multi_daemon_file = MultiDaemonFile.get_instance()
        if multi_daemon_file:
            multi_daemon_file.update()

        Terminal.message("GUI connected at %s" % gui_addr.url)

    def announce_controller(self, control_address):
        controller = Controller()
        controller.addr = control_address
        self.controller_list.append(controller)
        self.send(control_address, "/ray/control/server/announce",
                  ray.VERSION, self.server_status.value, self.options.value,
                  str(self.session.root), 1)

    def send_controller_message(self, message):
        for controller in self.controller_list:
            self.send(controller.addr, '/ray/control/message', message)

    def has_gui(self)->int:
        has_gui = False

        for gui_addr in self.gui_list:
            if are_on_same_machine(self.url, gui_addr.url):
                # we've got a local GUI
                return 3

            has_gui = True

        if has_gui:
            return 1

        return 0

    def get_local_gui_pid_list(self) -> str:
        pid_list = []
        for gui_addr in self.gui_list:
            if are_on_same_machine(gui_addr.url, self.url):
                pid_list.append(str(gui_addr.gui_pid))
        return ':'.join(pid_list)

    def is_gui_address(self, addr: Address) -> bool:
        for gui_addr in self.gui_list:
            if are_same_osc_port(gui_addr.url, addr.url):
                return True
        return False
