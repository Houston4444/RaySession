import functools
import math
import os
import random
import shutil
import string
import subprocess
import sys
import time
from liblo import Address
from PyQt5.QtCore import QCoreApplication, QTimer, QProcess
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
from scripter          import Scripter
from daemon_tools import TemplateRoots, RS, Terminal, CommandLineArgs

_translate = QCoreApplication.translate
signaler = Signaler.instance()

def dirname(*args):
    return os.path.dirname(*args)

def basename(*args):
    return os.path.basename(*args)

def session_operation(func):
    def wrapper(*args, **kwargs):
        if len(args) < 4:
            return 
        
        sess, path, osc_args, src_addr, *rest = args
        
        if sess.process_order:
            sess.send(src_addr, "/error", path, ray.Err.OPERATION_PENDING,
                      "An operation pending.")
            return
        
        if sess.file_copier.isActive():
            if path.startswith('/nsm/server/'):
                sess.send(src_addr, "/error", path, ray.Err.OPERATION_PENDING,
                      "An operation pending.")
            else:
                sess.send(src_addr, "/error", path, ray.Err.COPY_RUNNING, 
                        "ray-daemon is copying files.\n"
                            + "Wait copy finish or abort copy,\n"
                            + "and restart operation !\n")
            return
        
        sess.rememberOscArgs(path, osc_args, src_addr)
        
        response = func(*args)
        sess.nextFunction()
        
        return response
    return wrapper


