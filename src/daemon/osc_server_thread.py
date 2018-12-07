import os
import sys
import random
import shutil
import time
from liblo import ServerThread, Address, make_method, Message
from PyQt5.QtXml import QDomDocument

#from shared import *
import ray
import terminal
import shared_vars as shv
from signaler import Signaler

debug = False
instance = None
signaler = Signaler.instanciate()


def pathIsValid(path):
    return not bool('../' in path)

def ifDebug(string):
    if debug:
        print(string, file=sys.stderr)

#Osc server thread separated in many classes for confort.
#ClientCommunicating contains NSM protocol. Paths have to be never changed.
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
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        
        if not self.session.path:
            self.send(src_addr, "/error", path, ERR_NO_SESSION_OPEN, 
                      "Sorry, but there's no session open "
                      + "for this application to join.")
            return
        
        signaler.server_announce.emit(path, args, src_addr)
        
    @make_method('/reply', 'ss')
    def reply(self, path, args, types, src_addr):
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        signaler.server_reply.emit(path, args, src_addr)
            
    @make_method('/error', 'sis')
    def error(self, path, args, types, src_addr):
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        
        client = self.session.getClientByAddress(src_addr)
        if not client:
            terminal.WARNING("Error from unknown client")
            return
        
        err_code = args[1]
        message  = args[2]
        client.setReply(err_code, message)
        
        terminal.MESSAGE("Client \"%s\" replied with error: %s (%i)"
                         % ( client.name, message, err_code ))
        
        client.pending_command = shv.COMMAND_NONE
        client.setStatus(ray.ClientStatus.ERROR)
    
    @make_method('/nsm/client/progress', 'f')
    def nsmClientProgress(self, path, args, types, src_addr):
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        client = self.session.getClientByAddress(src_addr)
        if not client:
            return
        
        client.progress = args[0]
        self.sendGui("/ray/client/progress", client.client_id, 
                     client.progress)
    
    @make_method('/nsm/client/is_dirty', '')
    def nsmClientIs_dirty(self, path, args, types, src_addr):
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        
        
        
        client = self.session.getClientByAddress(src_addr)
        if not client:
            return
        
        terminal.MESSAGE("%s sends dirty" % client.client_id)
        
        client.dirty = 1
        client.last_dirty = time.time()
        
        self.sendGui("/ray/client/dirty", client.client_id, client.dirty)

    @make_method('/nsm/client/is_clean', '')
    def nsmClientIs_clean(self, path, args, types, src_addr):
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        
        client = self.session.getClientByAddress(src_addr)
        if not client:
            return
        
        terminal.MESSAGE("%s sends clean" % client.client_id)
        
        client.dirty = 0
        
        self.sendGui("/ray/client/dirty", client.client_id, client.dirty)
        
        if self.option_save_from_client:
            if (client.pending_command != shv.COMMAND_SAVE
                and client.last_dirty 
                and time.time() - client.last_dirty > 0.20
                and time.time() - client.last_save_time > 1.00):
                    signaler.server_save_from_client.emit(path, args,
                                                          src_addr,
                                                          client.client_id)
    
    @make_method('/nsm/client/message', 'is')
    def nsmClientMessage(self, path, args, types, src_addr):
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        
        client = self.session.getClientByAddress(src_addr)
        if not client:
            return
        
        self.sendGui("/ray/client/message", client.client_id, args[0], args[1])

    @make_method('/nsm/client/gui_is_hidden', '')
    def nsmClientGui_is_hidden(self, path, args, types, src_addr):
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        
        client = self.session.getClientByAddress(src_addr)
        if not client:
            return
        
        terminal.MESSAGE("Client '%s' sends gui hidden" % client.client_id)
        
        client.gui_visible = False
        
        self.sendGui("/ray/client/gui_visible", client.client_id,
                     int(client.gui_visible))

    @make_method('/nsm/client/gui_is_shown', '')
    def nsmClientGui_is_shown(self, path, args, types, src_addr):
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        
        client = self.session.getClientByAddress(src_addr)
        if not client:
            return
        
        terminal.MESSAGE("Client '%s' sends gui shown" % client.client_id)
        
        client.gui_visible = True
        
        self.sendGui("/ray/client/gui_visible", client.client_id,
                     int(client.gui_visible))

    @make_method('/nsm/client/label', 's')
    def nsmClientLabel(self, path, args, types, src_addr):
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        
        client = self.session.getClientByAddress(src_addr)
        if not client:
            return
        
        label = args[0]
        signaler.gui_client_label.emit(client.client_id, label)
      
    @make_method('/nsm/server/broadcast', None)
    def nsmServerBroadcast(self, path, args, types, src_addr):
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        
        if not args:
            return
        
        #don't allow clients to broadcast NSM commands
        if args[0].startswith('/nsm/') or args[0].startswith('/ray'):
            return
        
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
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        
        client = self.session.getClientByAddress(src_addr)
        if not client:
            return
        
        net_daemon_url, net_session_root = args
        
        signaler.client_net_properties.emit(client.client_id, net_daemon_url,
                                            net_session_root)

