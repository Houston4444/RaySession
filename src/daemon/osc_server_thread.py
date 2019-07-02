import os
import sys
import random
import shutil
import subprocess
import time
from liblo import ServerThread, Address, Message
import liblo
#from liblo import ServerThread, Address, make_method, Message
from PyQt5.QtXml import QDomDocument

#from shared import *
import ray
from signaler import Signaler
from multi_daemon_file import MultiDaemonFile
from daemon_tools import TemplateRoots, CommandLineArgs, Terminal, RS

instance = None
signaler = Signaler.instance()


def pathIsValid(path):
    return not bool('../' in path)

def ifDebug(string):
    if CommandLineArgs.debug:
        sys.stderr.write(string + '\n')

def make_method(path, types):
    def decorated(func):
        @liblo.make_method(path, types)
        def wrapper(*args, **kwargs):
            ifDebug('serverOSC::ray-daemon_receives %s, %s' 
                    % (path, str(args)))
            response = func(*args[:-1], **kwargs)
            if response != False:
                t_thread, t_path, t_args, t_types, src_addr, rest = args
                signaler.osc_recv.emit(t_path, t_args, t_types, src_addr)
            
            return response
        return wrapper
    return decorated

#Osc server thread separated in many classes for confort.

#ClientCommunicating contains NSM protocol.
#OSC paths have to be never changed.
class ClientCommunicating(ServerThread):
    def __init__(self, session, osc_num=0):
        ServerThread.__init__(self, osc_num)
        self.session = session
        self.gui_list = []
        self.server_status  = ray.ServerStatus.OFF
        self.is_nsm_locked  = False
        self.nsm_locker_url = ''
        self.net_master_daemon_addr = None
        self.net_master_daemon_url = ''
        self.net_daemon_id = random.randint(1, 999999999)
        
    @make_method('/nsm/server/announce', 'sssiii')
    def nsmServerAnnounce(self, path, args, types, src_addr):
        if not self.session.path:
            self.send(src_addr, "/error", path, ray.Err.NO_SESSION_OPEN, 
                      "Sorry, but there's no session open "
                      + "for this application to join.")
            return False
        
    @make_method('/reply', 'ss')
    def reply(self, path, args, types, src_addr):
        signaler.server_reply.emit(path, args, src_addr)
            
    @make_method('/error', 'sis')
    def error(self, path, args, types, src_addr):
        client = self.session.getClientByAddress(src_addr)
        if not client:
            Terminal.warning("Error from unknown client")
            return False
        
        err_code = args[1]
        message  = args[2]
        client.setReply(err_code, message)
        
        Terminal.message("Client \"%s\" replied with error: %s (%i)"
                         % ( client.name, message, err_code ))
        
        client.pending_command = ray.Command.NONE
        client.setStatus(ray.ClientStatus.ERROR)
    
    @make_method('/nsm/client/progress', 'f')
    def nsmClientProgress(self, path, args, types, src_addr):
        client = self.session.getClientByAddress(src_addr)
        if not client:
            return False
        
        client.progress = args[0]
        self.sendGui("/ray/client/progress", client.client_id, 
                     client.progress)
    
    @make_method('/nsm/client/is_dirty', '')
    def nsmClientIs_dirty(self, path, args, types, src_addr):
        client = self.session.getClientByAddress(src_addr)
        if not client:
            return False
        
        Terminal.message("%s sends dirty" % client.client_id)
        
        client.dirty = 1
        client.last_dirty = time.time()
        
        self.sendGui("/ray/client/dirty", client.client_id, client.dirty)

    @make_method('/nsm/client/is_clean', '')
    def nsmClientIs_clean(self, path, args, types, src_addr):
        client = self.session.getClientByAddress(src_addr)
        if not client:
            return False
        
        Terminal.message("%s sends clean" % client.client_id)
        
        client.dirty = 0
        
        self.sendGui("/ray/client/dirty", client.client_id, client.dirty)
        
        if self.option_save_from_client:
            if (client.pending_command != ray.Command.SAVE
                and client.last_dirty 
                and time.time() - client.last_dirty > 0.20
                and time.time() - client.last_save_time > 1.00):
                    signaler.server_save_from_client.emit(path, args,
                                                          src_addr,
                                                          client.client_id)
    
    @make_method('/nsm/client/message', 'is')
    def nsmClientMessage(self, path, args, types, src_addr):
        client = self.session.getClientByAddress(src_addr)
        if not client:
            return False
        
        self.sendGui("/ray/client/message", client.client_id, args[0], args[1])

    @make_method('/nsm/client/gui_is_hidden', '')
    def nsmClientGui_is_hidden(self, path, args, types, src_addr):
        client = self.session.getClientByAddress(src_addr)
        if not client:
            return False
        
        Terminal.message("Client '%s' sends gui hidden" % client.client_id)
        
        client.gui_visible = False
        
        self.sendGui("/ray/client/gui_visible", client.client_id,
                     int(client.gui_visible))

    @make_method('/nsm/client/gui_is_shown', '')
    def nsmClientGui_is_shown(self, path, args, types, src_addr):
        client = self.session.getClientByAddress(src_addr)
        if not client:
            return False
        
        Terminal.message("Client '%s' sends gui shown" % client.client_id)
        
        client.gui_visible = True
        
        self.sendGui("/ray/client/gui_visible", client.client_id,
                     int(client.gui_visible))

    @make_method('/nsm/client/label', 's')
    def nsmClientLabel(self, path, args, types, src_addr):
        pass
      
    @make_method('/nsm/server/broadcast', None)
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
                self.send(client.addr, Message(*args))
                
            #for gui_addr in self.gui_list:
                ##also relay to attached GUI so that the broadcast can be
                ##propagated to another NSMD instance
                #if gui_addr.url != src_addr.url:
                    #self.send(gui_addr, Message(*args))
      
    @make_method('/nsm/client/network_properties', 'ss')
    def nsmClientNetworkProperties(self, path, args, types, src_addr):
        pass

