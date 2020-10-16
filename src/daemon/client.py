import os
import shlex
import shutil
import signal
import subprocess
import time
from liblo import Address
from PyQt5.QtCore import (QCoreApplication, QProcess,
                          QProcessEnvironment, QTimer)
from PyQt5.QtXml import QDomDocument

import ray
from server_sender import ServerSender
from daemon_tools  import TemplateRoots, Terminal, RS, getCodeRoot
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

class Client(ServerSender, ray.ClientData):
    _reply_errcode = 0
    _reply_message = None

    #can be directly changed by OSC thread
    gui_visible = False
    gui_has_been_visible = False
    show_gui_ordered = False
    dirty = 0
    progress = 0

    #have to be modified by main thread for security
    addr = None
    pid = 0
    pending_command = ray.Command.NONE
    active = False
    did_announce = False

    status = ray.ClientStatus.STOPPED

    running_executable = ''
    running_arguments = ''
    tmp_arguments = ''

    auto_start = True
    start_gui_hidden = False
    no_save_level = 0
    is_external = False
    sent_to_gui = False
    switch_state = ray.SwitchState.NONE

    ignored_extensions = ray.getGitIgnoredExtensions()

    last_save_time = 0.00
    last_dirty = 0.00
    _last_announce_time = 0.00
    last_open_duration = 0.00

    has_been_started = False

    _desktop_label = ""
    _desktop_icon = ""
    _desktop_description = ""

    _from_nsm_file = False

    def __init__(self, parent_session):
        ServerSender.__init__(self)
        self.session = parent_session
        self.is_dummy = self.session.is_dummy

        process_env = QProcessEnvironment.systemEnvironment()
        process_env.insert('NSM_URL', self.getServerUrl())

        self.custom_data = {}
        self.custom_tmp_data = {}

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

        self.ray_hack = ray.RayHack()
        self.ray_net = ray.RayNet()
        self.scripter = ClientScripter(self)

        self.ray_hack_waiting_win = False

    def isRayHack(self)->bool:
        return bool(self.protocol == ray.Protocol.RAY_HACK)

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
        self.sendErrorToCaller(OSC_SRC_OPEN,
            ray.Err.GENERAL_ERROR,
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
        self.desktop_file = ctx.attribute('desktop_file')
        self.label = ctx.attribute('label')
        self.description = ctx.attribute('description')
        self.icon = ctx.attribute('icon')
        self.auto_start = bool(ctx.attribute('launched') != '0')
        self.check_last_save = bool(ctx.attribute('check_last_save') != '0')
        self.start_gui_hidden = bool(ctx.attribute('gui_visible') == '0')
        self.template_origin = ctx.attribute('template_origin')
        self._from_nsm_file = bool(ctx.attribute('from_nsm_file') == '1')

        self.updateInfosFromDesktopFile()

        ign_exts = ctx.attribute('ignored_extensions').split(' ')
        unign_exts = ctx.attribute('unignored_extensions').split(' ')

        global_exts = ray.getGitIgnoredExtensions().split(' ')
        self.ignored_extensions = ""

        for ext in global_exts:
            if ext and not ext in unign_exts:
                self.ignored_extensions += " %s" % ext

        for ext in ign_exts:
            if ext and not ext in global_exts:
                self.ignored_extensions += " %s" % ext
        
        gui_force_str = ctx.attribute('optional_gui_force')
        if gui_force_str.isdigit():
            self.optional_gui_force = int(gui_force_str)
        elif self.executable_path in ('ray-proxy', 'nsm-proxy'):
            self.optional_gui_force = ray.OptionalGuiForce.NONE
        
        open_duration = ctx.attribute('last_open_duration')
        if open_duration.replace('.', '', 1).isdigit():
            self.last_open_duration = float(open_duration)
        
        prefix_mode = ctx.attribute('prefix_mode')

        if (prefix_mode and prefix_mode.isdigit()
                and 0 <= int(prefix_mode) <= 2):
            self.prefix_mode = int(prefix_mode)
            if self.prefix_mode == ray.PrefixMode.CUSTOM:
                self.custom_prefix = ctx.attribute('custom_prefix')

        self.protocol = ray.protocolFromStr(ctx.attribute('protocol'))

        if self.protocol == ray.Protocol.RAY_HACK:
            self.ray_hack.config_file = ctx.attribute('config_file')
            ray_hack_save_sig = ctx.attribute('save_signal')
            if ray_hack_save_sig.isdigit():
                self.ray_hack.save_sig = int(ray_hack_save_sig)

            ray_hack_stop_sig = ctx.attribute('stop_signal')
            if ray_hack_stop_sig.isdigit():
                self.ray_hack.stop_sig = int(ray_hack_stop_sig)

            self.ray_hack.wait_win = bool(ctx.attribute('wait_window') == "1")

            no_save_level = ctx.attribute('no_save_level')
            if no_save_level.isdigit() and 0 <= int(no_save_level) <= 2:
                self.ray_hack.no_save_level = int(no_save_level)

        # backward compatibility with network session
        if (self.protocol == ray.Protocol.NSM 
                and basename(self.executable_path) == 'ray-network'):
            self.protocol = ray.Protocol.RAY_NET

            if self.arguments:
                eat_url = eat_root = False

                for arg in shlex.split(self.arguments):
                    if arg in ('--daemon-url', '-u'):
                        eat_url = True
                        continue
                    elif arg in ('--session-root', '-r'):
                        eat_root = True
                        continue
                    elif not (eat_url or eat_root):
                        eat_url = False
                        eat_root = False
                        continue

                    if eat_url:
                        self.ray_net.daemon_url = arg
                        eat_url = False
                    elif eat_root:
                        self.ray_net.session_root = arg
                        eat_root = False
            self.ray_net.session_template = ctx.attribute('net_session_template')

        elif self.protocol == ray.Protocol.RAY_NET:
            self.ray_net.daemon_url = ctx.attribute('net_daemon_url')
            self.ray_net.session_root = ctx.attribute('net_session_root')
            self.ray_net.session_template = ctx.attribute('net_session_template')
        
        if self.protocol == ray.Protocol.RAY_NET:
            # neeeded only to know if RAY_NET client is capable of switch
            self.executable_path = ray.RAYNET_BIN
            if self.ray_net.daemon_url and self.ray_net.session_root:
                self.arguments = self.getRayNetArgumentsLine()

        if ctx.attribute('id'):
            #session use "id" for absolutely needed client_id
            self.client_id = ctx.attribute('id')
        else:
            #template use "client_id" for wanted client_id
            self.client_id = self.session.generateClientId(
                                                ctx.attribute('client_id'))

        nodes = ctx.childNodes()
        for i in range(nodes.count()):
            node = nodes.at(i)
            el = node.toElement()
            if el.tagName() == 'custom_data':
                attributes = el.attributes()
                for j in range(attributes.count()):
                    attribute = attributes.item(j)
                    attribute_str = attribute.toAttr().name()
                    value = el.attribute(attribute_str)
                    self.custom_data[attribute_str] = value

    def writeXmlProperties(self, ctx):
        if self.protocol != ray.Protocol.RAY_NET:
            ctx.setAttribute('executable', self.executable_path)
            if self.arguments:
                ctx.setAttribute('arguments', self.arguments)

        ctx.setAttribute('name', self.name)
        if self.desktop_file:
            ctx.setAttribute('desktop_file', self.desktop_file)
        if self.label != self._desktop_label:
            ctx.setAttribute('label', self.label)
        if self.description != self._desktop_description:
            ctx.setAttribute('description', self.description)
        if self.icon != self._desktop_icon:
            ctx.setAttribute('icon', self.icon)
        if not self.check_last_save:
            ctx.setAttribute('check_last_save', 0)

        if self.prefix_mode != ray.PrefixMode.SESSION_NAME:
            ctx.setAttribute('prefix_mode', self.prefix_mode)
            if self.prefix_mode == ray.PrefixMode.CUSTOM:
                ctx.setAttribute('custom_prefix', self.custom_prefix)

        if self.isCapableOf(':optional-gui:'):
            ctx.setAttribute('gui_visible',
                             str(int(not self.start_gui_hidden)))
            if self.optional_gui_force != ray.OptionalGuiForce.SHOW:
                ctx.setAttribute('optional_gui_force', self.optional_gui_force)

        if self._from_nsm_file:
            ctx.setAttribute('from_nsm_file', 1)

        if self.template_origin:
            ctx.setAttribute('template_origin', self.template_origin)

        if self.protocol != ray.Protocol.NSM:
            ctx.setAttribute('protocol', ray.protocolToStr(self.protocol))

            if self.protocol == ray.Protocol.RAY_HACK:
                ctx.setAttribute('config_file', self.ray_hack.config_file)
                ctx.setAttribute('save_signal', self.ray_hack.save_sig)
                ctx.setAttribute('stop_signal', self.ray_hack.stop_sig)
                ctx.setAttribute('wait_win', int(self.ray_hack.wait_win))
                ctx.setAttribute('no_save_level', self.ray_hack.no_save_level)

            elif self.protocol == ray.Protocol.RAY_NET:
                ctx.setAttribute('net_daemon_url', self.ray_net.daemon_url)
                ctx.setAttribute('net_session_root',
                                 self.ray_net.session_root)
                ctx.setAttribute('net_session_template',
                                 self.ray_net.session_template)

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

        if self.custom_data:
            xml = QDomDocument()
            cdt_xml = xml.createElement('custom_data')
            for data in self.custom_data:
                cdt_xml.setAttribute(data, self.custom_data[data])
            ctx.appendChild(cdt_xml)


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

                if self.hasServerOption(ray.Option.GUI_STATES):
                    if (self.session.wait_for == ray.WaitFor.NONE
                            and self.isCapableOf(':optional-gui:')
                            and not self.start_gui_hidden
                            and not self.gui_visible
                            and not self.gui_has_been_visible
                            and self.optional_gui_force & ray.OptionalGuiForce.SHOW):
                        self.sendToSelfAddress('/nsm/client/show_optional_gui')

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
        if self.isRayHack():
            return False

        return bool(not self.did_announce)

    def isCapableOf(self, capability)->bool:
        return bool(capability in self.capabilities)

    def guiMsgStyle(self)->str:
        return "%s (%s)" % (self.name, self.client_id)

    def setNetworkProperties(self, net_daemon_url, net_session_root):
        if self.protocol != ray.Protocol.RAY_NET:
            return

        self.ray_net.daemon_url = net_daemon_url
        self.ray_net.running_daemon_url = net_daemon_url
        self.ray_net.session_root = net_session_root
        self.ray_net.running_session_root = net_session_root
        self.sendGuiClientProperties()

    def getRayNetArgumentsLine(self)->str:
        if self.protocol != ray.Protocol.RAY_NET:
            return ''
        return '--daemon-url %s --net-session-root "%s"' % (
                self.ray_net.daemon_url,
                self.ray_net.session_root.replace('"', '\\"'))

    def netDaemonOutOfTime(self):
        self.ray_net.duplicate_state = -1

        if self.session.wait_for == ray.WaitFor.DUPLICATE_FINISH:
            self.session.endTimerIfLastExpected(self)

    def setStatus(self, status):
        # ray.ClientStatus.COPY is not a status as the other ones.
        # GUI needs to know if client is started/open/stopped while files are
        # copied, so self.status doesn't remember ray.ClientStatus.COPY,
        # although it is sent to GUI

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
        if self.protocol == ray.Protocol.RAY_NET:
            # ray-net will use jack_client_name for template
            # quite dirty, but this is the easier way
            return self.ray_net.session_template

        # return same jack_client_name as NSM does
        # if client seems to have been made by NSM itself
        # else, jack connections could be lose
        # at NSM session import
        if self._from_nsm_file:
            return "%s.%s" % (self.name, self.client_id)

        jack_client_name = self.name

        # Mostly for ray_hack
        if not jack_client_name:
            jack_client_name = os.path.basename(self.executable_path)
            jack_client_name.capitalize()

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

        if self.prefix_mode == ray.PrefixMode.CLIENT_NAME:
            return self.name

        if self.prefix_mode == ray.PrefixMode.CUSTOM:
            return self.custom_prefix

        return ''

    def getProjectPath(self):
        if self.protocol == ray.Protocol.RAY_NET:
            return self.session.getShortPath()

        if self.prefix_mode == ray.PrefixMode.SESSION_NAME:
            return "%s/%s.%s" % (self.session.path, self.session.name,
                                 self.client_id)

        if self.prefix_mode == ray.PrefixMode.CLIENT_NAME:
            return "%s/%s.%s" % (self.session.path, self.name, self.client_id)

        if self.prefix_mode == ray.PrefixMode.CUSTOM:
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
        if self.isRayHack():
            return ''

        os.environ['RAY_SESSION_NAME'] = self.session.name
        os.environ['RAY_CLIENT_ID'] = self.client_id

        expanded_config_file = os.path.expandvars(self.ray_hack.config_file)

        os.unsetenv('RAY_SESSION_NAME')
        os.unsetenv('RAY_CLIENT_ID')

        return expanded_config_file

    def start(self, src_addr=None, src_path='', wait_open_to_reply=False):
        if src_addr and not wait_open_to_reply:
            self._osc_srcs[OSC_SRC_START] = (src_addr, src_path)

        self.session.setRenameable(False)

        self.last_dirty = 0.00
        self.gui_has_been_visible = False
        self.gui_visible = False
        self.show_gui_ordered = False

        if self.is_dummy:
            self.sendErrorToCaller(OSC_SRC_START, ray.Err.GENERAL_ERROR,
                _translate('GUIMSG', "can't start %s, it is a dummy client !")
                    % self.guiMsgStyle())
            return

        if (self.protocol == ray.Protocol.RAY_NET
                and not self.session.path.startswith(self.session.root + '/')):
            self.sendErrorToCaller(OSC_SRC_START, ray.Err.GENERAL_ERROR,
                _translate('GUIMSG',
                    "Impossible to run Ray-Net client when session is not in root folder"))
            return

        if self.scripter.start(ray.Command.START, src_addr,
                               self._osc_srcs[OSC_SRC_START]):
            self.setStatus(ray.ClientStatus.SCRIPT)
            return

        self.pending_command = ray.Command.START

        arguments = []
        
        if self.protocol == ray.Protocol.RAY_NET:
            server = self.getServer()
            if not server:
                return

            arguments += ['--net-daemon-id', str(server.net_daemon_id)]
            if self.ray_net.daemon_url:
                arguments += ['--daemon-url', self.ray_net.daemon_url]
                if self.ray_net.session_root:
                    arguments += ['--session-root', self.ray_net.session_root]
            self.ray_net.running_daemon_url = self.ray_net.daemon_url
            self.ray_net.running_session_root = self.ray_net.session_root
            self.process.start(ray.RAYNET_BIN, arguments)
            return
        
        if self.tmp_arguments:
            arguments += shlex.split(self.tmp_arguments)

        arguments_line = self.arguments

        if self.isRayHack():
            all_envs = {'CONFIG_FILE': ('', ''),
                        'RAY_SESSION_NAME': ('', ''),
                        'RAY_CLIENT_ID': ('', ''),
                        'RAY_JACK_CLIENT_NAME': ('', '')}

            all_envs['RAY_SESSION_NAME'] = (os.getenv('RAY_SESSION_NAME'),
                                            self.session.name)
            all_envs['RAY_CLIENT_ID'] = (os.getenv('RAY_CLIENT_ID'),
                                         self.client_id)
            all_envs['RAY_JACK_CLIENT_NAME'] = (
                os.getenv('RAY_JACK_CLIENT_NAME'),
                self.getJackClientName())

            for env in all_envs:
                os.environ[env] = all_envs[env][1]

            os.environ['CONFIG_FILE'] = os.path.expandvars(
                                                    self.ray_hack.config_file)

            back_pwd = os.getenv('PWD')
            ray_hack_pwd = self.getProjectPath()
            os.environ['PWD'] = ray_hack_pwd

            if not os.path.exists(ray_hack_pwd):
                try:
                    os.makedirs(ray_hack_pwd)
                except:
                    os.environ['PWD'] = back_pwd
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
        
        self.running_executable = self.executable_path
        self.running_arguments = self.arguments

        if self.isRayHack():
            self.process.setWorkingDirectory(ray_hack_pwd)
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

    def send_signal(self, sig: int, src_addr=None, src_path=""):
        try:
            tru_sig = signal.Signals(sig)
        except:
            if src_addr:
                self.send(src_addr, '/error', src_path,
                          ray.Err.GENERAL_ERROR, 'invalid signal %i' % sig)
            return

        if not self.isRunning():
            if src_addr:
                self.send(src_addr, '/error', src_path,
                          ray.Err.GENERAL_ERROR,
                          'client %s is not running' % self.client_id)
            return

        os.kill(self.pid, sig)
        self.send(src_addr, '/reply', src_path, 'signal sent')

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

        if self.isRayHack():
            if self.noSaveLevel():
                self.sendGui('/ray/gui/client/no_save_level',
                             self.client_id, self.noSaveLevel())
            if self.ray_hack.config_file:
                self.pending_command = ray.Command.OPEN
                self.setStatus(ray.ClientStatus.OPEN)
                QTimer.singleShot(500, self.rayHackNearReady)

    def processFinished(self, exit_code, exit_status):
        self.stopped_timer.stop()
        self.is_external = False

        if self.pending_command == ray.Command.STOP:
            self.sendGuiMessage(_translate('GUIMSG',
                                    "  %s: terminated by server instruction")
                                    % self.guiMsgStyle())
        else:
            self.sendGuiMessage(_translate('GUIMSG',
                                           "  %s: terminated itself.")
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
            if scripter_pending_command == ray.Command.SAVE:
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

    def rayHackNearReady(self):
        if not self.isRayHack():
            return

        if not self.isRunning():
            # TODO send to GUI to show exproxy dialog
            return

        if self.ray_hack.wait_win:
            self.ray_hack_waiting_win = True
            if not self.session.window_waiter.isActive():
                self.session.window_waiter.start()
        else:
            self.rayHackReady()

    def rayHackReady(self):
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
            self.pid = 0
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
        if self.isRayHack():
            if not self.ray_hack.saveable():
                return False

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
            if self.isRayHack():
                self.pending_command = ray.Command.SAVE
                self.setStatus(ray.ClientStatus.SAVE)
                if self.ray_hack.save_sig > 0:
                    os.kill(self.process.processId(), self.ray_hack.save_sig)
                QTimer.singleShot(300, self.rayHackSaved)

            elif self.canSaveNow():
                Terminal.message("Telling %s to save" % self.name)
                self.sendToSelfAddress("/nsm/client/save")

                self.pending_command = ray.Command.SAVE
                self.setStatus(ray.ClientStatus.SAVE)

            elif self.isDumbClient():
                self.setStatus(ray.ClientStatus.NOOP)

            if self.isCapableOf(':optional-gui:'):
                self.start_gui_hidden = not bool(self.gui_visible)

    def rayHackSaved(self):
        if not self.isRayHack():
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
            elif self.isRayHack() and self.ray_hack.stop_sig != 15:
                os.kill(self.process.pid(), self.ray_hack.stop_sig)
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
        self.desktop_file = new_client.desktop_file
        self.label = new_client.label
        self.description = new_client.description
        self.icon = new_client.icon
        self.auto_start = new_client.auto_start
        self.check_last_save = new_client.check_last_save
        self.ignored_extensions = new_client.ignored_extensions
        self.custom_data = new_client.custom_data
        self.description = new_client.description
        self._from_nsm_file = new_client._from_nsm_file

        self._desktop_label = new_client._desktop_label
        self._desktop_description = new_client._desktop_description
        self._desktop_icon = new_client._desktop_icon
        print('oezko', self.client_id, self.gui_visible, new_client.gui_visible)
        #self.gui_visible = new_client.gui_visible
        self.gui_has_been_visible = self.gui_visible

    def switch(self):
        jack_client_name = self.getJackClientName()
        client_project_path = self.getProjectPath()

        Terminal.message("Commanding %s to switch \"%s\""
                         % (self.name, client_project_path))

        self.sendToSelfAddress("/nsm/client/open", client_project_path,
                               self.session.name, jack_client_name)

        self.pending_command = ray.Command.OPEN
        self.sendGuiClientProperties()
        self.setStatus(ray.ClientStatus.SWITCH)
        if self.isCapableOf(':optional-gui:'):
            self.sendGui('/ray/gui/client/has_optional_gui', 
                         self.client_id)
            print('eorkk', self.client_id, self.gui_visible)
            self.sendGui('/ray/gui/client/gui_visible',
                         self.client_id, int(self.gui_visible))

    def canSwitchWith(self, other_client)->bool:
        if self.protocol == ray.Protocol.RAY_HACK:
            return False

        if self.protocol != other_client.protocol:
            return False

        if not (self.active and self.isCapableOf(':switch:')
                or (self.isDumbClient() and self.isRunning())):
            return False

        if self.protocol == ray.Protocol.RAY_NET:
            return bool(self.ray_net.running_daemon_url
                            == other_client.ray_net.daemon_url
                        and self.ray_net.running_session_root
                            == other_client.ray_net.session_root)

        return bool(self.running_executable == other_client.executable_path
                    and self.running_arguments == other_client.arguments)

    def sendGuiClientProperties(self, removed=False):
        ad = '/ray/gui/client/update' if self.sent_to_gui else '/ray/gui/client/new'
        hack_ad = '/ray/gui/client/ray_hack_update'
        net_ad = '/ray/gui/client/ray_net_update'

        if removed:
            ad = '/ray/gui/trash/add'
            hack_ad = '/ray/gui/trash/ray_hack_update'
            net_ad = '/ray/gui/trash/ray_net_update'

        self.sendGui(ad, *ray.ClientData.spreadClient(self))
        if self.protocol == ray.Protocol.RAY_HACK:
            self.sendGui(hack_ad,
                         self.client_id,
                         *self.ray_hack.spread())
        elif self.protocol == ray.Protocol.RAY_NET:
            self.sendGui(net_ad,
                         self.client_id,
                         *self.ray_net.spread())

        self.sent_to_gui = True

    def setPropertiesFromMessage(self, message):
        for line in message.split('\n'):
            prop, colon, value = line.partition(':')

            if prop == 'client_id':
                # do not change client_id !!!
                continue
            elif prop == 'executable':
                self.executable_path = value
            elif prop == 'arguments':
                self.arguments = value
            elif prop == 'name':
                # do not change client name,
                # It will be re-sent by client itself
                continue
            elif prop == 'prefix_mode':
                if value.isdigit() and 0 <= int(value) <= 2:
                    self.prefix_mode = int(value)
            elif prop == 'custom_prefix':
                self.custom_prefix = value
            elif prop == 'label':
                self.label = value
            elif prop == 'desktop_file':
                self.desktop_file = value
            elif prop == 'description':
                # description could contains many lines
                continue
            elif prop == 'icon':
                self.icon = value
            elif prop == 'capabilities':
                # do not change capabilities, no sense !
                continue
            elif prop == 'check_last_save':
                if value.isdigit():
                    self.check_last_save = bool(int(value))
            elif prop == 'ignored_extensions':
                self.ignored_extensions = value
            elif prop == 'protocol':
                # do not change protocol value
                continue
            elif prop == 'optional_gui_force':
                if value.isdigit():
                    self.optional_gui_force = int(value)

            if self.protocol == ray.Protocol.RAY_HACK:
                if prop == 'config_file':
                    self.ray_hack.config_file = value
                elif prop == 'save_sig':
                    try:
                        sig = signal.Signals(int(value))
                        self.ray_hack.save_sig = int(value)
                    except:
                        continue
                elif prop == 'stop_sig':
                    try:
                        sig = signal.Signals(int(value))
                        self.ray_hack.stop_sig = int(value)
                    except:
                        continue
                elif prop == 'wait_win':
                    self.ray_hack.wait_win = bool(
                        value.lower() in ('1', 'true'))
                elif prop == 'no_save_level':
                    if value.isdigit() and 0 <= int(value) <= 2:
                        self.ray_hack.no_save_level = int(value)

            elif self.protocol == ray.Protocol.RAY_NET:
                if prop == 'net_daemon_url':
                    self.ray_net.daemon_url = value
                elif prop == 'net_session_root':
                    self.ray_net.session_root = value
                elif prop == 'net_session_template':
                    self.ray_net.session_template = value

        self.sendGuiClientProperties()

    def getPropertiesMessage(self):
        message = """client_id:%s
protocol:%s
executable:%s
arguments:%s
name:%s
prefix_mode:%i
custom_prefix:%s
desktop_file:%s
label:%s
icon:%s
check_last_save:%i
ignored_extensions:%s
optional_gui_force:%i""" % (self.client_id,
                            ray.protocolToStr(self.protocol),
                            self.executable_path,
                            self.arguments,
                            self.name,
                            self.prefix_mode,
                            self.custom_prefix,
                            self.desktop_file,
                            self.label,
                            self.icon,
                            int(self.check_last_save),
                            self.ignored_extensions,
                            self.optional_gui_force)

        if self.protocol == ray.Protocol.NSM:
            message += "\ncapabilities:%s" % self.capabilities
        elif self.protocol == ray.Protocol.RAY_HACK:
            message += """\nconfig_file:%s
save_sig:%i
stop_sig:%i
wait_win:%i
no_save_level:%i""" % (self.ray_hack.config_file,
                       self.ray_hack.save_sig,
                       self.ray_hack.stop_sig,
                       int(self.ray_hack.wait_win),
                       self.ray_hack.no_save_level)
        elif self.protocol == ray.Protocol.RAY_NET:
            message += """\nnet_daemon_url:%s
net_session_root:%s
net_session_template:%s""" % (self.ray_net.daemon_url,
                              self.ray_net.session_root,
                              self.ray_net.session_template)
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

    def noSaveLevel(self)->int:
        if self.isRayHack():
            return self.ray_hack.noSaveLevel()

        return self.no_save_level

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
                    full_file_name = "%s/%s" % (self.session.path, filename)
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

    def setInfosFromDesktopContents(self, contents: str):
        lang = os.getenv('LANG')
        lang_strs = ("[%s]" % lang[0:5], "[%s]" % lang[0:2], "")
        all_data = {"Comment": ['', '', ''],
                    "Name":    ['', '', ''],
                    "Icon":    ['', '', '']}

        for line in contents.split('\n'):
            if line.startswith('[') and line != "[Desktop Entry]":
                break

            if '=' not in line:
                continue

            var, egal, value = line.partition('=')
            found = False

            for searched in all_data:
                for i in range(len(lang_strs)):
                    lang_str = lang_strs[i]
                    if var == searched + lang_str:
                        all_data[searched][i] = value
                        found = True
                        break

                if found:
                    break

        for data in all_data:
            for str_value in all_data[data]:
                if data == "Comment":
                    if str_value and not self.description:
                        self._desktop_description = str_value
                        self.description = str_value
                        break
                elif data == "Name":
                    if str_value and not self.label:
                        self._desktop_label = str_value
                        self.label = str_value
                        break
                elif data == "Icon":
                    if str_value and not self.icon:
                        self._desktop_icon = str_value
                        self.icon = str_value
                        break

    def updateInfosFromDesktopFile(self):
        if self.icon and self.description and self.label:
            return

        desk_path_list = (
            '%s/data' % getCodeRoot(),
            '%s/.local' % os.getenv('HOME'),
            '/usr/local',
            '/usr')

        desktop_file = self.desktop_file
        if desktop_file == '//not_found':
            return

        if not desktop_file:
            desktop_file = os.path.basename(self.executable_path)

        if not desktop_file.endswith('.desktop'):
            desktop_file += ".desktop"

        for desk_path in desk_path_list:
            org_prefixs = ('', 'org.gnome.', 'org.kde.')
            desk_file = ''

            for org_prefix in org_prefixs:
                desk_file = "%s/share/applications/%s%s" % (
                    desk_path, org_prefix, desktop_file)

                if os.path.isfile(desk_file):
                    break
            else:
                continue

            try:
                file = open(desk_file, 'r')
                contents = file.read()
            except:
                continue

            self.setInfosFromDesktopContents(contents)
            break

        else:
            desk_file_found = False
            for desk_path in desk_path_list:
                full_desk_path = "%s/share/applications" % desk_path
                if not os.path.isdir(full_desk_path):
                    # applications folder doesn't exists
                    continue

                if not os.access(full_desk_path, os.R_OK):
                    # no permission to read this applications folder
                    continue

                for desk_file in os.listdir(full_desk_path):
                    if not desk_file.endswith('.desktop'):
                        continue

                    full_desk_file = "%s/share/applications/%s" \
                                        % (desk_path, desk_file)

                    if os.path.isdir(full_desk_file):
                        continue

                    try:
                        file = open(full_desk_file, 'r')
                        contents = file.read()
                    except:
                        continue

                    for line in contents.split('\n'):
                        if line.startswith('Exec='):
                            value = line.partition('=')[2]
                            if (value == self.executable_path
                                    or value.startswith(
                                        "%s " % self.executable_path)
                                    or value.endswith(
                                        " %s" % self.executable_path)
                                    or " %s " in value):
                            #if self.executable_path in value:
                                desk_file_found = True

                                self.desktop_file = desk_file
                                self.setInfosFromDesktopContents(contents)
                                break

                    if desk_file_found:
                        break
                if desk_file_found:
                    break
            else:
                self.desktop_file = '//not_found'

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

        if self.protocol == ray.Protocol.RAY_NET:
            if self.ray_net.daemon_url:
                self.ray_net.session_template = template_name
                self.send(Address(self.ray_net.daemon_url),
                          '/ray/server/save_session_template',
                          self.session.name,
                          template_name,
                          self.net_session_root)

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

        self.template_origin = template_name
        self.sendGuiClientProperties()

        self.sendGuiMessage(
            _translate('message', 'Client template %s created')
                % template_name)

        self.sendReplyToCaller(OSC_SRC_SAVE_TP, 'client template created')

    def saveAsTemplateAborted(self, template_name):
        self.setStatus(self.status)
        self.sendErrorToCaller(OSC_SRC_SAVE_TP, ray.Err.COPY_ABORTED,
            _translate('GUIMSG', 'Copy has been aborted !'))

    def changePrefix(self, prefix_mode: int, custom_prefix: str):
        if self.isRunning():
            return

        old_prefix = self.session.name
        if self.prefix_mode == ray.PrefixMode.CLIENT_NAME:
            old_prefix = self.name
        elif self.prefix_mode == ray.PrefixMode.CUSTOM:
            old_prefix = self.custom_prefix

        new_prefix = self.session.name
        if prefix_mode == ray.PrefixMode.CLIENT_NAME:
            new_prefix = self.name
        elif prefix_mode == ray.PrefixMode.CUSTOM:
            new_prefix = custom_prefix

        self.renameFiles(self.session.path,
                         self.session.name, self.session.name,
                         old_prefix, new_prefix,
                         self.client_id, self.client_id)

        self.prefix_mode = prefix_mode
        self.custom_prefix = custom_prefix
        self.sendGuiClientProperties()

    def adjustFilesAfterCopy(self, new_session_full_name,
                             template_save=ray.Template.NONE):
        spath = self.session.path
        old_session_name = self.session.name
        new_session_name = basename(new_session_full_name)
        new_client_id = self.client_id
        old_client_id = self.client_id
        xsessionx = "XXX_SESSION_NAME_XXX"
        xclient_idx = "XXX_CLIENT_ID_XXX"

        if template_save == ray.Template.NONE:
            if self.prefix_mode != ray.PrefixMode.SESSION_NAME:
                return

            spath = ray.getFullPath(self.session.root, new_session_full_name)

        elif template_save == ray.Template.RENAME:
            spath = self.session.path

        elif template_save == ray.Template.SESSION_SAVE:
            spath = ray.getFullPath(TemplateRoots.user_sessions,
                                    new_session_full_name)
            new_session_name = xsessionx

        elif template_save == ray.Template.SESSION_SAVE_NET:
            spath = "%s/%s/%s" % (self.session.root,
                                  TemplateRoots.net_session_name,
                                  new_session_full_name)
            new_session_name = xsessionx

        elif template_save == ray.Template.SESSION_LOAD:
            spath = ray.getFullPath(self.session.root, new_session_full_name)
            old_session_name = xsessionx

        elif template_save == ray.Template.SESSION_LOAD_NET:
            spath = ray.getFullPath(self.session.root, new_session_full_name)
            old_session_name = xsessionx

        elif template_save == ray.Template.CLIENT_SAVE:
            spath = "%s/%s" % (TemplateRoots.user_clients,
                               new_session_full_name)
            new_session_name = xsessionx
            new_client_id = xclient_idx

        elif template_save == ray.Template.CLIENT_LOAD:
            spath = self.session.path
            old_session_name = xsessionx
            old_client_id = xclient_idx

        old_prefix = old_session_name
        new_prefix = new_session_name

        if self.prefix_mode == ray.PrefixMode.CLIENT_NAME:
            old_prefix = new_prefix = self.name
        elif self.prefix_mode == ray.PrefixMode.CUSTOM:
            old_prefix = new_prefix = self.custom_prefix

        self.renameFiles(spath, old_session_name, new_session_name,
                         old_prefix, new_prefix,
                         old_client_id, new_client_id)

    def renameFiles(self, spath,
                    old_session_name, new_session_name,
                    old_prefix, new_prefix,
                    old_client_id, new_client_id):
        scripts_dir = "%s/%s.%s" % (spath, ray.SCRIPTS_DIR, old_client_id)
        if os.access(scripts_dir, os.W_OK):
            os.rename(scripts_dir,
                      "%s/%s.%s" % (spath, ray.SCRIPTS_DIR, new_client_id))

        project_path = "%s/%s.%s" % (spath, old_prefix, old_client_id)

        files_to_rename = []
        do_rename = True

        if self.isRayHack():
            if os.path.isdir(project_path):
                if not os.access(project_path, os.W_OK):
                    do_rename = False
                else:
                    os.environ['RAY_SESSION_NAME'] = old_session_name
                    os.environ['RAY_CLIENT_ID'] = old_client_id
                    pre_config_file = os.path.expandvars(
                                                    self.ray_hack.config_file)

                    os.environ['RAY_SESSION_NAME'] = new_session_name
                    os.environ['RAY_CLIENT_ID'] = new_client_id
                    post_config_file = os.path.expandvars(
                                                    self.ray_hack.config_file)

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
                    ardour_file = "%s/%s.ardour" % (project_path, old_prefix)
                    ardour_bak = "%s/%s.ardour.bak" % (project_path, old_prefix)
                    ardour_audio = "%s/interchange/%s.%s" % (project_path,
                                                old_prefix, old_client_id)

                    if os.path.isfile(ardour_file) and os.access(ardour_file, os.W_OK):
                        new_ardour_file = "%s/%s.ardour" % (project_path, new_prefix)
                        if os.path.exists(new_ardour_file):
                            do_rename = False
                            break

                        files_to_rename.append((ardour_file, new_ardour_file))

                     # change Session name
                    try:
                        file = open(ardour_file, 'r')
                        xml = QDomDocument()
                        xml.setContent(file.read())
                        file.close()
                        root = xml.documentElement()

                        if root.tagName() == 'Session':
                            root.setAttribute('name', new_prefix)
                            file = open(ardour_file, 'w')
                            file.write(xml.toString())

                    except:
                        False

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

                                        if os.path.exists(new_config_file_path):
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
        self.addr = src_addr
        self.name = client_name
        self.active = True
        self.did_announce = True

        if is_new:
            self.is_external = True
            self.pid = pid
            self.running_executable = executable_path

        if self.executable_path in RS.non_active_clients:
            RS.non_active_clients.remove(self.executable_path)

        Terminal.message("Process has pid: %i" % pid)
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

        if self.isCapableOf(":optional-gui:"):
            self.sendGui("/ray/gui/client/has_optional_gui", self.client_id)

            if (self.hasServerOption(ray.Option.GUI_STATES)
                    and self.start_gui_hidden
                    and self.optional_gui_force & ray.OptionalGuiForce.HIDE_EARLY
                    and self.gui_visible):
                self.send(src_addr, "/nsm/client/hide_optional_gui")

        self.sendGuiClientProperties()
        self.setStatus(ray.ClientStatus.OPEN)

        client_project_path = self.getProjectPath()
        jack_client_name = self.getJackClientName()

        if self.protocol == ray.Protocol.RAY_NET:
            client_project_path = self.session.getShortPath()
            jack_client_name = self.ray_net.session_template

        self.send(src_addr, "/nsm/client/open", client_project_path,
                  self.session.name, jack_client_name)

        self.pending_command = ray.Command.OPEN

        if self.isCapableOf(":optional-gui:"):
            if (self.hasServerOption(ray.Option.GUI_STATES)
                    and self.start_gui_hidden
                    and self.optional_gui_force & ray.OptionalGuiForce.HIDE
                    and self.gui_visible):
                self.send(src_addr, "/nsm/client/hide_optional_gui")

        self._last_announce_time = time.time()
