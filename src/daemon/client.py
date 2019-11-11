import os
import shlex
import shutil
import subprocess
import time
from liblo import Address
from PyQt5.QtCore import (QCoreApplication, QProcess,
                          QProcessEnvironment, QTimer)
from PyQt5.QtXml import QDomDocument

import ray
from server_sender import ServerSender
from daemon_tools  import TemplateRoots, Terminal, RS

NSM_API_VERSION_MAJOR = 1
NSM_API_VERSION_MINOR = 0

_translate = QCoreApplication.translate

def dirname(*args):
    return os.path.dirname(*args)

def basename(*args):
    return os.path.basename(*args)

class Client(ServerSender):
    _reply_errcode   = 0
    _reply_message   = None
    
    #can be directly changed by OSC thread
    gui_visible      = True
    progress         = 0
    
    #have to be modified by main thread for security
    addr             = None
    pid              = 0
    pending_command  = ray.Command.NONE
    active           = False
    client_id        = ''
    capabilities     = ''
    did_announce     = False
    
    status           = ray.ClientStatus.STOPPED
    name             = ''
    executable_path  = ''
    arguments        = ''
    running_executable = ''
    running_arguments  = ''
    tmp_arguments    = ''
    label            = ''
    icon             = ''
    custom_prefix    = ""
    prefix_mode      = ray.PrefixMode.SESSION_NAME
    auto_start       = True
    start_gui_hidden = False
    check_last_save  = True
    no_save_level    = 0
    is_external      = False
    sent_to_gui      = False
    
    net_session_template = ''
    net_session_root     = ''
    net_daemon_url       = ''
    net_duplicate_state  = -1
    
    ignored_extensions = ray.getGitIgnoredExtensions()
    
    last_save_time = 0.00
    last_dirty = 0.00
    
    def __init__(self, parent_session):
        ServerSender.__init__(self)
        self.session = parent_session
        self.is_dummy = self.session.is_dummy
        
        process_env = QProcessEnvironment.systemEnvironment()
        process_env.insert('NSM_URL', self.getServerUrl())
        
        self.process = QProcess()
        self.process.started.connect(self.processStarted)
        if ray.QT_VERSION >= (5, 6):
            self.process.errorOccurred.connect(self.errorInProcess)
        self.process.finished.connect(self.processFinished)
        self.process.readyReadStandardError.connect(self.standardError)
        self.process.readyReadStandardOutput.connect(self.standardOutput)
        self.process.setProcessEnvironment(process_env)
        
        #if client is'n't stopped 2secs after stop, 
        #another stop becames a kill!
        self.stopped_since_long = False
        self.stopped_timer = QTimer()
        self.stopped_timer.setSingleShot(True)
        self.stopped_timer.setInterval(2000) #2sec
        self.stopped_timer.timeout.connect(self.stoppedSinceLong)
        
        self.net_daemon_copy_timer = QTimer()
        self.net_daemon_copy_timer.setSingleShot(True)
        self.net_daemon_copy_timer.setInterval(3000)
        self.net_daemon_copy_timer.timeout.connect(self.netDaemonOutOfTime)
    
    def sendToSelfAddress(self, *args):
        if not self.addr:
            return
        
        self.send(self.addr, *args)
        
    def sendStatusToGui(self):
        server = self.getServer()
        if not server:
            return
        
        server.sendClientStatusToGui(self)
    
    def readXmlProperties(self, ctx):
        #ctx is an xml sibling for client
        self.executable_path  = ctx.attribute('executable')
        self.arguments        = ctx.attribute('arguments')
        self.name             = ctx.attribute('name')
        self.label            = ctx.attribute('label')
        self.icon             = ctx.attribute('icon')
        self.auto_start       = bool(ctx.attribute('launched') != '0')
        self.check_last_save  = bool(ctx.attribute('check_last_save') != '0')
        self.start_gui_hidden = bool(ctx.attribute('gui_visible') == '0')
        
        ign_exts = ctx.attribute('ignored_extensions').split(' ')
        unign_exts = ctx.attribute('unignored_extensions').split(' ')
        
        global_exts = ray.getGitIgnoredExtensions().split(' ')
        self.ignored_extensions = ""
        
        for ext in global_exts:
            if ext and not ext in unign_exts:
                self.ignored_extensions+= " %s" % ext
                
        for ext in ign_exts:
            if ext and not ext in global_exts:
                self.ignored_extensions+= " %s" % ext
                
        prefix_mode = ctx.attribute('prefix_mode')
        
        if (prefix_mode and prefix_mode.isdigit()
                and 0 <= int(prefix_mode) <= 2 ):
            self.prefix_mode = int(prefix_mode)
            if self.prefix_mode == ray.PrefixMode.CUSTOM:
                self.custom_prefix = ctx.attribute('custom_prefix')
                    
        self.net_session_template = ctx.attribute('net_session_template')
        
        if basename(self.executable_path) == 'ray-network':
            if self.arguments:
                eat_url  = False
                eat_root = False
                
                for arg in shlex.split(self.arguments):
                    if arg in ('--daemon-url', '-u'):
                        eat_url  = True
                        continue
                    elif arg in ('--session-root', '-r'):
                        eat_root = True
                        continue
                    elif not (eat_url or eat_root):
                        eat_url  = False
                        eat_root = False
                        continue
                        
                    if eat_url:
                        self.net_daemon_url = arg
                        eat_url = False
                    elif eat_root:
                        self.net_session_root = arg
                        eat_root = False
        
        if ctx.attribute('id'):
            #session use "id" for absolutely needed client_id
            self.client_id = ctx.attribute('id')
            
        elif ctx.attribute('client_id'):
            #template use "client_id" for wanted client_id
            self.client_id = self.session.generateClientId(ctx.attribute('client_id'))
        
    def writeXmlProperties(self, ctx):
        ctx.setAttribute('executable', self.executable_path)
        ctx.setAttribute('name', self.name)
        if self.label:
            ctx.setAttribute('label', self.label)
        if self.icon:
            ctx.setAttribute('icon', self.icon)
        if not self.check_last_save:
            ctx.setAttribute('check_last_save', 0)
        if self.arguments:
            ctx.setAttribute('arguments', self.arguments)
            
        if self.prefix_mode != ray.PrefixMode.SESSION_NAME:
            ctx.setAttribute('prefix_mode', self.prefix_mode)
            
            if self.prefix_mode == ray.PrefixMode.CUSTOM:
                ctx.setAttribute('custom_prefix', self.custom_prefix)
                
        if self.isCapableOf(':optional-gui:'):
            if self.executable_path != 'ray-proxy':
                if self.start_gui_hidden:
                    ctx.setAttribute('gui_visible', '0')
                    
        if self.net_session_template:
            ctx.setAttribute('net_session_template',
                             self.net_session_template)
            
        if self.ignored_extensions != ray.getGitIgnoredExtensions():
            ignored = ""
            unignored = ""
            client_exts = [e for e in self.ignored_extensions.split(' ') if e]
            global_exts = [e for e in 
                           ray.getGitIgnoredExtensions().split(' ') if e]
            
            for cext in client_exts:
                if not cext in global_exts:
                    ignored += " %s" % cext
            
            for gext in global_exts:
                if not gext in client_exts:
                    unignored += " %s" % gext
                    
            if ignored:        
                ctx.setAttribute('ignored_extensions', ignored)
            else:
                ctx.removeAttribute('ignored_extensions')
                
            if unignored:
                ctx.setAttribute('unignored_extensions', unignored)
            else:
                ctx.removeAttribute('unignored_extensions')
                
    def setReply(self, errcode, message):
        self._reply_message = message
        self._reply_errcode = errcode
        
        if self._reply_errcode:
            Terminal.message("Client \"%s\" replied with error: %s (%i)"
                                % (self.name, message, errcode))
            
            self.setStatus(ray.ClientStatus.ERROR)
        else:
            if self.pending_command == ray.Command.SAVE:
                self.last_save_time = time.time()
                
                self.sendGuiMessage(
                    _translate('GUIMSG', '  %s: saved') 
                        % self.guiMsgStyle())
            elif self.pending_command == ray.Command.OPEN:
                self.sendGuiMessage(
                    _translate('GUIMSG', '  %s: project loaded') 
                        % self.guiMsgStyle())
            
            self.setStatus(ray.ClientStatus.READY)
            #self.message( "Client \"%s\" replied with: %s in %fms"
                            #% (client.name, message, 
                                #client.milliseconds_since_last_command()))
            
        self.pending_command = ray.Command.NONE
        
    def setLabel(self, label):
        self.label = label
        self.sendGuiClientProperties()
        
    def setIcon(self, icon_name):
        self.icon = icon_name
        self.sendGuiClientProperties()
        
    def hasError(self):
        return bool(self._reply_errcode)
        
    def errorCode(self):
        return self._reply_errcode
    
    def getMessage(self):
        return self._reply_message
    
    def isReplyPending(self):
        return bool(self.pending_command)
        
    def isDumbClient(self):
        return bool(not self.did_announce)
    
    def isCapableOf(self, capability):
        return bool(capability in self.capabilities)
    
    def guiMsgStyle(self):
        return "%s (%s)" % (self.name, self.client_id)
    
    def setNetworkProperties(self, net_daemon_url, net_session_root):
        if not self.isCapableOf(':ray-network:'):
            return
        
        if (net_daemon_url == self.net_daemon_url
                and net_session_root == self.net_session_root):
            return
        
        self.net_daemon_url   = net_daemon_url
        self.net_session_root = net_session_root
        
        self.arguments = '--daemon-url %s --net-session-root "%s"' % (
                            self.net_daemon_url,
                            self.net_session_root.replace('"', '\\"'))
    
    def netDaemonOutOfTime(self):
        self.net_duplicate_state = -1
        
        if self.session.wait_for == ray.WaitFor.DUPLICATE_FINISH:
            self.session.endTimerIfLastExpected(self)
            
    def setStatus(self, status):
        #ray.ClientStatus.COPY is not a status as the other ones.
        #GUI needs to know if client is started/open/stopped while files are
        #copied, so self.status doesn't remember ray.ClientStatus.COPY, 
        #although it is sent to GUI
        
        if status != ray.ClientStatus.COPY:
            self.status = status
            self.sendStatusToGui()
        
        if (status == ray.ClientStatus.COPY
            or self.session.file_copier.isActive(self.client_id)):
                self.sendGui("/ray/gui/client/status", self.client_id, 
                             ray.ClientStatus.COPY)
    
    def getJackClientName(self):
        if self.executable_path == 'ray-network':
            # ray-network will use jack_client_name for template
            # quite dirty, but this is the easier way
            return self.net_session_template
            
        jack_client_name = self.name
        
        numid = ''
        if '_' in self.client_id:
            numid = self.client_id.rpartition('_')[2]
        if numid.isdigit():
            jack_client_name += '_'
            jack_client_name += numid
        
        return jack_client_name
    
    def getPrefixString(self):
        if self.prefix_mode == ray.PrefixMode.SESSION_NAME:
            return self.session.name
        
        elif self.prefix_mode == ray.PrefixMode.CLIENT_NAME:
            return self.name
        
        elif self.prefix_mode == ray.PrefixMode.CUSTOM:
            return self.custom_prefix
        
        return ''
    
    def getProjectPath(self):
        if self.executable_path == 'ray-network':
            return self.session.getShortPath()
        
        if self.prefix_mode == ray.PrefixMode.SESSION_NAME:
            return "%s/%s.%s" % (self.session.path, self.session.name, 
                                 self.client_id)
        
        elif self.prefix_mode == ray.PrefixMode.CLIENT_NAME:
            return "%s/%s.%s" % (self.session.path, self.name, self.client_id)
        
        elif self.prefix_mode == ray.PrefixMode.CUSTOM:
            return "%s/%s.%s" % (self.session.path, self.custom_prefix,
                                 self.client_id)
        # should not happens
        return "%s/%s.%s" % (self.session.path, self.session.name,
                             self.client_id)
    
    def getProxyExecutable(self):
        if os.path.basename(self.executable_path) != 'ray-proxy':
            return ""
        
        xml_file = "%s/ray-proxy.xml" % self.getProjectPath()
        xml = QDomDocument()
        try:
            file = open(xml_file, 'r')
            xml.setContent(file.read())
        except:
            return ""
        
        content = xml.documentElement()
        if content.tagName() != "RAY-PROXY":
            file.close()
            return ""
            
        executable = content.attribute('executable')
        file.close()
        
        return executable
    
    def setDefaultGitIgnored(self, executable=""):
        executable = executable if executable else self.executable_path
        executable = os.path.basename(executable)
        if executable == 'ray-proxy':
            executable = self.getProxyExecutable()
        
        if executable in (
                'ardour', 'ardour4', 'ardour5', 'ardour6',
                'Ardour', 'Ardour4', 'Ardour5', 'Ardour6',
                'qtractor'):
            self.ignored_extensions += " .mid"
            
        elif executable in ('luppp', 'sooperlooper', 'sooperlooper_nsm'):
            if '.wav' in self.ignored_extensions:
                self.ignored_extensions = \
                    self.ignored_extensions.replace('.wav', '')
                
        elif executable == 'samplv1_jack':
            for ext in ('.wav', '.flac', '.ogg', '.mp3'):
                if ext in self.ignored_extensions:
                    self.ignored_extensions = \
                        self.ignored_extensions.replace(ext, '')
    
    def start(self):
        self.session.setRenameable(False)
        
        self.last_dirty = 0.00
        
        if self.is_dummy:
            return
        
        self.pending_command = ray.Command.START
        
        arguments = []
        
        if self.tmp_arguments:
            arguments += shlex.split(self.tmp_arguments)
            
        if self.arguments:
            arguments += shlex.split(self.arguments)
        
        if self.hasServer() and self.executable_path == 'ray-network':
            arguments.append('--net-daemon-id')
            arguments.append(str(self.getServer().net_daemon_id))
            
        self.running_executable = self.executable_path
        self.running_arguments  = self.arguments
        
        self.process.start(self.executable_path, arguments)
        
        ## Here for another way to debug clients.
        ## Konsole is a terminal software.
        #self.process.start(
            #'konsole', 
            #['--hide-tabbar', '--hide-menubar', '-e', self.executable_path]
                #+ arguments)
     
    def terminate(self):
        if self.isRunning():
            if self.is_external:
                os.kill(self.pid, 15) # 15 means signal.SIGTERM
            else:
                self.process.terminate()
        
    def kill(self):
        if self.is_external:
            os.kill(self.pid, 9) # 9 means signal.SIGKILL
            return
            
        if self.isRunning():
            self.process.kill()
            
    def isRunning(self):
        if self.is_external:
            return True
        return bool(self.process.state() == 2)
    
    def standardError(self):
        standard_error = self.process.readAllStandardError().data()
        Terminal.clientMessage(standard_error, self.name, self.client_id)
        
    def standardOutput(self):
        standard_output = self.process.readAllStandardOutput().data()
        Terminal.clientMessage(standard_output, self.name, self.client_id)
    
    def processStarted(self):
        self.stopped_since_long = False
        self.pid = self.process.pid()
        self.setStatus(ray.ClientStatus.LAUNCH)
        
        #Terminal.message("Process has pid: %i" % self.pid)
        
        self.sendGuiMessage(_translate("GUIMSG", "  %s: launched")
                            % self.guiMsgStyle())
    
    def processFinished(self, exit_code, exit_status):
        self.stopped_timer.stop()
        self.is_external = False
        
        if self.pending_command in (ray.Command.KILL, ray.Command.QUIT):
            self.sendGuiMessage(_translate('GUIMSG', 
                                           "  %s: terminated as planned")
                                    % self.guiMsgStyle())
        else:
            self.sendGuiMessage(_translate('GUIMSG',
                                           "  %s: died unexpectedly.")
                                    % self.guiMsgStyle())
        
        if self.session.wait_for:
            self.session.endTimerIfLastExpected(self)
        
        if self.pending_command == ray.Command.QUIT:
            self.session.removeClient(self)
            return
        else:
            self.setStatus(ray.ClientStatus.STOPPED)
                
        self.pending_command = ray.Command.NONE
        self.active = False
        self.pid = 0
        self.addr = None
        
        self.session.setRenameable(True)
        
    def errorInProcess(self, error):
        if error == QProcess.FailedToStart:
            self.sendGuiMessage(
                _translate('GUIMSG', "  %s: Failed to start !")
                    % self.guiMsgStyle())
            self.active = False
            self.pid    = 0
            self.setStatus(ray.ClientStatus.STOPPED)
            self.pending_command = ray.Command.NONE
            
            if self.session.osc_src_addr:
                error_message = "Failed to launch process!"
                if not self.session.osc_path.startswith('/nsm/server/'):
                    error_message = _translate('client',
                                               "Failed to launch process !")
                    
                self.session.oscReply("/error", self.session.osc_path, 
                                      ray.Err.LAUNCH_FAILED, 
                                      error_message)
            
            if self.session.wait_for:
                self.session.endTimerIfLastExpected(self)
        self.session.setRenameable(True)
    
    def stoppedSinceLong(self):
        self.stopped_since_long = True
        self.sendGui('/ray/gui/client/still_running', self.client_id)
    
    def tellClientSessionIsLoaded(self):
        if self.active and not self.isDumbClient():
            Terminal.message("Telling client %s that session is loaded."
                             % self.name)
            self.sendToSelfAddress("/nsm/client/session_is_loaded")
    
    def canSaveNow(self):
        return bool(self.active and not self.no_save_level) 
    
    def save(self):
        if self.isRunning():
            if self.canSaveNow():
                Terminal.message("Telling %s to save" % self.name)
                self.sendToSelfAddress("/nsm/client/save")
                
                self.pending_command = ray.Command.SAVE
                self.setStatus(ray.ClientStatus.SAVE)
            
            elif self.isDumbClient():
                self.setStatus(ray.ClientStatus.NOOP)
                
            if self.isCapableOf(':optional-gui:'):
                self.start_gui_hidden = not bool(self.gui_visible)
            
    def stop(self):
        self.sendGuiMessage(_translate('GUIMSG', "  %s: stopping")
                                % self.guiMsgStyle())
        
        #if self.is_external:
            #os.kill(self.pid, 15) # 15 means signal.SIGTERM
            #return
            
        if self.isRunning():
            self.pending_command = ray.Command.KILL
            self.setStatus(ray.ClientStatus.QUIT)
            
            if not self.stopped_timer.isActive():
                self.stopped_timer.start()
                
            self.terminate()
    
    def quit(self):
        Terminal.message("Commanding %s to quit" % self.name)
        if self.isRunning():
            self.pending_command = ray.Command.QUIT
            self.terminate()
            self.setStatus(ray.ClientStatus.QUIT)
        else:
            self.sendGui("/ray/gui/client/status", self.client_id, 
                         ray.ClientStatus.REMOVED)
    
    def switch(self, new_client):
        old_client_id      = self.client_id
        self.client_id     = new_client.client_id
        self.name          = new_client.name
        self.prefix_mode   = new_client.prefix_mode
        self.custom_prefix = new_client.custom_prefix
        self.label         = new_client.label
        self.icon          = new_client.icon
        
        jack_client_name    = self.getJackClientName()
        client_project_path = self.getProjectPath()
        
        Terminal.message("Commanding %s to switch \"%s\""
                         % (self.name, client_project_path))
        
        self.sendToSelfAddress("/nsm/client/open", client_project_path,
                               self.session.name, jack_client_name)
        
        self.pending_command = ray.Command.OPEN
        self.setStatus(ray.ClientStatus.SWITCH)
            
        self.sendGui("/ray/gui/client/switch", old_client_id, self.client_id)
    
    def sendGuiClientProperties(self, removed=False):
        ad = '/ray/gui/client/update' if self.sent_to_gui else '/ray/gui/client/new'
            
        if removed:
            ad = '/ray/gui/trash/add'
            
        self.sendGui(ad,
                        self.client_id, 
                        self.executable_path,
                        self.arguments,
                        self.name, 
                        self.prefix_mode, 
                        self.custom_prefix,
                        self.label,
                        self.icon,
                        self.capabilities,
                        int(self.check_last_save),
                        self.ignored_extensions)
        
        self.sent_to_gui = True
    
    def updateClientProperties(self, client_data):
        self.client_id       = client_data.client_id
        self.executable_path = client_data.executable_path
        self.arguments       = client_data.arguments
        self.prefix_mode     = client_data.prefix_mode
        self.custom_prefix   = client_data.custom_prefix
        self.label           = client_data.label
        self.icon            = client_data.icon
        self.capabilities    = client_data.capabilities
        self.check_last_save = client_data.check_last_save
        self.ignored_extensions = client_data.ignored_extensions
        
        self.sendGuiClientProperties()
    
    def prettyClientId(self):
        wanted = self.client_id
        
        if self.executable_path == 'ray-proxy':
            proxy_file = "%s/ray-proxy.xml" % self.getProjectPath()
            
            if os.path.exists(proxy_file):
                file = open(proxy_file, 'r')
                xml = QDomDocument()
                xml.setContent(file.read())
                file.close()
                
                content = xml.documentElement()
                if content.tagName() == 'RAY-PROXY':
                    executable = content.attribute('executable')
                    if executable:
                        wanted = executable
            
            
        if '_' in wanted:
            begin, udsc, end = wanted.rpartition('_')
            
            if not end:
                return wanted
            
            if not end.isdigit():
                return wanted
            
            return begin
        
        return wanted
    
    def getProjectFiles(self):
        #return a list of full filenames
        client_files = []
        
        project_path = self.getProjectPath()
        if os.path.exists(project_path):
            client_files.append(project_path)
            
        if project_path.startswith('%s/' % self.session.path):
            base_project = project_path.replace('%s/' % self.session.path,
                                                '', 1)
            
            for filename in os.listdir(self.session.path):
                if filename == base_project:
                    full_file_name =  "%s/%s" % (self.session.path, filename)
                    if not full_file_name in client_files:
                        client_files.append(full_file_name)
                        
                elif filename.startswith('%s.' % base_project):
                    client_files.append('%s/%s'
                                        % (self.session.path, filename))
                    
        return client_files
            
    def saveAsTemplate(self, template_name):
        #copy files
        client_files = self.getProjectFiles()
                    
        template_dir = "%s/%s" % (TemplateRoots.user_clients, 
                                    template_name)
        
        if os.path.exists(template_dir):
            if os.access(template_dir, os.W_OK):
                shutil.rmtree(template_dir)
            else:
                #TODO send error
                return
            
        os.makedirs(template_dir)
        
        if self.net_daemon_url:
            self.net_session_template = template_name
            self.send(Address(self.net_daemon_url), 
                      '/ray/server/save_session_template', self.session.name, 
                      template_name, self.net_session_root)
        
        if client_files:
            self.setStatus(ray.ClientStatus.COPY)
            fc = self.session.file_copier
            fc.startClientCopy(self.client_id, client_files, template_dir,
                                self.saveAsTemplate_step1,
                                self.saveAsTemplateAborted,
                                [template_name])
        else:
            self.saveAsTemplate_step1(template_name)

    def saveAsTemplate_step1(self, template_name):
        self.setStatus(self.status) #see setStatus to see why
        
        if self.prefix_mode != ray.PrefixMode.CUSTOM:
            self.adjustFilesAfterCopy(template_name, ray.Template.CLIENT_SAVE)
            
        xml_file = "%s/%s" % (TemplateRoots.user_clients,
                              'client_templates.xml')
        
        #security check
        if os.path.exists(xml_file):
            if not os.access(xml_file, os.W_OK):
                # TODO send error
                return
            
            if os.path.isdir(xml_file):
                #should not be a dir, remove it !
                subprocess.run('rm', '-R', xml_file)
        
        if not os.path.isdir(TemplateRoots.user_clients):
            os.makedirs(TemplateRoots.user_clients)
        
        #create client_templates.xml if not exists
        if not os.path.isfile(xml_file):
            file = open(xml_file, 'w')
            
            xml = QDomDocument()
            rct = xml.createElement('RAY-CLIENT-TEMPLATES')
            xml.appendChild(rct)
            file.write(xml.toString())
            file.close()
            del xml
            
        file = open(xml_file, 'r')
        xml = QDomDocument()
        xml.setContent(file.read())
        file.close()
        content = xml.documentElement()
                
        if not content.tagName() == 'RAY-CLIENT-TEMPLATES':
            return
        
        # remove existing template if it has the same name as the new one
        node = content.firstChild()
        while not node.isNull():
            if node.toElement().tagName() != 'Client-Template':
                node = node.nextSibling()
                continue
            
            if node.toElement().attribute('template-name') == template_name:
                content.removeChild(node)
            
            node = node.nextSibling()
        
        #create template
        rct = xml.createElement('Client-Template')
        
        self.writeXmlProperties(rct)
        rct.setAttribute('template-name', template_name)
        rct.setAttribute('client_id', self.prettyClientId())
        
        if not self.isRunning():
            rct.setAttribute('launched', False)
            
        content.appendChild(rct)
        
        file = open(xml_file, 'w')
        file.write(xml.toString())
        file.close()
        
        self.sendGuiMessage(
            _translate('message', 'Client template %s created')
                % template_name)
    
    def saveAsTemplateAborted(self, template_name):
        self.setStatus(self.status)
    
    def adjustFilesAfterCopy(self, new_session_full_name,
                             template_save=ray.Template.NONE):
        old_session_name = self.session.name
        new_session_name = basename(new_session_full_name)
        new_client_id    = self.client_id
        old_client_id    = self.client_id
        xsessionx   = "XXX_SESSION_NAME_XXX"
        xclient_idx = "XXX_CLIENT_ID_XXX"
        
        if template_save == ray.Template.NONE:
            if self.prefix_mode != ray.PrefixMode.SESSION_NAME:
                return
            
            spath = "%s/%s" % (self.session.root, new_session_full_name)
        
        elif template_save == ray.Template.RENAME:
            spath = self.session.path
            
        elif template_save == ray.Template.SESSION_SAVE:
            spath = "%s/%s" % (TemplateRoots.user_sessions,
                               new_session_full_name)
            new_session_name = xsessionx
        
        elif template_save == ray.Template.SESSION_SAVE_NET:
            spath = "%s/%s/%s" % (self.session.root, 
                                  TemplateRoots.net_session_name,
                                  new_session_full_name)
            new_session_name = xsessionx
        
        elif template_save == ray.Template.SESSION_LOAD:
            spath = "%s/%s" % (self.session.root, new_session_full_name)
            old_session_name = xsessionx
        
        elif template_save == ray.Template.SESSION_LOAD_NET:
            spath = "%s/%s" % (self.session.root, new_session_full_name)
            old_session_name = xsessionx
        
        elif template_save == ray.Template.CLIENT_SAVE:
            spath = "%s/%s" % (TemplateRoots.user_clients,
                               new_session_full_name)
            new_session_name = xsessionx
            new_client_id    = xclient_idx
           
        elif template_save == ray.Template.CLIENT_LOAD:
            spath = self.session.path
            old_session_name = xsessionx
            old_client_id    = xclient_idx
        
        old_prefix = old_session_name
        new_prefix = new_session_name
        
        if self.prefix_mode == ray.PrefixMode.CLIENT_NAME:
            old_prefix = new_prefix = self.name
        elif self.prefix_mode == ray.PrefixMode.CUSTOM:
            old_prefix = new_prefix = self.custom_prefix
        
        project_path = "%s/%s.%s" % (spath, old_prefix, old_client_id)
        
        if not os.path.exists(project_path):
            for file in os.listdir(spath):
                if (file.startswith("%s.%s." % (old_prefix, old_client_id))
                    or file == "%s.%s" % (old_prefix, old_client_id)):
                    
                    if not os.access("%s/%s" % (spath, file), os.W_OK):
                        continue
                    
                    endfile = file.replace("%s.%s."
                                           % (old_prefix, old_client_id),
                                           '', 1)
                    
                    os.rename('%s/%s' %(spath, file),
                              "%s/%s.%s.%s"
                              % (spath, new_prefix, new_client_id, endfile))
            return
        
        if not os.path.isdir(project_path):
            if not os.access(project_path, os.W_OK):
                return
            
            os.rename(project_path, "%s/%s.%s"
                                    % (spath, new_prefix, new_client_id))
            return
        
        #only for ardour
        ardour_file  = "%s/%s.ardour"     % (project_path, old_prefix)
        ardour_bak   = "%s/%s.ardour.bak" % (project_path, old_prefix)
        ardour_audio = "%s/interchange/%s.%s" % (project_path, old_prefix, 
                                                 old_client_id)
        
        if os.path.isfile(ardour_file) and os.access(ardour_file, os.W_OK):
            os.rename(ardour_file, "%s/%s.ardour"
                                   % (project_path, new_prefix))
            
        if os.path.isfile(ardour_bak) and os.access(ardour_bak, os.W_OK):
            os.rename(ardour_bak, "%s/%s.ardour.bak"
                                  % (project_path, new_prefix))
            
        if os.path.isdir(ardour_audio and os.access(ardour_audio, os.W_OK)):
            os.rename(ardour_audio,
                      "%s/interchange/%s.%s"
                      % (project_path, new_prefix, new_client_id))
        
        #change last_used snapshot of ardour
        instant_file = "%s/instant.xml" % project_path
        if os.path.isfile(instant_file) and os.access(instant_file, os.W_OK):
            try :
                file = open(instant_file, 'r')
                xml = QDomDocument()
                xml.setContent(file.read())
                content = xml.documentElement()
                
                if content.tagName() == 'instant':
                    node = content.firstChild()
                    while not node.isNull():
                        tag = node.toElement()
                        if tag.tagName() == 'LastUsedSnapshot':
                            if tag.attribute('name') == old_prefix:
                                tag.setAttribute('name', new_prefix)
                                file = open(instant_file, 'w')
                                file.write(xml.toString())
                            break
                            
                        node = node.nextSibling()
                file.close()
            except:
                False
        
        #for Vee One Suite
        for extfile in ('samplv1', 'synthv1', 'padthv1', 'drumkv1'):
            old_veeone_file = "%s/%s.%s" % (project_path, old_session_name,
                                            extfile)
            new_veeone_file = "%s/%s.%s" % (project_path, new_session_name,
                                            extfile)
            if (os.path.isfile(old_veeone_file)
                    and os.access(old_veeone_file, os.W_OK)
                    and not os.path.exists(new_veeone_file)):
                os.rename(old_veeone_file, new_veeone_file)
        
        #for ray-proxy, change config_file name
        proxy_file = "%s/ray-proxy.xml" % project_path
        if os.path.isfile(proxy_file):
            try:
                file = open(proxy_file, 'r')
                xml = QDomDocument()
                xml.setContent(file.read())
                content = xml.documentElement()
                
                if content.tagName() == "RAY-PROXY":
                    cte = content.toElement()
                    config_file = cte.attribute('config_file')
                    
                    if (('$RAY_SESSION_NAME' or '${RAY_SESSION_NAME}')
                            in config_file):
                        for env in ('"$RAY_SESSION_NAME"',
                                    '"${RAY_SESSION_NAME}"',
                                    "$RAY_SESSION_NAME",
                                    "${RAY_SESSION_NAME}"):
                            config_file = \
                                config_file.replace(env, old_session_name)
                        
                        if (config_file
                                and (config_file.split('.')[0] 
                                        == old_session_name)):
                            config_file_path = "%s/%s" % (project_path,
                                                          config_file)
                            
                            if (os.path.exists(config_file_path)
                                    and os.access(config_file_path, os.W_OK)):
                                os.rename(config_file_path, 
                                          "%s/%s" % (project_path, 
                                                     config_file.replace(
                                                        old_session_name, 
                                                        new_session_name)))
                file.close()
                        
            except:
                False
        
        if os.access(project_path, os.W_OK):
            subprocess.run(['mv', project_path, "%s/%s.%s"
                                                % (spath, new_prefix, 
                                                   new_client_id)])
    
    def serverAnnounce(self, path, args, src_addr, is_new):
        client_name, capabilities, executable_path, major, minor, pid = args
        
        if self.pending_command in (ray.Command.QUIT, ray.Command.KILL):
            # assume to not answer to a dying client.
            # He will never know, or perhaps, it depends on beliefs.
            return
        
        if major > NSM_API_VERSION_MAJOR:
            Terminal.message(
                "Client is using incompatible and more recent " 
                + "API version %i.%i" % (major, minor))
            self.send(src_addr, "/error", path, ray.Err.INCOMPATIBLE_API, 
                      "Server is using an incompatible API version.")
            return
        
        self.capabilities = capabilities
        self.addr         = src_addr
        self.name         = client_name
        self.active       = True
        self.did_announce = True
        
        if is_new:
            self.is_external = True
            self.pid = pid
            self.running_executable = executable_path
        
        if self.executable_path in RS.non_active_clients:
            RS.non_active_clients.remove(self.executable_path)
        
        Terminal.message("Process has pid: %i" % pid )
        Terminal.message(
            "The client \"%s\" at \"%s\" " % (self.name, self.addr.url)
            + "informs us it's ready to receive commands.")
        
        server = self.getServer()
        if not server:
            return 
        
        self.sendGuiMessage(
            _translate('GUIMSG', "  %s: announced" % self.guiMsgStyle()))
        
        # if this daemon is under another NSM session
        # do not enable server-control
        # because new, open and duplicate are forbidden 
        server_capabilities = "" 
        if not server.is_nsm_locked:
            server_capabilities += ":server-control"
        server_capabilities += ":broadcast:optional-gui:no-save-level:"
        
        self.send(src_addr, "/reply", path, 
                  "Well hello, stranger. Welcome to the party."
                  if is_new else "Howdy, what took you so long?",
                  ray.APP_TITLE,
                  server_capabilities)
        
        self.sendGuiClientProperties()
        self.setStatus(ray.ClientStatus.OPEN)
        
        client_project_path = self.getProjectPath()
        jack_client_name    = self.getJackClientName()
        
        if self.isCapableOf(':ray-network:'):
            client_project_path = self.session.getShortPath()
            jack_client_name = self.net_session_template
        
        self.send(src_addr, "/nsm/client/open", client_project_path,
                  self.session.name, jack_client_name)
        
        self.pending_command = ray.Command.OPEN
        
        if self.isCapableOf(":optional-gui:"):
            self.sendGui("/ray/gui/client/has_optional_gui", self.client_id)
            
            if self.start_gui_hidden:
                self.send(src_addr, "/nsm/client/hide_optional_gui")