class Session(ServerSender):
    def __init__(self, root):
        ServerSender.__init__(self)
        self.root = root
        self.is_dummy = False
        
        self.clients = []
        self.future_clients = []
        self.trashed_clients = []
        self.future_trashed_clients = []
        self.new_client_exec_args = []
        self.favorites = []
        self.name = ""
        self.path = ""
        self.future_session_path = ""
        self.future_session_name = ""
        
        self.is_renameable = True
        self.forbidden_ids_list = []
        
        self.file_copier = FileCopier(self)
        
        self.bookmarker = BookMarker()
        self.desktops_memory = DesktopsMemory(self)
        self.snapshoter = Snapshoter(self)
        self.running_scripts = []
    
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
    
    def setPath(self, session_path, session_name=''):
        if not self.is_dummy:
            if self.path:
                self.bookmarker.removeAll(self.path)
        
        self.path = session_path
        
        if session_name:
            self.setName(session_name)
        else:
            self.setName(session_path.rpartition('/')[2])
        
        if self.is_dummy:
            return
        
        multi_daemon_file = MultiDaemonFile.getInstance()
        if multi_daemon_file:
            multi_daemon_file.update()
        
        if self.path:
            server = self.getServer()
            if server and server.option_bookmark_session:
                self.bookmarker.setDaemonPort(server.port)
                self.bookmarker.makeAll(self.path)
    
    def noFuture(self):
        self.future_clients.clear()
        self.future_session_path = ''
        self.future_session_name = ''
        self.future_trashed_clients.clear()
    
    def getShortPath(self):
        if self.path.startswith("%s/" % self.root):
            return self.path.replace("%s/" % self.root, '', 1)
        else:
            return self.name
    
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
            raise NameError("No client to trash: %s" % client.client_id)
            return
        
        client.setStatus(ray.ClientStatus.REMOVED)
        
        if client.getProjectFiles() or client.net_daemon_url:
            self.trashed_clients.append(client)
            client.sendGuiClientProperties(removed=True)
        
        self.clients.remove(client)
    
    def removeClient(self, client):
        client.terminateScripts()
        
        if not client in self.clients:
            raise NameError("No client to remove: %s" % client.client_id)
            return
        
        client.setStatus(ray.ClientStatus.REMOVED)
        
        self.clients.remove(client)
    
    def restoreClient(self, client):
        client.sent_to_gui = False
        
        if not self.addClient(client):
            return
        
        self.sendGui('/ray/gui/trash/remove', client.client_id)
        self.trashed_clients.remove(client)
    
    def tellAllClientsSessionIsLoaded(self):
        self.message("Telling all clients that session is loaded...")
        for client in self.clients:
            client.tellClientSessionIsLoaded()
    
    def purgeInactiveClients(self):
        remove_item_list = []
        for i in range(len(self.clients)):
            if not self.clients[i].active:
                self.sendGui("/ray/gui/client/status", self.clients[i].client_id,
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
                        
        for client in self.clients + self.trashed_clients:
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
        
    def reOrderClients(self, client_ids_list, src_addr=None, src_path=''):
        client_newlist  = []
        
        for client_id in client_ids_list:
            for client in self.clients:
                if client.client_id == client_id:
                    client_newlist.append(client)
                    break
        
        if len(client_ids_list) != len(self.clients):
            if src_addr:
                self.send(src_addr, '/error', src_path, ray.Err.GENERAL_ERROR,
                          "%s clients are missing or incorrect" \
                            % (len(self.clients) - len(client_ids_list)))
            return
        
        self.clients.clear()
        for client in client_newlist:
            self.clients.append(client)
            
        if src_addr:
            self.send(src_addr, '/reply', src_path, "clients reordered")
    
    def getScriptPath(self, string):
        script_dir = self.getScriptDir()
        
        if not script_dir:
            return ''
        
        script_path = "%s/%s" % (script_dir, string)
        
        if os.access(script_path, os.X_OK):
            return script_path
        
        return ''
    
    def getScriptDir(self, spath=''):
        if not spath:
            spath = self.path
        
        if not spath:
            return ''
        
        base_path = spath
        while not os.path.isdir("%s/%s" % (base_path, ray.SCRIPTS_DIR)):
            base_path = os.path.dirname(base_path)
            if base_path == "/":
                return ''
        
        return "%s/%s" % (base_path, ray.SCRIPTS_DIR)
    
class OperatingSession(Session):
    def __init__(self, root):
        Session.__init__(self, root)
        self.wait_for = ray.WaitFor.NONE
        
        self.timer = QTimer()
        self.timer_redondant = False
        self.expected_clients = []
        
        self.timer_launch = QTimer()
        self.timer_launch.setInterval(100)
        self.timer_launch.timeout.connect(self.timerLaunchTimeOut)
        self.clients_to_launch = []
        
        self.timer_quit = QTimer()
        self.timer_quit.setInterval(100)
        self.timer_quit.timeout.connect(self.timerQuitTimeOut)
        self.clients_to_quit = []
        
        self.timer_waituser_progress = QTimer()
        self.timer_waituser_progress.setInterval(500)
        self.timer_waituser_progress.timeout.connect(
            self.timerWaituserProgressTimeOut)
        self.timer_wu_progress_n = 0
        
        self.osc_src_addr = None
        self.osc_path     = ''
        self.osc_args     = []
        
        self.process_order = []
        
        self.terminated_yet = False
        
        self.externals_timer = QTimer()
        self.externals_timer.setInterval(100)
        self.externals_timer.timeout.connect(self.checkExternalsStates)
        
        self.process_step_addr = None
        
    def rememberOscArgs(self, path, args, src_addr):
        self.osc_src_addr = src_addr
        self.osc_path = path
        self.osc_args = args
    
    def forgetOscArgs(self):
        self.osc_src_addr = None
        self.osc_path = ''
        self.osc_args.clear()
    
    def waitAndGoTo(self, duration, follow, wait_for, redondant=False):
        self.timer.stop()
        
        # we need to delete timer to change the timeout connect
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
            n_expected = len(self.expected_clients)
            
            if wait_for == ray.WaitFor.ANNOUNCE:
                if n_expected == 1:
                    message = _translate('GUIMSG',
                        'waiting announce from %s...'
                            % self.expected_clients[0].guiMsgStyle())
                else:
                    message = _translate('GUIMSG',
                        'waiting announce from %i clients...' % n_expected)
                self.sendGuiMessage(message)
            elif wait_for == ray.WaitFor.QUIT:
                if n_expected == 1:
                    message = _translate('GUIMSG',
                        'waiting for %s to stop...'
                            % self.expected_clients[0].guiMsgStyle())
                else:
                    message = _translate('GUIMSG',
                        'waiting for %i clients to stop...' % n_expected)
            
            self.timer_redondant = redondant
            
            self.wait_for = wait_for
            self.timer.setSingleShot(True)
            self.timer.timeout.connect(follow)
            self.timer.start(duration)
        else:
            follow()
    
    def endTimerIfLastExpected(self, client):
        if self.wait_for == ray.WaitFor.QUIT and client in self.clients:
            self.removeClient(client)
            
        if client in self.expected_clients:
            self.expected_clients.remove(client)
            
            if self.timer_redondant:
                self.timer.start()
                if self.timer_waituser_progress.isActive():
                    self.timer_wu_progress_n = 0
                    self.timer_waituser_progress.start()
            
        if not self.expected_clients:
            self.timer.setSingleShot(True)
            self.timer.stop()
            self.timer.start(0)
            
            self.timer_waituser_progress.stop()
    
    def cleanExpected(self):
        if self.expected_clients:
            client_names = []
            
            for client in self.expected_clients:
                client_names.append(client.guiMsgStyle())
            
            if self.wait_for == ray.WaitFor.ANNOUNCE:
                self.sendGuiMessage(
                    _translate('GUIMSG', "%s didn't announce.")
                        % ', '.join(client_names))
                
            elif self.wait_for == ray.WaitFor.QUIT:
                self.sendGuiMessage(_translate('GUIMSG', "%s still alive !")
                                    % ', '.join(client_names))
                
            self.expected_clients.clear()
            
        self.wait_for = ray.WaitFor.NONE
    
    def nextFunction(self, from_process_step=False):
        if self.process_step_addr and not from_process_step:
            self.send(self.process_step_addr, '/reply',
                      '/ray/session/process_step', 'step done')
            del self.process_step_addr
            self.process_step_addr = None
            return
        
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
            
            if self.path and not from_process_step:
                for step_string in ('save', 'close'):
                    if next_function == self.__getattribute__(step_string):
                        process_step_script = self.getScriptPath(step_string)
                                            
                        if (process_step_script 
                                and os.access(process_step_script, os.X_OK)):
                            script = Scripter(self, signaler, self.osc_src_addr, 
                                                self.osc_path)
                            script.setAsStepper(True)
                            script.setStepperProcess(step_string)
                            self.running_scripts.append(script)
                            self.sendGuiMessage(
                                _translate('GUIMSG', 
                                    '--- Custom step script %s started...')
                                    % ray.highlightText(process_step_script))
                            script.start(process_step_script, 
                                         [str(a) for a in arguments])
                            return
                        break
                    
            if from_process_step and next_function:
                for script in self.running_scripts:
                    if next_function == self.__getattribute__(
                                                script.getStepperProcess()):
                        script.setStepperHasCall(True)
                        break
                        
                
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
            client = self.clients_to_quit.pop(0)
            client.stop()
            
        if not self.clients_to_quit:
            self.timer_quit.stop()
    
    def timerWaituserProgressTimeOut(self):
        if not self.expected_clients:
            self.timer_waituser_progress.stop()
        
        self.timer_wu_progress_n += 1
        
        ratio = float(self.timer_wu_progress_n / 240)
        self.sendGui('/ray/gui/server/progress', ratio)
        
    def checkExternalsStates(self):
        has_externals = False
        
        for client in self.clients:
            if client.is_external:
                has_externals = True
                if not os.path.exists('/proc/%i' % client.pid):
                    # Quite dirty, but works.
                    client.processFinished(0, 0)
                    
        if not has_externals:
            self.externals_timer.stop()
    
    def sendReply(self, *messages):
        if not (self.osc_src_addr and self.osc_path):
            return
        
        self.sendEvenDummy(self.osc_src_addr, '/reply',
                           self.osc_path, *messages)
    
    def sendError(self, err, error_message):
        #clear process order to allow other new operations
        self.process_order.clear()
        
        if self.process_step_addr:
            self.send(self.process_step_addr, '/error', 
                      '/ray/session/process_step', err, error_message)
        
        if not (self.osc_src_addr and self.osc_path):
            return
        
        self.sendEvenDummy(self.osc_src_addr, "/error",
                           self.osc_path, err, error_message)
    
    def sendMinorError(self, err, error_message):
        if not (self.osc_src_addr and self.osc_path):
            return
        
        self.sendEvenDummy(self.osc_src_addr, "/minor_error",
                           self.osc_path, err, error_message)
    
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
            self.loadError(ray.Err.BAD_PROJECT)
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
        
    def save(self, from_client_id='', outing=False):
        if not self.path:
            self.nextFunction()
            return
        
        if outing:
            self.setServerStatus(ray.ServerStatus.OUT_SAVE)
        else:
            self.setServerStatus(ray.ServerStatus.SAVE)
        
        self.sendGuiMessage(_translate('GUIMSG', '-- Saving session %s --')
                                % ray.highlightText(self.getShortPath()))
        
        for client in self.clients:
            if from_client_id and client.client_id == from_client_id:
                continue
            
            if client.canSaveNow():
                self.expected_clients.append(client)
            client.save()
        
        if self.expected_clients:
            if len(self.expected_clients) == 1:
                self.sendGuiMessage(
                    _translate('GUIMSG', 'waiting for %s to save...')
                        % self.expected_clients[0].guiMsgStyle())
            else:
                self.sendGuiMessage(
                    _translate('GUIMSG', 'waiting for %i clients to save...')
                        % len(self.expected_clients))
        
        self.waitAndGoTo(10000, (self.save_step1, outing), ray.WaitFor.REPLY)
            
    def save_step1(self, outing=False):
        self.cleanExpected()
        
        if outing:
            for client in self.clients:
                if client.hasError():
                    self.sendError(ray.Err.GENERAL_ERROR,
                                  "Some clients could not save")
                    break
                
        if not self.path:
            self.nextFunction()
            return
        
        session_file = self.path + '/raysession.xml'
        
        if (os.path.isfile(session_file)
            and not os.access(session_file, os.W_OK)):
                self.saveError(ray.Err.CREATE_FAILED)
                return
        try:
            file = open(session_file, 'w')
        except:
            self.saveError(ray.Err.CREATE_FAILED)
            return
        
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
            
            launched = int(bool(client.isRunning() or 
                                (client.auto_start
                                 and not client.has_been_started)))
            
            cl.setAttribute('launched', launched)
            
            client.writeXmlProperties(cl)
            
            xml_cls.appendChild(cl)
            
        for client in self.trashed_clients:
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
        
        try:
            file.write(contents)
        except:
            file.close()
            self.saveError(ray.Err.CREATE_FAILED)
            
        file.close()
        
        self.sendGuiMessage(_translate('GUIMSG', "Session '%s' saved.")
                                % self.getShortPath())
        self.message("Session %s saved." % self.getShortPath())
            
        self.nextFunction()
    
    def saveDone(self):
        self.message("Done.")
        self.sendReply("Saved.")
        self.setServerStatus(ray.ServerStatus.READY)
    
    def saveError(self, err_saving):
        self.message("Failed")
        m = _translate('Load Error', "Unknown error")
        
        if err_saving == ray.Err.CREATE_FAILED:
            m = _translate(
                'GUIMSG', "Can't save session, session file is unwriteable !")
        
        self.message(m)
        self.sendGuiMessage(m)
        self.sendError(ray.Err.CREATE_FAILED, m)
        
        self.setServerStatus(ray.ServerStatus.READY)
        self.process_order.clear()
        self.forgetOscArgs()
    
    def snapshot(self, snapshot_name='', rewind_snapshot='',
                 force=False, outing=False):
        if not force:
            server = self.getServer()
            if not (server and server.option_snapshots
                    and not self.snapshoter.isAutoSnapshotPrevented()
                    and self.snapshoter.hasChanges()):
                self.nextFunction()
                return
        
        if outing:
            self.setServerStatus(ray.ServerStatus.OUT_SNAPSHOT)
        else:
            self.setServerStatus(ray.ServerStatus.SNAPSHOT)
        
        self.sendGuiMessage(_translate('GUIMSG', "snapshot started..."))
        self.snapshoter.save(snapshot_name, rewind_snapshot,
                             self.snapshot_step1, self.snapshotError)
    
    def snapshot_step1(self, aborted=False):
        if aborted:
            self.message('Snapshot aborted')
            self.sendGuiMessage(_translate('GUIMSG', 'Snapshot aborted!'))
        
        self.sendGuiMessage(_translate('GUIMSG', '...snapshot finished.'))
        self.nextFunction()
    
    def snapshotDone(self):
        self.setServerStatus(ray.ServerStatus.READY)
        self.sendReply("Snapshot taken.")
        
    def snapshotError(self, err_snapshot, info_str=''):
        m = _translate('Snapshot Error', "Unknown error")
        if err_snapshot == ray.Err.SUBPROCESS_UNTERMINATED:
            m = _translate('Snapshot Error',
                           "git didn't stop normally.\n%s") % info_str
        elif err_snapshot == ray.Err.SUBPROCESS_CRASH:
            m = _translate('Snapshot Error',
                           "git crashes.\n%s") % info_str
        elif err_snapshot == ray.Err.SUBPROCESS_EXITCODE:
            m = _translate('Snapshot Error',
                           "git exit with an error code.\n%s") % info_str
        self.message(m)
        self.sendGuiMessage(m)
        
        # quite dirty
        # minor error is not a fatal error
        # it's important for ray_control to not stop
        # if operation is not snapshot (ex: close or open)
        if self.nextFunction.__name__ == 'snapshotDone':
            self.sendError(err_snapshot, m)
            self.forgetOscArgs()
            return
        
        self.sendMinorError(err_snapshot, m)
        self.nextFunction()
    
    def closeNoSaveClients(self):
        self.cleanExpected()
        
        server = self.getServer()
        if server and server.option_has_wmctrl:
            self.desktops_memory.setActiveWindowList()
            for client in self.clients:
                if client.isRunning() and client.no_save_level == 2:
                    self.expected_clients.append(client)
                    self.desktops_memory.findAndClose(client.pid)
            
        if self.expected_clients:
            self.sendGuiMessage(
              _translate('GUIMSG', 
                'waiting for no saveable clients to be closed gracefully...'))
            
        duration = int(1000 * math.sqrt(len(self.expected_clients)))
        self.waitAndGoTo(duration, self.closeNoSaveClients_step1,
                         ray.WaitFor.QUIT)
    
    def closeNoSaveClients_step1(self):
        self.cleanExpected()
        has_nosave_clients = False
        
        for client in self.clients:
            if client.isRunning() and client.no_save_level:
                self.expected_clients.append(client)
                has_nosave_clients = True
        
        if has_nosave_clients:
            self.setServerStatus(ray.ServerStatus.WAIT_USER)
            self.timer_wu_progress_n = 0
            self.timer_waituser_progress.start()
            self.sendGuiMessage(_translate('GUIMSG',
                'waiting you to close yourself unsaveable clients...'))
            
        # Timer (2mn) is restarted if an expected client has been closed
        self.waitAndGoTo(120000, self.nextFunction, ray.WaitFor.QUIT, True)
    
    def close(self, clear_all_clients=False):
        self.expected_clients.clear()
        
        if not self.path:
            self.nextFunction()
            return
        
        byebye_client_list = []
        future_clients_exec_args = []
        
        if not clear_all_clients:
            for future_client in self.future_clients:
                if future_client.auto_start:
                    future_clients_exec_args.append(
                        (future_client.executable_path, future_client.arguments))
        
        has_keep_alive = False
        
        for client in self.clients:
            if (not clear_all_clients
                and (client.active and client.isCapableOf(':switch:')
                     or (client.isDumbClient() and client.isRunning()))
                and ((client.running_executable, client.running_arguments)
                     in future_clients_exec_args)):
                # client will switch
                # or keep alive if non active and running
                has_keep_alive = True
                future_clients_exec_args.remove(
                    (client.running_executable, client.running_arguments))
            else:
                # client is not capable of switch, or is not wanted 
                # in the new session
                if client.isRunning():
                    self.expected_clients.append(client)
                    #client.stop()
                else:
                    byebye_client_list.append(client)
        
        if has_keep_alive:
            self.setServerStatus(ray.ServerStatus.CLEAR)
        else:
            self.setServerStatus(ray.ServerStatus.CLOSE)
        
        for client in byebye_client_list:
            if client in self.clients:
                self.removeClient(client)
            else:
                raise NameError('no client %s to remove' % client.client_id)
        
        if self.expected_clients:
            if len(self.expected_clients) == 1:
                self.sendGuiMessage(
                    _translate('GUIMSG',
                            'waiting for %s to quit...')
                        % self.expected_clients[0].guiMsgStyle())
            else:
                self.sendGuiMessage(
                    _translate('GUIMSG',
                            'waiting for %i clients to quit...')
                        % len(self.expected_clients))
            
            for client in self.expected_clients.__reversed__():
                self.clients_to_quit.append(client)
                self.timer_quit.start()
            
        self.trashed_clients.clear()
        self.sendGui('/ray/gui/trash/clear')
        
        self.waitAndGoTo(30000, self.close_step1, ray.WaitFor.QUIT)
    
    #def close(self):
        #self.expected_clients.clear()
        #self.trashed_clients.clear()
        
        #if not self.path:
            #self.nextFunction()
            #return
        
        #self.setServerStatus(ray.ServerStatus.CLOSE)
        #self.sendGui('/ray/gui/trash/clear')
        
        #self.sendGuiMessage(_translate('GUIMSG', '-- Closing session %s --')
                            #% ray.highlightText(self.getShortPath()))
        
        #for client in self.clients.__reversed__():
            #if client.isRunning():
                #self.expected_clients.append(client)
                #self.clients_to_quit.append(client)
                #self.timer_quit.start()
        
        #if self.expected_clients:
            #if len(self.expected_clients) == 1:
                #self.sendGuiMessage(
                    #_translate('GUIMSG',
                               #'waiting for %s to stop...')
                        #% self.expected_clients[0].guiMsgStyle())
            #else:
                #self.sendGuiMessage(
                    #_translate('GUIMSG', 'waiting for %i clients to stop...')
                        #% len(self.expected_clients))
        
        #self.waitAndGoTo(30000, self.close_step1, ray.WaitFor.QUIT)
    
    def close_step1(self):
        for client in self.expected_clients:
            client.kill()
            
        self.waitAndGoTo(1000, self.close_step2, ray.WaitFor.QUIT)
    
    def close_step2(self):
        self.cleanExpected()
        
        #for client in self.clients:
            #client.setStatus(ray.ClientStatus.REMOVED)
        
        self.clients.clear()
        
        self.sendGuiMessage(_translate('GUIMSG', 'session %s closed.')
                            % ray.highlightText(self.getShortPath()))
        
        self.setPath('')
            
        self.sendGui("/ray/gui/session/name", "", "" )
        
        self.nextFunction()
    
    def closeDone(self):
        self.cleanExpected()
        self.clients.clear()
        self.setPath('')
        self.sendGui("/ray/gui/session/name", "", "" )
        self.sendReply("Closed.")
        self.message("Done")
        self.setServerStatus(ray.ServerStatus.OFF)
        self.forgetOscArgs()
    
    def abortDone(self):
        self.cleanExpected()
        self.clients.clear()
        self.setPath('')
        self.sendGui("/ray/gui/session/name", "", "" )
        self.sendReply("Aborted.")
        self.message("Done")
        self.setServerStatus(ray.ServerStatus.OFF)
        self.forgetOscArgs()
        
    def new(self, new_session_name):
        self.sendGuiMessage(
            _translate('GUIMSG', "Creating new session \"%s\"")
            % new_session_name)
        spath = self.root + '/' + new_session_name
        
        try:
            os.makedirs(spath)
        except:
            self.sendError(ray.Err.CREATE_FAILED, 
                           "Could not create the session directory")
            return
        
        self.setServerStatus(ray.ServerStatus.NEW)
        self.setPath(spath)
        self.sendGui("/ray/gui/session/name",
                     self.name, self.path)
        self.nextFunction()
    
    def newDone(self):
        self.sendGuiMessage(_translate('GUIMSG', 'Session is ready'))
        self.sendReply("Created.")
        self.setServerStatus(ray.ServerStatus.READY)
        self.forgetOscArgs()
    
    def initSnapshot(self, spath, snapshot):
        self.setServerStatus(ray.ServerStatus.REWIND)
        if self.snapshoter.load(spath, snapshot, self.initSnapshotError):
            self.nextFunction()
            
    def initSnapshotError(self, err, info_str=''):
        m = _translate('Snapshot Error', "Snapshot error")
        if err == ray.Err.SUBPROCESS_UNTERMINATED:
            m = _translate('Snapshot Error',
                           "command didn't stop normally:\n%s") % info_str
        elif err == ray.Err.SUBPROCESS_CRASH:
            m = _translate('Snapshot Error',
                           "command crashes:\n%s") % info_str
        elif err == ray.Err.SUBPROCESS_EXITCODE:
            m = _translate('Snapshot Error',
                           "command exit with an error code:\n%s") % info_str
        elif err == ray.Err.NO_SUCH_FILE:
            m = _translate('Snapshot Error',
                           "error reading file:\n%s") % info_str
        self.message(m)
        self.sendGuiMessage(m)
        self.sendError(err, m)
        
        self.setServerStatus(ray.ServerStatus.OFF)
        self.process_order.clear()
    
    def duplicate(self, new_session_full_name):
        if self.clientsHaveErrors():
            self.sendError(ray.Err.GENERAL_ERROR, 
                           _translate('error', "Some clients could not save"))
            return
        
        self.sendGui('/ray/gui/trash/clear')
        self.sendGuiMessage(
            _translate('GUIMSG', '-- Duplicating session %s to %s --')
                % (ray.highlightText(self.getShortPath()),
                   ray.highlightText(new_session_full_name)))
        
        for client in self.clients:
            client.net_duplicate_state = -1
            
            if (client.net_daemon_url
                and ray.isValidOscUrl(client.net_daemon_url)):
                    self.send(Address(client.net_daemon_url),
                              '/ray/session/duplicate_only',
                              self.getShortPath(),
                              new_session_full_name,
                              client.net_session_root)
                    
                    self.expected_clients.append(client)
        
        if self.expected_clients:
            self.sendGuiMessage(
                _translate('GUIMSG',
                    'waiting for network daemons to start duplicate...'))
                
        self.waitAndGoTo(2000,
                         (self.duplicate_step1, new_session_full_name),
                         ray.WaitFor.DUPLICATE_START)
        
    def duplicate_step1(self, new_session_full_name):
        spath = "%s/%s" % (self.root, new_session_full_name)
        self.setServerStatus(ray.ServerStatus.COPY)
        
        self.sendGuiMessage(_translate('GUIMSG', 'start session copy...'))
        
        self.file_copier.startSessionCopy(self.path, 
                                          spath, 
                                          self.duplicate_step2, 
                                          self.duplicateAborted, 
                                          [new_session_full_name])
    
    def duplicate_step2(self, new_session_full_name):
        self.cleanExpected()
        
        self.sendGuiMessage(_translate('GUIMSG', '...session copy finished.'))
        for client in self.clients:
            if 0 <= client.net_duplicate_state < 1:
                self.expected_clients.append(client)
        
        if self.expected_clients:
            self.sendGuiMessage(
                _translate('GUIMSG',
                    'waiting for network daemons to finish duplicate'))
        
        self.waitAndGoTo(3600000,  #1Hour
                         (self.duplicate_step3, new_session_full_name),
                         ray.WaitFor.DUPLICATE_FINISH)
        
    def duplicate_step3(self, new_session_full_name):
        self.adjustFilesAfterCopy(new_session_full_name, ray.Template.NONE)
        self.nextFunction()
    
    def duplicateAborted(self, new_session_full_name):
        self.process_order.clear()
        
        self.sendError(ray.Err.NO_SUCH_FILE, "No such file.")
        self.send(self.osc_src_addr, '/ray/net_daemon/duplicate_state', 1)
        
        self.setServerStatus(ray.ServerStatus.READY)
        self.forgetOscArgs()
    
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
        
        # For network sessions, 
        # save as template the network session only 
        # if there is no other server on this same machine.
        # Else, one could erase template just created by another one.
        # To prevent all confusion, 
        # all seen machines are sent to prevent an erase by looping 
        # (a network session can contains another network session 
        # on the machine where is the master daemon, for example).
        
        for client in self.clients:
            if client.net_daemon_url:
                self.send(Address(client.net_daemon_url), 
                          '/ray/server/save_session_template', 
                          self.name,
                          template_name,
                          client.net_session_root)
        
        self.setServerStatus(ray.ServerStatus.COPY)
        
        self.sendGuiMessage(
            _translate('GUIMSG', 'start session copy to template...'))
        
        self.file_copier.startSessionCopy(self.path, 
                                          spath, 
                                          self.saveSessionTemplate_step_1, 
                                          self.saveSessionTemplateAborted, 
                                          [template_name, net])
        
    def saveSessionTemplate_step_1(self, template_name, net):
        tp_mode = ray.Template.SESSION_SAVE
        if net:
            tp_mode = ray.Template.SESSION_SAVE_NET
        
        for client in self.clients + self.trashed_clients:
            client.adjustFilesAfterCopy(template_name, tp_mode)
        
        self.message("Done")
        self.sendGuiMessage(
            _translate('GUIMSG', "...session saved as template named %s")
                % ray.highlightText(template_name))
        
        self.sendReply("Saved as template.")
        self.setServerStatus(ray.ServerStatus.READY)
    
    def saveSessionTemplateAborted(self, template_name):
        self.process_order.clear()
        self.sendReply("Session template aborted")
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
            self.sendMinorError(ray.Err.GENERAL_ERROR, 
                           _translate("error", "No template named %s")
                           % template_name)
            self.nextFunction()
            return
        
        new_session_name = basename(new_session_full_name)
        spath = "%s/%s" % (self.root, new_session_full_name)
        
        if os.path.exists(spath):
            self.sendError(ray.Err.CREATE_FAILED, 
                           _translate("error", "Folder\n%s\nalready exists")
                           % spath)
            return
        
        if self.path:
            self.setServerStatus(ray.ServerStatus.COPY)
        else:
            self.setServerStatus(ray.ServerStatus.PRECOPY)
            self.sendGui("/ray/gui/session/name",  
                         new_session_name, spath)
        
        self.sendGuiMessage(
            _translate('GUIMSG', 
                       'start copy from template to session folder'))
        
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
        if self.path:
            self.setServerStatus(ray.ServerStatus.READY)
        else:
            self.setServerStatus(ray.ServerStatus.OFF)
        
            self.setPath('')
            self.sendGui('/ray/gui/session/name', '', '')
    
    def rename(self, new_session_name):
        for client in self.clients + self.trashed_clients:
            client.adjustFilesAfterCopy(new_session_name, ray.Template.RENAME)
        
        try:
            spath = "%s/%s" % (dirname(self.path), new_session_name)
            subprocess.run(['mv', self.path, spath])
            self.setPath(spath)
            
            self.sendGuiMessage(
                _translate('GUIMSG', 'Session directory is now: %s')
                % self.path)
        except:
            pass
        
        self.nextFunction()
    
    def renameDone(self, new_session_name):
        self.sendGuiMessage(
            _translate('GUIMSG', 'Session %s has been renamed to %s .')
            % (self.name, new_session_name))
        self.sendReply("Session '%s' has been renamed to '%s' ."
                        % (self.name, new_session_name))
        self.forgetOscArgs()
    
    def preload(self, session_full_name):
        # load session data in self.future* (clients, trashed_clients, 
        #                                    session_path, session_name)
        
        spath = "%s/%s" % (self.root, session_full_name)
        if session_full_name.startswith('/'):
            spath = session_full_name
        
        if spath == self.path:
            self.loadError(ray.Err.SESSION_LOCKED)
            return
        
        if not os.path.exists(spath):
            try:
                os.makedirs(spath)
            except:
                self.loadError(ray.Err.CREATE_FAILED)
                return
        
        multi_daemon_file = MultiDaemonFile.getInstance()
        if (multi_daemon_file
                and not multi_daemon_file.isFreeForSession(spath)):
            Terminal.warning("Session %s is used by another daemon")
            self.loadError(ray.Err.SESSION_LOCKED)
            return
        
        self.message("Attempting to open %s" % spath)
        
        session_ray_file = "%s/raysession.xml" % spath
        session_nsm_file = "%s/session.nsm" % spath
        
        is_ray_file = True
        
        try:
            ray_file = open(session_ray_file, 'r')
        except:
            is_ray_file = False
            
        if not is_ray_file:
            try:
                file = open(session_nsm_file, 'r')
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
                    self.loadError(ray.Err.CREATE_FAILED)
                    return
                
        self.noFuture()
        sess_name = ""
        
        if is_ray_file:
            xml = QDomDocument()
            try:
                xml.setContent(ray_file.read())
            except:
                self.loadError(ray.Err.BAD_PROJECT)
                return
            
            content = xml.documentElement()
            
            if content.tagName() != "RAYSESSION":
                ray_file.close()
                self.loadError(ray.Err.BAD_PROJECT)
                return
            
            sess_name = content.attribute('name')
            
            client_id_list = []
            
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
                        
                        if client.client_id in client_id_list:
                            # prevent double same id
                            continue
                        
                        if tag_name == 'Clients':
                            self.future_clients.append(client)
                            
                        elif tag_name == 'RemovedClients':
                            self.future_trashed_clients.append(client)
                        else:
                            continue
                        
                        client_id_list.append(client.client_id)
                        
                elif tag_name == "Windows":
                    server = self.getServer()
                    if server and server.option_desktops_memory:
                        self.desktops_memory.readXml(node.toElement())
            
            ray_file.close()
            
        else:
            # prevent to load a locked NSM session 
            if os.path.isfile(spath + '/.lock'):
                Terminal.warning("Session %s is locked by another process")
                self.loadError(ray.Err.SESSION_LOCKED)
                return
            
            for line in file.read().split('\n'):
                elements = line.split(':')
                if len(elements) >= 3:
                    client = Client(self)
                    client.name = elements[0]
                    client.executable_path = elements[1]
                    client.client_id = elements[2]
                    client.prefix_mode = ray.PrefixMode.CLIENT_NAME
                    client.auto_start = True
                    self.future_clients.append(client)
                    
            file.close()
            self.sendGui('/ray/gui/session/is_nsm')
            
        self.future_session_path = spath
        self.future_session_name = sess_name
        
        self.nextFunction()
    
    def load(self, open_off=False):
        self.cleanExpected()
        
        future_session_short_path = self.future_session_path
        if future_session_short_path.startswith("%s/" % self.root):
            future_session_short_path = \
                future_session_short_path.replace("%s/" % self.root, '', 1)
            
        self.sendGuiMessage(_translate('GUIMSG', "-- Opening session %s --")
                                % ray.highlightText(future_session_short_path))
        
        self.setPath(self.future_session_path, self.future_session_name)
        
        if (self.future_session_name
                and self.future_session_name != os.path.basename(
                                                  self.future_session_path)):
            # session folder has been renamed
            # so rename session to it
            for client in self.future_clients + self.future_trashed_clients:
                client.adjustFilesAfterCopy(self.future_session_path,
                                            ray.Template.RENAME)
            self.setPath(self.future_session_path)
        
        for trashed_client in self.future_trashed_clients:
            self.trashed_clients.append(trashed_client)
            trashed_client.sendGuiClientProperties(removed=True)
        
        self.message("Commanding smart clients to switch")
        
        has_switch = False
        
        new_client_id_list = []
        
        for future_client in self.future_clients:
            #/* in a duplicated session, clients will have the same
            #* IDs, so be sure to pick the right one to avoid race
            #* conditions in JACK name registration. */
            for client in self.clients:
                if (client.client_id == future_client.client_id
                    and client.running_executable == future_client.executable_path
                    and client.running_arguments == future_client.arguments):
                    #we found the good existing client
                    break
            else:
                for client in self.clients:
                    if (client.running_executable == future_client.executable_path
                        and client.running_arguments == future_client.arguments):
                        #we found a switchable client
                        break
                else:
                    client = None
            
            
            if client and client.isRunning():
                if client.active and not client.isReplyPending():
                    #since we already shutdown clients not capable of 
                    #'switch', we can assume that these are.
                    client.switch(future_client)
                    has_switch = True
            else:
                #* sleep a little bit because liblo derives its sequence
                #* of port numbers from the system time (second
                #* resolution) and if too many clients start at once they
                #* won't be able to find a free port. */
                if not self.addClient(future_client):
                    continue
                    
                if future_client.auto_start and not (self.is_dummy or open_off):
                    self.clients_to_launch.append(future_client)
                    
                    if (not future_client.executable_path
                            in RS.non_active_clients):
                        self.expected_clients.append(future_client)
            
            new_client_id_list.append(future_client.client_id)
            
        self.sendGui("/ray/gui/session/name",  self.name, self.path)
        self.noFuture()
        
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
        self.sendGui('/ray/gui/session/sort_clients', *new_client_id_list)
        
        wait_time = 4000 + len(self.expected_clients) * 1000
        
        self.waitAndGoTo(wait_time, self.load_step2, ray.WaitFor.ANNOUNCE)
    
    def load_step2(self):
        for client in self.expected_clients:
            if (not client.executable_path in RS.non_active_clients):
                RS.non_active_clients.append(client.executable_path)
                
        RS.settings.setValue('daemon/non_active_list', RS.non_active_clients)
        
        self.cleanExpected()
        
        self.setServerStatus(ray.ServerStatus.OPEN)
        
        for client in self.clients:
            if client.active and client.isReplyPending():
                self.expected_clients.append(client)
            elif client.isRunning() and client.isDumbClient():
                client.setStatus(ray.ClientStatus.NOOP)
                
        if self.expected_clients:
            n_expected = len(self.expected_clients)
            if n_expected == 1:
                self.sendGuiMessage(
                    _translate('GUIMSG', 
                            'waiting for %s to load its project...')
                        % self.expected_clients[0].guiMsgStyle())
            else:
                self.sendGuiMessage(
                    _translate('GUIMSG',
                            'waiting for %s clients to load their project...')
                        % n_expected)
        
        wait_time = 8000 + len(self.expected_clients) * 2000
        for client in self.expected_clients:
            wait_time = max(2 * 1000 * client.last_open_duration, wait_time)
            
        self.waitAndGoTo(wait_time, self.load_step3, ray.WaitFor.REPLY)
        
    def load_step3(self):
        self.cleanExpected()
        
        server = self.getServer()
        if server and server.option_desktops_memory:
            self.desktops_memory.replace()
        
        self.tellAllClientsSessionIsLoaded()
        self.message('Loaded')
        self.sendGuiMessage(
            _translate('GUIMSG', 'session %s is loaded.') 
                % ray.highlightText(self.getShortPath()))
        self.sendGui("/ray/gui/session/name",  self.name, self.path)
        
        self.nextFunction()
    
    def loadDone(self):
        self.sendReply("Loaded.")
        self.message("Done")
        self.setServerStatus(ray.ServerStatus.READY)
        self.forgetOscArgs()
    
    def loadError(self, err_loading):
        self.message("Failed")
        m = _translate('Load Error', "Unknown error")
        if err_loading == ray.Err.CREATE_FAILED:
            m = _translate('Load Error', "Could not create session file!")
        elif err_loading == ray.Err.SESSION_LOCKED:
            m = _translate('Load Error', 
                           "Session is locked by another process!")
        elif err_loading == ray.Err.NO_SUCH_FILE:
            m = _translate('Load Error', "The named session does not exist.")
        elif err_loading == ray.Err.BAD_PROJECT:
            m = _translate('Load Error', "Could not load session file.")
        
        self.sendError(err_loading, m)
        
        if self.path:
            self.setServerStatus(ray.ServerStatus.READY)
        else:
            self.setServerStatus(ray.ServerStatus.OFF)
            
        self.process_order.clear()
    
    def duplicateOnlyDone(self):
        self.send(self.osc_src_addr, '/ray/net_daemon/duplicate_state', 1)
        self.forgetOscArgs()
    
    def duplicateDone(self):
        self.message("Done")
        self.sendReply("Duplicated.")
        self.setServerStatus(ray.ServerStatus.READY)
        self.forgetOscArgs()
        
    def exitNow(self):
        # here we can use self.expected_clients for scripts
        # because we are leaving
        for script in self.running_scripts:
            self.expected_clients.append(script)
            script.terminate()
                
        self.waitAndGoTo(3000, self.exitNow_step2, ray.WaitFor.QUIT)
    
    def exitNow_step2(self):
        for script in self.expected_clients:
            script.kill()
       
        self.message("Bye Bye...")
        self.setServerStatus(ray.ServerStatus.OFF)
        self.sendReply("Bye Bye...")
        self.sendGui('/ray/gui/server/disannounce')
        QCoreApplication.quit()
        
    def addClientTemplate(self, src_addr, src_path, 
                          template_name, factory=False):
        templates_root = TemplateRoots.user_clients
        if factory:
            templates_root = TemplateRoots.factory_clients
            
        xml_file = "%s/%s" % (templates_root, 'client_templates.xml')
        try:
            file = open(xml_file, 'r')
            xml = QDomDocument()
            xml.setContent(file.read())
            file.close()
        except:
            self.send(src_addr, '/error', src_path, ray.Err.NO_SUCH_FILE, 
              _translate('GUIMSG', '%s is missing or corrupted !') % xml_file)
            return
        
        if xml.documentElement().tagName() != 'RAY-CLIENT-TEMPLATES':
            self.send(src_addr, src_path, ray.Err.BAD_PROJECT, 
                _translate('GUIMSG', 
                           '%s has no RAY-CLIENT-TEMPLATES top element !')
                    % xml_file)
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
                    version_process = QProcess()
                    version_process.start(client.executable_path, ['--version'])
                    version_process.waitForFinished(500)
                    
                    if version_process.state():
                        version_process.terminate()
                        version_process.waitForFinished(500)
                        continue
                    
                    full_program_version = str(
                        version_process.readAllStandardOutput(),
                        encoding='utf-8')
                    
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
                            self.addClientTemplateAborted, 
                            [src_addr, src_path, client])
                    else:
                        self.addClientTemplate_step_1(src_addr, src_path,
                                                      client)
                    
                break
        else:
            # no template found with that name
            for favorite in RS.favorites:
                if (favorite.name == template_name
                        and favorite.factory == factory):
                    self.sendGui('/ray/gui/favorites/removed',
                                 favorite.name,
                                 int(favorite.factory))
                    RS.favorites.remove(favorite)
                    break
            
            self.send(src_addr, '/error', src_path, ray.Err.NO_SUCH_FILE,
                      _translate('GUIMSG', "%s is not an existing template !")
                        % ray.highlightText(template_name))
    
    def addClientTemplate_step_1(self, src_addr, src_path, client):
        client.adjustFilesAfterCopy(self.name, ray.Template.CLIENT_LOAD)
        
        if client.auto_start:
            client.start()
        else:
            client.setStatus(ray.ClientStatus.STOPPED)
            
        self.send(src_addr, '/reply', src_path, client.client_id)
    
    def addClientTemplateAborted(self, src_addr, src_path, client):
        self.removeClient(client)
        self.send(src_addr, '/error', src_path, ray.Err.COPY_ABORTED,
                  _translate('GUIMSG', 'Copy has been aborted !'))
        
    def closeClient(self, client):
        self.setServerStatus(ray.ServerStatus.READY)
        
        self.expected_clients.append(client)
        client.stop()
        
        self.waitAndGoTo(30000, (self.closeClient_step1, client),
                         ray.WaitFor.STOP_ONE)
        
    def closeClient_step1(self, client):
        if client in self.expected_clients:
            client.kill()
            
        self.waitAndGoTo(1000, self.nextFunction, ray.WaitFor.STOP_ONE)
        
    def loadClientSnapshot(self, client_id, snapshot):
        self.setServerStatus(ray.ServerStatus.REWIND)
        if self.snapshoter.loadClientExclusive(client_id, snapshot,
                                               self.loadClientSnapshotError):
            self.setServerStatus(ray.ServerStatus.READY)
            self.nextFunction()
    
    def loadClientSnapshotError(self, err, info_str=''):
        m = _translate('Snapshot Error', "Snapshot error")
        if err == ray.Err.SUBPROCESS_UNTERMINATED:
            m = _translate('Snapshot Error',
                           "command didn't stop normally:\n%s") % info_str
        elif err == ray.Err.SUBPROCESS_CRASH:
            m = _translate('Snapshot Error',
                           "command crashes:\n%s") % info_str
        elif err == ray.Err.SUBPROCESS_EXITCODE:
            m = _translate('Snapshot Error',
                           "command exit with an error code:\n%s") % info_str
        elif err == ray.Err.NO_SUCH_FILE:
            m = _translate('Snapshot Error',
                           "error reading file:\n%s") % info_str
        self.message(m)
        self.sendGuiMessage(m)
        self.sendError(err, m)
        
        self.setServerStatus(ray.ServerStatus.OFF)
        self.process_order.clear()
    
    def startClient(self, client):
        client.start()
        self.nextFunction()


