import logging
import os
import shlex
import sys
import random
import shutil
import subprocess
import time
from typing import TYPE_CHECKING
from pathlib import Path
import xml.etree.ElementTree as ET

try:
    import liblo
except ImportError:
    import pyliblo3 as liblo
from PyQt5.QtCore import QCoreApplication

import ray
from signaler import Signaler
from multi_daemon_file import MultiDaemonFile
from daemon_tools import (
    TemplateRoots,
    CommandLineArgs,
    Terminal,
    RS,
    get_code_root)
from xml_tools import XmlElement
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

def ray_method(path, types):
    def decorated(func):
        @liblo.make_method(path, types)
        def wrapper(*args, **kwargs):
            t_thread, t_path, t_args, t_types, src_addr, rest = args
            if CommandLineArgs.debug:
                sys.stderr.write(
                    '\033[94mOSC::daemon_receives\033[0m %s, %s, %s, %s\n'
                    % (t_path, t_types, t_args, src_addr.url))

            response = func(*args[:-1], **kwargs)
            if response != False:
                signaler.osc_recv.emit(t_path, t_args, t_types, src_addr)

            return response
        return wrapper
    return decorated


class Controller:
    addr: liblo.Address = None
    pid = 0


class GuiAdress(liblo.Address):
    gui_pid = 0


# Osc server thread separated in many classes for confort.

