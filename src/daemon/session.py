import functools
import os
import random
import shutil
import string
import subprocess
import sys
import time
from liblo import Address
from PyQt5.QtCore import QCoreApplication, QTimer
from PyQt5.QtXml  import QDomDocument

import ray
from bookmarker        import BookMarker
from desktops_memory   import DesktopsMemory
from snapshoter        import Snapshoter
from multi_daemon_file import MultiDaemonFile
from signaler          import Signaler
from server_sender     import ServerSender
from file_copier       import FileCopier
from client            import Client
from daemon_tools import TemplateRoots, RS, Terminal, CommandLineArgs

_translate = QCoreApplication.translate
signaler = Signaler.instance()

def dirname(*args):
    return os.path.dirname(*args)

def basename(*args):
    return os.path.basename(*args)

class Session(ServerSender):
    def __init__(self, root):
        ServerSender.__init__(self)
        self.root = root
        self.is_dummy = False
        
        self.clients = []
        self.new_clients = []
        self.removed_clients = []
        self.name = ""
        self.path = ""
        
        self.is_renameable = True
        self.forbidden_ids_list = []
        
        self.file_copier = FileCopier(self)
        
        self.bookmarker = BookMarker()
        self.desktops_memory = DesktopsMemory(self)
        self.snapshoter = Snapshoter(self)
    
    #############
    def oscReply(self, *args):
        if not self.osc_src_addr:
            return
        
        self.send(self.osc_src_addr, *args)
    
    def setRenameable(self, renameable):
        if not renameable:
            if self.is_renameable:
                self.is_renameable = False
                if self.hasServer():
                    self.getServer().sendRenameable(False)
            return
        
        for client in self.clients:
            if client.isRunning():
                return
            
        self.is_renameable = True
        if self.hasServer():
            self.getServer().sendRenameable(True)
    
    def message(self, string, even_dummy=False):
        if self.is_dummy and not even_dummy:
            return
        
        Terminal.message(string)
        
    def setRoot(self, session_root):
        if self.path:
            raise NameError("impossible to change root. session %s is loaded"
                                % self.path)
            return
        
        self.root = session_root
        
        multi_daemon_file = MultiDaemonFile.getInstance()
        if multi_daemon_file:
            multi_daemon_file.update()
        
    def setName(self, session_name):
        self.name = session_name
    
    def setPath(self, session_path):
        if self.path:
            self.bookmarker.removeAll(self.path)
        
        self.path = session_path
        self.setName(session_path.rpartition('/')[2])
        
        multi_daemon_file = MultiDaemonFile.getInstance()
        if multi_daemon_file:
            multi_daemon_file.update()
        
        if self.path:
            server = self.getServer()
            if server and server.option_bookmark_session:
                self.bookmarker.setDaemonPort(server.port)
                self.bookmarker.makeAll(self.path)
    
    def getClient(self, client_id):
        for client in self.clients:
            if client.client_id == client_id:
                return client
        else:
            sys.stderr.write("client_id %s is not in ray-daemon session\n")
    
    def getClientByAddress(self, addr):
        if not addr:
            return None
        
        for client in self.clients:
            if client.addr and client.addr.url == addr.url:
                return client
    
    def newClient(self, executable, client_id=None):
        client = Client(self)
        client.executable_path = executable
        client.name = basename(executable)
        client.client_id = client_id
        if not client_id:
            client.client_id = self.generateClientId(executable)
            
        self.clients.append(client)
        return client
    
    def trashClient(self, client):
        if not client in self.clients:
            raise NameError("No client to remove: %s" % client.client_id)
            return
        
        client.setStatus(ray.ClientStatus.REMOVED)
        
        if client.getProjectFiles() or client.net_daemon_url:
            self.removed_clients.append(client)
            client.sendGuiClientProperties(removed=True)
        
        self.clients.remove(client)
    
    def removeClient(self, client):
        if not client in self.clients:
            raise NameError("No client to remove: %s" % client.client_id)
            return
        
        client.setStatus(ray.ClientStatus.REMOVED)
        
        self.clients.remove(client)
    
    def restoreClient(self, client):
        client.sent_to_gui = False
        
        if not self.addClient(client):
            return
        
        self.sendGui('/ray/trash/remove', client.client_id)
        self.removed_clients.remove(client)
        
        if client.auto_start:
            client.start()
    
    def tellAllClientsSessionIsLoaded(self):
        self.message("Telling all clients that session is loaded...")
        for client in self.clients:
            client.tellClientSessionIsLoaded()
    
    def purgeInactiveClients(self):
        remove_item_list = []
        for i in range(len(self.clients)):
            if not self.clients[i].active:
                self.sendGui("/ray/client/status", self.clients[i].client_id,
                             ray.ClientStatus.REMOVED)
                remove_item_list.append(i)
        
        remove_item_list.reverse()
        
        for i in remove_item_list:
            self.clients.__delitem__(i)
            
        del remove_item_list
            
    def clientsHaveErrors(self):
        for client in self.clients:
            if client.active and client.hasError():
                return True
        return False
    
    def updateForbiddenIdsList(self):
        if not self.path:
            return
        
        self.forbidden_ids_list.clear()
        
        for file in os.listdir(self.path):
            if os.path.isdir("%s/%s" % (self.path, file)) and '.' in file:
                client_id = file.rpartition('.')[2]
                if not client_id in self.forbidden_ids_list:
                    self.forbidden_ids_list.append(client_id)
                    
            elif os.path.isfile("%s/%s" % (self.path, file)) and '.' in file:
                for string in file.split('.')[1:]:
                    if not string in self.forbidden_ids_list:
                        self.forbidden_ids_list.append(string)
                        
        for client in self.clients + self.removed_clients:
            if not client.client_id in self.forbidden_ids_list:
                self.forbidden_ids_list.append(client.client_id)
    
    def generateClientIdAsNsm(self):
        client_id = 'n'
        for l in range(4):
            client_id += random.choice(string.ascii_uppercase)
            
        return client_id
    
    def generateClientId(self, wanted_id=""):
        self.updateForbiddenIdsList()
        
        wanted_id = basename(wanted_id)
        
        if wanted_id:
            for to_rm in ('ray-', 'non-', 'carla-'):
                if wanted_id.startswith(to_rm):
                    wanted_id = wanted_id.replace(to_rm, '', 1)
                    break
            
            wanted_id = wanted_id.replace('jack', '')
            
            #reduce string if contains '-'
            if '-' in wanted_id:
                new_wanted_id = ''
                seplist = wanted_id.split('-')
                for sep in seplist[:-1]:
                    if len(sep) > 0:
                        new_wanted_id += (sep[0] + '_')
                new_wanted_id += seplist[-1]
                wanted_id = new_wanted_id
            
            
            #prevent non alpha numeric characters
            new_wanted_id = ''
            last_is_ = False
            for char in wanted_id:
                if char.isalnum():
                    new_wanted_id += char
                else:
                    if not last_is_:
                        new_wanted_id += '_'
                        last_is_ = True
            
            wanted_id = new_wanted_id
            
            while wanted_id and wanted_id.startswith('_'):
                wanted_id = wanted_id[1:]
            
            while wanted_id and wanted_id.endswith('_'):
                wanted_id = wanted_id[:-1]
            
            if not wanted_id:
                wanted_id = self.generateClientIdAsNsm()
                while wanted_id in self.forbidden_ids_list:
                    wanted_id = self.generateClientIdAsNsm()
            
            #limit string to 10 characters
            if len(wanted_id) >= 11:
                wanted_id = wanted_id[:10]
            
            if not wanted_id in self.forbidden_ids_list:
                self.forbidden_ids_list.append(wanted_id)
                return wanted_id
            
            n=2
            while "%s_%i" % (wanted_id, n) in self.forbidden_ids_list:
                n+=1
            
            self.forbidden_ids_list.append(wanted_id)
            return "%s_%i" % (wanted_id, n)
                
                
        client_id = 'n'
        for l in range(4):
            client_id += random.choice(string.ascii_uppercase)
        
        while client_id in self.forbidden_ids_list:
            client_id = 'n'
            for l in range(4):
                client_id += random.choice(string.ascii_uppercase)
        
        self.forbidden_ids_list.append(client_id)
        return client_id
    
    def getListOfExistingClientIds(self):
        if not self.path:
            return []
        
        client_ids_list = []
        
        for file in os.listdir(self.path):
            if os.path.isdir(file) and file.contains('.'):
                client_ids_list.append(file.rpartition('.')[2])
            elif os.path.isfile(file) and file.contains('.'):
                file_without_extension = file.rpartition('.')[0]
                
    
    def addClient(self, client):
        self.clients.append(client)
        client.sendGuiClientProperties()
        return True
        
    def reOrderClients(self, client_ids_list):
        client_newlist  = []
        
        for client_id in client_ids_list:
            for client in self.clients:
                if client.client_id == client_id:
                    client_newlist.append(client)
                    break
        
        if len(client_ids_list) != len(self.clients):
            return
        
        self.clients.clear()
        for client in client_newlist:
            self.clients.append(client)