class SignaledSession(OperatingSession):
    def __init__(self, root):
        OperatingSession.__init__(self, root)
        
        signaler.osc_recv.connect(self.oscReceive)
        signaler.script_finished.connect(self.scriptFinished)
        signaler.dummy_load_and_template.connect(self.dummyLoadAndTemplate)
        
    def oscReceive(self, path, args, types, src_addr):
        nsm_equivs = {"/nsm/server/add" : "/ray/session/add_executable",
                      "/nsm/server/save": "/ray/session/save",
                      "/nsm/server/open": "/ray/server/open_session",
                      "/nsm/server/new" : "/ray/server/new_session",
                      "/nsm/server/duplicate": "/ray/session/duplicate",
                      "/nsm/server/close": "/ray/session/close",
                      "/nsm/server/abort": "/ray/session/abort",
                      "/nsm/server/quit" : "/ray/server/quit"}
                      # /nsm/server/list is not used here because it doesn't
                      # works as /ray/server/list_sessions
        
        nsm_path = nsm_equivs.get(path)
        func_path = nsm_path if nsm_path else path
        
        func_name = func_path.replace('/', '_')
        
        if func_name in self.__dir__():
            function = self.__getattribute__(func_name)
            client_id = ''
            
            if ((func_name.startswith('ray_session_')
            #if ((func_name.startswith(('_ray_session_', '_ray_client_'))
                  and self.path)
                or func_name == '_ray_server_open_session'):
                # start custom script if any
                base_script = func_name.replace('_ray_session_', '', 1)
                script_dir = self.getScriptDir()
                
                if func_name == '_ray_server_open_session':
                    base_script = 'open'
                    session_name = args[0]
                    
                    if session_name.startswith('/'):
                        spath = session_name
                    else:
                        spath = "%s/%s" % (self.root, session_name)
                        
                    script_dir = self.getScriptDir(spath)
                        
                elif func_name.startswith('_ray_client_'):
                    client_id = args[0]
                    #base_script = "%s/%s" % (
                        #client_id, func_name.replace('_ray_client_', '', 1))
                    base_script = "client/%s" % \
                                    func_name.replace('_ray_client_', '', 1)
                                
                script_path = "%s/%s" % (script_dir, base_script)
                
                if os.access(script_path, os.X_OK):
                    for script in self.running_scripts:
                        if script.getPath() == script_path:
                            # this script is already started
                            # So, do not launch it again
                            # and run normal function.
                            break
                    else:
                        if client_id:
                            for client in self.clients:
                                if client.client_id == client_id:
                                    for script in client.running_scripts:
                                        if script.getPath() == script_path:
                                            function(path, args, src_addr)
                                            return
                                        
                                    script = Scripter(client, src_addr, path)
                                    client.running_scripts.append(script)
                                    script.start(script_path, [str(a) for a in args])
                                    break
                        else:
                            script = Scripter(self, src_addr, path)
                            self.running_scripts.append(script)
                            script.start(script_path, [str(a) for a in args])
                        return
                    
            function(path, args, src_addr)
    
    def scriptFinished(self, script_path, exit_code, client_id):
        is_stepper = False
        
        for i in range(len(self.running_scripts)):
            script = self.running_scripts[i]
            
            if (script.getPath() == script_path
                    and script.clientId() == client_id):
                if exit_code:
                    if exit_code == 101:
                        message = _translate('GUIMSG', 
                                    'script %s failed to start !') % (
                                        ray.highlightText(script_path))
                    else:
                        message = _translate('GUIMSG', 
                                'script %s terminate whit exit code %i') % (
                                    ray.highlightText(script_path), exit_code)
                    
                    if script.src_addr:
                        self.send(script.src_addr, '/error', script.src_path,
                                  - exit_code, message)
                else:
                    self.sendGuiMessage(
                        _translate('GUIMSG', '...script %s finished. ---')
                            % ray.highlightText(script_path))
                    
                    if script.src_addr:
                        self.send(script.src_addr, '/reply', script.src_path,
                                  'script finished')
                    #self.sendGui('/ray/gui/hide_script_info')
                    
                if script.isStepper():
                    is_stepper = True
                    if not script.stepperHasCalled():
                        # script has not call the next_function (save, close)
                        # so skip this next_function
                        if self.process_order:
                            self.process_order.__delitem__(0)
                
                if script.clientId() and script.pendingCommand():
                    for client in self.clients:
                        if client.client_id == script.clientId():
                            client.pending_command = ray.Command.NONE
                            break
                    
                break
        else:
            return
        
        self.running_scripts.remove(script)
        del script
        
        if is_stepper:
            self.nextFunction()
    
    def sendErrorNoClient(self, src_addr, path, client_id):
        self.send(src_addr, "/error", path, ray.Err.CREATE_FAILED,
                  _translate('GUIMSG', "No client with this client_id:%s")
                    % client_id)
    
    def sendErrorCopyRunning(self, src_addr, path):
        self.send(src_addr, "/error", path, ray.Err.COPY_RUNNING,
                  _translate('GUIMSG', "Impossible, copy running !"))
    
    ############## FUNCTIONS CONNECTED TO SIGNALS FROM OSC ###################
    
    def _nsm_server_announce(self, path, args, src_addr):
        client_name, capabilities, executable_path, major, minor, pid = args
        
        if self.wait_for == ray.WaitFor.QUIT:
            if path.startswith('/nsm/server/'):
                # Error is wrong but compatible with NSM API
                self.send(src_addr, "/error", path, ray.Err.NO_SESSION_OPEN, 
                          "Sorry, but there's no session open "
                          + "for this application to join.")
            return
        
        #we can't be absolutely sure that the announcer is the good one
        #but if client announce a known PID, 
        #we can be sure of which client is announcing
        for client in self.clients: 
            if client.pid == pid and not client.active and client.isRunning():
                client.serverAnnounce(path, args, src_addr, False)
                break
        else:
            for client in self.clients:
                if (not client.active and client.isRunning()
                    and ray.isPidChildOf(pid, client.pid)):
                        client.serverAnnounce(path, args, src_addr, False)
                        break
            else:
                # Client launched externally from daemon
                # by command : $:NSM_URL=url executable
                client = self.newClient(args[2])
                self.externals_timer.start()
                client.serverAnnounce(path, args, src_addr, True)
            
            
            
            
            #n = 0
            #for client in self.clients:
                #if (basename(client.executable_path) \
                        #== basename(executable_path)
                    #and not client.active
                    #and client.pending_command == ray.Command.START):
                        #n+=1
                        #if n>1:
                            #break
                        
            #if n == 0:
                ## Client launched externally from daemon
                ## by command : $:NSM_URL=url executable
                #client = self.newClient(args[2])
                #client.is_external = True
                #self.externals_timer.start()
                #client.serverAnnounce(path, args, src_addr, True)
                #return
                
            #elif n == 1:
                #for client in self.clients:
                    #if (basename(client.executable_path) \
                            #== basename(executable_path)
                        #and not client.active
                        #and client.pending_command == ray.Command.START):
                            #client.serverAnnounce(path, args, src_addr, False)
                            #break
            #else:
                #for client in self.clients:
                    #if (not client.active
                        #and client.pending_command == ray.Command.START):
                            #if ray.isPidChildOf(pid, client.pid):
                                #client.serverAnnounce(path, args, 
                                                      #src_addr, False)
                                #break
        
        if self.wait_for == ray.WaitFor.ANNOUNCE:
            self.endTimerIfLastExpected(client)
    
    def _reply(self, path, args, src_addr):
        if self.wait_for == ray.WaitFor.QUIT:
            return
        
        message = args[1]
        client = self.getClientByAddress(src_addr)
        if client:
            client.setReply(ray.Err.OK, message)
            
            server = self.getServer()
            if (server 
                    and server.getServerStatus() == ray.ServerStatus.READY
                    and server.option_desktops_memory):
                self.desktops_memory.replace()
        else:
            self.message("Reply from unknown client")
    
    def _error(self, path, args, src_addr):
        path, errcode, message = args
        
        client = self.getClientByAddress(src_addr)
        if client:
            client.setReply(errcode, message)
            
            if self.wait_for == ray.WaitFor.REPLY:
                self.endTimerIfLastExpected(client)
        else:
            self.message("error from unknown client")
    
    def _nsm_client_is_clean(self, path, args, src_addr):
        # save session from client clean (not dirty) message
        if self.process_order:
            return 
        
        if self.file_copier.isActive():
            return 
        
        self.rememberOscArgs(path, args, None)
        
        client = self.getClientByAddress(src_addr)
        if not client:
            return
        
        self.process_order = [(self.save, client.client_id),
                              self.snapshot,
                              self.saveDone]
        self.nextFunction()
    
    def _nsm_client_label(self, path, args, src_addr):
        client = self.getClientByAddress(src_addr)
        if client:
            client.setLabel(args[0])
    
    def _nsm_client_network_properties(self, path, args, src_addr):
        client = self.getClientByAddress(src_addr)
        if client:
            net_daemon_url, net_session_root = args
            client.setNetworkProperties(net_daemon_url, net_session_root)
    
    def _nsm_client_no_save_level(self, path, args, src_addr):
        client = self.getClientByAddress(src_addr)
        if client and client.isCapableOf(':warning-no-save:'):
            client.no_save_level = args[0]
            
            self.sendGui('/ray/gui/client/no_save_level',
                         client.client_id, client.no_save_level)
    
    def _ray_server_abort_copy(self, path, args, src_addr):
        self.file_copier.abort()
    
    def _ray_server_abort_snapshot(self, path, args, src_addr):
        self.snapshoter.abort()
    
    def _ray_server_change_root(self, path, args, src_addr):
        session_root = args[0]
        if self.path:
            self.send(src_addr, '/error', path, ray.Err.SESSION_LOCKED,
                      "impossible to change root. session %s is loaded"
                        % self.path)
            return
        
        if not os.path.exists(session_root):
            try:
                os.makedirs(session_root)
            except:
                self.send(src_addr, '/error', path, ray.Err.CREATE_FAILED,
                          "invalid session root !")
                return
        
        if not os.access(session_root, os.W_OK):
            self.send(src_addr, '/error', path, ray.Err.CREATE_FAILED,
                      "unwriteable session root !")
            return
        
        self.root = session_root
        
        multi_daemon_file = MultiDaemonFile.getInstance()
        if multi_daemon_file:
            multi_daemon_file.update()
            
        self.send(src_addr, '/reply', path, 
                  "root folder changed to %s" % self.root)
        self.sendGui('/ray/gui/server/root', self.root)
    
    def _ray_server_list_sessions(self, path, args, src_addr):
        with_net = False
        if args:
            with_net = args[0]
        
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
            
            already_sent = False
            
            for file in files:
                if file in ('raysession.xml', 'session.nsm'):
                    if not already_sent:
                        basefolder = root.replace(self.root + '/', '', 1)
                        session_list.append(basefolder)
                        if len(session_list) == 20:
                            self.send(src_addr, "/reply", path,
                                      *session_list)
                            
                            session_list.clear()
                        already_sent = True
                    
        if session_list:
            self.send(src_addr, "/reply", path, *session_list)
            
        self.send(src_addr, "/reply", path)
    
    def _nsm_server_list(self, path, args, src_addr):
        session_list = []
        
        if self.root:
            for root, dirs, files in os.walk(self.root):
                #exclude hidden files and dirs
                files   = [f for f in files if not f.startswith('.')]
                dirs[:] = [d for d in dirs  if not d.startswith('.')]
                
                if root == self.root:
                    continue
                
                for file in files:
                    if file in ('raysession.xml', 'session.nsm'):
                        basefolder = root.replace(self.root + '/', '', 1)
                        self.send(src_addr, '/reply', '/nsm/server/list',
                                basefolder)
                        
        self.send(src_addr, path, ray.Err.OK, "Done.")
    
    @session_operation
    def _ray_server_new_session(self, path, args, src_addr):
        if len(args) == 2 and args[1]:
            session_name, template_name = args
            
            spath = ''
            if session_name.startswith('/'):
                spath = session_name
            else:
                spath = "%s/%s" % (self.root, session_name)
            
            if not os.path.exists(spath):
                self.process_order = [self.save,
                                      self.closeNoSaveClients,
                                      self.snapshot,
                                      (self.prepareTemplate, *args, False), 
                                      (self.load, session_name),
                                       self.newDone]
                return
        
        self.process_order = [self.save,
                              self.closeNoSaveClients,
                              self.snapshot,
                              self.close,
                              (self.new, args[0]),
                              self.save,
                              self.newDone]
    
    @session_operation
    def _ray_server_open_session(self, path, args, src_addr, open_off=False):
        session_name = args[0]
        save_previous = True
        template_name = ''
        
        if len(args) >= 2:
            save_previous = bool(args[1])
        if len(args) >= 3:
            template_name = args[2]
            
        if (not session_name
                or '//' in session_name
                or session_name.startswith(('../', '.ray-', 'ray-'))):
            self.sendError(ray.Err.CREATE_FAILED, 'invalid session name.')
            return
        
        if template_name:
            if '/' in template_name:
                self.sendError(ray.Err.CREATE_FAILED, 'invalid template name')
                return
            
        spath = ''
        if session_name.startswith('/'):
            spath = session_name
        else:
            spath = "%s/%s" % (self.root, session_name)
        
        if spath == self.path:
            self.sendError(ray.Err.SESSION_LOCKED,
                _translate('GUIMSG', 'session %s is already opened !')
                    % ray.highlightText(session_name))
            return
        
        multi_daemon_file = MultiDaemonFile.getInstance()
        if (multi_daemon_file
                and not multi_daemon_file.isFreeForSession(spath)):
            Terminal.warning("Session %s is used by another daemon"
                              % ray.highlightText(spath))
            
            self.sendError(ray.Err.SESSION_LOCKED,
                _translate('GUIMSG', 
                    'session %s is already used by another daemon !')
                        % ray.highlightText(session_name))
            return
        
        # don't use template if session folder already exists
        if os.path.exists(spath):
            template_name = ''
        
        self.process_order = []
        
        if save_previous:
            self.process_order += [(self.save, '', True)]
        
        self.process_order += [self.closeNoSaveClients]
        
        if save_previous:
            self.process_order += [(self.snapshot, '', '', False, True)]
        
        if template_name:
            self.process_order += [(self.prepareTemplate, session_name, 
                                    template_name, True)]
        
        self.process_order += [(self.preload, session_name),
                               (self.close, open_off),
                               (self.load, open_off),
                               self.loadDone]
    
    def _ray_server_open_session_off(self, path, args, src_addr):
        self._ray_server_open_session(path, args, src_addr, True)
    
    def _ray_server_rename_session(self, path, args, src_addr):
        tmp_session = DummySession(self.root)
        tmp_session.ray_server_rename_session(path, args, src_addr)
    
    @session_operation
    def _ray_session_save(self, path, args, src_addr):
        self.process_order = [self.save, self.snapshot, self.saveDone]
    
    @session_operation
    def _ray_session_save_as_template(self, path, args, src_addr):
        template_name = args[0]
        net = False if len(args) < 2 else args[1]
        
        for client in self.clients:
            if client.executable_path == 'ray-network':
                client.net_session_template = template_name
        
        self.process_order = [self.save, self.snapshot,
                              (self.saveSessionTemplate, 
                               template_name, net)]
                              
    def _ray_server_save_session_template(self, path, args, src_addr):
        if len(args) == 2:
            session_name, template_name = args
            sess_root = self.root
            net=False
        else:
            session_name, template_name, sess_root = args
            net=True
        
        tmp_session = DummySession(sess_root)
        tmp_session.ray_server_save_session_template(path, 
                                [session_name, template_name, net], 
                                src_addr)
        
        #if (sess_root != self.root or session_name != self.name):
            #tmp_session = DummySession(sess_root)
            #tmp_session.ray_server_save_session_template(path, 
                                #[session_name, template_name, net], 
                                #src_addr)
            #return
        
        #self.ray_session_save_as_template(path, [template_name, net],
                                          #src_addr)
                                          
                                          
        #if net:
            #for client in self.clients:
                #if client.executable_path == 'ray-network':
                    #client.net_session_template = template_name
        
        #self.rememberOscArgs()
        #self.process_order = [self.save, self.snapshot,
                              #(self.saveSessionTemplate, template_name, net)]
        #self.nextFunction()
    
    @session_operation
    def _ray_session_take_snapshot(self, path, args, src_addr):
        snapshot_name, with_save = args
            
        self.process_order.clear()
        
        if with_save:
            self.process_order.append(self.save)
        self.process_order += [(self.snapshot, snapshot_name, '', True),
                               self.snapshotDone]
    
    @session_operation
    def _ray_session_close(self, path, args, src_addr):
        self.process_order = [(self.save, '', True),
                              self.closeNoSaveClients,
                              self.snapshot,
                              self.close,
                              self.closeDone]
    
    def _ray_session_abort(self, path, args, src_addr):
        if not self.path:
            self.send(src_addr, "/error", path, ray.Err.NO_SESSION_OPEN,
                      "No session to abort." )
            return
        
        self.wait_for = ray.WaitFor.NONE
        self.timer.stop()
        
        # Non Session Manager can't abort if an operation pending
        # RS can and it would be a big regression to remove this feature
        # So before to abort we need to send an error reply
        # to the last server control message
        # if an operation pending.
        
        if self.process_order:
            if self.osc_path.startswith('/nsm/server/'):
                short_path = self.osc_path.rpartition('/')[2]
                
                if short_path == 'save':
                    self.saveError(ray.Err.CREATE_FAILED)
                elif short_path == 'open':
                    self.loadError(ray.Err.SESSION_LOCKED)
                elif short_path == 'new':
                    self.sendError(ray.Err.CREATE_FAILED, 
                                "Could not create the session directory")
                elif short_path == 'duplicate':
                    self.duplicateAborted(self.osc_args[0])
                elif short_path in ('close', 'abort', 'quit'):
                    # let the current close works here
                    self.send(src_addr, "/error", path, 
                              ray.Err.OPERATION_PENDING,
                              "An operation pending.")
                    return
            else:
                self.sendError(ray.Err.ABORT_ORDERED, 
                               _translate('GUIMSG',
                                    'abort ordered from elsewhere, sorry !'))
        
        self.rememberOscArgs(path, args, src_addr)
        self.process_order = [self.close, self.abortDone]
        
        if self.file_copier.isActive():
            self.file_copier.abort(self.nextFunction, [])
        else:
            self.nextFunction()
    
    def _ray_server_quit(self, path, args, src_addr):
        self.rememberOscArgs(path, args, src_addr)
        self.process_order = [self.close, self.exitNow]
        
        if self.file_copier.isActive():
            self.file_copier.abort(self.nextFunction, [])
        else:
            self.nextFunction()
    
    def _ray_session_cancel_close(self, path, args, src_addr):
        if not self.process_order:
            return 
        
        self.timer.stop()
        self.timer_waituser_progress.stop()
        self.process_order.clear()
        self.cleanExpected()
        self.setServerStatus(ray.ServerStatus.READY)
        
    def _ray_session_skip_wait_user(self, path, args, src_addr):
        if not self.process_order:
            return 
        
        self.timer.stop()
        self.timer_waituser_progress.stop()
        self.cleanExpected()
        self.nextFunction()
    
    @session_operation
    def _ray_session_duplicate(self, path, args, src_addr):
        new_session_full_name = args[0]
        
        spath = ''
        if new_session_full_name.startswith('/'):
            spath = new_session_full_name
        else:
            spath = "%s/%s" % (self.root, new_session_full_name)
        
        if os.path.exists(spath):
            self.sendError(ray.Err.CREATE_FAILED, 
                _translate('GUIMSG', "%s already exists !")
                    % ray.highlightText(spath))
            return
        
        multi_daemon_file = MultiDaemonFile.getInstance()
        if (multi_daemon_file
                and not multi_daemon_file.isFreeForSession(spath)):
            Terminal.warning("Session %s is used by another daemon"
                             % ray.highlightText(new_session_full_name))
            self.sendError(ray.Err.SESSION_LOCKED,
                _translate('GUIMSG', 
                    'session %s is already used by this or another daemon !')
                        % ray.highlightText(new_session_full_name))
            return
        
        self.process_order = [self.save,
                              self.closeNoSaveClients,
                              self.snapshot,
                              (self.duplicate, new_session_full_name),
                              (self.preload, new_session_full_name),
                              self.close,
                              self.load, 
                              self.duplicateDone]
        
    def _ray_session_duplicate_only(self, path, args, src_addr):
        session_to_load, new_session, sess_root = args
        
        spath = ''
        if new_session.startswith('/'):
            spath = new_session
        else:
            spath = "%s/%s" % (sess_root, new_session)
        
        if os.path.exists(spath):
            self.send(src_addr, '/ray/net_daemon/duplicate_state', 1)
            self.send(src_addr, '/error', path, ray.Err.CREATE_FAILED, 
                      _translate('GUIMSG', "%s already exists !")
                        % ray.highlightText(spath))
            return
        
        if sess_root == self.root and session_to_load == self.getShortPath():
            if (self.process_order
                or self.file_copier.isActive()):
                    self.send(src_addr, '/ray/net_daemon/duplicate_state', 1)
                    return
            
            self.rememberOscArgs(path, args, src_addr)
            
            self.process_order = [self.save,
                                  self.snapshot,
                                  (self.duplicate, new_session),
                                  self.duplicateOnlyDone]
            
            self.nextFunction()
        
        else:
            tmp_session = DummySession(sess_root)
            tmp_session.osc_src_addr = src_addr
            tmp_session.dummyDuplicate(session_to_load, new_session)
    
    @session_operation
    def _ray_session_open_snapshot(self, path, args, src_addr):
        if not self.path:
            return 
        
        snapshot = args[0]
        
        self.process_order = [self.save,
                              self.closeNoSaveClients,
                              (self.snapshot, '', snapshot, True),
                              (self.close, True)
                              (self.initSnapshot, self.path, snapshot),
                              (self.preload, self.path),
                              self.load,
                              self.loadDone]
    
    def _ray_session_rename(self, path, args, src_addr):
        new_session_name = args[0]
        
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
                    # another directory exists with new session name
                    return
        
        for client in self.clients:
            if client.isRunning():
                self.sendGuiMessage(
                    _translate('GUIMSG', 
                               'Stop all clients before rename session !'))
                return
        
        for client in self.clients + self.trashed_clients:
            client.adjustFilesAfterCopy(new_session_name, ray.Template.RENAME)
        
        if not self.isNsmLocked():
            try:
                spath = "%s/%s" % (dirname(self.path), new_session_name)
                subprocess.run(['mv', self.path, spath])
                self.setPath(spath)
                
                self.sendGuiMessage(
                    _translate('GUIMSG', 'Session directory is now: %s')
                    % self.path)
            except:
                pass
        
        self.sendGuiMessage(
            _translate('GUIMSG', 'Session %s has been renamed to %s .')
            % (self.name, new_session_name))
        self.sendGui('/ray/gui/session/name', self.name, self.path)
    
    def _ray_session_add_executable(self, path, args, src_addr):
        executable = args[0]
        via_proxy = 0
        prefix_mode = ray.PrefixMode.SESSION_NAME
        custom_prefix = ''
        client_id = ""
        start_it = True
        
        if len(args) == 2 and args[1] == 'not_auto_start':
            start_it = False
        
        if len(args) == 5:
            executable, via_proxy, prefix_mode, custom_prefix, client_id = args
            
            if prefix_mode == ray.PrefixMode.CUSTOM and not custom_prefix:
                prefix_mode = ray.PrefixMode.SESSION_NAME
            
            if client_id:
                if not client_id.replace('_', '').isalnum():
                    self.sendError(ray.Err.CREATE_FAILED,
                            _translate("error", "client_id %s is not alphanumeric")
                                % client_id )
                    return
                
                # Check if client_id already exists
                for client in self.clients + self.trashed_clients:
                    if client.client_id == client_id:
                        self.sendError(ray.Err.CREATE_FAILED,
                            _translate("error", "client_id %s is already used")
                                % client_id )
                        return
        
        if not client_id:
            client_id = self.generateClientId(executable)
            
        client = Client(self)
        
        if via_proxy:
            client.executable_path = 'ray-proxy'
            client.tmp_arguments = "--executable %s" % executable
        else:
            client.executable_path = executable
        
        client.name = basename(executable)
        client.client_id = client_id
        client.prefix_mode = prefix_mode
        client.custom_prefix = custom_prefix
        client.icon = client.name.lower().replace('_', '-')
        client.setDefaultGitIgnored(executable)
        
        if self.addClient(client):
            if start_it:
                client.start()
            self.send(src_addr, '/reply', path, client.client_id)
    
    def _ray_session_add_proxy(self, path, args, src_addr):
        executable = args[0]
        
        client = Client(self)
        client.executable_path = 'ray-proxy'
        
        client.tmp_arguments  = "--executable %s" % executable
        if CommandLineArgs.debug:
            client.tmp_arguments += " --debug"
            
        client.name      = basename(executable)
        client.client_id = self.generateClientId(client.name)
        client.icon      = client.name.lower().replace('_', '-')
        client.setDefaultGitIgnored(executable)
        
        if self.addClient(client):
            client.start()
            self.send(src_addr, '/reply', path, client.client_id)
    
    def _ray_session_add_client_template(self, path, args, src_addr):
        self.rememberOscArgs(path, args, src_addr)
        
        factory = bool(args[0])
        template_name = args[1]
        
        self.addClientTemplate(src_addr, path, template_name, factory)
    
    def _ray_session_reorder_clients(self, path, args, src_addr):
        client_ids_list = args
        
        if not self.path:
            self.send(src_addr, '/error', path, ray.Err.NO_SESSION_OPEN,
                      "no session to reorder clients")
        
        if len(self.clients) < 2:
            self.send(src_addr, '/reply', path, "clients reordered")
            return
        
        self.reOrderClients(client_ids_list, src_addr, path)
    
    def _ray_session_list_snapshots(self, path, args, src_addr, client_id=""):
        if not self.path:
            self.send(src_addr, '/error', path, ray.Err.NO_SESSION_OPEN,
                      "no session to list snapshots")
            return
        
        auto_snapshot = not bool(
            self.snapshoter.isAutoSnapshotPrevented())
        self.sendGui('/ray/gui/session/auto_snapshot',  int(auto_snapshot))
        
        snapshots = self.snapshoter.list(client_id)
        
        i=0
        snap_send = []
        
        for snapshot in snapshots:
            if i == 20:
                self.send(src_addr, '/reply', path, *snap_send)
                
                snap_send.clear()
                i=0
            else:
                snap_send.append(snapshot)
                i+=1
        
        if snap_send:
            self.send(src_addr, '/reply', path, *snap_send)
        self.send(src_addr, '/reply', path)
        
    def _ray_session_set_auto_snapshot(self, path, args, src_addr):
        self.snapshoter.setAutoSnapshot(bool(args[0]))
    
    def _ray_session_list_clients(self, path, args, src_addr):
        if not self.path:
            self.send(src_addr, '/error', path, ray.Err.NO_SESSION_OPEN,
                      _translate('GUIMSG', 'No session to list clients !'))
            return 
        
        f_started = -1
        f_active = -1
        f_auto_start = -1
        f_no_save_level = -1
        
        search_properties = []
        
        for arg in args:
            cape = 1
            if arg.startswith('not_'):
                cape = 0
                arg = arg.replace('not_', '', 1)
            
            if ':' in arg:
              search_properties.append((cape, arg))
            
            elif arg == 'started':
                f_started = cape
            elif arg == 'active':
                f_active = cape
            elif arg == 'auto_start':
                f_auto_start = cape
            elif arg == 'no_save_level':
                f_no_save_level = cape
                
        client_id_list = []
        
        for client in self.clients:
            if ((f_started < 0 or f_started == client.isRunning())
                and (f_active < 0 or f_active == client.active)
                and (f_auto_start < 0 or f_auto_start == client.auto_start)
                and (f_no_save_level < 0 
                     or f_no_save_level == int(bool(client.no_save_level)))):
                if search_properties:
                    message = client.getPropertiesMessage()
                    
                    for cape, search_prop in search_properties:
                        line_found = False
                        
                        for line in message.split('\n'):
                            if line == search_prop:
                                line_found = True
                                break
                            
                        if cape != line_found:
                            break
                    else:
                        client_id_list.append(client.client_id)
                else:
                    client_id_list.append(client.client_id)
                    
        if client_id_list:
            self.send(src_addr, '/reply', path, *client_id_list)
        self.send(src_addr, '/reply', path)
    
    def _ray_session_list_trashed_clients(self, path, args, src_addr):
        client_id_list = []
        
        for trashed_client in self.trashed_clients:
            client_id_list.append(trashed_client.client_id)
            
        if client_id_list:
            self.send(src_addr, '/reply', path, *client_id_list)
        self.send(src_addr, '/reply', path)
    
    def _ray_session_process_step(self, path, args, src_addr):
        if not self.process_order:
            self.send(src_addr, '/error', ray.Err.GENERAL_ERROR,
                      'No operation pending !')
            return
        
        self.process_step_addr = src_addr
        self.nextFunction(True)
        #self.send(src_addr, '/reply', path, 'good') 
    
    def _ray_client_stop(self, path, args, src_addr):
        client_id = args[0]
        
        for client in self.clients:
            if client.client_id == client_id:
                client.stop(src_addr, path)
                break
        else:
            self.sendErrorNoClient(src_addr, path, client_id)
    
    def _ray_client_kill(self, path, args, src_addr):
        client_id = args[0]
        
        for client in self.clients:
            if client.client_id == client_id:
                client.kill()
                self.send(src_addr, "/reply", path, "Client killed." )
                break
        else:
            self.sendErrorNoClient(src_addr, path, client_id)
    
    def _ray_client_trash(self, path, args, src_addr):
        client_id = args[0]
        
        for client in self.clients:
            if client.client_id == client_id:
                if client.isRunning():
                    self.send(src_addr, '/error', path, ray.Err.OPERATION_PENDING,
                              "Stop client before to trash it !")
                    return
                
                if self.file_copier.isActive(client_id):
                    self.file_copier.abort()
                    self.send(src_addr, '/error', path, ray.Err.COPY_RUNNING,
                              "Files were copying for this client.")
                    return
                
                self.trashClient(client)
                
                self.send(src_addr, "/reply", path, "Client removed.")
                break
        else:
            self.sendErrorNoClient(src_addr, path, client_id)
    
    def _ray_client_start(self, path, args, src_addr):
        self._ray_client_resume(path, args, src_addr)
    
    def _ray_client_resume(self, path, args, src_addr):
        client_id = args[0]
        
        for client in self.clients:
            if client.client_id == client_id:
                if client.isRunning():
                    self.sendGuiMessage(
                        _translate('GUIMSG', 'client %s is already running.')
                            % client.guiMsgStyle())
                    
                    # make ray_control exit code 0 in this case
                    self.send(src_addr, '/reply', path, 'client running')
                    return
                    
                if self.file_copier.isActive(client.client_id):
                    self.sendErrorCopyRunning(src_addr, path)
                    return
                
                client.start(src_addr, path)
                break
        else:
            self.sendErrorNoClient(src_addr, path, client_id)
    
    def _ray_client_open(self, path, args, src_addr):
        client_id = args[0]
        
        for client in self.clients:
            if client.client_id == client_id:
                if self.file_copier.isActive(client.client_id):
                    self.sendErrorCopyRunning(src_addr, path)
                    return
                
                if client.active:
                    self.sendGuiMessage(
                        _translate('GUIMSG', 'client %s is already active.')
                            % client.guiMsgStyle())
                    
                    # make ray_control exit code 0 in this case
                    self.send(src_addr, '/reply', path, 'client active')
                else:
                    client.load(src_addr, path)
                break
        else:
            self.sendErrorNoClient(src_addr, path, client_id)
    
    def _ray_client_save(self, path, args, src_addr):
        client_id = args[0]
        
        for client in self.clients:
            if client.client_id == client_id:
                if client.active and not client.no_save_level:
                    if self.file_copier.isActive(client.client_id):
                        self.sendErrorCopyRunning(src_addr, path)
                        return
                    client.save(src_addr, path)
                else:
                    self.sendGuiMessage(_translate('GUIMSG',
                                                   "%s is not saveable.")
                                            % client.guiMsgStyle())
                    self.send(src_addr, '/reply', path, 'client saved')
                break
        else:
            self.sendErrorNoClient(src_addr, path, client_id)
    
    def _ray_client_save_as_template(self, path, args, src_addr):
        client_id, template_name = args
        
        if self.file_copier.isActive():
            self.sendErrorCopyRunning(src_addr, path)
            return
        
        for client in self.clients:
            if client.client_id == client_id:
                client.saveAsTemplate(template_name, src_addr, path)
                break
        else:
            self.sendErrorNoClient(src_addr, path, client_id)
    
    def _ray_client_show_optional_gui(self, path, args, src_addr):
        client_id = args[0]
        
        for client in self.clients:
            if client.client_id == client_id:
                client.sendToSelfAddress("/nsm/client/show_optional_gui")
                self.send(src_addr, '/reply', path, 'show optional GUI asked')
                break
        else:
            self.sendErrorNoClient(src_addr, path, client_id)
    
    def _ray_client_hide_optional_gui(self, path, args, src_addr):
        client_id = args[0]
        
        for client in self.clients:
            if client.client_id == client_id:
                client.sendToSelfAddress("/nsm/client/hide_optional_gui")
                self.send(src_addr, '/reply', path, 'hide optional GUI asked')
                break
        else:
            self.sendErrorNoClient(src_addr, path, client_id)
    
    def _ray_client_update_properties(self, path, args, src_addr):
        client_data = ray.ClientData(*args)
        
        for client in self.clients:
            if client.client_id == client_data.client_id:
                client.updateClientProperties(client_data)
                self.send(src_addr, '/reply', path,
                          'client properties updated')
                break
        else:
            self.sendErrorNoClient(src_addr, path, client_data.client_id)
    
    def _ray_client_set_properties(self, path, args, src_addr):
        client_id = args.pop(0)
        
        message = ''
        
        for arg in args:
            message+="%s\n" % arg
        
        for client in self.clients:
            if client.client_id == client_id:
                client.setPropertiesFromMessage(message)
                self.send(src_addr, '/reply', path,
                          'client properties updated')
                break
        else:
            self.sendErrorNoClient(src_addr, path, client_id)
    
    def _ray_client_get_properties(self, path, args, src_addr):
        client_id = args[0]
        
        for client in self.clients:
            if client.client_id == client_id:
                message = client.getPropertiesMessage()
                self.send(src_addr, '/reply', path, message)
                self.send(src_addr, '/reply', path)
                break
        else:
            self.sendErrorNoClient(src_addr, path, client_id)
    
    def _ray_client_get_proxy_properties(self, path, args, src_addr):
        client_id = args[0]
        
        for client in self.clients:
            if client.client_id == client_id:
                proxy_file = '%s/ray-proxy.xml' % client.getProjectPath()
                
                if not os.path.isfile(proxy_file):
                    self.send(src_addr, '/error', path, ray.Err.GENERAL_ERROR,
                        _translate('GUIMSG',
                                   '%s seems to not be a proxy client !')
                            % client.guiMsgStyle())
                    return
                
                try:
                    file = open(proxy_file, 'r')
                    xml = QDomDocument()
                    xml.setContent(file.read())
                    content = xml.documentElement()
                    file.close()
                except:
                    self.send(src_addr, '/error', path, ray.Err.BAD_PROJECT,
                        _translate('GUIMSG',
                                   "impossible to read %s correctly !")
                            % proxy_file)
                    return
                    
                if content.tagName() != "RAY-PROXY":
                    self.send(src_addr, '/error', path, ray.Err.BAD_PROJECT,
                        _translate('GUIMSG',
                                   "impossible to read %s correctly !")
                            % proxy_file)
                    return
                    
                cte = content.toElement()
                message = ""
                for property in ('executable', 'arguments', 'config_file',
                                    'save_signal', 'stop_signal',
                                    'no_save_level', 'wait_window',
                                    'VERSION'):
                    message += "%s:%s\n" % (property, cte.attribute(property))
                
                # remove last empty line
                message = message.rpartition('\n')[0]
                
                self.send(src_addr, '/reply', path, message)
                self.send(src_addr, '/reply', path)
                    
                break
        else:
            self.sendErrorNoClient(src_addr, path, client_id)
    
    def _ray_client_set_proxy_properties(self, path, args, src_addr):
        client_id = args.pop(0)
        
        message=''
        for arg in args:
            message+= "%s\n" % arg
            
        for client in self.clients:
            if client.client_id == client_id:
                proxy_file = '%s/ray-proxy.xml' % client.getProjectPath()
                
                if not os.path.isfile(proxy_file):
                    self.send(src_addr, '/error', path, ray.Err.GENERAL_ERROR,
                        _translate('GUIMSG',
                                   '%s seems to not be a proxy client !')
                            % client.guiMsgStyle())
                    return
                
                try:
                    file = open(proxy_file, 'r')
                    xml = QDomDocument()
                    xml.setContent(file.read())
                    content = xml.documentElement()
                    file.close()
                except:
                    self.send(src_addr, '/error', path, ray.Err.BAD_PROJECT,
                        _translate('GUIMSG',
                                   "impossible to read %s correctly !")
                            % proxy_file)
                    return
                    
                if content.tagName() != "RAY-PROXY":
                    self.send(src_addr, '/error', path, ray.Err.BAD_PROJECT,
                        _translate('GUIMSG',
                                   "impossible to read %s correctly !")
                            % proxy_file)
                    return
                    
                cte = content.toElement()
                
                for line in message.split('\n'):
                    property, colon, value = line.partition(':')
                    if property in ('executable', 'arguments', 
                            'config_file', 'save_signal', 'stop_signal',
                            'no_save_level', 'wait_window', 'VERSION'):
                        cte.setAttribute(property, value)
                
                try:
                    file = open(proxy_file, 'w')
                    file.write(xml.toString())
                    file.close()
                except:
                    self.send(src_addr, '/error', path, ray.Err.BAD_PROJECT,
                        _translate('GUIMSG',
                                   "%s is not writeable")
                            % proxy_file)
                    return
                
                self.send(src_addr, '/reply', path, message)
                self.send(src_addr, '/reply', path)
                    
                break
        else:
            self.sendErrorNoClient(src_addr, path, client_id)
    
    def _ray_client_list_files(self, path, args, src_addr):
        client_id = args[0]
        
        for client in self.clients:
            if client.client_id == client_id:
                client_files = client.getProjectFiles()
                self.send(src_addr, '/reply', path, *client_files)
                self.send(src_addr, '/reply', path)
                break
        else:
            self.sendErrorNoClient(src_addr, path, client_id)
    
    def _ray_client_list_snapshots(self, path, args, src_addr):
        self._ray_session_list_snapshots(path, [], src_addr, args[0])
    
    @session_operation
    def _ray_client_open_snapshot(self, path, args, src_addr):
        client_id, snapshot = args
        
        for client in self.clients:
            if client.client_id == client_id:
                if client.isRunning():
                    self.process_order = [
                        self.save,
                        (self.snapshot, '', snapshot, True),
                        (self.closeClient, client),
                        (self.loadClientSnapshot, client_id, snapshot),
                        (self.startClient, client)]
                else:
                    self.process_order = [
                        self.save,
                        (self.snapshot, '', snapshot, True),
                        (self.loadClientSnapshot, client_id, snapshot)]
                break
        else:
            self.sendErrorNoClient(src_addr, path, client_id)
    
    def _ray_client_is_started(self, path, args, src_addr):
        client_id = args[0]
        
        for client in self.clients:
            if client.client_id == client_id:
                if client.isRunning():
                    self.sendGuiMessage(
                        _translate('GUIMSG', '%s is running.')
                            % client.guiMsgStyle())
                    self.send(src_addr, '/reply', path, 'client running')
                else:
                    self.send(src_addr, '/error', path, ray.Err.GENERAL_ERROR,
                              _translate('GUIMSG', '%s is not running.')
                                % client.guiMsgStyle())
                break
        else:
            self.sendErrorNoClient(src_addr, path, client_id)
    
    def _ray_trashed_client_restore(self, path, args, src_addr):
        if not self.path:
            self.send(src_addr, "/error", path, ray.Err.NO_SESSION_OPEN,
                      "Cannot add to session because no session is loaded.")
            return
        
        for client in self.trashed_clients:
            if client.client_id == args[0]:
                self.restoreClient(client)
                self.send(src_addr, '/reply', path, "client restored")
                break
        else:
            self.send(src_addr, "/error", path, -10, "No such client.")
    
    def _ray_trashed_client_remove_definitely(self, path, args, src_addr):
        if not self.path:
            self.send(src_addr, "/error", path, ray.Err.NO_SESSION_OPEN,
                      "Cannot add to session because no session is loaded.")
            return
        
        for client in self.trashed_clients:
            if client.client_id == args[0]:
                break
        else:
            self.send(src_addr, "/error", path, -10, "No such client.")
            return
        
        self.sendGui('/ray/gui/trash/remove', client.client_id)
        
        for file in client.getProjectFiles():
            try:
                subprocess.run(['rm', '-R', file])
            except:
                self.send(src_addr, '/minor_error', path,  -10, 
                          "Error while removing client file %s" % file)
                continue
            
        self.trashed_clients.remove(client)
        
        self.send(src_addr, '/reply', path, "client definitely removed") 
    
    def _ray_net_daemon_duplicate_state(self, path, args, src_addr):
        state = args[0]
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
    
    def _ray_option_bookmark_session_folder(self, path, args, src_addr):
        if self.path:
            if args[0]:
                self.bookmarker.makeAll(self.path)
            else:
                self.bookmarker.removeAll(self.path)
    
    def serverOpenSessionAtStart(self, session_name):
        self.process_order = [(self.preload, session_name),
                              self.load,
                              self.loadDone]
        self.nextFunction()
    
    def dummyLoadAndTemplate(self, session_name, template_name, sess_root):
        tmp_session = DummySession(sess_root)
        tmp_session.dummyLoadAndTemplate(session_name, template_name)
    
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
        self.process_order = [(self.preload, session_full_name),
                              self.load,
                              (self.saveSessionTemplate, template_name, True)]
        self.nextFunction()
        
    def dummyDuplicate(self, session_to_load, new_session_full_name):
        self.process_order = [(self.preload, session_to_load),
                              self.load,
                              (self.duplicate, new_session_full_name),
                              self.duplicateOnlyDone]
        self.nextFunction()
        
    def ray_server_save_session_template(self, path, args, src_addr):
        self.rememberOscArgs(path, args, src_addr)
        session_name, template_name, net = args
        self.process_order = [(self.preload, session_name),
                              self.load,
                              (self.saveSessionTemplate, template_name, net)]
        self.nextFunction()
        
    def ray_server_rename_session(self, path, args, src_addr):
        self.rememberOscArgs(path, args, src_addr)
        full_session_name, new_session_name = args
        
        self.process_order = [(self.preload, full_session_name),
                              self.load,
                              (self.rename, new_session_name),
                              self.save,
                              (self.renameDone, new_session_name)]
        self.nextFunction()
        
        