# ClientCommunicating contains NSM protocol.
# OSC paths have to be never changed.
class ClientCommunicating(liblo.ServerThread):
    def __init__(self, session: 'SignaledSession', osc_num=0):
        liblo.ServerThread.__init__(self, osc_num)
        self.session = session

        self._nsm_locker_url = ''
        self._net_master_daemon_url = ''
        self._list_asker_addr = None

        self.gui_list = list[GuiAdress]()
        self.controller_list = list[Controller]()
        self.monitor_list = list[liblo.Address]()
        self.server_status = ray.ServerStatus.OFF
        self.is_nsm_locked = False
        self.not_default = False

        self.net_daemon_id = random.randint(1, 999999999)
        self.options = 0

    @ray_method('/osc/ping', '')
    def oscPing(self, path, args, types, src_addr):
        self.send(src_addr, "/reply", path)

    @ray_method('/reply', None)
    def reply(self, path, args, types, src_addr):
        if not ray.types_are_all_strings(types):
            self._unknown_message(path, types, src_addr)

        if not len(args) >= 1:
            self._unknown_message(path, types, src_addr)
            return False

        reply_path = args[0]

        if reply_path == '/ray/server/list_sessions':
            # this reply is only used here for reply from net_daemon
            # it directly resend its infos
            # to the last addr that asked session list
            if self._list_asker_addr:
                self.send(self._list_asker_addr, path, *args)
            return False

        if reply_path == '/ray/gui/script_user_action':
            self.send_gui('/ray/gui/hide_script_user_action')
            for controller in self.controller_list:
                self.send(controller.addr, '/reply',
                          '/ray/server/script_user_action',
                          'User action dialog validate')
            return False

        if not len(args) == 2:
            # assume this is a normal client, not a net_daemon
            self._unknown_message(path, types, src_addr)
            return False

    @ray_method('/error', 'sis')
    def error(self, path, args, types, src_addr):
        error_path, error_code, error_string = args

        if error_path == '/ray/gui/script_user_action':
            self.send_gui('/ray/gui/hide_script_user_action')

            for controller in self.controller_list:
                self.send(controller.addr, '/error',
                          '/ray/server/script_user_action', -1,
                          'User action dialog aborted !')
            return False

    @ray_method('/minor_error', 'sis')
    def minor_error(self, path, args, types, src_addr):
        # prevent minor_error to minor_error loop in daemon <-> daemon communication
        pass

    # SERVER_CONTROL messages
    # following messages only for :server-control: capability
    @ray_method('/nsm/server/add', 's')
    def nsmServerAdd(self, path, args, types, src_addr):
        executable_path = args[0]

        if not self.session.path:
            self.send(src_addr, "/error", path, ray.Err.NO_SESSION_OPEN,
                      "Cannot add to session because no session is loaded.")
            return False

        if '/' in executable_path:
            self.send(src_addr, "/error", path, ray.Err.LAUNCH_FAILED,
                "Absolute paths are not permitted. Clients must be in $PATH")
            return False

    @ray_method('/nsm/server/save', '')
    def nsmServerSave(self, path, args, types, src_addr):
        if not self.session.path:
            self.send(src_addr, "/error", path, ray.Err.NO_SESSION_OPEN,
                      "No session to save.")
            return False

    @ray_method('/nsm/server/open', 's')
    def nsmServerOpen(self, path, args, types, src_addr):
        pass

    @ray_method('/nsm/server/new', 's')
    def nsmServerNew(self, path, args, types, src_addr):
        if self.is_nsm_locked:
            return False

        if not _path_is_valid(args[0]):
            self.send(src_addr, "/error", path, ray.Err.CREATE_FAILED,
                      "Invalid session name.")
            return False

    @ray_method('/nsm/server/duplicate', 's')
    def nsmServerDuplicate(self, path, args, types, src_addr):
        if self.is_nsm_locked or not self.session.path:
            self.send(src_addr, "/error", path, ray.Err.NO_SESSION_OPEN,
                      "No session to duplicate.")
            return False

        if not _path_is_valid(args[0]):
            self.send(src_addr, "/error", path, ray.Err.CREATE_FAILED,
                      "Invalid session name.")
            return False

    @ray_method('/nsm/server/close', '')
    def nsmServerClose(self, path, args, types, src_addr):
        if not self.session.path:
            self.send(src_addr, "/error", path, ray.Err.NO_SESSION_OPEN,
                      "No session to close.")
            return False

    @ray_method('/nsm/server/abort', '')
    def nsmServerAbort(self, path, args, types, src_addr):
        if not self.session.path:
            self.send(src_addr, "/error", path, ray.Err.NO_SESSION_OPEN,
                      "No session to abort.")
            return False

    @ray_method('/nsm/server/quit', '')
    def nsmServerQuit(self, path, args, types, src_addr):
        pass

    @ray_method('/nsm/server/list', '')
    def nsmServerList(self, path, args, types, src_addr):
        pass
    # END OF SERVER_CONTROL messages

    @ray_method('/nsm/server/announce', 'sssiii')
    def nsmServerAnnounce(self, path, args, types, src_addr):
        if not self.session.path:
            self.send(src_addr, "/error", path, ray.Err.NO_SESSION_OPEN,
                      "Sorry, but there's no session open "
                      + "for this application to join.")
            return False

    @ray_method('/nsm/server/broadcast', None)
    def nsmServerBroadcast(self, path, args, types, src_addr: liblo.Address):
        if not args:
            return False

        if not isinstance(args[0], str):
            return False

        #don't allow clients to broadcast NSM commands
        follow_path = args[0]
        if not isinstance(follow_path, str):
            return False
        if follow_path.startswith(('/nsm/', '/ray/')):
            return False

        for client in self.session.clients:
            if not client.addr:
                continue

            if not ray.are_same_osc_port(client.addr.url, src_addr.url):
                self.send(client.addr, liblo.Message(*args))

            # TODO broadcast to slave daemons
            #for gui_addr in self.gui_list:
                ##also relay to attached GUI so that the broadcast can be
                ##propagated to another NSMD instance
                #if gui_addr.url != src_addr.url:
                    #self.send(gui_addr, Message(*args))

    @ray_method('/nsm/server/monitor_reset', '')
    def nsmServerGetAllStates(self, path, args, types, src_addr):
        self.send(src_addr, '/reply', path, 'monitor reset')
        self.session.send_initial_monitor(src_addr, monitor_is_client=True)

    @ray_method('/nsm/client/progress', 'f')
    def nsmClientProgress(self, path, args, types, src_addr):
        client = self.session.get_client_by_address(src_addr)
        if not client:
            return False

        client.progress = args[0]
        self.send_gui("/ray/gui/client/progress", client.client_id,
                     client.progress)

    @ray_method('/nsm/client/is_dirty', '')
    def nsmClientIs_dirty(self, path, args, types, src_addr):
        client = self.session.get_client_by_address(src_addr)
        if not client:
            return False

        Terminal.message("%s sends dirty" % client.client_id)

        client.dirty = 1
        client.last_dirty = time.time()

        self.send_gui("/ray/gui/client/dirty", client.client_id, client.dirty)

    @ray_method('/nsm/client/is_clean', '')
    def nsmClientIs_clean(self, path, args, types, src_addr):
        client = self.session.get_client_by_address(src_addr)
        if not client:
            return False

        Terminal.message("%s sends clean" % client.client_id)

        client.dirty = 0

        self.send_gui("/ray/gui/client/dirty", client.client_id, client.dirty)
        return False

    @ray_method('/nsm/client/message', 'is')
    def nsmClientMessage(self, path, args, types, src_addr):
        client = self.session.get_client_by_address(src_addr)
        if not client:
            return False

        self.send_gui("/ray/gui/client/message",
                      client.client_id, args[0], args[1])

    @ray_method('/nsm/client/gui_is_hidden', '')
    def nsmClientGui_is_hidden(self, path, args, types, src_addr):
        client = self.session.get_client_by_address(src_addr)
        if not client:
            return False

        Terminal.message("Client '%s' sends gui hidden" % client.client_id)

        client.gui_visible = False

        self.send_gui("/ray/gui/client/gui_visible", client.client_id,
                     int(client.gui_visible))

    @ray_method('/nsm/client/gui_is_shown', '')
    def nsmClientGui_is_shown(self, path, args, types, src_addr):
        client = self.session.get_client_by_address(src_addr)
        if not client:
            return False

        Terminal.message("Client '%s' sends gui shown" % client.client_id)

        client.gui_visible = True
        client.gui_has_been_visible = True

        self.send_gui("/ray/gui/client/gui_visible", client.client_id,
                     int(client.gui_visible))

    @ray_method('/nsm/client/label', 's')
    def nsmClientLabel(self, path, args, types, src_addr):
        pass

    @ray_method('/nsm/client/network_properties', 'ss')
    def nsmClientNetworkProperties(self, path, args, types, src_addr):
        pass

    @ray_method('/nsm/client/no_save_level', 'i')
    def nsmClientNoSaveLevel(self, path, args, types, src_addr):
        pass

    def _unknown_message(self, path, types, src_addr):
        self.send(src_addr, '/minor_error', path, ray.Err.UNKNOWN_MESSAGE,
                  "unknown osc message: %s %s" % (path, types))

    def send_gui(self, *args):
        # should be overclassed
        pass