class OscServerThread(ClientCommunicating):
    def __init__(self, session, settings, osc_num=0):
        ClientCommunicating.__init__(self, session, osc_num)
        self.list_asker_addr = None
        
        self.option_save_from_client = settings.value(
            'daemon/save_all_from_saved_client', True, type=bool)
        self.option_bookmark_session = settings.value(
            'daemon/bookmark_session_folder', True, type=bool)
        self.option_desktops_memory  = settings.value(
            'daemon/desktops_memory', False, type=bool)
        
        self.option_has_wmctrl = bool(shutil.which('wmctrl'))
        if not self.option_has_wmctrl:
            self.option_desktops_memory = False
            
        global instance
        instance = self
        
    @staticmethod
    def getInstance():
        return instance
    
    @make_method('/osc/ping', '')
    def oscPing(self, path, args, types, src_addr):
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        
        self.send(src_addr, "/reply", path)
    
    @make_method('/ray/server/gui_announce', 'sisii')
    def rayGuiGui_announce(self, path, args, types, src_addr):
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        
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
            is_net_free = multi_daemon_file.isFreeForRoot(self.net_daemon_id,
                                                          self.session.root)
        
        #not needed here, in fact args[3] isn't used, that was for that:
        self.option_save_from_client = \
            bool(args[3] & ray.Option.SAVE_FROM_CLIENT)
        self.option_bookmark_session = \
            bool(args[3] & ray.Option.BOOKMARK_SESSION)
            
        self.announceGui(src_addr.url, nsm_locked, is_net_free)

    @make_method('/ray/server/gui_disannounce', '')
    def rayGuiGui_disannounce(self, path, args, types, src_addr):
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        
        for addr in self.gui_list:
            if addr.url == src_addr.url:
                break
        else:
            return
        
        self.gui_list.remove(addr)
        
        if src_addr.url == self.nsm_locker_url:
            self.net_daemon_id  = random.randint(1, 999999999)
            multi_daemon_file.update()
            
            self.is_nsm_locked  = False
            self.nsm_locker_url = ''
            self.sendGui('/ray/gui/daemon_nsm_locked', 0)
    
    @make_method('/ray/server/set_nsm_locked', '')
    def rayServerSetNsmLocked(self, path, args, types, src_addr):
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        
        self.is_nsm_locked = True
        self.nsm_locker_url = src_addr.url
        
        for gui_addr in self.gui_list:
            if gui_addr.url != src_addr.url:
                self.send(gui_addr, '/ray/gui/daemon_nsm_locked', 1)
    
    @make_method('/ray/server/quit', '')
    def nsmServerQuit(self, path, args):
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        sys.exit(0)
    
    @make_method('/ray/server/abort_copy', '')
    def rayServerAbortCopy(self, path, args):
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        
        signaler.copy_aborted.emit()
    
    @make_method('/ray/server/change_root', 's')
    def rayServerChangeRoot(self, path, args, types, src_addr):
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        
        if self.session.path:
            self.send(src_addr, '/reply', 
                      "Can't change session_root while a session is running")
            return
        
        self.session.setRoot(args[0])
    
    @make_method('/ray/server/list_path', '')
    def rayServerListPath(self, path, args, types, src_addr):
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        
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
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        
        if not os.path.isdir(shv.session_template_root):
            return
        
        template_list = []
        
        all_files = os.listdir(shv.session_template_root)
        for file in all_files:
            if os.path.isdir("%s/%s" % (shv.session_template_root, file)):
                template_list.append(file)
                
                if len(template_list) == 100:
                    self.send(src_addr, '/reply_session_templates',
                              *template_list)
                    template_list.clear()
                    
        if template_list:
            self.send(src_addr, '/reply_session_templates', *template_list)
    
    @make_method('/ray/server/list_user_client_templates', '')
    def rayServerListUserClientTemplates(self, path, args, types, src_addr):
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        
        self.listClientTemplates(src_addr, False)
    
    @make_method('/ray/server/list_factory_client_templates', '')
    def rayServerListFactoryClientTemplates(self, path, args, types,
                                            src_addr):
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        
        self.listClientTemplates(src_addr, True)
        
    @make_method('/ray/server/list_sessions', 'i')
    def nsmServerListAll(self, path, args, types, src_addr):
        print('zmeof')
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        print('zeli')
        self.list_asker_addr = src_addr
        with_net = bool(args[0])
        print('rmoan')
        signaler.server_list_sessions.emit(src_addr, with_net)
    
    @make_method('/ray/server/new_session', 's')
    def nsmServerNew(self, path, args, types, src_addr):
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        
        if self.is_nsm_locked:
            return
        
        if self.isOperationPending(src_addr, path):
            return
        
        if not pathIsValid(args[0]):
            self.send(src_addr, "/error", path, ERR_CREATE_FAILED,
                      "Invalid session name.")
            return
        
        signaler.server_new.emit(path, args, src_addr)
    
    @make_method('/ray/server/new_from_template', 'ss')
    def rayServerNewFromTemplate(self, path, args, types, src_addr):
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        
        if self.is_nsm_locked:
            return
        
        if self.isOperationPending(src_addr, path):
            return
        
        signaler.server_new_from_tp.emit(path, args, src_addr, False)
    
    @make_method('/ray/server/open_session', 's')
    def nsmServerOpen(self, path, args, types, src_addr):
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        
        if self.isOperationPending(src_addr, path):
            return
        
        signaler.server_open.emit(path, args, src_addr)
          
    @make_method('/ray/server/open_session', 'ss')
    def nsmServerOpenWithTemplate(self, path, args, types, src_addr):
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        
        if self.isOperationPending(src_addr, path):
            return
        
        session_name, template_name = args
        
        if template_name:
            spath = ''
            if session_name.startswith('/'):
                spath = session_name
            else:
                spath = "%s/%s" % (session.root, session_name)
            
            if not os.path.exists(spath):
                signaler.server_new_from_tp.emit(path, args, src_addr, True)
                return
        
        signaler.server_open.emit(path, [args[0]], src_addr)
    
    @make_method('/reply_sessions_list', None)
    def replySessionsList(self, path, args, types, src_addr):
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        #this reply is only used here for reply from net_daemon
        #it directly resend its infos to the last gui that asked session list
        if self.list_asker_addr:
            self.send(self.list_asker_addr, '/reply_sessions_list', *args)
    
    
    @make_method('/ray/session/save', '')
    def nsmServerSave(self, path, args, types, src_addr):
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        
        if self.isOperationPending(src_addr, path):
            return
        
        if not self.session.path:
            self.send(src_addr, "/error", path, ERR_NO_SESSION_OPEN,
                      "No session to save.")
            return 0
        
        signaler.server_save.emit(path, args, src_addr)
    
    @make_method('/ray/session/save_as_template', 's')
    def nsmServerSaveSessionTemplate(self, path, args, types, src_addr):
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        
        if self.isOperationPending(src_addr, path):
            return
        
        if not self.session.path:
            self.send(src_addr, "/error", path, ERR_NO_SESSION_OPEN,
                      "No session to save as template.")
            return
        
        if not pathIsValid(args[0]):
            self.send(src_addr, "/error", path, ERR_CREATE_FAILED,
                      "Invalid session name.")
            return
        
        signaler.server_save_session_template.emit(path, args,
                                                   src_addr, False)
        
    @make_method('/ray/session/save_as_template', 'sss')
    def nsmServerSaveSessionTemplateOff(self, path, args, types, src_addr):
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        #save as template an not loaded session
        session_name, template_name, sess_root = args
        
        if not pathIsValid(session_name):
            self.send(src_addr, "/error", path, ERR_CREATE_FAILED,
                      "Invalid session name.")
            return
        
        if not pathIsValid(template_name):
            self.send(src_addr, "/error", path, ERR_CREATE_FAILED,
                      "Invalid session name.")
            return
        
        if (sess_root == self.session.root
                and session_name == self.session.name):
            net = True
            signaler.server_save_session_template.emit(path, [template_name],
                                                       src_addr, net)
            return
        
        signaler.dummy_load_and_template.emit(*args)
    
    @make_method('/ray/session/close', '')
    def nsmServerClose(self, path, args, types, src_addr):
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        
        if self.isOperationPending(src_addr, path):
            return
        
        if not self.session.path:
            self.send(src_addr, "/error", path, ERR_NO_SESSION_OPEN,
                      "No session to close.")
            return 0
        
        signaler.server_close.emit(path, args, src_addr)
    
    @make_method('/ray/session/abort', '')
    def nsmServerAbort(self, path, args, types, src_addr):
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        
        if self.server_status == ray.ServerStatus.PRECOPY:
            signaler.copy_aborted.emit()
            return
        
        if not self.session.path:
            self.send(src_addr, "/error", path, ERR_NO_SESSION_OPEN,
                      "No session to abort." )
            return
        
        signaler.server_abort.emit(path, args, src_addr)
    
    @make_method('/ray/session/duplicate', 's')
    def nsmServerDuplicate(self, path, args, types, src_addr):
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        
        if self.is_nsm_locked:
            return
        
        if self.isOperationPending(src_addr, path):
            return
        
        if not self.session.path:
            self.send(src_addr, "/error", path, ERR_NO_SESSION_OPEN,
                      "No session to duplicate.")
            return
        
        if not pathIsValid(args[0]):
            self.send(src_addr, "/error", path, ERR_CREATE_FAILED,
                      "Invalid session name.")
            return
        
        signaler.server_duplicate.emit(path, args, src_addr)
        
    @make_method('/ray/session/duplicate_only', 'sss')
    def nsmServerDuplicateOnly(self, path, args, types, src_addr):
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        
        session_full_name, new_session_full_name, sess_root = args
        
        self.send(src_addr, '/ray/net_daemon/duplicate_state', 0)
        
        if (sess_root == self.session.root
                and session_full_name == self.session.name):
            signaler.server_duplicate_only.emit(path, [new_session_full_name],
                                                src_addr)
            return
        
        signaler.dummy_duplicate.emit(src_addr, *args)
    
    @make_method('/ray/session/rename', 's')
    def rayServerRename(self, path, args, types, src_addr):
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        
        new_session_name = args[0]
        
        #prevent rename session in network session
        if self.nsm_locker_url:
            NSM_URL = os.getenv('NSM_URL')
            if not NSM_URL:
                return
            
            if not ray.areSameOscPort(self.nsm_locker_url, NSM_URL):
                return
        
        if '/' in new_session_name:
            self.send(src_addr, "/error", path, ERR_CREATE_FAILED,
                      "Invalid session name.")
            return
        
        if self.isOperationPending(src_addr, path):
            return
        
        if not self.session.path:
            self.send(src_addr, "/error", path, ERR_NO_SESSION_OPEN,
                      "No session to rename.")
            return
        
        signaler.server_rename.emit(new_session_name)
      
    @make_method('/ray/session/add_executable', 's')
    def nsmServerAdd(self, path, args, types, src_addr):
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        
        if not self.session.path:
            self.send(src_addr, "/error", path, ERR_NO_SESSION_OPEN,
                      "Cannot add to session because no session is loaded.")
            return
        
        signaler.server_add.emit(path, args, src_addr)
    
    @make_method('/ray/session/add_proxy', 's')
    def rayServerAddProxy(self, path, args, types, src_addr):
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        
        if not self.session.path:
            self.send(src_addr, "/error", path, ERR_NO_SESSION_OPEN,
                      "Cannot add to session because no session is loaded.")
            return
        
        signaler.server_add_proxy.emit(path, args, src_addr)

    @make_method('/ray/session/add_client_template', 'is')
    def rayServerAddClientTemplate(self, path, args, types, src_addr):
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        
        if not self.session.path:
            self.send(src_addr, "/error", path, ERR_NO_SESSION_OPEN,
                      "Cannot add to session because no session is loaded.")
            return
        
        signaler.server_add_client_template.emit(path, args, src_addr)
    
    @make_method('/ray/session/reorder_clients', None)
    def rayServerReorderClients(self, path, args):
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        
        if not ray.areTheyAllString(args):
            return
        
        signaler.server_reorder_clients.emit(path, args)
    
    @make_method('/ray/session/open_folder', '')
    def rayServerOpenFolder(self, path, args):
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        if self.session.path:
            subprocess.Popen(['xdg-open',  self.session.path])
    
    @make_method('/ray/client/stop', 's')
    def rayGuiClientStop(self, path, args):
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        signaler.gui_client_stop.emit(path, args)
    
    @make_method('/ray/client/kill', 's')
    def rayGuiClientKill(self, path, args):
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        signaler.gui_client_kill.emit(path, args)            
    
    @make_method('/ray/client/remove', 's')
    def rayGuiClientRemove(self, path, args):
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        signaler.gui_client_remove.emit(path, args)
    
    @make_method('/ray/client/resume', 's')
    def rayGuiClientResume(self, path, args):
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        signaler.gui_client_resume.emit(path, args)
                
    @make_method('/ray/client/save', 's')
    def rayGuiClientSave(self, path, args):
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        signaler.gui_client_save.emit(path, args)

    @make_method('/ray/client/save_as_template', 'ss')
    def rayGuiClientSaveAsTemplate(self, path, args):
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        
        signaler.gui_client_save_template.emit(path, args)
    
    @make_method('/ray/client/show_optional_gui', 's')
    def nsmGuiClientShow_optional_gui(self, path, args):
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        
        client = self.session.getClient(args[0])
        
        if client and client.active:
            self.send(client.addr, "/nsm/client/show_optional_gui")

    @make_method('/ray/client/hide_optional_gui', 's')
    def nsmGuiClientHide_optional_gui(self, path, args):
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        
        client = self.session.getClient(args[0])
        
        if client and client.active:
            self.send(client.addr, "/nsm/client/hide_optional_gui")

    @make_method('/ray/client/update_properties', 'ssssissssi')
    def rayGuiClientUpdateProperties(self, path, args):
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        
        client_data = ray.ClientData(*args)
        signaler.gui_update_client_properties.emit(client_data)
        
    @make_method('/ray/net_daemon/duplicate_state', 'f')
    def rayDuplicateState(self, path, args, types, src_addr):
        signaler.net_duplicate_state.emit(src_addr, args[0])
    
    @make_method('/ray/trash/restore', 's')
    def rayGuiTrashRestore(self, path, args, types, src_addr):
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        
        if not self.session.path:
            self.send(src_addr, "/error", path, ERR_NO_SESSION_OPEN,
                      "Cannot add to session because no session is loaded.")
            return
        
        client_id = args[0]
        
        signaler.gui_trash_restore.emit(client_id)
        
    @make_method('/ray/trash/remove_definitely', 's')
    def rayGuiTrashRemoveDefinitely(self, path, args, types, src_addr):
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        
        client_id = args[0]
        
        signaler.gui_trash_remove_definitely.emit(client_id)
    
    @make_method('/ray/option/save_from_client', 'i')
    def rayOptionSaveFromClient(self, path, args):
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
    
        self.option_save_from_client = bool(args[0])
    
    @make_method('/ray/option/bookmark_session_folder', 'i')
    def rayOptionBookmarkSessionFolder(self, path, args):
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        
        self.option_bookmark_session = bool(args[0])
        signaler.bookmark_option_changed.emit(bool(args[0]))        
    
    @make_method('/ray/option/desktops_memory', 'i')
    def rayOptionDesktopsMemory(self, path, args):
        ifDebug('serverOSC::ray-daemon_receives %s, %s' % (path, str(args)))
        
        self.option_desktops_memory = bool(args[0])
    
    def isOperationPending(self, src_addr, path):
        if self.session.file_copier.isActive():
            self.send(src_addr, "/error", path, ERR_COPY_RUNNING, 
                      "ray-daemon is copying files. "
                        + "Wait copy finish or abort copy, "
                        + "and restart operation !")
            return True
        
        if self.session.process_order:
            self.send(src_addr, "/error", path, ERR_OPERATION_PENDING,
                      "An operation pending.")
            return True
        
        return False
        
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
        
        templates_root    = shv.client_template_local_root
        response_osc_path = '/reply_user_client_templates'
        
        if factory:
            templates_root    = shv.client_template_factory_root
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
            + ray.Option.DESKTOPS_MEMORY * self.option_desktops_memory)
        
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
                      int(client.check_last_save))
            
            self.send(gui_addr, "/ray/client/status",
                      client.client_id,  client.status)
        
        self.gui_list.append(gui_addr)
        terminal.MESSAGE("Registered with GUI")
