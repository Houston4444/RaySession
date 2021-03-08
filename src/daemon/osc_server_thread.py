import os
import sys
import random
import shutil
import subprocess
import time
import liblo

from PyQt5.QtCore import QCoreApplication
from PyQt5.QtXml import QDomDocument

import ray
from signaler import Signaler
from multi_daemon_file import MultiDaemonFile
from daemon_tools import (TemplateRoots, CommandLineArgs, Terminal, RS,
                          getCodeRoot)

instance = None
signaler = Signaler.instance()
_translate = QCoreApplication.translate

def pathIsValid(path: str)->bool:
    if path.startswith(('./', '../')):
        return False

    for forbidden in ('//', '/./', '/../'):
        if forbidden in path:
            return False

    if path.endswith(('/.', '/..')):
        return False
    return True

def ifDebug(string):
    if CommandLineArgs.debug:
        sys.stderr.write(string + '\n')

def ray_method(path, types):
    def decorated(func):
        @liblo.make_method(path, types)
        def wrapper(*args, **kwargs):
            t_thread, t_path, t_args, t_types, src_addr, rest = args
            if CommandLineArgs.debug:
                sys.stderr.write('\033[94mOSC::daemon_receives\033[0m %s, %s, %s, %s\n'
                                 % (t_path, t_types, t_args, src_addr.url))

            response = func(*args[:-1], **kwargs)
            if response != False:
                signaler.osc_recv.emit(t_path, t_args, t_types, src_addr)

            return response
        return wrapper
    return decorated

class Controller:
    addr = None
    pid = 0


class GuiAdress(liblo.Address):
    gui_pid = 0

# Osc server thread separated in many classes for confort.