class OperatingSession(Session):
    #Session is separated in 3 parts only for faster search and modifications.
    def __init__(self, root):
        Session.__init__(self, root)
        self.wait_for = ray.WaitFor.NONE
        
        self.timer = QTimer()
        self.expected_clients = []
        
        self.timer_launch = QTimer()
        self.timer_launch.setInterval(100)
        self.timer_launch.timeout.connect(self.timerLaunchTimeOut)
        self.clients_to_launch = []
        
        self.timer_quit = QTimer()
        self.timer_quit.setInterval(100)
        self.timer_quit.timeout.connect(self.timerQuitTimeOut)
        self.clients_to_quit = []
        
        self.err_loading = ray.Err.OK
        self.err_saving  = ray.Err.OK
        
        self.osc_path     = None
        self.osc_args     = None
        self.osc_src_addr = None
        
        self.process_order = []
        
        self.terminated_yet = False
        
    def rememberOscArgs(self, path, args, src_addr):
        self.osc_path     = path
        self.osc_args     = args
        self.osc_src_addr = src_addr
    
    def waitAndGoTo(self, duration, follow, wait_for, single_shot=True):
        self.timer.stop()
        
        #we need to delete timer to change the timeout connect
        del self.timer
        self.timer = QTimer()
        
        if type(follow) in (list, tuple):
            if len(follow) == 0:
                return
            elif len(follow) == 1:
                follow = follow[0]
            else:
                follow = functools.partial(follow[0], *follow[1:])
        
        if self.expected_clients:
            if wait_for == ray.WaitFor.ANNOUNCE:
                self.sendGuiMessage(
                    _translate('GUIMSG', 'waiting for clients announces...'))
            elif wait_for == ray.WaitFor.STOP:
                self.sendGuiMessage(
                    _translate('GUIMSG', 'waiting for clients to die...'))
            
            self.wait_for = wait_for
            self.timer.setSingleShot(True)
            self.timer.timeout.connect(follow)
            self.timer.start(duration)
        else:
            follow()
    
    def endTimerIfLastExpected(self, client):
        if client in self.expected_clients:
            self.expected_clients.remove(client)
        if not self.expected_clients:
            self.timer.setSingleShot(True)
            self.timer.stop()
            self.timer.start(0)
    
    def cleanExpected(self):
        if self.expected_clients:
            client_names = ""
            
            for client in self.expected_clients:
                client_names += client.name + ', ' 
            
            if self.wait_for == ray.WaitFor.ANNOUNCE:
                self.sendGuiMessage(_translate('GUIMSG', "%sdidn't announce")
                                    % client_names)
                
            elif self.wait_for == ray.WaitFor.STOP:
                self.sendGuiMessage(_translate('GUIMSG', "%sstill alive !")
                                    % client_names)
                
            self.expected_clients.clear()
        else:
            if self.wait_for == ray.WaitFor.ANNOUNCE:
                self.sendGuiMessage(
                    _translate('GUIMSG',
                               'All expected clients are announced'))
                
            elif self.wait_for == ray.WaitFor.STOP:
                self.sendGuiMessage(
                    _translate('GUIMSG', 'All expected clients are died'))
                
        self.wait_for = ray.WaitFor.NONE
    
    def nextFunction(self):
        if len(self.process_order) > 0:
            next_item = self.process_order[0]
            next_function = next_item
            arguments = []
            
            if type(next_item) in (tuple, list):
                if len(next_item) == 0:
                    return
                else:
                    next_function = next_item[0]
                    if len(next_item) > 1:
                        arguments = next_item[1:]
            
            
            self.process_order.__delitem__(0)
            next_function(*arguments)
    
    def timerLaunchTimeOut(self):
        if self.clients_to_launch:
            self.clients_to_launch[0].start()
            self.clients_to_launch.__delitem__(0)
            
        if not self.clients_to_launch:
            self.timer_launch.stop()
            
    def timerQuitTimeOut(self):
        if self.clients_to_quit:
            self.clients_to_quit[0].quit()
            self.clients_to_quit.__delitem__(0)
            
        if not self.clients_to_quit:
            self.timer_quit.stop()
    
    def sendError(self, err, error_message):
        #clear process order to allow other new operations
        self.process_order.clear()
        
        if not (self.osc_src_addr or self.osc_path):
            return
        
        self.oscReply("/error", self.osc_path, err, error_message)
    
    def adjustFilesAfterCopy(self, new_session_full_name, template_mode):
        new_session_name = basename(new_session_full_name)
        spath = "%s/%s" % (self.root, new_session_full_name)
        
        #create temp clients from raysession.xml to adjust Files after copy
        session_file = "%s/%s" % (spath, "raysession.xml")
        
        try:
            ray_file = open(session_file, 'r')
        except:
            self.sendError(ray.Err.BAD_PROJECT, 
                           _translate("error", "impossible to read %s")
                           % session_file)
            return
        
        tmp_clients = []
        
        xml = QDomDocument()
        xml.setContent(ray_file.read())

        content = xml.documentElement()
        
        if content.tagName() != "RAYSESSION":
            ray_file.close()
            self.err_loading = ray.Err.BAD_PROJECT
            self.loadError()
            return
        
        content.setAttribute('name', new_session_name)
        
        nodes = content.childNodes()
        
        for i in range(nodes.count()):
            node = nodes.at(i)
            tag_name = node.toElement().tagName()
            if tag_name in ('Clients', 'RemovedClients'):
                clients_xml = node.toElement().childNodes()
                
                for j in range(clients_xml.count()):
                    client_xml = clients_xml.at(j)
                    client = Client(self)
                    cx = client_xml.toElement()
                    client.readXmlProperties(cx)
                    
                    tmp_clients.append(client)
        
        ray_file.close()
        
        ray_file_w = open(session_file, 'w')
        ray_file_w.write(xml.toString())
        ray_file_w.close()
        
        
        for client in tmp_clients:
            client.adjustFilesAfterCopy(new_session_full_name, template_mode)
    
    
    ############################## COMPLEX OPERATIONS ###################
    # All functions are splitted when we need to wait clients 
    # for something (announce, reply, quit).
    # For example, at the end of save(), timer is launched, 
    # then, when timer is timeout or when all client replied, 
    # save_step1 is launched.
        
    def save(self, from_client_id=''):
        if not self.path:
            self.nextFunction()
            return
        
        self.setServerStatus(ray.ServerStatus.SAVE)
        
        for client in self.clients:
            if from_client_id and client.client_id == from_client_id:
                continue
            
            if client.active:
                self.expected_clients.append(client)
            client.save()
                
        self.waitAndGoTo(10000, self.save_step1, ray.WaitFor.REPLY)
            
    def save_step1(self):
        self.cleanExpected()
        
        if not self.path:
            self.nextFunction()
            return
        
        session_file = self.path + '/raysession.xml'
        
        if (os.path.isfile(session_file)
            and not os.access(session_file, os.W_OK)):
                self.err_saving = ray.Err.CREATE_FAILED
                self.saveError()
                return
        try:
            file = open(session_file, 'w')
        except:
            self.err_saving = ray.Err.CREATE_FAILED
            self.saveError()
            return
        
        self.err_saving = ray.Err.OK
        
        xml = QDomDocument()
        p = xml.createElement('RAYSESSION')
        p.setAttribute('VERSION', ray.VERSION)
        p.setAttribute('name', self.name)
        
        xml_cls   = xml.createElement('Clients')
        xml_rmcls = xml.createElement('RemovedClients')
        xml_wins  = xml.createElement('Windows')
        for client in self.clients:
            cl = xml.createElement('client')
            cl.setAttribute('id', client.client_id)
            cl.setAttribute('launched', int(bool(client.isRunning())))
            
            client.writeXmlProperties(cl)
            
            xml_cls.appendChild(cl)
            
        for client in self.removed_clients:
            cl = xml.createElement('client')
            cl.setAttribute('id', client.client_id)
            
            client.writeXmlProperties(cl)
            
            xml_rmcls.appendChild(cl)
        
        if self.hasServer() and self.getServer().option_desktops_memory:
            self.desktops_memory.save()
        
        for win in self.desktops_memory.saved_windows:
            xml_win = xml.createElement('window')
            xml_win.setAttribute('class', win.wclass)
            xml_win.setAttribute('name', win.name)
            xml_win.setAttribute('desktop', win.desktop)
            xml_wins.appendChild(xml_win)
        
        p.appendChild(xml_cls)
        p.appendChild(xml_rmcls)
        p.appendChild(xml_wins)
        
        xml.appendChild(p)
        
        
        contents = ("<?xml version='1.0' encoding='UTF-8'?>\n"
                    "<!DOCTYPE RAYSESSION>\n")
        
        contents += xml.toString()
        
        file.write(contents)
        file.close()
        
        self.sendGuiMessage(_translate('GUIMSG', "Session saved."))
        self.message("Session saved.")
        
        self.snapshoter.save()
        self.nextFunction()
    
    def saveDone(self):
        if not self.err_loading:
            self.message("Done.")
            self.oscReply("/reply", self.osc_path, "Saved." )
        self.setServerStatus(ray.ServerStatus.READY)
    
    def saveError(self):
        self.message("Failed")
        m = _translate('Load Error', "Unknown error")
        if self.err_saving == ray.Err.CREATE_FAILED:
            m = _translate(
                'GUIMSG', "Can't save session, session file is unwriteable !")
        
        self.message(m)
        self.sendGuiMessage(m)
        self.oscReply("/error", self.osc_path, ray.Err.CREATE_FAILED, m)
        
        self.process_order.clear()
        self.setServerStatus(ray.ServerStatus.READY)
        
    def close(self):
        self.sendGuiMessage(
            _translate('GUIMSG', "Commanding attached clients to quit."))
        
        self.expected_clients.clear()
        self.removed_clients.clear()
        
        if not self.path:
            self.nextFunction()
            return
        
        self.setServerStatus(ray.ServerStatus.CLOSE)
        self.sendGui('/ray/trash/clear')
        
        
        for client in self.clients.__reversed__():
            if client.isRunning():
                self.expected_clients.append(client)
                self.clients_to_quit.append(client)
                self.timer_quit.start()
        
        self.waitAndGoTo(30000, self.close_step1, ray.WaitFor.STOP)
    
    def close_step1(self):
        for client in self.expected_clients:
            client.kill()
            
        self.waitAndGoTo(1000, self.close_step2, ray.WaitFor.STOP)
    
    def close_step2(self):
        self.cleanExpected()
        
        #self.purgeInactiveClients()
        self.clients.clear()
        
        if self.path:
            lock_file =  self.path + '/.lock'
            if os.path.isfile(lock_file):
                os.remove(lock_file)
                
        self.setPath('')
            
        self.sendGui("/ray/gui/session/name", "", "" )
        self.nextFunction()
    
    def closeDone(self):
        self.oscReply("/reply", self.osc_path, "Closed.")
        self.message("Done")
        self.setServerStatus(ray.ServerStatus.OFF)
    
    def abortDone(self):
        self.oscReply("/reply", self.osc_path, "Aborted.")
        self.message("Done")
        self.setServerStatus(ray.ServerStatus.OFF)
        
    def new(self, new_session_name):
        self.sendGuiMessage(
            _translate('GUIMSG', "Creating new session \"%s\"")
            % new_session_name)
        spath = self.root + '/' + new_session_name
        
        try:
            os.makedirs(spath)
        except:
            self.oscReply("/error", self.osc_path, ray.Err.CREATE_FAILED, 
                          "Could not create the session directory")
            return
        
        self.setServerStatus(ray.ServerStatus.NEW)
        self.setPath(spath)
        self.oscReply("/reply", self.osc_path, "Created." )
        self.sendGui("/ray/gui/session/session", new_session_name)
        self.sendGui("/ray/gui/session/name",
                     new_session_name, new_session_name)
        
        self.oscReply("/reply", self.osc_path, "Session created")
        self.nextFunction()
    
    def newDone(self):
        self.sendGuiMessage(_translate('GUIMSG', 'Session is ready'))
        self.setServerStatus(ray.ServerStatus.READY)
    
    def duplicate(self, new_session_full_name):
        if self.clientsHaveErrors():
            self.sendError(ray.Err.GENERAL_ERROR, 
                           _translate('error', "Some clients could not save"))
            self.process_order.clear()
            return
        
        self.sendGui('/ray/trash/clear')
        
        for client in self.clients:
            client.net_duplicate_state = -1
            
            if (client.net_daemon_url
                and ray.isValidOscUrl(client.net_daemon_url)):
                    self.send(Address(client.net_daemon_url),
                              '/ray/session/duplicate_only',
                              self.name,
                              new_session_full_name,
                              client.net_session_root)
                    
                    self.expected_clients.append(client)
        
        self.waitAndGoTo(2000,
                         (self.duplicate_step1, new_session_full_name),
                         ray.WaitFor.DUPLICATE_START) 
        
    def duplicate_step1(self, new_session_full_name):
        spath = "%s/%s" % (self.root, new_session_full_name)
        
        self.setServerStatus(ray.ServerStatus.COPY)
        self.file_copier.startSessionCopy(self.path, 
                                          spath, 
                                          self.duplicate_step2, 
                                          self.duplicateAborted, 
                                          [new_session_full_name])
    
    def duplicate_step2(self, new_session_full_name):
        self.cleanExpected()
        
        for client in self.clients:
            if client.net_duplicate_state == 0:
                self.expected_clients.append(client)
        
        self.waitAndGoTo(3600000,  #1Hour
                         (self.duplicate_step3, new_session_full_name),
                         ray.WaitFor.DUPLICATE_FINISH)
        
    def duplicate_step3(self, new_session_full_name):
        self.adjustFilesAfterCopy(new_session_full_name, ray.Template.NONE)
        self.nextFunction()
    
    def duplicateAborted(self, new_session_full_name):
        self.process_order.clear()
        self.oscReply('/ray/net_daemon/duplicate_state', 1)
        self.setServerStatus(ray.ServerStatus.READY)
    
    def saveSessionTemplate(self, template_name, net=False):
        template_root = TemplateRoots.user_sessions
        
        if net:
            template_root = "%s/%s" \
                            % (self.root, TemplateRoots.net_session_name)
        
        spath = "%s/%s" % (template_root, template_name)
        
        #overwrite existing template
        if os.path.isdir(spath):
            if not os.access(spath, os.W_OK):
                self.sendError(
                    ray.Err.GENERAL_ERROR, 
                    _translate(
                        "error", 
                        "Impossible to save template, unwriteable file !"))
                    
                self.setServerStatus(ray.ServerStatus.READY)
                return
            
            shutil.rmtree(spath)
        
        if not os.path.exists(template_root):
            os.makedirs(template_root)
        
        
        #For network sessions, 
        #save as template the network session only 
        #if there is no other server on this same machine.
        #Else, one could erase template just created by another one.
        #To prevent all confusion, 
        #all seen machines are sended to prevent an erase by looping 
        #(a network session can contains another network session 
        #on the machine where is the master daemon, for example).
        
        for client in self.clients:
            if client.net_daemon_url:
                self.send(Address(client.net_daemon_url), 
                          '/ray/session/save_as_template', 
                          self.name, 
                          template_name, 
                          client.net_session_root)
        
        self.setServerStatus(ray.ServerStatus.COPY)
        self.file_copier.startSessionCopy(self.path, 
                                          spath, 
                                          self.saveSessionTemplate_step_1, 
                                          self.saveSessionTemplateAborted, 
                                          [template_name, net])
        
    def saveSessionTemplate_step_1(self, template_name, net):
        tp_mode = ray.Template.SESSION_SAVE_NET if net else ray.Template.SESSION_SAVE
        
        for client in self.clients + self.removed_clients:
            client.adjustFilesAfterCopy(template_name, tp_mode)
        
        self.message("Done")
        self.sendGuiMessage(_translate('GUIMSG', 
                                       "Session saved as template named %s")
                            % template_name)
        
        self.oscReply("/reply", self.osc_path, "Saved as template.")
        self.setServerStatus(ray.ServerStatus.READY)
    
    def saveSessionTemplateAborted(self, template_name):
        self.process_order.clear()
        self.setServerStatus(ray.ServerStatus.READY)
    
    def prepareTemplate(self, new_session_full_name, 
                        template_name, net=False):
        template_root = TemplateRoots.user_sessions
        
        if net:
            template_root = "%s/%s" \
                            % (self.root, TemplateRoots.net_session_name)
        
        template_path = "%s/%s" % (template_root, template_name)
        
        if template_name.startswith('///'):
            template_name = template_name.replace('///', '')
            template_path = "%s/%s" \
                            % (TemplateRoots.factory_sessions, template_name)
            
        if not os.path.isdir(template_path):
            self.sendError(ray.Err.GENERAL_ERROR, 
                           _translate("error", "No template named %s")
                           % template_name)
            return
        
        new_session_name = basename(new_session_full_name)
        spath = "%s/%s" % (self.root, new_session_full_name)
        
        if os.path.exists(spath):
            self.sendError(ray.Err.CREATE_FAILED, 
                           _translate("error", "Folder \n%s \nalready exists")
                           % spath)
            return
        
        if self.path:
            self.setServerStatus(ray.ServerStatus.COPY)
        else:
            self.setServerStatus(ray.ServerStatus.PRECOPY)
            self.sendGui("/ray/gui/session/name",  
                         new_session_name, new_session_name)
            
        self.file_copier.startSessionCopy(template_path, 
                                          spath, 
                                          self.prepareTemplate_step1, 
                                          self.prepareTemplateAborted, 
                                          [new_session_full_name])
        
    def prepareTemplate_step1(self, new_session_full_name):
        self.adjustFilesAfterCopy(new_session_full_name,
                                  ray.Template.SESSION_LOAD)
        self.nextFunction()
    
    def prepareTemplateAborted(self, new_session_full_name):
        self.process_order.clear()
        if self.name:
            self.setServerStatus(ray.ServerStatus.READY)
        else:
            self.setServerStatus(ray.ServerStatus.OFF)
        
            self.setPath('')
            self.sendGui('/ray/gui/session/name', '', '')
        
    def load(self, session_full_name):
        #terminate or switch clients
        spath = self.root + '/' + session_full_name
        if session_full_name.startswith('/'):
            spath = session_full_name
            
        if not os.path.exists(spath):
            try:
                os.makedirs(spath)
            except:
                self.err_loading = ray.Err.CREATE_FAILED
                self.loadError()
                return
        
        multi_daemon_file = MultiDaemonFile.getInstance()
        if (multi_daemon_file
                and not multi_daemon_file.isFreeForSession(spath)):
            Terminal.warning("Session is used by another daemon")
            self.err_loading = ray.Err.SESSION_LOCKED
            self.loadError()
            return
        
        if os.path.isfile(spath + '/.lock'):
            Terminal.warning("Session is locked by another process")
            self.err_loading = ray.Err.SESSION_LOCKED
            self.loadError()
            return
        
        
        self.message("Attempting to open %s" % spath)
        
        session_ray_file = spath + '/raysession.xml'
        session_nsm_file = spath + '/session.nsm'
        
        self.err_loading = ray.Err.OK
        
        
        
        is_ray_file = True
        
        try:
            ray_file = open(session_ray_file, 'r')
        except:
            is_ray_file = False
            
        if not is_ray_file:
            try:
                file = open(session_nsm_file, 'r')
                self.sendGui('/ray/opening_nsm_session')
            except:
                try:
                    ray_file = open(session_ray_file, 'w')
                    xml = QDomDocument()
                    p = xml.createElement('RAYSESSION')
                    p.setAttribute('VERSION', ray.VERSION)
                    
                    if self.isNsmLocked():
                        name = basename(session_full_name).rpartition('.')[0]
                        p.setAttribute('name', name)
                    
                    xml.appendChild(p)
                    
                    ray_file.write(xml.toString())
                    ray_file.close()
                    
                    ray_file = open(session_ray_file, 'r')
                    
                    is_ray_file = True
                    
                except:
                    self.err_loading = ray.Err.CREATE_FAILED
                    self.loadError()
                    return
                
        self.sendGuiMessage(_translate('GUIMSG', "Opening session %s")
                                % session_full_name)
        
        self.removed_clients.clear()
        self.sendGui('/ray/trash/clear')
        
        
        self.new_clients = []
        new_client_exec_args = []
        
        self.setPath(spath)
        
        if is_ray_file:
            xml = QDomDocument()
            xml.setContent(ray_file.read())

            content = xml.documentElement()
            
            if content.tagName() != "RAYSESSION":
                ray_file.close()
                self.err_loading = ray.Err.BAD_PROJECT
                self.loadError()
                return
            
            sess_name = content.attribute('name')
            if sess_name:
                self.name = sess_name
            
            nodes = content.childNodes()
            
            for i in range(nodes.count()):
                node = nodes.at(i)
                tag_name = node.toElement().tagName()
                if tag_name in ('Clients', 'RemovedClients'):
                    clients_xml = node.toElement().childNodes()
                    
                    for j in range(clients_xml.count()):
                        client_xml = clients_xml.at(j)
                        client = Client(self)
                        cx = client_xml.toElement()
                        client.readXmlProperties(cx)
                        
                        if tag_name == 'Clients':
                            if client.auto_start:
                                new_client_exec_args.append(
                                    (client.executable_path, 
                                     client.arguments))
                            
                            self.new_clients.append(client)
                            
                        elif tag_name == 'RemovedClients':
                            self.removed_clients.append(client)
                            client.sendGuiClientProperties(removed=True)
                            
                elif tag_name == "Windows":
                    server = self.getServer()
                    if server and server.option_desktops_memory:
                        self.desktops_memory.readXml(node.toElement())
            
            ray_file.close()
        else:
            for line in file.read().split('\n'):
                elements = line.split(':')
                if len(elements) >= 3:
                    client = Client(self)
                    client.name            = elements[0]
                    client.executable_path = elements[1]
                    client.client_id       = elements[2]
                    client.prefix_mode     = ray.PrefixMode.CLIENT_NAME
                    self.new_clients.append(client)
                    new_client_exec_args.append((client.executable_path, ''))
                    
            file.close()
        
        self.message("Commanding unneeded and dumb clients to quit")
        
        for client in self.clients:
            if ((client.active and client.isCapableOf(':switch:')
                    or (client.isDumbClient() and client.isRunning()))
                and ((client.executable_path, client.arguments)
                     in new_client_exec_args)):
                # client will switch
                # or keep alive if non active and running
                new_client_exec_args.remove(
                    (client.executable_path, client.arguments))
                
            else:
                # client is not capable of switch, or is not wanted 
                # in the new session
                if client.isRunning():
                    self.expected_clients.append(client)
                    client.quit()
                else:
                    client.quit()
                    self.removeClient(client)
        
        if self.expected_clients:
            self.setServerStatus(ray.ServerStatus.CLEAR)
        
        self.waitAndGoTo(20000, self.load_step1, ray.WaitFor.STOP)
    
    def load_step1(self):
        self.cleanExpected()
            
        self.message("Commanding smart clients to switch")
        
        has_switch = False
        
        new_client_id_list = []
        
        for new_client in self.new_clients:
            #/* in a duplicated session, clients will have the same
            #* IDs, so be sure to pick the right one to avoid race
            #* conditions in JACK name registration. */
            for client in self.clients:
                if (client.client_id == new_client.client_id
                    and client.executable_path == new_client.executable_path
                    and client.arguments == new_client.arguments):
                    #we found the good existing client
                    break
            else:
                for client in self.clients:
                    if (client.executable_path == new_client.executable_path
                            and client.arguments == new_client.arguments):
                        #we found a switchable client
                        break
                else:
                    client = None
            
            
            if client and client.isRunning():
                if client.active and not client.isReplyPending():
                    #since we already shutdown clients not capable of 
                    #'switch', we can assume that these are.
                    client.switch(new_client)
                    has_switch = True
            else:
                #* sleep a little bit because liblo derives its sequence
                #* of port numbers from the system time (second
                #* resolution) and if too many clients start at once they
                #* won't be able to find a free port. */
                if not self.addClient(new_client):
                    continue
                    
                if new_client.auto_start and not self.is_dummy:
                    self.clients_to_launch.append(new_client)
                    
                    if (not new_client.executable_path
                            in RS.non_active_clients):
                        self.expected_clients.append(new_client)
            
            new_client_id_list.append(new_client.client_id)
            
        self.sendGui("/ray/gui/session/name",  self.name, self.name)
        
        
        if has_switch:
            self.setServerStatus(ray.ServerStatus.SWITCH)
        else:
            self.setServerStatus(ray.ServerStatus.LAUNCH) 
        
        
        #* this part is a little tricky... the clients need some time to
        #* send their 'announce' messages before we can send them 'open'
        #* and know that a reply is pending and we should continue waiting
        #* until they finish.

        #* dumb clients will never send an 'announce message', so we need
        #* to give up waiting on them fairly soon. */
        
        self.timer_launch.start()
        
        self.reOrderClients(new_client_id_list)
        self.sendGui('/ray/gui/clients_reordered', *new_client_id_list)
        
        self.waitAndGoTo(5000, self.load_step2, ray.WaitFor.ANNOUNCE)
    
    def load_step2(self):
        for client in self.expected_clients:
            if not client.executable_path in RS.non_active_clients:
                RS.non_active_clients.append(client.executable_path)
                
        RS.settings.setValue('daemon/non_active_list', RS.non_active_clients)
        
        self.cleanExpected()
        
        self.setServerStatus(ray.ServerStatus.OPEN)
        
        for client in self.clients:
            if client.active and client.isReplyPending():
                self.expected_clients.append(client)
            elif client.isRunning() and client.isDumbClient():
                client.setStatus(ray.ClientStatus.NOOP)
                
        self.waitAndGoTo(10000, self.load_step3, ray.WaitFor.REPLY)
        
    def load_step3(self):
        self.cleanExpected()
        
        server = self.getServer()
        if server and server.option_desktops_memory:
            self.desktops_memory.replace()
        
        self.tellAllClientsSessionIsLoaded()
        self.message('Loaded')
        
        self.sendGui("/ray/gui/session/name",  self.name, self.name)
        self.oscReply("/reply", self.osc_path, "Loaded.")
        
        self.nextFunction()
    
    def loadDone(self):
        self.message("Done")
        self.setServerStatus(ray.ServerStatus.READY)
    
    def loadError(self):
        self.message("Failed")
        m = _translate('Load Error', "Unknown error")
        if self.err_loading == ray.Err.CREATE_FAILED:
            m = _translate('Load Error', "Could not create session file!")
        elif self.err_loading == ray.Err.SESSION_LOCKED:
            m = _translate('Load Error', 
                           "Session is locked by another process!")
        elif self.err_loading == ray.Err.NO_SUCH_FILE:
            m = _translate('Load Error', "The named session does not exist.")
        elif self.err_loading == ray.Err.BAD_PROJECT:
            m = _translate('Load Error', "Could not load session file.")
        
        self.oscReply("/error", self.osc_path, self.err_loading, m)
        
        if self.name:
            self.setServerStatus(ray.ServerStatus.READY)
        else:
            self.setServerStatus(ray.ServerStatus.OFF)
            
        self.process_order.clear()
    
    def duplicateOnlyDone(self):
        self.oscReply('/ray/net_daemon/duplicate_state', 1)
    
    def duplicateDone(self):
        self.message("Done")
        self.oscReply("/reply", self.osc_path, "Duplicated.")
        self.setServerStatus(ray.ServerStatus.READY)
        
    def exitNow(self):
        self.message("Bye Bye...")
        self.setServerStatus(ray.ServerStatus.OFF)
        QCoreApplication.quit()
        