class OscServerThread(ClientCommunicating):
    def __init__(self, session, osc_num=0):
        ClientCommunicating.__init__(self, session, osc_num)
        self.list_asker_addr = None
        
        self.option_save_from_client = RS.settings.value(
            'daemon/save_all_from_saved_client', True, type=bool)
        self.option_bookmark_session = RS.settings.value(
            'daemon/bookmark_session_folder', True, type=bool)
        self.option_desktops_memory  = RS.settings.value(
            'daemon/desktops_memory', False, type=bool)
        self.option_snapshots        = RS.settings.value(
            'daemon/snapshots', True, type=bool)
        
        self.option_has_wmctrl = bool(shutil.which('wmctrl'))
        if not self.option_has_wmctrl:
            self.option_desktops_memory = False
        
        self.option_has_git = bool(shutil.which('git'))
        if not self.option_has_git:
            self.option_snapshots = False
        
        global instance
        instance = self
        
    @staticmethod
    def getInstance():
        return instance
    
    @make_method('/osc/ping', '')
    def oscPing(self, path, args, types, src_addr):
        self.send(src_addr, "/reply", path)
    
    @make_method('/ray/server/gui_announce', 'sisii')
    def rayGuiGui_announce(self, path, args, types, src_addr):
        version    = args[0]
        nsm_locked = bool(args[1])
        is_net_free = True
        
        if nsm_locked:
            self.net_master_daemon_url = args[2]
            self.is_nsm_locked = True
            self.nsm_locker_url = src_addr.url
            
            for gui_addr in self.gui_list:
                if gui_addr.url != src_addr.url:
                    self.send(gui_addr, '/ray/gui/daemon_nsm_locked', 1)
                    
            self.net_daemon_id = args[4]
            
            multi_daemon_file = MultiDaemonFile.getInstance()
            
            if multi_daemon_file:
                is_net_free = multi_daemon_file.isFreeForRoot(
                    self.net_daemon_id, self.session.root)
        
        #not needed here, in fact args[3] isn't used, that was for that:
        self.option_save_from_client = \
            bool(args[3] & ray.Option.SAVE_FROM_CLIENT)
        self.option_bookmark_session = \
            bool(args[3] & ray.Option.BOOKMARK_SESSION)
            
        self.announceGui(src_addr.url, nsm_locked, is_net_free)

    @make_method('/ray/server/gui_disannounce', '')
    def rayGuiGui_disannounce(self, path, args, types, src_addr):
        for addr in self.gui_list:
            if addr.url == src_addr.url:
                break
        else:
            return False
        
        self.gui_list.remove(addr)
        
        if src_addr.url == self.nsm_locker_url:
            self.net_daemon_id  = random.randint(1, 999999999)
            
            multi_daemon_file = MultiDaemonFile.getInstance()
            if multi_daemon_file:
                multi_daemon_file.update()
            
            self.is_nsm_locked  = False
            self.nsm_locker_url = ''
            self.sendGui('/ray/gui/daemon_nsm_locked', 0)
    
    @make_method('/ray/server/set_nsm_locked', '')
    def rayServerSetNsmLocked(self, path, args, types, src_addr):
        self.is_nsm_locked = True
        self.nsm_locker_url = src_addr.url
        
        for gui_addr in self.gui_list:
            if gui_addr.url != src_addr.url:
                self.send(gui_addr, '/ray/gui/daemon_nsm_locked', 1)
    
    @make_method('/ray/server/quit', '')
    def nsmServerQuit(self, path, args, types, src_addr):
        sys.exit(0)
    
    @make_method('/ray/server/abort_copy', '')
    def rayServerAbortCopy(self, path, args, types, src_addr):
        pass
    
    @make_method('/ray/server/change_root', 's')
    def rayServerChangeRoot(self, path, args, types, src_addr):
        if self.isOperationPending(src_addr, path):
            self.send(src_addr, '/error', 
                      "Can't change session_root. Operation pending")
            return False
        
        session_root = args[0]
        
        self.session.setRoot(session_root)
        self.sendGui('/ray/server/root_changed', session_root)
    
    @make_method('/ray/server/list_path', '')
    def rayServerListPath(self, path, args, types, src_addr):
        exec_list = []
        tmp_exec_list = []
        
        pathlist = os.getenv('PATH').split(':')
        for path in pathlist:
            if os.path.isdir(path):
                listexe = os.listdir(path)
                for exe in listexe:
                    fullexe = path + '/' + exe
                    
                    if (os.path.isfile(fullexe)
                            and os.access(fullexe, os.X_OK)
                            and not exe in exec_list):
                        exec_list.append(exe)
                        tmp_exec_list.append(exe)
                        
                        if len(tmp_exec_list) == 100:
                            self.send(src_addr, '/reply_path', *tmp_exec_list)
                            tmp_exec_list.clear()
        
        if tmp_exec_list:
            self.send(src_addr, '/reply_path', *tmp_exec_list)
            
    @make_method('/ray/server/list_session_templates', '')
    def rayServerListSessionTemplates(self, path, args, types, src_addr):
        if not os.path.isdir(TemplateRoots.user_sessions):
            return False
        
        template_list = []
        
        all_files = os.listdir(TemplateRoots.user_sessions)
        for file in all_files:
            if os.path.isdir("%s/%s" % (TemplateRoots.user_sessions, file)):
                template_list.append(file)
                
                if len(template_list) == 100:
                    self.send(src_addr, '/reply_session_templates',
                              *template_list)
                    template_list.clear()
                    
        if template_list:
            self.send(src_addr, '/reply_session_templates', *template_list)
    
    @make_method('/ray/server/list_user_client_templates', '')
    def rayServerListUserClientTemplates(self, path, args, types, src_addr):
        self.listClientTemplates(src_addr, False)
    
    @make_method('/ray/server/list_factory_client_templates', '')
    def rayServerListFactoryClientTemplates(self, path, args, types,
                                            src_addr):
        self.listClientTemplates(src_addr, True)
        
    @make_method('/ray/server/list_sessions', 'i')
    def nsmServerListAll(self, path, args, types, src_addr):
        self.list_asker_addr = src_addr
    
    @make_method('/ray/server/new_session', None)
    def nsmServerNew(self, path, args, types, src_addr):
        if not ray.areTheyAllString(args):
            return False
        
        if self.is_nsm_locked:
            return False
        
        if not pathIsValid(args[0]):
            self.send(src_addr, "/error", path, ray.Err.CREATE_FAILED,
                      "Invalid session name.")
            return False
    
    @make_method('/ray/server/open_session', None)
    def nsmServerOpen(self, path, args, types, src_addr):
        if not ray.areTheyAllString(args):
            return False
    
    @make_method('/reply_sessions_list', None)
    def replySessionsList(self, path, args, types, src_addr):
        # this reply is only used here for reply from net_daemon
        # it directly resend its infos to the last gui that asked session list
        if self.list_asker_addr:
            self.send(self.list_asker_addr, '/reply_sessions_list', *args)
    
    
    @make_method('/ray/session/save', '')
    def nsmServerSave(self, path, args, types, src_addr):
        if not self.session.path:
            self.send(src_addr, "/error", path, ray.Err.NO_SESSION_OPEN,
                      "No session to save.")
            return False
    
    @make_method('/ray/session/save_as_template', None)
    def nsmServerSaveSessionTemplate(self, path, args, types, src_addr):
        if not len(args) in (1, 3):
            return False
        
        if not ray.areTheyAllString(args):
            return False
        
        session_name = args[0]
        if not pathIsValid(session_name):
            self.send(src_addr, "/error", path, ray.Err.CREATE_FAILED,
                      "Invalid session name.")
            return False
        
        if len(args) == 3:
            #save as template an not loaded session
            session_name, template_name, sess_root = args
        
            if not pathIsValid(template_name):
                self.send(src_addr, "/error", path, ray.Err.CREATE_FAILED,
                        "Invalid session name.")
                return False
        
            if not (sess_root == self.session.root
                    and session_name == self.session.name):
                signaler.dummy_load_and_template.emit(*args)
                return False
            
                #net = True
                #signaler.server_save_session_template.emit(path, [template_name],
                                                        #src_addr, net)
                #return False
        
        
    
    @make_method('/ray/session/take_snapshot', 's')
    def raySessionTakeSnapshot(self, path, args, types, src_addr):
        pass
    
    @make_method('/ray/session/close', '')
    def nsmServerClose(self, path, args, types, src_addr):
        if not self.session.path:
            self.send(src_addr, "/error", path, ray.Err.NO_SESSION_OPEN,
                      "No session to close.")
            return False
    
    @make_method('/ray/session/abort', '')
    def nsmServerAbort(self, path, args, types, src_addr):
        if self.server_status == ray.ServerStatus.PRECOPY:
            signaler.copy_aborted.emit()
            return False
        
        if not self.session.path:
            self.send(src_addr, "/error", path, ray.Err.NO_SESSION_OPEN,
                      "No session to abort." )
            return False
    
    @make_method('/ray/session/duplicate', 's')
    def nsmServerDuplicate(self, path, args, types, src_addr):
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
        
    @make_method('/ray/session/duplicate_only', 'sss')
    def nsmServerDuplicateOnly(self, path, args, types, src_addr):
        self.send(src_addr, '/ray/net_daemon/duplicate_state', 0)
    
    @make_method('/ray/session/open_snapshot', 's')
    def raySessionOpenSnapshot(self, path, args, types, src_addr):
        pass
    
    @make_method('/ray/session/rename', 's')
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
      
    @make_method('/ray/session/add_executable', 's')
    def nsmServerAdd(self, path, args, types, src_addr):
        if not self.session.path:
            self.send(src_addr, "/error", path, ray.Err.NO_SESSION_OPEN,
                      "Cannot add to session because no session is loaded.")
            return False
    
    @make_method('/ray/session/add_proxy', 's')
    def rayServerAddProxy(self, path, args, types, src_addr):
        if not self.session.path:
            self.send(src_addr, "/error", path, ray.Err.NO_SESSION_OPEN,
                      "Cannot add to session because no session is loaded.")
            return False

    @make_method('/ray/session/add_client_template', 'is')
    def rayServerAddClientTemplate(self, path, args, types, src_addr):
        if not self.session.path:
            self.send(src_addr, "/error", path, ray.Err.NO_SESSION_OPEN,
                      "Cannot add to session because no session is loaded.")
            return False
    
    @make_method('/ray/session/reorder_clients', None)
    def rayServerReorderClients(self, path, args, types, src_addr):
        if not ray.areTheyAllString(args):
            return False
    
    @make_method('/ray/session/list_snapshots', '')
    def rayServerListSnapshots(self, path, args, types, src_addr):
        pass
    
    @make_method('/ray/session/set_auto_snapshot', 'i')
    def rayServerSetAutoSnapshot(self, path, args, types, src_addr):
        pass
    
    @make_method('/ray/session/ask_auto_snapshot', '')
    def rayServerHasAutoSnapshot(self, path, args, types, src_addr):
        pass
    
    @make_method('/ray/session/open_folder', '')
    def rayServerOpenFolder(self, path, args, types, src_addr):
        if self.session.path:
            subprocess.Popen(['xdg-open',  self.session.path])
    
    @make_method('/ray/client/stop', 's')
    def rayGuiClientStop(self, path, args, types, src_addr):
        pass
    
    @make_method('/ray/client/kill', 's')
    def rayGuiClientKill(self, path, args, types, src_addr):
        pass           
    
    @make_method('/ray/client/trash', 's')
    def rayGuiClientRemove(self, path, args, types, src_addr):
        pass
    
    @make_method('/ray/client/resume', 's')
    def rayGuiClientResume(self, path, args, types, src_addr):
        pass
                
    @make_method('/ray/client/save', 's')
    def rayGuiClientSave(self, path, args, types, src_addr):
        pass

    @make_method('/ray/client/save_as_template', 'ss')
    def rayGuiClientSaveAsTemplate(self, path, args, types, src_addr):
        pass
    
    @make_method('/ray/client/show_optional_gui', 's')
    def nsmGuiClientShow_optional_gui(self, path, args, types, src_addr):
        client = self.session.getClient(args[0])
        
        if client and client.active:
            self.send(client.addr, "/nsm/client/show_optional_gui")

    @make_method('/ray/client/hide_optional_gui', 's')
    def nsmGuiClientHide_optional_gui(self, path, args, types, src_addr):
        client = self.session.getClient(args[0])
        
        if client and client.active:
            self.send(client.addr, "/nsm/client/hide_optional_gui")

    @make_method('/ray/client/update_properties', 'ssssissssis')
    def rayGuiClientUpdateProperties(self, path, args, types, src_addr):
        pass
    
    @make_method('/ray/client/list_snapshots', 's')
    def rayClientListSnapshots(self, path, args, types, src_addr):
        pass
    
    @make_method('/ray/client/load_snapshot', 'ss')
    def rayClientLoadSnapshot(self, path, args, types, src_addr):
        pass
    
    @make_method('/ray/net_daemon/duplicate_state', 'f')
    def rayDuplicateState(self, path, args, types, src_addr):
        pass
    
    @make_method('/ray/trash/restore', 's')
    def rayGuiTrashRestore(self, path, args, types, src_addr):
        if not self.session.path:
            self.send(src_addr, "/error", path, ray.Err.NO_SESSION_OPEN,
                      "Cannot add to session because no session is loaded.")
            return False
        
    @make_method('/ray/trash/remove_definitely', 's')
    def rayGuiTrashRemoveDefinitely(self, path, args, types, src_addr):
        pass
    
    @make_method('/ray/option/save_from_client', 'i')
    def rayOptionSaveFromClient(self, path, args, types, src_addr):
        self.option_save_from_client = bool(args[0])
    
    @make_method('/ray/option/bookmark_session_folder', 'i')
    def rayOptionBookmarkSessionFolder(self, path, args, types, src_addr):
        self.option_bookmark_session = bool(args[0])
    
    @make_method('/ray/option/desktops_memory', 'i')
    def rayOptionDesktopsMemory(self, path, args, types, src_addr):
        self.option_desktops_memory = bool(args[0])
    
    @make_method('/ray/option/snapshots', 'i')
    def rayOptionSnapshots(self, path, args, types, src_addr):
        self.option_snapshots = bool(args[0])
    
    def isOperationPending(self, src_addr, path):
        if self.session.file_copier.isActive():
            self.send(src_addr, "/error", path, ray.Err.COPY_RUNNING, 
                      "ray-daemon is copying files. "
                        + "Wait copy finish or abort copy, "
                        + "and restart operation !")
            return True
        
        if self.session.process_order:
            self.send(src_addr, "/error", path, ray.Err.OPERATION_PENDING,
                      "An operation pending.")
            return True
        
        return False
        
    def send(self, *args):
        ifDebug('serverOSC::ray-daemon sends: '
                + str(args[1:]))
        
        ClientCommunicating.send(self, *args)
        
    def sendGui(self, *args):
        for gui_addr in self.gui_list:
            self.send(gui_addr, *args)
    
    def sendClientStatusToGui(self, client):
        self.sendGui("/ray/client/status", client.client_id, client.status)
            
    def setServerStatus(self, server_status):
        self.server_status = server_status
        self.sendGui('/ray/server_status', server_status) 
    
    def informCopytoGui(self, copy_state):
        self.sendGui('/ray/gui/server/copying', int(copy_state))
    
    def listClientTemplates(self, src_addr, factory=False):
        template_list = []
        tmp_template_list = []
        
        templates_root    = TemplateRoots.user_clients
        response_osc_path = '/reply_user_client_templates'
        
        if factory:
            templates_root    = TemplateRoots.factory_clients
            response_osc_path = '/reply_factory_client_templates'
        
        
        templates_file = "%s/%s" % (templates_root, 'client_templates.xml')
        
        if not os.path.isfile(templates_file):
            return
        
        if not os.access(templates_file, os.R_OK):
            return
        
        file = open(templates_file)
        xml = QDomDocument()
        xml.setContent(file.read())
        file.close()
        
        content = xml.documentElement()
        
        if content.tagName() != "RAY-CLIENT-TEMPLATES":
            return
        
        nodes = content.childNodes()
        
        for i in range(nodes.count()):
            node = nodes.at(i)
            ct = node.toElement()
            tag_name = ct.tagName()
            if tag_name != 'Client-Template':
                continue
            
            template_name = ct.attribute('template-name')
            
            if not template_name or template_name in template_list:
                continue
            
            executable = ct.attribute('executable') 
            
            if not executable:
                continue
            
            try_exec_line = ct.attribute('try-exec')
            
            try_exec_list = []
            if try_exec_line:
                try_exec_list = ct.attribute('try-exec').split(';')
                
            try_exec_list.append(executable)
            try_exec_ok = True
            
            for try_exec in try_exec_list:
                path = shutil.which(try_exec)
                if not path:
                    try_exec_ok = False
                    break
            
            if not try_exec_ok:
                continue
            
            template_list.append("%s/%s" % (template_name,
                                            ct.attribute('icon')))
            tmp_template_list.append("%s/%s" % (template_name,
                                                ct.attribute('icon')))
            
            if len(tmp_template_list) == 100:
                self.send(src_addr, response_osc_path, *tmp_template_list)
                template_list.clear()
        
        if tmp_template_list:
            self.send(src_addr, response_osc_path, *tmp_template_list)
    
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
    
    def announceGui(self, url, nsm_locked=False, is_net_free=True):
        gui_addr = Address(url)
        
        options = (
            ray.Option.NSM_LOCKED * self.is_nsm_locked
            + ray.Option.SAVE_FROM_CLIENT * self.option_save_from_client
            + ray.Option.BOOKMARK_SESSION * self.option_bookmark_session
            + ray.Option.HAS_WMCTRL * self.option_has_wmctrl
            + ray.Option.DESKTOPS_MEMORY * self.option_desktops_memory
            + ray.Option.HAS_GIT * self.option_has_git
            + ray.Option.SNAPSHOTS * self.option_snapshots)
        
        self.send(gui_addr, "/ray/gui/daemon_announce", ray.VERSION,
                  self.server_status, options, self.session.root,
                  int(is_net_free))
        
        self.send(gui_addr, "/ray/server_status", self.server_status)
        self.send(gui_addr, "/ray/gui/session/name",
                  self.session.name, self.session.path)
        
        for client in self.session.clients:
            self.send(gui_addr, 
                      '/ray/client/new',
                      client.client_id, 
                      client.executable_path,
                      client.arguments,
                      client.name, 
                      client.prefix_mode, 
                      client.project_path,
                      client.label,
                      client.icon,
                      client.capabilities,
                      int(client.check_last_save),
                      client.ignored_extensions)
            
            self.send(gui_addr, "/ray/client/status",
                      client.client_id,  client.status)
        
        self.gui_list.append(gui_addr)
        Terminal.message("Registered with GUI")