# ClientCommunicating contains NSM protocol.
# OSC paths have to be never changed.
class ClientCommunicating(liblo.ServerThread):
    def __init__(self, session, osc_num=0):
        liblo.ServerThread.__init__(self, osc_num)
        self.session = session
        self.gui_list = []
        self.controller_list = []
        self.server_status = ray.ServerStatus.OFF
        self.gui_embedded = False
        self.is_nsm_locked = False
        self.not_default = False
        self.nsm_locker_url = ''
        self.net_master_daemon_addr = None
        self.net_master_daemon_url = ''
        self.net_daemon_id = random.randint(1, 999999999)
        self.list_asker_addr = None
        self.options = 0

    @ray_method('/osc/ping', '')
    def oscPing(self, path, args, types, src_addr):
        self.send(src_addr, "/reply", path)

    @ray_method('/reply', None)
    def reply(self, path, args, types, src_addr):
        if not ray.areTheyAllString(args):
            self.unknownMessage(path, types, src_addr)

        if not len(args) >= 1:
            self.unknownMessage(path, types, src_addr)
            return False

        reply_path = args[0]

        if reply_path == '/ray/server/list_sessions':
            # this reply is only used here for reply from net_daemon
            # it directly resend its infos
            # to the last addr that asked session list
            if self.list_asker_addr:
                self.send(self.list_asker_addr, path, *args)
            return False

        if reply_path == '/ray/gui/script_user_action':
            self.sendGui('/ray/gui/hide_script_user_action')
            for controller in self.controller_list:
                self.send(controller.addr, '/reply',
                          '/ray/server/script_user_action',
                          'User action dialog validate')
            return False

        if not len(args) == 2:
            # assume this is a normal client, not a net_daemon
            self.unknownMessage(path, types, src_addr)
            return False

    @ray_method('/error', 'sis')
    def error(self, path, args, types, src_addr):
        error_path, error_code, error_string = args

        if error_path == '/ray/gui/script_user_action':
            self.sendGui('/ray/gui/hide_script_user_action')

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

        if not pathIsValid(args[0]):
            self.send(src_addr, "/error", path, ray.Err.CREATE_FAILED,
                      "Invalid session name.")
            return False

    @ray_method('/nsm/server/duplicate', 's')
    def nsmServerDuplicate(self, path, args, types, src_addr):
        if self.is_nsm_locked or not self.session.path:
            self.send(src_addr, "/error", path, ray.Err.NO_SESSION_OPEN,
                      "No session to duplicate.")
            return False

        if not pathIsValid(args[0]):
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
    def nsmServerBroadcast(self, path, args, types, src_addr):
        if not args:
            return False

        #don't allow clients to broadcast NSM commands
        if args[0].startswith('/nsm/') or args[0].startswith('/ray'):
            return False

        for client in self.session.clients:
            if not client.addr:
                continue

            if not ray.areSameOscPort(client.addr.url, src_addr.url):
                self.send(client.addr, liblo.Message(*args))

            # TODO broadcast to slave daemons
            #for gui_addr in self.gui_list:
                ##also relay to attached GUI so that the broadcast can be
                ##propagated to another NSMD instance
                #if gui_addr.url != src_addr.url:
                    #self.send(gui_addr, Message(*args))

    @ray_method('/nsm/client/progress', 'f')
    def nsmClientProgress(self, path, args, types, src_addr):
        client = self.session.getClientByAddress(src_addr)
        if not client:
            return False

        client.progress = args[0]
        self.sendGui("/ray/gui/client/progress", client.client_id,
                     client.progress)

    @ray_method('/nsm/client/is_dirty', '')
    def nsmClientIs_dirty(self, path, args, types, src_addr):
        client = self.session.getClientByAddress(src_addr)
        if not client:
            return False

        Terminal.message("%s sends dirty" % client.client_id)

        client.dirty = 1
        client.last_dirty = time.time()

        self.sendGui("/ray/gui/client/dirty", client.client_id, client.dirty)

    @ray_method('/nsm/client/is_clean', '')
    def nsmClientIs_clean(self, path, args, types, src_addr):
        client = self.session.getClientByAddress(src_addr)
        if not client:
            return False

        Terminal.message("%s sends clean" % client.client_id)

        client.dirty = 0

        self.sendGui("/ray/gui/client/dirty", client.client_id, client.dirty)
        return False

    @ray_method('/nsm/client/message', 'is')
    def nsmClientMessage(self, path, args, types, src_addr):
        client = self.session.getClientByAddress(src_addr)
        if not client:
            return False

        self.sendGui("/ray/gui/client/message",
                     client.client_id, args[0], args[1])

    @ray_method('/nsm/client/gui_is_hidden', '')
    def nsmClientGui_is_hidden(self, path, args, types, src_addr):
        client = self.session.getClientByAddress(src_addr)
        if not client:
            return False

        Terminal.message("Client '%s' sends gui hidden" % client.client_id)

        client.gui_visible = False

        self.sendGui("/ray/gui/client/gui_visible", client.client_id,
                     int(client.gui_visible))

    @ray_method('/nsm/client/gui_is_shown', '')
    def nsmClientGui_is_shown(self, path, args, types, src_addr):
        client = self.session.getClientByAddress(src_addr)
        if not client:
            return False

        Terminal.message("Client '%s' sends gui shown" % client.client_id)

        client.gui_visible = True
        client.gui_has_been_visible = True

        self.sendGui("/ray/gui/client/gui_visible", client.client_id,
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
                + ray.Option.SESSION_SCRIPTS
                + ray.Option.GUI_STATES,
            type=int)

        if CommandLineArgs.no_options:
            self.options = 0

        if shutil.which('wmctrl'):
            self.options |= ray.Option.HAS_WMCTRL
        elif self.options & ray.Option.HAS_WMCTRL:
            self.options -= ray.Option.HAS_WMCTRL

        if shutil.which('git'):
            self.options |= ray.Option.HAS_GIT
        elif self.options & ray.Option.HAS_GIT:
            self.options -= ray.Option.HAS_GIT

        global instance
        instance = self

    @staticmethod
    def getInstance():
        return instance

    @ray_method('/ray/server/gui_announce', 'sisii')
    def rayGuiGui_announce(self, path, args, types, src_addr):
        (version, int_nsm_locked, net_master_daemon_url,
         gui_pid, net_daemon_id) = args

        nsm_locked = bool(int_nsm_locked)
        is_net_free = True

        if nsm_locked:
            self.net_master_daemon_url = net_master_daemon_url
            self.is_nsm_locked = True
            self.nsm_locker_url = src_addr.url

            for gui_addr in self.gui_list:
                if not ray.areSameOscPort(gui_addr.url, src_addr.url):
                    self.send(gui_addr, '/ray/gui/server/nsm_locked', 1)

            self.net_daemon_id = net_daemon_id

            multi_daemon_file = MultiDaemonFile.getInstance()

            if multi_daemon_file:
                is_net_free = multi_daemon_file.isFreeForRoot(
                    self.net_daemon_id, self.session.root)

        self.announceGui(src_addr.url, nsm_locked, is_net_free, gui_pid)

    @ray_method('/ray/server/gui_disannounce', '')
    def rayGuiGui_disannounce(self, path, args, types, src_addr):
        for addr in self.gui_list:
            if ray.areSameOscPort(addr.url, src_addr.url):
                break
        else:
            return False

        self.gui_list.remove(addr)
        self.gui_embedded = False

        if src_addr.url == self.nsm_locker_url:
            self.net_daemon_id = random.randint(1, 999999999)

            self.is_nsm_locked = False
            self.nsm_locker_url = ''
            self.sendGui('/ray/gui/server/nsm_locked', 0)

        multi_daemon_file = MultiDaemonFile.getInstance()
        if multi_daemon_file:
            multi_daemon_file.update()

    @ray_method('/ray/server/ask_for_patchbay', '')
    def rayServerGetPatchbayPort(self, path, args, types, src_addr):
        patchbay_file = '/tmp/RaySession/patchbay_infos'
        patchbay_port = 0

        if (os.path.exists(patchbay_file)
                and os.access(patchbay_file, os.R_OK)):
            file = open(patchbay_file, 'r')
            contents = file.read()
            file.close()
            for line in contents.splitlines():
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
    def rayServerControllerDisannounce(self, path, args, types, src_addr):
        for controller in self.controller_list:
            if controller.addr.url == src_addr.url:
                break
        else:
            return

        self.controller_list.remove(controller)

    @ray_method('/ray/server/set_nsm_locked', '')
    def rayServerSetNsmLocked(self, path, args, types, src_addr):
        self.is_nsm_locked = True
        self.nsm_locker_url = src_addr.url

        for gui_addr in self.gui_list:
            if gui_addr.url != src_addr.url:
                self.send(gui_addr, '/ray/gui/server/nsm_locked', 1)

    @ray_method('/ray/server/quit', '')
    def rayServerQuit(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/server/abort_copy', '')
    def rayServerAbortCopy(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/server/abort_snapshot', '')
    def rayServerAbortSnapshot(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/server/change_root', 's')
    def rayServerChangeRoot(self, path, args, types, src_addr):
        new_root = args[0]
        if not(new_root.startswith('/') and pathIsValid(new_root)):
            self.send(src_addr, '/error', path, ray.Err.CREATE_FAILED,
                      "invalid session root !")

        if self.isOperationPending(src_addr, path):
            self.send(src_addr, '/error', path, ray.Err.OPERATION_PENDING,
                      "Can't change session_root. Operation pending")
            return False

    @ray_method('/ray/server/list_path', '')
    def rayServerListPath(self, path, args, types, src_addr):
        exec_list = []
        tmp_exec_list = []
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
        if not os.path.isdir(TemplateRoots.user_sessions):
            return False

        template_list = []

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

    @ray_method('/ray/server/list_user_client_templates', '')
    def rayServerListUserClientTemplates(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/server/list_factory_client_templates', '')
    def rayServerListFactoryClientTemplates(self, path, args, types,
                                            src_addr):
        pass

    @ray_method('/ray/server/remove_client_template', 's')
    def rayServerRemoveClientTemplate(self, path, args, types, src_addr):
        template_name = args[0]

        templates_root = TemplateRoots.user_clients
        templates_file = "%s/%s" % (templates_root, 'client_templates.xml')

        if not os.path.isfile(templates_file):
            self.send(src_addr, '/error', path, ray.Err.NO_SUCH_FILE,
                      "file %s is missing !" % templates_file)
            return False

        if not os.access(templates_file, os.W_OK):
            self.send(src_addr, '/error', path, ray.Err.NO_SUCH_FILE,
                      "file %s in unwriteable !" % templates_file)
            return False

        file = open(templates_file, 'r')
        xml = QDomDocument()
        xml.setContent(file.read())
        file.close()

        content = xml.documentElement()

        if content.tagName() != "RAY-CLIENT-TEMPLATES":
            self.send(src_addr, '/error', path, ray.Err.BAD_PROJECT,
                      "file %s is not write correctly !" % templates_file)
            return False

        nodes = content.childNodes()

        for i in range(nodes.count()):
            node = nodes.at(i)
            ct = node.toElement()
            tag_name = ct.tagName()
            if tag_name != 'Client-Template':
                continue

            if template_name == ct.attribute('template-name'):
                break
        else:
            self.send(src_addr, '/error', path, ray.Err.NO_SUCH_FILE,
                      "No template \"%s\" to remove !" % template_name)
            return False

        content.removeChild(nodes.at(i))

        file = open(templates_file, 'w')
        file.write(xml.toString())
        file.close()

        template_dir = '%s/%s' % (templates_root, template_name)

        if os.path.isdir(template_dir):
            subprocess.run(['rm', '-R', template_dir])

        self.send(src_addr, '/reply', path,
                  "template \"%s\" removed." % template_name)

    @ray_method('/ray/server/list_sessions', '')
    def rayServerListSessions(self, path, args, types, src_addr):
        self.list_asker_addr = src_addr

    @ray_method('/ray/server/list_sessions', 'i')
    def rayServerListSessionsWithNet(self, path, args, types, src_addr):
        self.list_asker_addr = src_addr

    @ray_method('/ray/server/new_session', None)
    def rayServerNewSession(self, path, args, types, src_addr):
        if not ray.areTheyAllString(args):
            self.unknownMessage(path, types, src_addr)
            return False

        if self.is_nsm_locked:
            return False

        if not pathIsValid(args[0]):
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

        if not pathIsValid(session_name):
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
        if not pathIsValid(session_name):
            self.send(src_addr, "/error", path, ray.Err.CREATE_FAILED,
                    "Invalid template name.")
            return False

        if '/' in template_name:
            self.send(src_addr, "/error", path, ray.Err.CREATE_FAILED,
                      "Invalid session name.")
            return False

    @ray_method('/ray/server/script_info', 's')
    def rayServerScriptInfo(self, path, args, types, src_addr):
        self.sendGui('/ray/gui/script_info', args[0])
        self.send(src_addr, "/reply", path, "Info sent")

    @ray_method('/ray/server/hide_script_info', '')
    def rayServerHideScriptInfo(self, path, args, types, src_addr):
        self.sendGui('/ray/gui/hide_script_info')
        self.send(src_addr, "/reply", path, "Info hidden")

    @ray_method('/ray/server/script_user_action', 's')
    def rayServerScriptUserAction(self, path, args, types, src_addr):
        if not self.gui_list:
            self.send(src_addr, '/error', path, ray.Err.LAUNCH_FAILED,
                      "This server has no attached GUI")
            return
        self.sendGui('/ray/gui/script_user_action', args[0])

    # set option from GUI
    @ray_method('/ray/server/set_option', 'i')
    def rayServerSetOption(self, path, args, types, src_addr):
        option = args[0]
        self.setOption(option)

        for gui_addr in self.gui_list:
            if not ray.areSameOscPort(gui_addr.url, src_addr.url):
                self.send(gui_addr, '/ray/gui/server/options', self.options)

    # set options from ray_control
    @ray_method('/ray/server/set_options', None)
    def rayServerSetOptions(self, path, args, types, src_addr):
        if not ray.areTheyAllString(args):
            self.unknownMessage(path, types, src_addr)
            return False

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
                            "wmctrl is not present. Impossible to activate 'desktops_memory' option")
                        continue
                    if (option == ray.Option.SNAPSHOTS
                            and not self.options & ray.Option.HAS_GIT):
                        self.send(src_addr, '/minor_error', path,
                            "git is not present. Impossible to activate 'snapshots' option")
                        continue

                if not option_value:
                    option = -option
                self.setOption(option)

        for gui_addr in self.gui_list:
            if not ray.areSameOscPort(gui_addr.url, src_addr.url):
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

    @ray_method('/ray/server/exotic_action', 's')
    def rayServerExoticAction(self, path, args, types, src_addr):
        action = args[0]
        autostart_dir = "%s/.config/autostart" % os.getenv('HOME')
        desk_file = "ray-jack_checker.desktop"

        if action == 'set_jack_checker_autostart':
            if not os.path.exists(autostart_dir):
                os.makedirs(autostart_dir)

            src_full_file = "%s/data/share/applications/%s" % (getCodeRoot(),
                                                               desk_file)
            dest_full_path = "%s/%s" % (autostart_dir, desk_file)

            shutil.copyfile(src_full_file, dest_full_path)

        elif action == 'unset_jack_checker_autostart':
            os.remove("%s/%s" % (autostart_dir, desk_file))

    @ray_method('/ray/server/patchbay/save_coordinates', 'isii')
    def rayServerPatchbaySaveCoordinates(self, path, args, types, src_addr):
        pass
    
    @ray_method('/ray/server/patchbay/save_portgroup', 'siss')
    def rayServerPatchbaySavePortGroup(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/session/save', '')
    def raySessionSave(self, path, args, types, src_addr):
        if not self.session.path:
            self.send(src_addr, "/error", path, ray.Err.NO_SESSION_OPEN,
                      "No session to save.")
            return False

    @ray_method('/ray/session/run_step', None)
    def raySessionProcessStep(self, path, args, types, src_addr):
        if not ray.areTheyAllString(args):
            self.unknownMessage(path, types, src_addr)
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

    @ray_method('/ray/session/take_snapshot', 'si')
    def raySessionTakeSnapshot(self, path, args, types, src_addr):
        pass

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

        if not pathIsValid(args[0]):
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
        if self.nsm_locker_url:
            NSM_URL = os.getenv('NSM_URL')
            if not NSM_URL:
                return False

            if not ray.areSameOscPort(self.nsm_locker_url, NSM_URL):
                return False

        if '/' in new_session_name:
            self.send(src_addr, "/error", path, ray.Err.CREATE_FAILED,
                      "Invalid session name.")
            return False

        if self.isOperationPending(src_addr, path):
            return False

        if not self.session.path:
            self.send(src_addr, "/error", path, ray.Err.NO_SESSION_OPEN,
                      "No session to rename.")
            return False

    @ray_method('/ray/session/set_notes', 's')
    def raySessionSetNotes(self, path, args, types, src_addr):
        self.session.notes = args[0]

        for gui_addr in self.gui_list:
            if not ray.areSameOscPort(gui_addr.url, src_addr.url):
                self.send(gui_addr, '/ray/gui/session/notes',
                          self.session.notes)

    @ray_method('/ray/session/get_notes', '')
    def raySessionGetNotes(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/session/add_executable', 'siiiss')
    def raySessionAddExecutableAdvanced(self, path, args, types, src_addr):
        executable_path, auto_start, protocol, \
            prefix_mode, prefix_pattern, client_id = args

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
        if not (args and ray.areTheyAllString(args)):
            self.unknownMessage(path, types, src_addr)
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

    @ray_method('/ray/session/add_client_template', 'is')
    def rayServerAddClientTemplate(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/session/add_factory_client_template', None)
    def raySessionAddFactoryClientTemplate(self, path, args, types, src_addr):
        if not (args and ray.areTheyAllString(args)):
            self.unknownMessage(path, types, src_addr)
            return False

    @ray_method('/ray/session/add_user_client_template', None)
    def raySessionAddUserClientTemplate(self, path, args, types, src_addr):
        if not (args and ray.areTheyAllString(args)):
            self.unknownMessage(path, types, src_addr)
            return False

    @ray_method('/ray/session/reorder_clients', None)
    def rayServerReorderClients(self, path, args, types, src_addr):
        if not (args and ray.areTheyAllString(args)):
            self.unknownMessage(path, types, src_addr)
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

    @ray_method('/ray/session/clear_clients', None)
    def raySessionStopClients(self, path, args, types, src_addr):
        if not ray.areTheyAllString(args):
            self.unknownMessage(path, types, src_addr)
            return False

    @ray_method('/ray/session/show_notes', '')
    def raySessionShowNotes(self, path, args, types, src_addr):
        if not self.session.path:
            self.send(src_addr, '/error', path, ray.Err.NO_SESSION_OPEN,
                      "No session to show notes")
            return False

        self.session.notes_shown = True
        self.sendGui('/ray/gui/session/notes_shown')
        self.send(src_addr, '/reply', path, 'notes shown')

    @ray_method('/ray/session/hide_notes', '')
    def raySessionHideNotes(self, path, args, types, src_addr):
        if not self.session.path:
            self.send(src_addr, '/error', path, ray.Err.NO_SESSION_OPEN,
                      "No session to hide notes")
            return False

        self.session.notes_shown = False
        self.sendGui('/ray/gui/session/notes_hidden')
        self.send(src_addr, '/reply', path, 'notes hidden')

    @ray_method('/ray/session/list_clients', None)
    def raySessionListClients(self, path, args, types, src_addr):
        if not ray.areTheyAllString(args):
            self.unknownMessage(path, types, src_addr)
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
        if not (len(args) >= 2 and ray.areTheyAllString(args)):
            self.unknownMessage(path, types, src_addr)
            return

    @ray_method('/ray/client/get_proxy_properties', 's')
    def rayClientGetProxyProperties(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/client/set_proxy_properties', None)
    def rayClientSetProxyProperties(self, path, args, types, src_addr):
        if not (len(args) >= 2 and ray.areTheyAllString(args)):
            self.unknownMessage(path, types, src_addr)
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
            self.unknownMessage(path, types, src_addr)
            return False

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

    @ray_method('/ray/net_daemon/duplicate_state', 'f')
    def rayDuplicateState(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/favorites/add', 'ssi')
    def rayFavoriteAdd(self, path, args, types, src_addr):
        name, icon, int_factory = args

        for favorite in RS.favorites:
            if (favorite.name == name
                    and bool(int_factory) == favorite.factory):
                favorite.icon = icon
                break
        else:
            RS.favorites.append(ray.Favorite(name, icon, bool(int_factory)))

        self.sendGui('/ray/gui/favorites/added', *args)

    @ray_method('/ray/favorites/remove', 'si')
    def rayFavoriteRemove(self, path, args, types, src_addr):
        name, int_factory = args

        for favorite in RS.favorites:
            if (favorite.name == name
                    and bool(int_factory) == favorite.factory):
                RS.favorites.remove(favorite)
                break

        self.sendGui('/ray/gui/favorites/removed', *args)

    @ray_method(None, None)
    def noneMethod(self, path, args, types, src_addr):
        types_str = ''
        for t in types:
            types_str += t

        self.unknownMessage(path, types, src_addr)
        return False

    def unknownMessage(self, path, types, src_addr):
        self.send(src_addr, '/minor_error', path, ray.Err.UNKNOWN_MESSAGE,
                  "unknown osc message: %s %s" % (path, types))

    def isOperationPending(self, src_addr, path):
        if self.session.file_copier.isActive():
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

    def send(self, *args):
        ifDebug('\033[96mOSC::daemon sends\033[0m '
                + str(args[1:]))

        ClientCommunicating.send(self, *args)

    def sendGui(self, *args):
        for gui_addr in self.gui_list:
            self.send(gui_addr, *args)

    def sendClientStatusToGui(self, client):
        self.sendGui("/ray/gui/client/status",
                     client.client_id, client.status)

    def setServerStatus(self, server_status):
        self.server_status = server_status
        self.sendGui('/ray/gui/server/status', server_status)

    def getServerStatus(self):
        return self.server_status

    def informCopytoGui(self, copy_state):
        self.sendGui('/ray/gui/server/copying', int(copy_state))


    def sendRenameable(self, renameable):
        if not renameable:
            self.sendGui('/ray/gui/session/renameable', 0)
            return

        if self.nsm_locker_url:
            NSM_URL = os.getenv('NSM_URL')
            if not NSM_URL:
                return
            if not ray.areSameOscPort(self.nsm_locker_url, NSM_URL):
                return

        self.sendGui('/ray/gui/session/renameable', 1)

    def announceGui(self, url, nsm_locked=False, is_net_free=True, gui_pid=0):
        gui_addr = GuiAdress(url)
        gui_addr.gui_pid = gui_pid

        self.send(gui_addr, "/ray/gui/server/announce", ray.VERSION,
                  self.server_status, self.options, self.session.root,
                  int(is_net_free))

        self.send(gui_addr, "/ray/gui/server/status", self.server_status)
        self.send(gui_addr, "/ray/gui/session/name",
                  self.session.name, self.session.path)
        self.send(gui_addr, '/ray/gui/session/notes', self.session.notes)

        self.session.canvas_saver.send_all_group_positions(gui_addr)
        
        for favorite in RS.favorites:
            self.send(gui_addr, "/ray/gui/favorites/added",
                      favorite.name, favorite.icon, int(favorite.factory))

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

            if client.isCapableOf(':optional-gui:'):
                #self.send(gui_addr, '/ray/gui/client/has_optional_gui',
                          #client.client_id)

                self.send(gui_addr, '/ray/gui/client/gui_visible',
                          client.client_id, int(client.gui_visible))

            if client.isCapableOf(':dirty:'):
                self.send(gui_addr, '/ray/gui/is_dirty', client.dirty)

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

        self.send(gui_addr, '/ray/gui/server/message',
                  _translate('daemon', "daemon runs at %s") % self.url)

        self.gui_list.append(gui_addr)

        multi_daemon_file = MultiDaemonFile.getInstance()
        if multi_daemon_file:
            multi_daemon_file.update()

        Terminal.message("GUI connected at %s" % gui_addr.url)

    def announceController(self, control_address):
        controller = Controller()
        controller.addr = control_address
        self.controller_list.append(controller)
        self.send(control_address, "/ray/control/server/announce",
                  ray.VERSION, self.server_status, self.options,
                  self.session.root, 1)

    def sendControllerMessage(self, message):
        for controller in self.controller_list:
            self.send(controller.addr, '/ray/control/message', message)

    def getControllerPid(self, addr):
        for controller in self.controller_list:
            if controller.addr == addr:
                return controller.pid

        return 0

    def setAsNotDefault(self):
        self.not_default = True

    def hasGui(self)->int:
        has_gui = False

        for gui_addr in self.gui_list:
            if ray.areOnSameMachine(self.url, gui_addr.url):
                # we've got a local GUI
                return 3

            has_gui = True

        if has_gui:
            return 1

        return 0

    def getLocalGuiPidList(self)->str:
        pid_list = []
        for gui_addr in self.gui_list:
            if ray.areOnSameMachine(gui_addr.url, self.url):
                pid_list.append(str(gui_addr.gui_pid))
        return ':'.join(pid_list)

    def isGuiAddress(self, addr):
        for gui_addr in self.gui_list:
            if ray.areSameOscPort(gui_addr.url, addr.url):
                return True
        return False

    def setOption(self, option: int):
        if option > 0:
            self.options |= option
        else:
            self.options &= ~option