class SignaledSession(OperatingSession):
    def __init__(self, root):
        OperatingSession.__init__(self, root)
        
        signaler.server_new.connect(self.serverNewSession)
        signaler.server_new_from_tp.connect(self.serverNewSessionFromTemplate)
        signaler.server_open.connect(self.serverOpenSession)
        signaler.server_save.connect(self.serverSaveSession)
        signaler.server_save_from_client.connect(
            self.serverSaveSessionFromClient)
        signaler.server_rename.connect(self.serverRenameSession)
        signaler.server_duplicate.connect(self.serverDuplicateSession)
        signaler.server_duplicate_only.connect(
            self.serverDuplicateSessionOnly)
        signaler.server_save_session_template.connect(
            self.serverSaveSessionTemplate)
        signaler.server_close.connect(self.serverCloseSession)
        signaler.server_abort.connect(self.serverAbortSession)
        signaler.server_list_sessions.connect(self.serverListSessions)
        
        signaler.server_reorder_clients.connect(self.serverReorderClients)
        
        signaler.server_list_snapshots.connect(self.serverListSnapshots)
        
        signaler.server_add.connect(self.serverAdd)
        signaler.server_add_proxy.connect(self.serverAddProxy)
        signaler.server_add_client_template.connect(
            self.serverAddClientTemplate)
        signaler.server_add_user_client_template.connect(
            self.serverAddUserClientTemplate)
        signaler.server_add_factory_client_template.connect(
            self.serverAddFactoryClientTemplate)
        
        signaler.server_announce.connect(self.serverAnnounce)
        signaler.server_reply.connect(self.serverReply)
        
        signaler.gui_client_stop.connect(self.guiClientStop)
        signaler.gui_client_kill.connect(self.guiClientKill)
        signaler.gui_client_trash.connect(self.guiClientTrash)
        signaler.gui_client_resume.connect(self.guiClientResume)
        signaler.gui_client_save.connect(self.guiClientSave)
        signaler.gui_client_save_template.connect(self.guiClientSaveTemplate)
        signaler.gui_client_label.connect(self.guiClientLabel)
        signaler.gui_client_icon.connect(self.guiClientIcon)
        signaler.gui_update_client_properties.connect(
            self.updateClientProperties)
        
        signaler.gui_trash_restore.connect(self.guiTrashRestore)
        signaler.gui_trash_remove_definitely.connect(
            self.guiTrashRemoveDefinitely)
        
        signaler.bookmark_option_changed.connect(self.bookmarkOptionChanged)
        
        signaler.copy_aborted.connect(self.abortCopy)
        
        signaler.client_net_properties.connect(
            self.setClientNetworkProperties)
        signaler.net_duplicate_state.connect(self.setClientNetDuplicateState)
        
        signaler.dummy_load_and_template.connect(self.dummyLoadAndTemplate)
        signaler.dummy_duplicate.connect(self.dummyDuplicate)
        
        
    ############################# FUNCTIONS CONNECTED TO SIGNALS FROM OSC ###############################
    
    def serverNewSession(self, path, args, src_addr):
        if self.process_order:
            return
        self.rememberOscArgs(path, args, src_addr)
        if len(args) < 1:
            return
        
        self.process_order = [self.save, self.close, (self.new, args[0]),
                              self.save, self.newDone]
        self.nextFunction()
        
    def serverNewSessionFromTemplate(self, path, args, src_addr, net=False):
        if self.process_order:
            return
        
        self.rememberOscArgs(path, args, src_addr)
        
        if len(args) != 2:
            return
        
        new_session_full_name, template_name = args
        
        self.process_order = [self.save, 
                              (self.prepareTemplate, *args, net), 
                              (self.load, new_session_full_name),
                              self.loadDone]
        self.nextFunction()
        
    def serverOpenSession(self, path, args, src_addr):
        if self.process_order:
            return
        self.rememberOscArgs(path, args, src_addr)
        self.process_order = [self.save, (self.load, *args), self.loadDone]
        self.nextFunction()
        
    def serverOpenSessionAtStart(self, session_name):
        self.process_order = [self.save, (self.load, session_name), self.loadDone]
        self.nextFunction()
    
    def serverSaveSession(self, path, args, src_addr):
        if self.process_order:
            return
        self.rememberOscArgs(path, args, src_addr)
        self.process_order = [self.save, self.saveDone]
        self.nextFunction()
        
    def serverSaveSessionFromClient(self, path, args, src_addr, client_id):
        if self.process_order:
            return
        
        self.rememberOscArgs(path, args, src_addr)
        self.process_order = [(self.save, client_id), self.saveDone]
        self.nextFunction()
        
        
    def serverCloseSession(self, path, args, src_addr):
        if self.process_order:
            return
        self.rememberOscArgs(path, args, src_addr)
        self.process_order = [self.save, self.close, self.closeDone]
        self.nextFunction()
    
    def serverRenameSession(self, new_session_name):
        if self.process_order:
            return
        
        if not self.path:
            return
        
        if self.file_copier.isActive():
            return
        
        if new_session_name == self.name:
            return
        
        if not self.isNsmLocked():
            for filename in os.listdir(dirname(self.path)):
                if filename == new_session_name:
                    return
        
        for client in self.clients:
            if client.isRunning():
                self.sendGuiMessage(
                    _translate('GUIMSG', 
                               'Stop all clients before rename session !'))
                return
        
        for client in self.clients + self.removed_clients:
            client.adjustFilesAfterCopy(new_session_name, ray.Template.RENAME)
        
        self.sendGuiMessage(
            _translate('GUIMSG', 'Session %s has been renamed to %s .')
            % (self.name, new_session_name))
        
        if not self.isNsmLocked():
            try:
                spath = "%s/%s" % (dirname(self.path), new_session_name)
                subprocess.run(['mv', self.path, spath])
                self.path = spath
                
                self.sendGuiMessage(
                    _translate('GUIMSG', 'Session directory is now: %s')
                    % self.path)
                
            except:
                pass
        
        self.name = new_session_name
        
        self.sendGui('/ray/gui/session/name', self.name, self.name)
    
    def serverDuplicateSession(self, path, args, src_addr):
        if self.process_order:
            return
        
        if len(args) != 1:
            return
        
        new_session_full_name = args[0]
        
        self.rememberOscArgs(path, args, src_addr)
        
        
        self.process_order = [self.save, 
                              (self.duplicate, new_session_full_name), 
                              (self.load, new_session_full_name), 
                              self.duplicateDone]
        self.nextFunction()
    
    def serverDuplicateSessionOnly(self, path, args, src_addr):
        if (self.process_order
            or len(args) != 1
            or self.file_copier.isActive()):
                self.oscReply('/ray/net_daemon/duplicate_state', 1)
                return
        
        new_session_full_name = args[0]
        
        self.rememberOscArgs(path, args, src_addr)
        
        self.process_order = [self.save, 
                              (self.duplicate, new_session_full_name),
                              self.duplicateOnlyDone]
        self.nextFunction()
    
    def serverSaveSessionTemplate(self, path, args, src_addr, net=False):
        if self.process_order:
            return
        
        if len(args) != 1:
            return
        
        self.rememberOscArgs(path, args, src_addr)
        
        template_name = args[0]
        
        for client in self.clients:
            if client.executable_path == 'ray-network':
                client.net_session_template = template_name
        
        self.process_order = [self.save, 
                              (self.saveSessionTemplate, 
                               template_name, 
                               net)]
        self.nextFunction()
        
    def serverAbortSession(self, path, args, src_addr):
        self.wait_for = ray.WaitFor.NONE
        self.timer.stop()
        
        self.rememberOscArgs(path, args, src_addr)
        self.process_order = [self.close, self.abortDone]
        
        if self.file_copier.isActive():
            self.file_copier.abort(self.nextFunction, [])
        else:
            self.nextFunction()
    
    def serverListSessions(self, src_addr, with_net):
        if with_net:
            for client in self.clients:
                if client.net_daemon_url:
                    self.send(Address(client.net_daemon_url), 
                              '/ray/server/list_sessions', 1)
        
        if not self.root:
            return
        
        session_list = []
        
        for root, dirs, files in os.walk(self.root):
            #exclude hidden files and dirs
            files   = [f for f in files if not f.startswith('.')]
            dirs[:] = [d for d in dirs  if not d.startswith('.')]
            
            if root == self.root:
                continue
            
            already_send = False
            
            for file in files:
                if file in ('raysession.xml', 'session.nsm'):
                    if not already_send:
                        basefolder = root.replace(self.root + '/', '', 1)
                        session_list.append(basefolder)
                        if len(session_list) == 100:
                            self.send(src_addr, "/reply_sessions_list",
                                      *session_list)
                            
                            session_list.clear()
                        already_send = True
                    
        if session_list:
            self.send(src_addr, "/reply_sessions_list", *session_list)
        
    def serverReorderClients(self, path, args):
        client_ids_list = args
        
        self.reOrderClients(client_ids_list)
        
    def serverListSnapshots(self, src_addr):
        snapshots = self.snapshoter.list()
        
        i=0
        snap_send = []
        
        for snapshot in snapshots:
            if i == 20:
                self.serverSend(src_addr, '/ray/reply_snapshots_list',
                                *snap_send)
                
                snap_send.clear()
                i=0
            else:
                snap_send.append(snapshot)
                i+=1
        
        if snap_send:
            self.serverSend(src_addr, '/ray/reply_snapshots_list', *snap_send)
    
    def serverAdd(self, path, args, src_addr):
        self.rememberOscArgs(path, args, src_addr)
        executable = args[0]
        
        client = Client(self)
        client.executable_path = executable
        client.name            = basename(executable)
        client.client_id       = self.generateClientId(executable)
        client.icon            = client.name.lower().replace('_', '-')
        
        if self.addClient(client):
            client.start()
    
    def serverAddProxy(self, path, args, src_addr):
        self.rememberOscArgs(path, args, src_addr)
        executable = args[0]
        
        client = Client(self)
        client.executable_path = 'ray-proxy'
        
        client.tmp_arguments  = "--executable %s" % executable
        if CommandLineArgs.debug:
            client.tmp_arguments += " --debug"
            
        client.name            = basename(executable)
        client.client_id       = self.generateClientId(client.name)
        client.icon            = client.name.lower().replace('_', '-')
        
        if self.addClient(client):
            client.start()
    
    def addClientTemplate(self, template_name, factory=False):
        templates_root = TemplateRoots.user_clients
        if factory:
            templates_root = TemplateRoots.factory_clients
            
        xml_file = "%s/%s" % (templates_root, 'client_templates.xml')
        file = open(xml_file, 'r')
        xml = QDomDocument()
        xml.setContent(file.read())
        file.close()
        
        if xml.documentElement().tagName() != 'RAY-CLIENT-TEMPLATES':
            return
        
        nodes = xml.documentElement().childNodes()
        
        for i in range(nodes.count()):
            node = nodes.at(i)
            ct = node.toElement()
            
            if ct.tagName() != 'Client-Template':
                continue
            
            if ct.attribute('template-name') == template_name:
                client = Client(self)
                client.readXmlProperties(ct)
                
                needed_version = ct.attribute('needed-version')
                
                if (needed_version.startswith('.')
                    or needed_version.endswith('.')
                    or not needed_version.replace('.', '').isdigit()):
                        #needed-version not writed correctly, ignores it
                        needed_version = ''
                
                if factory and needed_version:
                    try:
                        full_program_version = subprocess.check_output(
                            [client.executable_path, '--version']).decode()
                    except:
                        continue
                    
                    previous_is_digit = False
                    program_version = ''
                    
                    for character in full_program_version:
                        if character.isdigit():
                            program_version+=character
                            previous_is_digit = True
                        elif character == '.':
                            if previous_is_digit:
                                program_version+=character
                            previous_is_digit = False
                        else:
                            if program_version:
                                break
                            
                    if not program_version:
                        continue
                    
                    
                    neededs = []
                    progvss = []
                    
                    for n in needed_version.split('.'):
                        neededs.append(int(n))
                        
                    for n in program_version.split('.'):
                        progvss.append(int(n))
                    
                    if neededs > progvss:
                        node = node.nextSibling()
                        continue
                
                full_name_files = []
                
                if not needed_version: 
                    #if there is a needed version, 
                    #then files are ignored because factory templates with
                    #version must be NSM compatible
                    #and dont need files (factory)
                    template_path = "%s/%s" % (templates_root, template_name)
                    
                    if os.path.isdir(template_path):
                        for file in os.listdir(template_path):
                            full_name_files.append("%s/%s"
                                                   % (template_path, file))
                            
                if self.addClient(client):
                    if full_name_files:
                        client.setStatus(ray.ClientStatus.PRECOPY)
                        self.file_copier.startClientCopy(
                            client.client_id, full_name_files, self.path, 
                            self.addClientTemplate_step_1, 
                            self.addClientTemplateAborted, [client])
                    else:
                        self.addClientTemplate_step_1(client)
                    
                break
    
    def addClientTemplate_step_1(self, client):
        client.adjustFilesAfterCopy(self.name, ray.Template.CLIENT_LOAD)
        
        if client.auto_start:
            client.start()
    
    def addClientTemplateAborted(self, client):
        self.removeClient(client)
    
    def serverAddClientTemplate(self, path, args, src_addr):
        self.rememberOscArgs(path, args, src_addr)
        
        factory = bool(args[0])
        template_name = args[1]
        
        self.addClientTemplate(template_name, factory)
    
    def serverAddUserClientTemplate(self, path, args, src_addr):
        self.rememberOscArgs(path, args, src_addr)
        template_name = args[0]
        
        self.addClientTemplate(template_name, False)
        
    def serverAddFactoryClientTemplate(self, path, args, src_addr):
        self.rememberOscArgs(path, args, src_addr)
        template_name = args[0]
        
        self.addClientTemplate(template_name, True)
     
    def serverAnnounce(self, path, args, src_addr):
        client_name, capabilities, executable_path, major, minor, pid = args
        
        if self.wait_for == ray.WaitFor.STOP:
            return
        
        #we can't be absolutely sure that the announcer is the good one
        #but if client announce a known PID, 
        #we can be sure of which client is announcing
        for client in self.clients: 
            if client.pid == pid and not client.active and client.isRunning():
                client.serverAnnounce(path, args, src_addr, False)
                break
        else:
            n=0
            for client in self.clients:
                if (basename(client.executable_path) \
                        == basename(executable_path)
                    and not client.active
                    and client.pending_command == ray.Command.START):
                        n+=1
                        if n>1:
                            break
            
            if n==1:
                for client in self.clients:
                    if (basename(client.executable_path) \
                            == basename(executable_path)
                        and not client.active
                        and client.pending_command == ray.Command.START):
                            client.serverAnnounce(path, args, src_addr, False)
                            break
            else:
                for client in self.clients:
                    if (not client.active
                        and client.pending_command == ray.Command.START):
                            if ray.isPidChildOf(pid, client.pid):
                                client.serverAnnounce(path, args, 
                                                      src_addr, False)
                                break
                
                #Ray Session won't add clients that aren't launched 
                #by Ray Session itself. 
            
        if self.wait_for == ray.WaitFor.ANNOUNCE:
            self.endTimerIfLastExpected(client)
    
    def serverReply(self, path, args, src_addr):
        if self.wait_for == ray.WaitFor.STOP:
            return
        
        message = args[1]
        client = self.getClientByAddress(src_addr)
        if client:
            client.setReply(ray.Err.OK, message)
            #self.message( "Client \"%s\" replied with: %s in %fms"
                         #% (client.name, message, 
                            #client.milliseconds_since_last_command()))
            
            if client.pending_command == ray.Command.SAVE:
                client.last_save_time = time.time()
            
            client.pending_command = ray.Command.NONE
            
            client.setStatus(ray.ClientStatus.READY)
            
            server = self.getServer()
            if (server 
                    and self.getServerStatus() == ray.ServerStatus.READY
                    and server.option_desktops_memory):
                        self.desktops_memory.replace()
            
            if self.wait_for == ray.WaitFor.REPLY:
                self.endTimerIfLastExpected(client)
        else:
            self.message("Reply from unknown client")
    
    def dummyLoadAndTemplate(self, session_name, template_name, sess_root):
        tmp_session = DummySession(sess_root)
        tmp_session.dummyLoadAndTemplate(session_name, template_name)
        
    def dummyDuplicate(self, src_addr, session_to_load,
                       new_session, sess_root):
        tmp_session = DummySession(sess_root)
        tmp_session.osc_src_addr = src_addr
        tmp_session.dummyDuplicate(session_to_load, new_session)
    
    def setClientNetworkProperties(self, client_id, 
                                   net_daemon_url, net_session_root):
        for client in self.clients:
            if client.client_id == client_id:
                client.setNetworkProperties(net_daemon_url, net_session_root)
                break
    
    def setClientNetDuplicateState(self, src_addr, state):
        for client in self.clients:
            if (client.net_daemon_url
                and ray.areSameOscPort(client.net_daemon_url, src_addr.url)):
                    client.net_duplicate_state = state
                    client.net_daemon_copy_timer.stop()
                    break
        else:
            return
        
        if state == 1:
            if self.wait_for == ray.WaitFor.DUPLICATE_FINISH:
                self.endTimerIfLastExpected(client)
            return
        
        if (self.wait_for == ray.WaitFor.DUPLICATE_START and state == 0):
            self.endTimerIfLastExpected(client)
            
        client.net_daemon_copy_timer.start()
            
    
    def guiClientStop(self, path, args):
        for client in self.clients:
            if client.client_id == args[0]:
                client.stop()
                self.sendGui("/reply", "Client stopped." )
                break
        else:
            self.sendGui("/error", -10, "No such client." )
    
    def guiClientKill(self, path, args):
        for client in self.clients:
            if client.client_id == args[0]:
                client.kill()
                self.sendGui("/reply", "Client killed." )
                break
        else:
            self.sendGui("/error", -10, "No such client." )
    
    def guiClientTrash(self, path, args):
        client_id = args[0]
        
        for client in self.clients:
            if client.client_id == client_id:
                if client.isRunning():
                    return
                
                if self.file_copier.isActive(client_id):
                    self.file_copier.abort()
                    return
                
                self.trashClient(client)
                
                self.sendGui("/reply", "Client removed.")
                break
        else:
            self.sendGui("/error", -10, "No such client.")
            
    def guiClientResume(self, path, args):
        for client in self.clients:
            if client.client_id == args[0] and not client.isRunning():
                if self.file_copier.isActive(client.client_id):
                    self.sendGui("/error", -13, "Impossible, copy running")
                    return
                
                client.start()
                break
    
    def guiClientSave(self, path, args):
        for client in self.clients:
            if client.client_id == args[0] and client.active:
                if self.file_copier.isActive(client.client_id):
                    self.sendGui("/error", -13, "Impossible, copy running")
                    return
                client.save()
                break
    
    def guiClientSaveTemplate(self, path, args):
        if self.file_copier.isActive():
            self.sendGui("/error", -13, "Impossible, copy running")
            return
        
        for client in self.clients:
            if client.client_id == args[0]:
                client.saveAsTemplate(args[1])
                break
    
    def guiClientLabel(self, client_id, label):
        for client in self.clients:
            if client.client_id == client_id:
                client.setLabel(label)
                break
            
    def guiClientIcon(self, client_id, icon):
        for client in self.clients:
            if client.client_id == client_id:
                client.setIcon(icon)
                break
    
    def updateClientProperties(self, client_data):
        for client in self.clients:
            if client.client_id == client_data.client_id:
                client.updateClientProperties(client_data)
                break
    
    def guiTrashRestore(self, client_id):
        for client in self.removed_clients:
            if client.client_id == client_id:
                self.restoreClient(client)
                break
        else:
            self.sendGui("/error", -10, "No such client.")
            
    def guiTrashRemoveDefinitely(self, client_id):
        for client in self.removed_clients:
            if client.client_id == client_id:
                break
        else:
            return
        
        self.sendGui('/ray/trash/remove', client_id)
        
        for file in client.getProjectFiles():
            try:
                subprocess.run(['rm', '-R', file])
            except:
                continue
            
        self.removed_clients.remove(client)
    
    def bookmarkOptionChanged(self, state):
        if self.path:
            if state:
                self.bookmarker.makeAll(self.path)
            else:
                self.bookmarker.removeAll(self.path)
    
    def abortCopy(self):
        self.file_copier.abort()
    
    def terminate(self):
        if self.terminated_yet:
            return
        
        if self.file_copier.isActive():
            self.file_copier.abort()
        
        self.terminated_yet = True
        self.process_order = [self.close, self.exitNow]
        self.nextFunction()

class DummySession(OperatingSession):
    def __init__(self, root):
        OperatingSession.__init__(self, root)
        self.is_dummy = True
        
    def dummyLoadAndTemplate(self, session_full_name, template_name):
        self.process_order = [(self.load, session_full_name), (self.saveSessionTemplate, template_name, True)]
        self.nextFunction()
        
    def dummyDuplicate(self, session_to_load, new_session_full_name):
        self.process_order = [(self.load, session_to_load), (self.duplicate, new_session_full_name), self.duplicateOnlyDone]
        self.nextFunction()
