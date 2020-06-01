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
from signaler import Signaler
from scripter import ClientScripter

NSM_API_VERSION_MAJOR = 1
NSM_API_VERSION_MINOR = 0

OSC_SRC_START = 0
OSC_SRC_OPEN = 1
OSC_SRC_SAVE = 2
OSC_SRC_SAVE_TP = 3
OSC_SRC_STOP = 4

_translate = QCoreApplication.translate
signaler = Signaler.instance()


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
    description      = ''
    icon             = ''
    custom_prefix    = ''
    prefix_mode      = ray.PrefixMode.SESSION_NAME
    auto_start       = True
    start_gui_hidden = False
    check_last_save  = True
    no_save_level    = 0
    is_external      = False
    sent_to_gui      = False
    switch_state = ray.SwitchState.NONE
    
    non_nsm = False
    non_nsm_config_file = ""
    non_nsm_save_sig = 0
    non_nsm_stop_sig = 15
    
    
    net_session_template = ''
    net_session_root     = ''
    net_daemon_url       = ''
    net_duplicate_state  = -1
    
    ignored_extensions = ray.getGitIgnoredExtensions()
    
    last_save_time = 0.00
    last_dirty = 0.00
    _last_announce_time = 0.00
    last_open_duration = 0.00
    
    has_been_started = False
    
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
        
        # stock osc src_addr and src_path of respectively
        # start, open, save, save_tp, stop
        self._osc_srcs = [(None, ''), (None, ''), (None, ''),
                          (None, ''), (None, '')]
        
        self._open_timer = QTimer()
        self._open_timer.setSingleShot(True)
        self._open_timer.timeout.connect(self.openTimerTimeout)
        
        self.scripter = ClientScripter(self)
        
    def sendToSelfAddress(self, *args):
        if not self.addr:
            return
        
        self.send(self.addr, *args)
    
    def sendReplyToCaller(self, slot, message):
        src_addr, src_path = self._osc_srcs[slot]
        if src_addr:
            self.send(src_addr, '/reply', src_path, message)
            self._osc_srcs[slot] = (None, '')
            
            if (self.scripter.isRunning()
                    and self.scripter.pendingCommand() == self.pending_command):
                self._osc_srcs[slot] = self.scripter.initialCaller()
            
        if slot == OSC_SRC_OPEN:
            self._open_timer.stop()
    
    def sendErrorToCaller(self, slot, err, message):
        src_addr, src_path = self._osc_srcs[slot]
        if src_addr:
            self.send(src_addr, '/error', src_path, err, message)
            self._osc_srcs[slot] = (None, '')
            
            if (self.scripter.isRunning()
                    and self.scripter.pendingCommand() == self.pending_command):
                self._osc_srcs[slot] = self.scripter.initialCaller()
        
        if slot == OSC_SRC_OPEN:
            self._open_timer.stop()
    
    def openTimerTimeout(self):
        self.sendErrorToCaller(OSC_SRC_OPEN, ray.Err.GENERAL_ERROR,
            _translate('GUIMSG', '%s is started but not active')
                % self.guiMsgStyle())
    
    def sendStatusToGui(self):
        server = self.getServer()
        if not server:
            return
        
        server.sendClientStatusToGui(self)
    
    def readXmlProperties(self, ctx):
        #ctx is an xml sibling for client
        self.executable_path = ctx.attribute('executable')
        self.arguments = ctx.attribute('arguments')
        self.name = ctx.attribute('name')
        self.label = ctx.attribute('label')
        self.description = ctx.attribute('description')
        self.icon = ctx.attribute('icon')
        self.auto_start = bool(ctx.attribute('launched') != '0')
        self.check_last_save = bool(ctx.attribute('check_last_save') != '0')
        self.start_gui_hidden = bool(ctx.attribute('gui_visible') == '0')
        
        if not self.description:
            self.description = self.get_description_from_desktop_file()
        
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
        
        self.non_nsm = bool(ctx.attribute('non_nsm') == '1')
        if self.non_nsm:
            self.non_nsm_config_file = ctx.attribute('config_file')
            non_nsm_save_sig = ctx.attribute('save_signal')
            if non_nsm_save_sig.isdigit():
                self.non_nsm_save_sig = int(non_nsm_save_sig)
            
            non_nsm_stop_sig = ctx.attribute('stop_signal')
            if non_nsm_stop_sig.isdigit():
                self.non_nsm_stop_sig = int(non_nsm_stop_sig)
        
        self.net_session_template = ctx.attribute('net_session_template')
        
        open_duration = ctx.attribute('last_open_duration')
        if open_duration.replace('.', '', 1).isdigit():
            self.last_open_duration = float(open_duration)
        
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
            self.client_id = self.session.generateClientId(
                                                ctx.attribute('client_id'))
        
    def writeXmlProperties(self, ctx):
        ctx.setAttribute('executable', self.executable_path)
        ctx.setAttribute('name', self.name)
        if self.label:
            ctx.setAttribute('label', self.label)
        if self.description:
            ctx.setAttribute('description', self.description)
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
        
        if self.non_nsm:
            ctx.setAttribute('non_nsm', 1)
            ctx.setAttribute('config_file', self.non_nsm_config_file)
            ctx.setAttribute('save_signal', self.non_nsm_save_sig)
            ctx.setAttribute('stop_signal', self.non_nsm_stop_sig)
        
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
        
        if self.last_open_duration >= 5.0:
            ctx.setAttribute('last_open_duration',
                             str(self.last_open_duration))
        
    def setReply(self, errcode, message):
        self._reply_message = message
        self._reply_errcode = errcode
        
        if self._reply_errcode:
            Terminal.message("Client \"%s\" replied with error: %s (%i)"
                                % (self.name, message, errcode))
            
            if self.pending_command == ray.Command.SAVE:
                self.sendErrorToCaller(OSC_SRC_SAVE, ray.Err.GENERAL_ERROR,
                                    _translate('GUIMSG', '%s failed to save!')
                                            % self.guiMsgStyle())
            elif self.pending_command == ray.Command.OPEN:
                self.sendErrorToCaller(OSC_SRC_OPEN, ray.Err.GENERAL_ERROR,
                                    _translate('GUIMSG', '%s failed to open!')
                                            % self.guiMsgStyle())
                
            self.setStatus(ray.ClientStatus.ERROR)
        else:
            if self.pending_command == ray.Command.SAVE:
                self.last_save_time = time.time()
                
                self.sendGuiMessage(
                    _translate('GUIMSG', '  %s: saved') 
                        % self.guiMsgStyle())
                
                self.sendReplyToCaller(OSC_SRC_SAVE, 'client saved.')
                
            elif self.pending_command == ray.Command.OPEN:
                self.sendGuiMessage(
                    _translate('GUIMSG', '  %s: project loaded') 
                        % self.guiMsgStyle())
                
                self.last_open_duration = \
                                        time.time() - self._last_announce_time
                self.sendReplyToCaller(OSC_SRC_OPEN, 'client opened')
            
            self.setStatus(ray.ClientStatus.READY)
            #self.message( "Client \"%s\" replied with: %s in %fms"
                            #% (client.name, message, 
                                #client.milliseconds_since_last_command()))
        if (self.scripter.isRunning()
                and self.scripter.pendingCommand() == self.pending_command):
            return
        
        self.pending_command = ray.Command.NONE
        
        if self.session.wait_for == ray.WaitFor.REPLY:
            self.session.endTimerIfLastExpected(self)
        
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
    
    def isReplyPending(self)->bool:
        return bool(self.pending_command)
        
    def isDumbClient(self)->bool:
        if self.non_nsm:
            return False
        
        return bool(not self.did_announce)
    
    def isCapableOf(self, capability)->bool:
        return bool(capability in self.capabilities)
    
    def guiMsgStyle(self)->str:
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
    
    def hasNSMClientId(self)->bool:
        return bool(len(self.client_id) == 5
                    and self.client_id[0] == 'n'
                    and self.client_id[1:4].isalpha()
                    and self.client_id[1:4].isupper())
    
    def getJackClientName(self):
        if self.executable_path == 'ray-network':
            # ray-network will use jack_client_name for template
            # quite dirty, but this is the easier way
            return self.net_session_template
        
        # return same jack_client_name as NSM does
        # if client seems to have been made by NSM itself
        # else, jack connections could be lose
        # at NSM session import
        if self.hasNSMClientId():
            return "%s.%s" % (self.name, self.client_id)
        
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
    
    def nonNsmGetExpandedConfigFile(self)->str:
        if not self.non_nsm:
            return ''
        
        os.environ['RAY_SESSION_NAME'] = self.session.name
        os.environ['RAY_CLIENT_ID'] = self.client_id
        
        expanded_config_file = os.path.expandvars(self.non_nsm_config_file)
        
        os.unsetenv('RAY_SESSION_NAME')
        os.unsetenv('RAY_CLIENT_ID')
        
        return expanded_config_file
    
    def start(self, src_addr=None, src_path='', wait_open_to_reply=False):
        if src_addr and not wait_open_to_reply:
            self._osc_srcs[OSC_SRC_START] = (src_addr, src_path)
        
        self.session.setRenameable(False)
        
        self.last_dirty = 0.00
        
        if self.is_dummy:
            self.sendErrorToCaller(OSC_SRC_START, ray.Err.GENERAL_ERROR,
                _translate('GUIMSG', "can't start %s, it is a dummy client !")
                    % self.guiMsgStyle())
            return
        
        if self.scripter.start(ray.Command.START, src_addr,
                               self._osc_srcs[OSC_SRC_START]):
            self.setStatus(ray.ClientStatus.SCRIPT)
            return
        
        self.pending_command = ray.Command.START
        
        arguments = []
        
        if self.tmp_arguments:
            arguments += shlex.split(self.tmp_arguments)
        
        arguments_line = self.arguments
        
        if self.non_nsm:
            all_envs = {'CONFIG_FILE': ('', ''),
                        'RAY_SESSION_NAME': ('', ''),
                        'RAY_CLIENT_ID': ('', '')}
            
            all_envs['RAY_SESSION_NAME'] = (os.getenv('RAY_SESSION_NAME'),
                                            self.session.name)
            all_envs['RAY_CLIENT_ID'] = (os.getenv('RAY_CLIENT_ID'),
                                         self.client_id)
            #all_envs['CONFIG_FILE'] = (os.getenv('CONFIG_FILE'),
                                       #self.non_nsm_config_file)
            
            for env in all_envs:
                os.environ[env] = all_envs[env][1]
            
            os.environ['CONFIG_FILE'] = os.path.expandvars(
                                                    self.non_nsm_config_file)
            
            back_pwd = os.getenv('PWD')
            non_nsm_pwd = self.getProjectPath()
            os.environ['PWD'] = non_nsm_pwd
            
            if not os.path.exists(non_nsm_pwd):
                try:
                    os.makedirs(non_nsm_pwd)
                except:
                    # TODO
                    return
                    
            arguments_line = os.path.expandvars(self.arguments)
            
            if back_pwd is None:
                os.unsetenv('PWD')
            else:
                os.environ['PWD'] = back_pwd
            
            for env in all_envs:
                if all_envs[env][0] is None:
                    os.unsetenv(env)
                else:
                    os.environ[env] = all_envs[env][0]
            
        if self.arguments:
            arguments += shlex.split(arguments_line)
        
        if self.hasServer() and self.executable_path == 'ray-network':
            arguments.append('--net-daemon-id')
            arguments.append(str(self.getServer().net_daemon_id))
            
        self.running_executable = self.executable_path
        self.running_arguments = self.arguments
        
        if self.non_nsm:
            self.process.setWorkingDirectory(non_nsm_pwd)
            process_env = QProcessEnvironment.systemEnvironment()
            process_env.insert('RAY_SESSION_NAME', self.session.name)
            process_env.insert('RAY_CLIENT_ID', self.client_id)
            self.process.setProcessEnvironment(process_env)
        
        self.process.start(self.executable_path, arguments)
        
        ## Here for another way to debug clients.
        ## Konsole is a terminal software.
        #self.process.start(
            #'konsole', 
            #['--hide-tabbar', '--hide-menubar', '-e', self.executable_path]
                #+ arguments)
    
    def load(self, src_addr=None, src_path=''):
        if src_addr:
            self._osc_srcs[OSC_SRC_OPEN] = (src_addr, src_path)
        
        if self.active:
            self.sendReplyToCaller(OSC_SRC_OPEN, 'client active')
            return 
        
        if self.pending_command == ray.Command.STOP:
            self.sendErrorToCaller(OSC_SRC_OPEN, ray.Err.GENERAL_ERROR,
                _translate('GUIMSG', '%s is exiting.') % self.guiMsgStyle())
        
        if self.isRunning() and self.isDumbClient():
            self.sendErrorToCaller(OSC_SRC_OPEN, ray.Err.GENERAL_ERROR,
                _translate('GUIMSG', '%s seems to can not open')
                    % self.guiMsgStyle())
        
        duration = max(8000, 2 * self.last_open_duration)
        self._open_timer.setInterval(duration)
        self._open_timer.start()
        
        if self.pending_command == ray.Command.OPEN:
            return
        
        if not self.isRunning():
            if self.executable_path in RS.non_active_clients:
                if src_addr:
                    self._osc_srcs[OSC_SRC_START] = (src_addr, src_path)
                    self._osc_srcs[OSC_SRC_OPEN] = (None, '')
            
            self.start(src_addr, src_path, True)
            return 
        
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
        self.has_been_started = True
        self.stopped_since_long = False
        self.pid = self.process.pid()
        self.setStatus(ray.ClientStatus.LAUNCH)
        
        #Terminal.message("Process has pid: %i" % self.pid)
        
        self.sendGuiMessage(_translate("GUIMSG", "  %s: launched")
                            % self.guiMsgStyle())
        
        self.sendReplyToCaller(OSC_SRC_START, 'client started')
        
        if self.non_nsm:
            self.pending_command = ray.Command.OPEN
            self.setStatus(ray.ClientStatus.OPEN)
            QTimer.singleShot(500, self.nonNsmReady)
    
    def processFinished(self, exit_code, exit_status):
        self.stopped_timer.stop()
        self.is_external = False
        
        if self.pending_command == ray.Command.STOP:
            self.sendGuiMessage(_translate('GUIMSG', 
                                           "  %s: terminated as planned")
                                    % self.guiMsgStyle())
        else:
            self.sendGuiMessage(_translate('GUIMSG',
                                           "  %s: died unexpectedly.")
                                    % self.guiMsgStyle())
        
        self.sendReplyToCaller(OSC_SRC_STOP, 'client stopped')
        
        for osc_src in (OSC_SRC_OPEN, OSC_SRC_SAVE):
            self.sendErrorToCaller(osc_src, ray.Err.GENERAL_ERROR,
                    _translate('GUIMSG', '%s died !' % self.guiMsgStyle()))
        
        self.setStatus(ray.ClientStatus.STOPPED)
                
        self.pending_command = ray.Command.NONE
        self.active = False
        self.pid = 0
        self.addr = None
        
        self.session.setRenameable(True)
        
        if self.scripter.pendingCommand() == ray.Command.STOP:
            return
        
        if self.session.wait_for:
            self.session.endTimerIfLastExpected(self)
    
    def scriptFinished(self, exit_code):
        if self.scripter.isAskedForTerminate():
            if self.session.wait_for == ray.WaitFor.QUIT:
                self.session.endTimerIfLastExpected(self)
            return
        
        scripter_pending_command = self.scripter.pendingCommand()
        
        if exit_code:
            error_text = "script %s ended with an error code" \
                            % self.scripter.getPath()
            if scripter_pending_command == ray.Command.SAVE:
                self.sendErrorToCaller(OSC_SRC_SAVE, - exit_code, 
                                        error_text)
            elif scripter_pending_command == ray.Command.START:
                self.sendErrorToCaller(OSC_SRC_START, - exit_code,
                                        error_text)
            elif scripter_pending_command == ray.Command.STOP:
                self.sendErrorToCaller(OSC_SRC_STOP, - exit_code,
                                        error_text)
        else:
            if scripter_pending_command== ray.Command.SAVE:
                self.sendReplyToCaller(OSC_SRC_SAVE, 'saved')
            elif scripter_pending_command == ray.Command.START:
                self.sendReplyToCaller(OSC_SRC_START, 'started')
            elif scripter_pending_command == ray.Command.STOP:
                self.sendReplyToCaller(OSC_SRC_STOP, 'stopped')
        
        if scripter_pending_command == self.pending_command:
            self.pending_command = ray.Command.NONE
            
        if (scripter_pending_command == ray.Command.STOP
                and self.isRunning()):
            # if stop script ends with a not stopped client
            # We must stop it, else it would prevent session close
            self.stop()
        
        if self.session.wait_for:
            self.session.endTimerIfLastExpected(self)
    
    def nonNsmReady(self):
        if not self.non_nsm:
            return
        
        if not self.isRunning():
            # TODO send to GUI to show exproxy dialog
            return
        
        self.sendGuiMessage(
            _translate('GUIMSG', '  %s: project probably loaded')
                % self.guiMsgStyle())
                
        self.sendReplyToCaller(OSC_SRC_OPEN, 'client opened')
        
        self.pending_command = ray.Command.NONE
        self.setStatus(ray.ClientStatus.READY)
        
        if self.session.wait_for == ray.WaitFor.REPLY:
            self.session.endTimerIfLastExpected(self)
    
    def terminateScripts(self):
        self.scripter.terminate()
    
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
            
            for osc_slot in (OSC_SRC_START, OSC_SRC_OPEN):
                self.sendErrorToCaller(osc_slot, ray.Err.LAUNCH_FAILED,
                    _translate('GUIMSG', '%s failed to launch')
                        % self.guiMsgStyle())
            
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
        if self.non_nsm:
            print('zoefof', self.isRunning(), self.pending_command)
            return bool(self.isRunning()
                        and self.pending_command == ray.Command.NONE)
        
        return bool(self.active and not self.no_save_level)
    
    def save(self, src_addr=None, src_path=''):
        if self.switch_state in (ray.SwitchState.RESERVED,
                                 ray.SwitchState.NEEDED):
            if src_addr:
                self.send(src_addr, '/error', src_path, ray.Err.NOT_NOW,
                "Save cancelled because client has not switch yet !")
            return
        
        if src_addr:
            self._osc_srcs[OSC_SRC_SAVE] = (src_addr, src_path)
            
        if self.isRunning():
            if self.scripter.start(ray.Command.SAVE, src_addr,
                                   self._osc_srcs[OSC_SRC_SAVE]):
                self.setStatus(ray.ClientStatus.SCRIPT)
                return
        
        if self.pending_command == ray.Command.SAVE:
            self.sendErrorToCaller(OSC_SRC_SAVE, ray.Err.GENERAL_ERROR,
                _translate('GUIMSG', '%s is already saving, please wait!')
                    % self.guiMsgStyle())
        
        if self.isRunning():
            if self.non_nsm:
                if self.non_nsm_save_sig > 0:
                    self.pending_command = ray.Command.SAVE
                    self.setStatus(ray.ClientStatus.SAVE)
                    os.kill(self.process.processId(), self.non_nsm_save_sig)
                    QTimer.singleShot(300, self.nonNsmSaved)
                
            elif self.canSaveNow():
                Terminal.message("Telling %s to save" % self.name)
                self.sendToSelfAddress("/nsm/client/save")
                
                self.pending_command = ray.Command.SAVE
                self.setStatus(ray.ClientStatus.SAVE)
            
            elif self.isDumbClient():
                self.setStatus(ray.ClientStatus.NOOP)
                
            if self.isCapableOf(':optional-gui:'):
                self.start_gui_hidden = not bool(self.gui_visible)
    
    def nonNsmSaved(self):
        if not self.non_nsm:
            return
        
        if self.pending_command == ray.Command.SAVE:
            self.pending_command = ray.Command.NONE
            self.setStatus(ray.ClientStatus.READY)
            
            self.last_save_time = time.time()
                
            self.sendGuiMessage(
                _translate('GUIMSG', '  %s: saved') 
                    % self.guiMsgStyle())
            
            self.sendReplyToCaller(OSC_SRC_SAVE, 'client saved.')
        
        if self.session.wait_for == ray.WaitFor.REPLY:
            self.session.endTimerIfLastExpected(self)
            
    def stop(self, src_addr=None, src_path=''):
        if self.switch_state == ray.SwitchState.NEEDED:
            if src_addr:
                self.send(src_addr, '/error', src_path, ray.Err.NOT_NOW,
                "Stop cancelled because client is needed for opening session")
            return
        
        if src_addr:
            self._osc_srcs[OSC_SRC_STOP] = (src_addr, src_path)
        
        self.sendGuiMessage(_translate('GUIMSG', "  %s: stopping")
                                % self.guiMsgStyle())
            
        if self.isRunning():
            if self.scripter.start(ray.Command.STOP, src_addr,
                                   self._osc_srcs[OSC_SRC_STOP]):
                self.setStatus(ray.ClientStatus.SCRIPT)
                return
            
            self.pending_command = ray.Command.STOP
            self.setStatus(ray.ClientStatus.QUIT)
            
            if not self.stopped_timer.isActive():
                self.stopped_timer.start()
            
            if self.is_external:
                os.kill(self.pid, 15) # 15 means signal.SIGTERM
            else:
                self.process.terminate()
        else:
            self.sendReplyToCaller(OSC_SRC_STOP, 'client stopped.')
    
    def quit(self):
        Terminal.message("Commanding %s to quit" % self.name)
        if self.isRunning():
            self.pending_command = ray.Command.STOP
            self.terminate()
            self.setStatus(ray.ClientStatus.QUIT)
        else:
            self.sendGui("/ray/gui/client/status", self.client_id, 
                         ray.ClientStatus.REMOVED)
    
    def eatAttributes(self, new_client):
        self.client_id = new_client.client_id
        self.executable_path = new_client.executable_path
        self.arguments = new_client.arguments
        self.name = new_client.name
        self.prefix_mode = new_client.prefix_mode
        self.custom_prefix = new_client.custom_prefix
        self.label = new_client.label
        self.description = new_client.description
        self.icon = new_client.icon
        self.auto_start = new_client.auto_start
        self.check_last_save = new_client.check_last_save
        self.ignored_extensions = new_client.ignored_extensions
    
    def switch(self):
        jack_client_name    = self.getJackClientName()
        client_project_path = self.getProjectPath()
        
        Terminal.message("Commanding %s to switch \"%s\""
                         % (self.name, client_project_path))
        
        self.sendToSelfAddress("/nsm/client/open", client_project_path,
                               self.session.name, jack_client_name)
        
        self.pending_command = ray.Command.OPEN
        self.sendGuiClientProperties()
        self.setStatus(ray.ClientStatus.SWITCH)
    
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
                        self.description,
                        self.icon,
                        self.capabilities,
                        int(self.check_last_save),
                        self.ignored_extensions,
                        int(self.non_nsm))
        
        self.sent_to_gui = True
    
    def updateClientProperties(self, client_data):
        self.client_id       = client_data.client_id
        self.executable_path = client_data.executable_path
        self.arguments       = client_data.arguments
        self.prefix_mode     = client_data.prefix_mode
        self.custom_prefix   = client_data.custom_prefix
        self.label           = client_data.label
        self.description     = client_data.description
        self.icon            = client_data.icon
        self.capabilities    = client_data.capabilities
        self.check_last_save = client_data.check_last_save
        self.ignored_extensions = client_data.ignored_extensions
        self.non_nsm = client_data.non_nsm
        
        self.sendGuiClientProperties()
    
    def setPropertiesFromMessage(self, message):
        for line in message.split('\n'):
            property, colon, value = line.partition(':')
            
            if property == 'client_id':
                # do not change client_id !!!
                continue
            elif property == 'executable':
                self.executable_path = value
            elif property == 'arguments':
                self.arguments = value
            elif property == 'name':
                # do not change client name,
                # It will be re-sent by client itself
                continue
            elif property == 'prefix_mode':
                if value.isdigit() and 0 <= int(value) <= 2:
                    self.prefix_mode = int(value)
            elif property == 'custom_prefix':
                self.custom_prefix = value
            elif property == 'label':
                self.label = value
            elif property == 'description':
                # description could contains many lines
                continue
            elif property == 'icon':
                self.icon = value
            elif property == 'capabilities':
                # do not change capabilities, no sense !
                continue
            elif property == 'check_last_save':
                if value.isdigit():
                    self.check_last_save = bool(int(value))
            elif property == 'ignored_extensions':
                self.ignored_extensions = value
            elif property == 'non_nsm':
                # do not change non_nsm value
                continue
                
        self.sendGuiClientProperties()
    
    def getPropertiesMessage(self):
        message = """client_id:%s
executable:%s
arguments:%s
name:%s
prefix_mode:%i
custom_prefix:%s
label:%s
icon:%s
capabilities:%s
check_last_save:%i
ignored_extensions:%s
non_nsm:%i""" % (self.client_id, 
                         self.executable_path,
                         self.arguments,
                         self.name, 
                         self.prefix_mode, 
                         self.custom_prefix,
                         self.label,
                         self.icon,
                         self.capabilities,
                         int(self.check_last_save),
                         self.ignored_extensions,
                         int(self.non_nsm))
        return message
    
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
        # returns a list of full filenames
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
        
        scripts_dir = "%s/%s.%s" % (self.session.path, ray.SCRIPTS_DIR,
                                    self.client_id)
        
        if os.path.exists(scripts_dir):
            client_files.append(scripts_dir)
                    
        return client_files
    
    def get_description_from_desktop_file(self)->str:
        desk_path_list = ("%s/.local" % os.getenv('HOME'),
                          '/usr/local', '/usr')
        
        executable = self.executable_path
        if executable == 'ray-proxy':
            executable = self.getProxyExecutable()
        
        for desk_path in desk_path_list:
            desk_file = "%s/share/applications/%s.desktop" \
                        % (desk_path, executable)
            
            if not os.path.isfile(desk_file):
                continue
            
            try:
                file = open(desk_file, 'r')
                contents = file.read()
            except:
                continue
                
            comment_found = False
            tr_comment_found = False
            exec_found = False
            
            lang = os.getenv('LANG')
            
            comment_tr_5 = ""
            comment_tr_2 = ""
            comment = ""
            
            for line in contents.split('\n'):
                if line.startswith('[') and line != "[Desktop Entry]":
                    break
                
                if line.startswith("Comment[%s]=" % lang[0:2]):
                    comment_tr_2 = line.partition('=')[2]
                elif line.startswith("Comment[%s]=" % lang[0:5]):
                    comment_tr_5 = line.partition('=')[2]
                elif line.startswith("Comment="):
                    comment = line.partition('=')[2]
                elif line.startswith('Exec='):
                    exe_line = line.partition('=')[2]
                    
                    if executable in exe_line:
                        exec_found = True
            
            if not exec_found:
                continue
            
            if comment_tr_5:
                return comment_tr_5
            elif comment_tr_2:
                return comment_tr_2
            elif comment:
                return comment
            else:
                return ""
            
        return ""

    def saveAsTemplate(self, template_name, src_addr=None, src_path=''):
        if src_addr:
            self._osc_srcs[OSC_SRC_SAVE_TP] = (src_addr, src_path)
        #copy files
        client_files = self.getProjectFiles()
                    
        template_dir = "%s/%s" % (TemplateRoots.user_clients, 
                                    template_name)
        
        if os.path.exists(template_dir):
            if os.access(template_dir, os.W_OK):
                shutil.rmtree(template_dir)
            else:
                self.sendErrorToCaller(OSC_SRC_SAVE_TP, ray.Err.CREATE_FAILED,
                            _translate('GUIMSG', 'impossible to remove %s !')
                                % ray.highlightText(template_dir))
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
                                self.saveAsTemplate_substep1,
                                self.saveAsTemplateAborted,
                                [template_name])
        else:
            self.saveAsTemplate_substep1(template_name)

    def saveAsTemplate_substep1(self, template_name):
        self.setStatus(self.status) # see setStatus to see why
        
        if self.prefix_mode != ray.PrefixMode.CUSTOM:
            self.adjustFilesAfterCopy(template_name, ray.Template.CLIENT_SAVE)
            
        xml_file = "%s/%s" % (TemplateRoots.user_clients,
                              'client_templates.xml')
        
        # security check
        if os.path.exists(xml_file):
            if not os.access(xml_file, os.W_OK):
                self.sendErrorToCaller(OSC_SRC_SAVE_TP, ray.Err.CREATE_FAILED,
                                _translate('GUIMSG', '%s is not writeable !')
                                    % xml_file)
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
        
        self.sendReplyToCaller(OSC_SRC_SAVE_TP, 'client template created')
    
    def saveAsTemplateAborted(self, template_name):
        self.setStatus(self.status)
        self.sendErrorToCaller(OSC_SRC_SAVE_TP, ray.Err.COPY_ABORTED,
            _translate('GUIMSG', 'Copy has been aborted !'))
    
    def adjustFilesAfterCopy(self, new_session_full_name,
                             template_save=ray.Template.NONE):
        old_session_name = self.session.name
        new_session_name = basename(new_session_full_name)
        new_client_id = self.client_id
        old_client_id = self.client_id
        xsessionx = "XXX_SESSION_NAME_XXX"
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
        
        scripts_dir = "%s/%s.%s" % (spath, ray.SCRIPTS_DIR, old_client_id)
        if os.access(scripts_dir, os.W_OK):
            os.rename(scripts_dir,
                      "%s/%s.%s" % (spath, ray.SCRIPTS_DIR, new_client_id))
        
        
        project_path = "%s/%s.%s" % (spath, old_prefix, old_client_id)
        
        files_to_rename = []
        do_rename = True
        
        if self.non_nsm:
            if os.path.isdir(project_path):
                if not os.access(project_path, os.W_OK):
                    do_rename = False
                else:
                    os.environ['RAY_SESSION_NAME'] = old_session_name
                    os.environ['RAY_CLIENT_ID'] = old_client_id
                    pre_config_file = os.path.expandvars(
                                                    self.non_nsm_config_file)
                    
                    os.environ['RAY_SESSION_NAME'] = new_session_name
                    os.environ['RAY_CLIENT_ID'] = new_client_id
                    post_config_file = os.path.expandvars(
                                                    self.non_nsm_config_file)
                    
                    os.unsetenv('RAY_SESSION_NAME')
                    os.unsetenv('RAY_CLIENT_ID')
                    
                    full_pre_config_file = "%s/%s" % (project_path,
                                                 pre_config_file)
                    full_post_config_file = "%s/%s" % (project_path,
                                                 post_config_file)
                    
                    if os.path.exists(full_pre_config_file):
                        files_to_rename.append((full_pre_config_file,
                                                full_post_config_file))
                    
                    files_to_rename.append((project_path,
                        "%s/%s.%s" % (spath, new_prefix, new_client_id)))
        else:
            for file_path in os.listdir(spath):
                if file_path.startswith("%s.%s." % (old_prefix, old_client_id)):
                    if not os.access("%s/%s" % (spath, file_path), os.W_OK):
                        do_rename = False
                        break
                    
                    endfile = file_path.replace("%s.%s."
                                            % (old_prefix, old_client_id),
                                            '', 1)
                    
                    next_path = "%s/%s.%s.%s" % (spath, new_prefix,
                                                    new_client_id, endfile)
                    if os.path.exists(next_path):
                        do_rename = False
                        break
                    
                    files_to_rename.append(("%s/%s" % (spath, file_path),
                                            next_path))
                    
                elif file_path == "%s.%s" % (old_prefix, old_client_id):
                    if not os.access("%s/%s" % (spath, file_path), os.W_OK):
                        do_rename = False
                        break
                    
                    next_path = "%s/%s.%s" % (spath, new_prefix, new_client_id)
                    
                    if os.path.exists(next_path):
                        do_rename = False
                        break
                    
                    # only for ardour
                    ardour_file  = "%s/%s.ardour"     % (project_path, old_prefix)
                    ardour_bak   = "%s/%s.ardour.bak" % (project_path, old_prefix)
                    ardour_audio = "%s/interchange/%s.%s" % (project_path, 
                                                old_prefix, old_client_id)
                    
                    if os.path.isfile(ardour_file) and os.access(ardour_file, os.W_OK):
                        new_ardour_file = "%s/%s.ardour" % (project_path, new_prefix)
                        if os.path.exists(new_ardour_file):
                            do_rename = False
                            break
                        
                        files_to_rename.append((ardour_file, new_ardour_file))
                        
                    if os.path.isfile(ardour_bak) and os.access(ardour_bak, os.W_OK):
                        new_ardour_bak = "%s/%s.ardour.bak" % (project_path, new_prefix)
                        if os.path.exists(new_ardour_bak):
                            do_rename = False
                            break
                        
                        files_to_rename.append((ardour_bak, new_ardour_bak))
                    
                    if os.path.isdir(ardour_audio) and os.access(ardour_audio, os.W_OK):
                        new_ardour_audio = "%s/interchange/%s.%s" % (project_path,
                                                        new_prefix, new_client_id)
                        if os.path.exists(new_ardour_audio):
                            do_rename = False
                            break
                        
                        files_to_rename.append((ardour_audio, new_ardour_audio))
                    
                    #for Vee One Suite
                    for extfile in ('samplv1', 'synthv1', 'padthv1', 'drumkv1'):
                        old_veeone_file = "%s/%s.%s" % (project_path,
                                            old_session_name, extfile)
                        new_veeone_file = "%s/%s.%s" % (project_path,
                                            new_session_name, extfile)
                        if (os.path.isfile(old_veeone_file)
                                and os.access(old_veeone_file, os.W_OK)):
                            if os.path.exists(new_veeone_file):
                                do_rename = False
                                break
                            
                            files_to_rename.append((old_veeone_file,
                                                    new_veeone_file))
                    
                    # for ray-proxy, change config_file name
                    proxy_file = "%s/ray-proxy.xml" % project_path
                    if os.path.isfile(proxy_file):
                        try:
                            file = open(proxy_file, 'r')
                            xml = QDomDocument()
                            xml.setContent(file.read())
                            file.close()
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
                                            config_file.replace(env,
                                                                old_session_name)
                                    
                                    if (config_file
                                            and (config_file.split('.')[0]
                                                    == old_session_name)):
                                        config_file_path = "%s/%s" % (
                                                        project_path, config_file)
                                        
                                        new_config_file_path = "%s/%s" % (
                                            project_path,
                                            config_file.replace(old_session_name,
                                                                new_session_name))
                                        
                                        if (os.path.exists(new_config_file_path)):
                                            # replace config_file attribute
                                            # with variable replaced
                                            cte.setAttribute('config_file',
                                                            config_file)
                                            try:
                                                file = open(proxy_file, 'w')
                                                file.write(xml.toString())
                                            except:
                                                False
                                        elif (os.path.exists(config_file_path)
                                            and os.access(config_file_path,
                                                            os.W_OK)):
                                            files_to_rename.append(
                                                (config_file_path, 
                                                new_config_file_path))
                        except:
                            False
                    
                    files_to_rename.append(("%s/%s" % (spath, file_path),
                                            next_path))
                
        if not do_rename:
            self.prefix_mode = ray.PrefixMode.CUSTOM
            self.custom_prefix = old_prefix
            # it should not be a client_id problem here
            return
        
        # change last_used snapshot of ardour
        instant_file = "%s/instant.xml" % project_path
        if os.path.isfile(instant_file) and os.access(instant_file, os.W_OK):
            try:
                file = open(instant_file, 'r')
                xml = QDomDocument()
                xml.setContent(file.read())
                file.close()
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
            except:
                False
        
        for now_path, next_path in files_to_rename:
            os.rename(now_path, next_path)
    
    def serverAnnounce(self, path, args, src_addr, is_new):
        client_name, capabilities, executable_path, major, minor, pid = args
        
        if self.pending_command == ray.Command.STOP:
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
                
        self._last_announce_time = time.time()