class OscServerThread(ClientCommunicating):
    def __init__(self, session, osc_num=0):
        ClientCommunicating.__init__(self, session, osc_num)

        self.options_dict = {
            'save_from_client': ray.Option.SAVE_FROM_CLIENT,
            'bookmark_session_folder': ray.Option.BOOKMARK_SESSION,
            'desktops_memory': ray.Option.DESKTOPS_MEMORY,
            'snapshots': ray.Option.SNAPSHOTS,
            'session_scripts': ray.Option.SESSION_SCRIPTS,
            'gui_states': ray.Option.GUI_STATES}

        self.options = RS.settings.value(
            'daemon/options',
            ray.Option.BOOKMARK_SESSION
            + ray.Option.SNAPSHOTS
            + ray.Option.SESSION_SCRIPTS,
            type=int
        )

        if CommandLineArgs.no_options:
            self.options = 0

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

        global instance
        instance = self

    @staticmethod
    def get_instance() -> 'OscServerThread':
        return instance

    @ray_method('/ray/server/gui_announce', 'sisii')
    def rayGuiGui_announce(self, path, args, types, src_addr: liblo.Address):
        (version, int_nsm_locked, net_master_daemon_url,
         gui_pid, net_daemon_id) = args

        nsm_locked = bool(int_nsm_locked)
        is_net_free = True

        if nsm_locked:
            self._net_master_daemon_url = net_master_daemon_url
            self.is_nsm_locked = True
            self._nsm_locker_url = src_addr.url

            for gui_addr in self.gui_list:
                if not ray.are_same_osc_port(gui_addr.url, src_addr.url):
                    self.send(gui_addr, '/ray/gui/server/nsm_locked', 1)

            self.net_daemon_id = net_daemon_id

            multi_daemon_file = MultiDaemonFile.get_instance()
            if multi_daemon_file:
                is_net_free = multi_daemon_file.is_free_for_root(
                    self.net_daemon_id, self.session.root)

        self.announce_gui(src_addr.url, nsm_locked, is_net_free, gui_pid)

    @ray_method('/ray/server/gui_disannounce', '')
    def rayGuiGui_disannounce(self, path, args, types, src_addr: liblo.Address):
        for addr in self.gui_list:
            if ray.are_same_osc_port(addr.url, src_addr.url):
                break
        else:
            return False

        self.gui_list.remove(addr)

        if src_addr.url == self._nsm_locker_url:
            self.net_daemon_id = random.randint(1, 999999999)

            self.is_nsm_locked = False
            self._nsm_locker_url = ''
            self.send_gui('/ray/gui/server/nsm_locked', 0)

        multi_daemon_file = MultiDaemonFile.get_instance()
        if multi_daemon_file:
            multi_daemon_file.update()

    @ray_method('/ray/server/ask_for_patchbay', '')
    def rayServerGetPatchbayPort(self, path, args, types, src_addr):
        patchbay_file = '/tmp/RaySession/patchbay_daemons/' + str(self.port)

        if not os.path.exists(patchbay_file):
            return True

        with open(patchbay_file, 'r') as file:
            file = open(patchbay_file, 'r')
            contents = file.read()
            #file.close()
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
                        patchbay_addr = liblo.Address(int(port_str))
                        good_port = True
                    except:
                        patchbay_addr = None
                        sys.stderr.write(
                            'port given for patchbay %s is not a valid osc port')

                    if good_port:
                        self.send(patchbay_addr, '/ray/patchbay/add_gui',
                                  src_addr.url)
                        return False
                    break

        # continue in main thread if patchbay_to_osc is not started yet
        # see session_signaled.py -> _ray_server_ask_for_patchbay

    @ray_method('/ray/server/controller_announce', 'i')
    def rayServerControllerAnnounce(self, path, args, types, src_addr):
        controller = Controller()
        controller.addr = src_addr
        controller.pid = args[0]
        self.controller_list.append(controller)
        self.send(src_addr, '/reply', path, 'announced')

    @ray_method('/ray/server/controller_disannounce', '')
    def rayServerControllerDisannounce(self, path, args, types, src_addr: liblo.Address):
        for controller in self.controller_list:
            if controller.addr.url == src_addr.url:
                break
        else:
            return

        self.controller_list.remove(controller)
        self.send(src_addr, '/reply', path, 'disannounced')

    @ray_method('/ray/server/monitor_announce', '')
    def rayServerMonitorAnnounce(self, path, args, types, src_addr):
        monitor_addr = src_addr
        self.monitor_list.append(monitor_addr)
        self.session.send_initial_monitor(src_addr, monitor_is_client=False)
        self.send(src_addr, '/reply', path, 'announced')
    
    @ray_method('/ray/server/monitor_quit', '')
    def rayServerMonitorDisannounce(self, path, args, types, src_addr: liblo.Address):
        for monitor_addr in self.monitor_list:
            if monitor_addr.url == src_addr.url:
                break
        else:
            return
        
        self.monitor_list.remove(monitor_addr)
        self.send(src_addr, '/reply', path, 'monitor exit')

    @ray_method('/ray/server/set_nsm_locked', '')
    def rayServerSetNsmLocked(self, path, args, types, src_addr: liblo.Address):
        self.is_nsm_locked = True
        self._nsm_locker_url = src_addr.url

        for gui_addr in self.gui_list:
            if gui_addr.url != src_addr.url:
                self.send(gui_addr, '/ray/gui/server/nsm_locked', 1)

    @ray_method('/ray/server/quit', '')
    def rayServerQuit(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/server/abort_copy', '')
    def rayServerAbortCopy(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/server/abort_parrallel_copy', 'i')
    def rayServerAbortParrallelCopy(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/server/abort_snapshot', '')
    def rayServerAbortSnapshot(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/server/change_root', 's')
    def rayServerChangeRoot(self, path, args, types, src_addr):
        new_root: str = args[0]
        if not(new_root.startswith('/') and _path_is_valid(new_root)):
            self.send(src_addr, '/error', path, ray.Err.CREATE_FAILED,
                      "invalid session root !")

        if self._is_operation_pending(src_addr, path):
            self.send(src_addr, '/error', path, ray.Err.OPERATION_PENDING,
                      "Can't change session_root. Operation pending")
            return False

    @ray_method('/ray/server/set_terminal_command', 's')
    def rayServerSetTerminalCommand(self, path, args, types, src_addr):
        if args[0] != self.terminal_command:
            self.terminal_command = args[0]
            if not self.terminal_command:
                self.terminal_command = shlex.join(
                    which_terminal(title='RAY_TERMINAL_TITLE'))
            self.send_gui('/ray/gui/server/terminal_command',
                          self.terminal_command)
        self.send(src_addr, '/reply', path, 'terminal command set')

    @ray_method('/ray/server/list_path', '')
    def rayServerListPath(self, path, args, types, src_addr):
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
                            self.send(src_addr, '/reply',
                                      path, *tmp_exec_list)
                            tmp_exec_list.clear()
                            n = 0

        if tmp_exec_list:
            self.send(src_addr, '/reply', path, *tmp_exec_list)

    @ray_method('/ray/server/list_session_templates', '')
    def rayServerListSessionTemplates(self, path, args, types, src_addr):
        if not TemplateRoots.user_sessions.is_dir():
            self.send(src_addr, '/reply', path)
            return False

        template_list = list[str]()

        all_files = os.listdir(TemplateRoots.user_sessions)
        for file in all_files:
            if os.path.isdir("%s/%s" % (TemplateRoots.user_sessions, file)):
                template_list.append(file)

                if len(template_list) == 100:
                    self.send(src_addr, '/reply', path, *template_list)
                    template_list.clear()

        if template_list:
            self.send(src_addr, '/reply', path, *template_list)

        self.send(src_addr, '/reply', path)

    @ray_method('/ray/server/list_user_client_templates', None)
    def rayServerListUserClientTemplates(self, path, args, types, src_addr):
        for a in types:
            if a != 's':
                self._unknown_message(path, types, src_addr)
                return False

    @ray_method('/ray/server/list_factory_client_templates', None)
    def rayServerListFactoryClientTemplates(self, path, args, types,
                                            src_addr):
        for a in types:
            if a != 's':
                self._unknown_message(path, types, src_addr)
                return False

    @ray_method('/ray/server/remove_client_template', 's')
    def rayServerRemoveClientTemplate(self, path, args, types, src_addr):
        template_name: str = args[0]
        templates_root = TemplateRoots.user_clients
        templates_file = templates_root / 'client_templates.xml'

        if not templates_file.is_file():
            self.send(src_addr, '/error', path, ray.Err.NO_SUCH_FILE,
                      "file %s is missing !" % templates_file)
            return False

        if not os.access(templates_file, os.W_OK):
            self.send(src_addr, '/error', path, ray.Err.NO_SUCH_FILE,
                      "file %s in unwriteable !" % templates_file)
            return False

        tree = ET.parse(templates_file)
        root = tree.getroot()

        if root.tag != 'RAY-CLIENT-TEMPLATES':
            self.send(src_addr, '/error', path, ray.Err.BAD_PROJECT,
                      "file %s is not write correctly !" % templates_file)
            return False

        xroot = XmlElement(root)

        for c in xroot.iter():
            if c.el.tag != 'Client-Template':
                continue
            
            if c.str('template-name') == template_name:
                break
        else:
            self.send(src_addr, '/error', path, ray.Err.NO_SUCH_FILE,
                      "No template \"%s\" to remove !" % template_name)
            return False
        
        root.remove(c.el)
        
        try:
            tree.write(templates_file)
        except BaseException as e:
            _logger.error(str(e))
            self.send(src_addr, '/error', path, ray.Err.CREATE_FAILED,
                      "Impossible to rewrite user client templates xml file")
            return False
        
        templates_dir = templates_root / template_name
        if templates_dir.is_dir():
            try:
                shutil.rmtree(templates_dir)
            except BaseException as e:
                _logger.error(str(e))
                self.send(src_addr, '/error', path, ray.Err.CREATE_FAILED,
                      "Failed to remove the folder %s" % str(templates_dir))
                return False

        self.send(src_addr, '/reply', path,
                  f'template "{template_name}" removed.')

    @ray_method('/ray/server/list_sessions', '')
    def rayServerListSessions(self, path, args, types, src_addr):
        self._list_asker_addr = src_addr

    @ray_method('/ray/server/list_sessions', 'i')
    def rayServerListSessionsWithNet(self, path, args, types, src_addr):
        self._list_asker_addr = src_addr

    @ray_method('/ray/server/new_session', None)
    def rayServerNewSession(self, path, args, types, src_addr):
        if not ray.types_are_all_strings(types):
            self._unknown_message(path, types, src_addr)
            return False

        if self.is_nsm_locked:
            return False

        if not _path_is_valid(args[0]):
            self.send(src_addr, "/error", path, ray.Err.CREATE_FAILED,
                      "Invalid session name.")
            return False

    @ray_method('/ray/server/open_session', 's')
    def rayServerOpenSession(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/server/open_session', 'si')
    def rayServerOpenSessionWithoutSave(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/server/open_session', 'sis')
    def rayServerOpenSessionWithTemplate(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/server/open_session_off', 's')
    def rayServerOpenSessionOff(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/server/open_session_off', 'si')
    def rayServerOpenSessionWithoutSaveOff(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/server/save_session_template', 'ss')
    def rayServerSaveSessionTemplate(self, path, args, types, src_addr):
        #save as template an not loaded session
        session_name, template_name = args

        if not _path_is_valid(session_name):
            self.send(src_addr, "/error", path, ray.Err.CREATE_FAILED,
                    "Invalid session name.")
            return False

        if '/' in template_name:
            self.send(src_addr, "/error", path, ray.Err.CREATE_FAILED,
                      "Invalid template name.")
            return False

    @ray_method('/ray/server/rename_session', 'ss')
    def rayServerRenameSession(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/server/save_session_template', 'sss')
    def rayServerSaveSessionTemplateWithRoot(self, path, args,
                                             types, src_addr):
        #save as template an not loaded session
        session_name, template_name, sess_root = args
        if not _path_is_valid(session_name):
            self.send(src_addr, "/error", path, ray.Err.CREATE_FAILED,
                    "Invalid template name.")
            return False

        if '/' in template_name:
            self.send(src_addr, "/error", path, ray.Err.CREATE_FAILED,
                      "Invalid session name.")
            return False

    @ray_method('/ray/server/get_session_preview', 's')
    def rayServerGetSessionPreview(self, path, args, types, src_addr):
        self.session_to_preview = args[0]
    
    @ray_method('/ray/server/script_info', 's')
    def rayServerScriptInfo(self, path, args, types, src_addr):
        self.send_gui('/ray/gui/script_info', args[0])
        self.send(src_addr, "/reply", path, "Info sent")

    @ray_method('/ray/server/hide_script_info', '')
    def rayServerHideScriptInfo(self, path, args, types, src_addr):
        self.send_gui('/ray/gui/hide_script_info')
        self.send(src_addr, "/reply", path, "Info hidden")

    @ray_method('/ray/server/script_user_action', 's')
    def rayServerScriptUserAction(self, path, args, types, src_addr):
        if not self.gui_list:
            self.send(src_addr, '/error', path, ray.Err.LAUNCH_FAILED,
                      "This server has no attached GUI")
            return
        self.send_gui('/ray/gui/script_user_action', args[0])

    # set option from GUI
    @ray_method('/ray/server/set_option', 'i')
    def rayServerSetOption(self, path, args, types, src_addr):
        option = args[0]
        self._set_option(option)

        for gui_addr in self.gui_list:
            if not ray.are_same_osc_port(gui_addr.url, src_addr.url):
                self.send(gui_addr, '/ray/gui/server/options', self.options)

    # set options from ray_control
    @ray_method('/ray/server/set_options', None)
    def rayServerSetOptions(self, path, args, types, src_addr: liblo.Address):
        if not ray.types_are_all_strings(types):
            self._unknown_message(path, types, src_addr)
            return False

        if TYPE_CHECKING:
            assert isinstance(args, list[str])

        for option_str in args:
            option_value = True
            if option_str.startswith('not_'):
                option_value = False
                option_str = option_str.replace('not_', '', 1)

            if option_str in self.options_dict:
                option = self.options_dict[option_str]
                if option_value:
                    if (option == ray.Option.DESKTOPS_MEMORY
                            and not self.options & ray.Option.HAS_WMCTRL):
                        self.send(src_addr, '/minor_error', path,
                            "wmctrl is not present. "
                            "Impossible to activate 'desktops_memory' option")
                        continue
                    if (option == ray.Option.SNAPSHOTS
                            and not self.options & ray.Option.HAS_GIT):
                        self.send(src_addr, '/minor_error', path,
                            "git is not present. "
                            "Impossible to activate 'snapshots' option")
                        continue

                if not option_value:
                    option = -option
                self._set_option(option)

        for gui_addr in self.gui_list:
            if not ray.are_same_osc_port(gui_addr.url, src_addr.url):
                self.send(gui_addr, '/ray/gui/server/options', self.options)

        self.send(src_addr, '/reply', path, 'Options set')

    @ray_method('/ray/server/has_option', 's')
    def rayServerHasOption(self, path, args, types, src_addr):
        option_str = args[0]
        option_value = False

        if option_str not in self.options_dict:
            self.send(src_addr, '/error', path, ray.Err.GENERAL_ERROR,
                      "option \"%s\" doesn't exists" % option_str)
            return

        if self.options & self.options_dict[option_str]:
            self.send(src_addr, '/reply', path, 'Has option')
        else:
            self.send(src_addr, '/error', path, ray.Err.GENERAL_ERROR,
                      "Option %s is not currently used" % option_str)

    @ray_method('/ray/server/clear_client_templates_database', '')
    def rayServerClearClientTemplatesDatabase(self, path, args, types, src_addr):
        self.client_templates_database['factory'].clear()
        self.client_templates_database['user'].clear()
        self.send(src_addr, '/reply', path, 'database cleared')

    @ray_method('/ray/server/open_file_manager_at', 's')
    def rayServerOpenFileManagerAt(self, path, args, types, src_addr):
        folder_path = args[0]
        if os.path.isdir(folder_path):
            subprocess.Popen(['xdg-open', folder_path])
        self.send(src_addr, '/reply', path, '')

    @ray_method('/ray/server/exotic_action', 's')
    def rayServerExoticAction(self, path, args, types, src_addr):
        action = args[0]
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

    @ray_method('/ray/server/patchbay/save_group_position',
                ray.GroupPosition.sisi())
    def rayServerPatchbaySaveCoordinates(self, path, args, types, src_addr):
        # here send to others GUI the new group position
        for gui_addr in self.gui_list:
            if not ray.are_same_osc_port(gui_addr.url, src_addr.url):
                self.send(gui_addr, '/ray/gui/patchbay/update_group_position',
                          *args)

    @ray_method('/ray/server/patchbay/save_portgroup', None)
    def rayServerPatchbaySavePortGroup(self, path, args, types: str, src_addr):
        # args must be group_name, port_type, port_mode, above_metadatas, *port_names
        # where port_names are all strings
        # so types must start with 'siiis' and may continue with strings only
        if not types.startswith('siiis'):
            self._unknown_message(path, types, src_addr)
            return False

        other_types = types.replace('siiis', '', 1)
        for t in other_types:
            if t != 's':
                self._unknown_message(path, types, src_addr)
                return False

    @ray_method('/ray/session/save', '')
    def raySessionSave(self, path, args, types, src_addr):
        if not self.session.path:
            self.send(src_addr, "/error", path, ray.Err.NO_SESSION_OPEN,
                      "No session to save.")
            return False

    @ray_method('/ray/session/run_step', None)
    def raySessionProcessStep(self, path, args, types, src_addr):
        if not ray.types_are_all_strings(types):
            self._unknown_message(path, types, src_addr)
            return False

    @ray_method('/ray/session/save_as_template', 's')
    def raySessionSaveAsTemplate(self, path, args, types, src_addr):
        template_name = args[0]
        if '/' in template_name or template_name == '.':
            self.send(src_addr, "/error", path, ray.Err.CREATE_FAILED,
                      "Invalid session template name.")
            return False

    @ray_method('/ray/session/get_session_name', '')
    def raySessionGetSessionName(self, path, args, types, src_addr):
        if not self.session.path:
            self.send(src_addr, "/error", path, ray.Err.NO_SESSION_OPEN,
                      "No session loaded.")
            return False

        self.send(src_addr, '/reply', path, self.session.name)
        self.send(src_addr, '/reply', path)
        return False

    @ray_method('/ray/session/take_snapshot', 's')
    def raySessionTakeSnapshotOnly(self, path, args, types, src_addr):
        if not self.options & ray.Option.HAS_GIT:
            self.send(src_addr, '/error', path,
                      "snapshot impossible because git is not installed")
            return False

    @ray_method('/ray/session/take_snapshot', 'si')
    def raySessionTakeSnapshot(self, path, args, types, src_addr):
        if not self.options & ray.Option.HAS_GIT:
            self.send(src_addr, '/error', path,
                      "snapshot impossible because git is not installed")
            return False

    @ray_method('/ray/session/close', '')
    def raySessionClose(self, path, args, types, src_addr):
        if not self.session.path:
            self.send(src_addr, "/error", path, ray.Err.NO_SESSION_OPEN,
                      "No session to close.")
            return False

    @ray_method('/ray/session/abort', '')
    def raySessionAbort(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/session/cancel_close', '')
    def raySessionCancelClose(self, path, args, types, src_addr):
        if not self.session.path:
            self.send(src_addr, "/error", path, ray.Err.NO_SESSION_OPEN,
                      "No session to cancel close.")
            return False

    @ray_method('/ray/session/skip_wait_user', '')
    def raySessionSkipWaitUser(self, path, args, types, src_addr):
        if self.server_status != ray.ServerStatus.WAIT_USER:
            return False

    @ray_method('/ray/session/duplicate', 's')
    def raySessionDuplicate(self, path, args, types, src_addr):
        if self.is_nsm_locked:
            return False

        if not self.session.path:
            self.send(src_addr, "/error", path, ray.Err.NO_SESSION_OPEN,
                      "No session to duplicate.")
            return False

        if not _path_is_valid(args[0]):
            self.send(src_addr, "/error", path, ray.Err.CREATE_FAILED,
                      "Invalid session name.")
            return False

    @ray_method('/ray/session/duplicate_only', 'sss')
    def nsmServerDuplicateOnly(self, path, args, types, src_addr):
        self.send(src_addr, '/ray/net_daemon/duplicate_state', 0)

    @ray_method('/ray/session/open_snapshot', 's')
    def raySessionOpenSnapshot(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/session/rename', 's')
    def rayServerRename(self, path, args, types, src_addr):
        new_session_name = args[0]

        #prevent rename session in network session
        if self._nsm_locker_url:
            NSM_URL = os.getenv('NSM_URL')
            if not NSM_URL:
                return False

            if not ray.are_same_osc_port(self._nsm_locker_url, NSM_URL):
                return False

        if '/' in new_session_name:
            self.send(src_addr, "/error", path, ray.Err.CREATE_FAILED,
                      "Invalid session name.")
            return False

        if self._is_operation_pending(src_addr, path):
            return False

        if not self.session.path:
            self.send(src_addr, "/error", path, ray.Err.NO_SESSION_OPEN,
                      "No session to rename.")
            return False

    @ray_method('/ray/session/set_notes', 's')
    def raySessionSetNotes(self, path, args, types, src_addr):
        self.session.notes = args[0]

        for gui_addr in self.gui_list:
            if not ray.are_same_osc_port(gui_addr.url, src_addr.url):
                self.send(gui_addr, '/ray/gui/session/notes',
                          self.session.notes)

    @ray_method('/ray/session/get_notes', '')
    def raySessionGetNotes(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/session/add_executable', 'siiissi')
    def raySessionAddExecutableAdvanced(self, path, args, types, src_addr):
        executable_path, auto_start, protocol, \
            prefix_mode, prefix_pattern, client_id, jack_naming = args

        if not self.session.path:
            self.send(src_addr, "/error", path, ray.Err.NO_SESSION_OPEN,
                      "Cannot add to session because no session is loaded.")
            return False

        if protocol == ray.Protocol.NSM and '/' in executable_path:
            self.send(src_addr, "/error", path, ray.Err.LAUNCH_FAILED,
                "Absolute paths are not permitted. Clients must be in $PATH")
            return False

    @ray_method('/ray/session/add_executable', None)
    def raySessionAddExecutableStrings(self, path, args, types, src_addr):
        if not (types and ray.types_are_all_strings(types)):
            self._unknown_message(path, types, src_addr)
            return False

        if not self.session.path:
            self.send(src_addr, "/error", path, ray.Err.NO_SESSION_OPEN,
                      "Cannot add to session because no session is loaded.")
            return False

        executable_path = args[0]
        via_proxy = bool(len(args) > 1 and 'via_proxy' in args[1:])
        ray_hack = bool(len(args) > 1 and 'ray_hack' in args[1:])

        if '/' in executable_path and not (via_proxy or ray_hack):
            self.send(src_addr, "/error", path, ray.Err.LAUNCH_FAILED,
                "Absolute paths are not permitted. Clients must be in $PATH")
            return False

    @ray_method('/ray/session/add_client_template', 'isss')
    def rayServerAddClientTemplate(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/session/add_factory_client_template', None)
    def raySessionAddFactoryClientTemplate(self, path, args, types, src_addr):
        if not (types and ray.types_are_all_strings(types)):
            self._unknown_message(path, types, src_addr)
            return False

    @ray_method('/ray/session/add_user_client_template', None)
    def raySessionAddUserClientTemplate(self, path, args, types, src_addr):
        if not (types and ray.types_are_all_strings(types)):
            self._unknown_message(path, types, src_addr)
            return False

    @ray_method('/ray/session/add_other_session_client', 'ss')
    def raySessionEatOtherSessionClient(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/session/reorder_clients', None)
    def rayServerReorderClients(self, path, args, types, src_addr):
        if not (types and ray.types_are_all_strings(types)):
            self._unknown_message(path, types, src_addr)
            return False

    @ray_method('/ray/session/list_snapshots', '')
    def rayServerListSnapshots(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/session/set_auto_snapshot', 'i')
    def rayServerSetAutoSnapshot(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/session/open_folder', '')
    def rayServerOpenFolder(self, path, args, types, src_addr):
        if self.session.path:
            subprocess.Popen(['xdg-open', self.session.path])
        self.send(src_addr, '/reply', path, '')

    @ray_method('/ray/session/clear_clients', None)
    def raySessionStopClients(self, path, args, types, src_addr):
        if not ray.types_are_all_strings(types):
            self._unknown_message(path, types, src_addr)
            return False

    @ray_method('/ray/session/show_notes', '')
    def raySessionShowNotes(self, path, args, types, src_addr):
        if not self.session.path:
            self.send(src_addr, '/error', path, ray.Err.NO_SESSION_OPEN,
                      "No session to show notes")
            return False

        self.session.notes_shown = True
        self.send_gui('/ray/gui/session/notes_shown')
        self.send(src_addr, '/reply', path, 'notes shown')

    @ray_method('/ray/session/hide_notes', '')
    def raySessionHideNotes(self, path, args, types, src_addr):
        if not self.session.path:
            self.send(src_addr, '/error', path, ray.Err.NO_SESSION_OPEN,
                      "No session to hide notes")
            return False

        self.session.notes_shown = False
        self.send_gui('/ray/gui/session/notes_hidden')
        self.send(src_addr, '/reply', path, 'notes hidden')

    @ray_method('/ray/session/list_clients', None)
    def raySessionListClients(self, path, args, types, src_addr):
        if not ray.types_are_all_strings(types):
            self._unknown_message(path, types, src_addr)
            return False

    @ray_method('/ray/session/list_trashed_clients', '')
    def raySessionListTrashedClients(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/client/stop', 's')
    def rayGuiClientStop(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/client/kill', 's')
    def rayGuiClientKill(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/client/trash', 's')
    def rayGuiClientRemove(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/client/start', 's')
    def rayGuiClientStart(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/client/resume', 's')
    def rayGuiClientResume(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/client/open', 's')
    def rayClientOpen(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/client/save', 's')
    def rayGuiClientSave(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/client/save_as_template', 'ss')
    def rayGuiClientSaveAsTemplate(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/client/show_optional_gui', 's')
    def nsmGuiClientShow_optional_gui(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/client/hide_optional_gui', 's')
    def nsmGuiClientHide_optional_gui(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/client/update_properties', ray.ClientData.sisi())
    def rayGuiClientUpdateProperties(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/client/update_ray_hack_properties', 's' + ray.RayHack.sisi())
    def rayClientUpdateRayHackProperties(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/client/update_ray_net_properties', 's' + ray.RayNet.sisi())
    def rayClientUpdateRayNetProperties(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/client/get_properties', 's')
    def rayClientGetProperties(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/client/set_properties', None)
    def rayGuiClientSetProperties(self, path, args, types, src_addr):
        if not (len(args) >= 2 and ray.types_are_all_strings(types)):
            self._unknown_message(path, types, src_addr)
            return

    @ray_method('/ray/client/get_proxy_properties', 's')
    def rayClientGetProxyProperties(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/client/set_proxy_properties', None)
    def rayClientSetProxyProperties(self, path, args, types, src_addr):
        if not (len(args) >= 2 and ray.types_are_all_strings(types)):
            self._unknown_message(path, types, src_addr)
            return

    @ray_method('/ray/client/change_prefix', None)
    def rayClientChangePrefix(self, path, args, types, src_addr):
        # here message can be si, ss, sis, sss
        invalid = False

        if len(args) < 2:
            invalid = True

        elif args[1] in (ray.PrefixMode.CUSTOM, 'custom'):
            if len(args) < 3:
                invalid = True

        if invalid:
            self._unknown_message(path, types, src_addr)
            return False

    @ray_method('/ray/client/change_advanced_properties', 'ssisi')
    def rayClientChangeAdvancedProperties(self, path, args, types, src_addr):
        pass
    
    @ray_method('/ray/client/full_rename', 'ss')
    def rayClientFullRename(self, path, args, types, src_addr):
        pass
    
    @ray_method('/ray/client/change_id', 'ss')
    def rayClientChangeId(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/client/set_description', 'ss')
    def rayClientSetDescription(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/client/get_description', 's')
    def rayClientGetDescription(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/client/get_pid', 's')
    def ratClientGetPid(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/client/list_files', 's')
    def rayClientListFiles(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/client/list_snapshots', 's')
    def rayClientListSnapshots(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/client/open_snapshot', 'ss')
    def rayClientLoadSnapshot(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/client/is_started', 's')
    def rayClientIsStarted(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/client/set_custom_data', 'sss')
    def rayClientSetCustomData(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/client/get_custom_data', 'ss')
    def rayClientGetCustomData(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/client/set_tmp_data', 'sss')
    def rayClientSetTmpData(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/client/get_tmp_data', 'ss')
    def rayClientGetTmpData(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/client/send_signal', 'si')
    def rayClientSendSignal(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/trashed_client/restore', 's')
    def rayTrashedClientRestore(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/trashed_client/remove_definitely', 's')
    def rayTrashedClientRemoveDefinitely(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/trashed_client/remove_keep_files', 's')
    def rayTrashedClientRemoveKeepFiles(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/net_daemon/duplicate_state', 'f')
    def rayDuplicateState(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/favorites/add', 'ssis')
    def rayFavoriteAdd(self, path, args, types, src_addr):
        name, icon, int_factory, display_name = args

        for favorite in RS.favorites:
            if (favorite.name == name
                    and bool(int_factory) == favorite.factory):
                favorite.icon = icon
                favorite.display_name = display_name
                break
        else:
            RS.favorites.append(
                ray.Favorite(name, icon, bool(int_factory), display_name))

        self.send_gui('/ray/gui/favorites/added', *args)

    @ray_method('/ray/favorites/remove', 'si')
    def rayFavoriteRemove(self, path, args, types, src_addr):
        name, int_factory = args

        for favorite in RS.favorites:
            if (favorite.name == name
                    and bool(int_factory) == favorite.factory):
                RS.favorites.remove(favorite)
                break

        self.send_gui('/ray/gui/favorites/removed', *args)

    @ray_method(None, None)
    def noneMethod(self, path, args, types, src_addr):
        types_str = ''
        for t in types:
            types_str += t

        self._unknown_message(path, types, src_addr)
        return False

    def _is_operation_pending(self, src_addr, path):
        if self.session.file_copier.is_active():
            self.send(src_addr, "/error", path, ray.Err.COPY_RUNNING,
                      "ray-daemon is copying files. "
                        + "Wait copy finish or abort copy, "
                        + "and restart operation !")
            return True

        if self.session.steps_order:
            self.send(src_addr, "/error", path, ray.Err.OPERATION_PENDING,
                      "An operation pending.")
            return True

        return False

    def _set_option(self, option: int):
        if option >= 0:
            self.options |= option
        else:
            self.options &= ~abs(option)

    def send(self, *args):
        if CommandLineArgs.debug:
            sys.stderr.write(
                '\033[96mOSC::daemon sends\033[0m ' + str(args[1:]) + '\n')

        ClientCommunicating.send(self, *args)

    def send_gui(self, *args):
        for gui_addr in self.gui_list:
            self.send(gui_addr, *args)

    def set_server_status(self, server_status:int):
        self.server_status = server_status
        self.send_gui('/ray/gui/server/status', server_status)

    def send_renameable(self, renameable:bool):
        if not renameable:
            self.send_gui('/ray/gui/session/renameable', 0)
            return

        if self._nsm_locker_url:
            nsm_url = os.getenv('NSM_URL')
            if not nsm_url:
                return
            if not ray.are_same_osc_port(self._nsm_locker_url, nsm_url):
                return

        self.send_gui('/ray/gui/session/renameable', 1)

    def announce_gui(self, url, nsm_locked=False, is_net_free=True, gui_pid=0):
        gui_addr = GuiAdress(url)
        gui_addr.gui_pid = gui_pid

        self.send(gui_addr, "/ray/gui/server/announce", ray.VERSION,
                  self.server_status, self.options, self.session.root,
                  int(is_net_free))

        self.send(gui_addr, "/ray/gui/server/status", self.server_status)
        self.send(gui_addr, "/ray/gui/session/name",
                  self.session.name, self.session.path)
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

            if client.protocol == ray.Protocol.RAY_HACK:
                self.send(gui_addr,
                          '/ray/gui/client/ray_hack_update',
                          client.client_id,
                          *client.ray_hack.spread())
            elif client.protocol == ray.Protocol.RAY_NET:
                self.send(gui_addr,
                          '/ray/gui/client/ray_net_update',
                          client.client_id,
                          *client.ray_net.spread())

            self.send(gui_addr, "/ray/gui/client/status",
                      client.client_id, client.status)

            if client.is_capable_of(':optional-gui:'):
                self.send(gui_addr, '/ray/gui/client/gui_visible',
                          client.client_id, int(client.gui_visible))

            if client.is_capable_of(':dirty:'):
                self.send(gui_addr, '/ray/gui/client/dirty',
                          client.client_id, client.dirty)

        for trashed_client in self.session.trashed_clients:
            self.send(gui_addr, '/ray/gui/trash/add',
                      *trashed_client.spread())

            if trashed_client.protocol == ray.Protocol.RAY_HACK:
                self.send(gui_addr, '/ray/gui/trash/ray_hack_update',
                          trashed_client.client_id,
                          *trashed_client.ray_hack.spread())
            elif trashed_client.protocol == ray.Protocol.RAY_NET:
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
                  ray.VERSION, self.server_status, self.options,
                  self.session.root, 1)

    def send_controller_message(self, message):
        for controller in self.controller_list:
            self.send(controller.addr, '/ray/control/message', message)

    def has_gui(self)->int:
        has_gui = False

        for gui_addr in self.gui_list:
            if ray.are_on_same_machine(self.url, gui_addr.url):
                # we've got a local GUI
                return 3

            has_gui = True

        if has_gui:
            return 1

        return 0

    def get_local_gui_pid_list(self) -> str:
        pid_list = []
        for gui_addr in self.gui_list:
            if ray.are_on_same_machine(gui_addr.url, self.url):
                pid_list.append(str(gui_addr.gui_pid))
        return ':'.join(pid_list)

    def is_gui_address(self, addr: liblo.Address) -> bool:
        for gui_addr in self.gui_list:
            if ray.are_same_osc_port(gui_addr.url, addr.url):
                return True
        return False
