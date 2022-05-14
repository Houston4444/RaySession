import os
import shlex
import shutil
import signal
import time
from pathlib import Path
from liblo import Address
from PyQt5.QtCore import (QCoreApplication, QProcess,
                          QProcessEnvironment, QTimer)
from PyQt5.QtXml import QDomDocument, QDomElement


import xdg
import ray
from server_sender import ServerSender
from daemon_tools  import (TemplateRoots, Terminal, RS,
                           get_code_root, highlight_text)
from signaler import Signaler
from scripter import ClientScripter

# only used to identify session functions in the IDE
# 'Session' is not importable simply because it would be
# a circular import.
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from session_signaled import SignaledSession

NSM_API_VERSION_MAJOR = 1
NSM_API_VERSION_MINOR = 0

OSC_SRC_START = 0
OSC_SRC_OPEN = 1
OSC_SRC_SAVE = 2
OSC_SRC_SAVE_TP = 3
OSC_SRC_STOP = 4

_translate = QCoreApplication.translate
signaler = Signaler.instance()


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

    last_save_time = 0.00
    last_dirty = 0.00
    _last_announce_time = 0.00
    last_open_duration = 0.00

    has_been_started = False

    _desktop_label = ""
    _desktop_icon = ""
    _desktop_description = ""

    jack_naming = ray.JackNaming.SHORT

    def __init__(self, parent_session: 'SignaledSession'):
        ServerSender.__init__(self)
        self.session = parent_session
        self.is_dummy = self.session.is_dummy

        # process_env = QProcessEnvironment.systemEnvironment()
        # process_env.insert('NSM_URL', self.get_server_url())

        self.custom_data = {}
        self.custom_tmp_data = {}

        self._process = QProcess()
        self._process.started.connect(self._process_started)
        if ray.QT_VERSION >= (5, 6):
            self._process.errorOccurred.connect(self._error_in_process)
        self._process.finished.connect(self._process_finished)
        self._process.readyReadStandardError.connect(self._standard_error)
        self._process.readyReadStandardOutput.connect(self._standard_output)
        # self._process.setProcessEnvironment(process_env)

        #if client is'n't stopped 2secs after stop,
        #another stop becames a kill!
        self._stopped_since_long_ = False
        self._stopped_timer = QTimer()
        self._stopped_timer.setSingleShot(True)
        self._stopped_timer.setInterval(2000) #2sec
        self._stopped_timer.timeout.connect(self._stopped_since_long)

        self.net_daemon_copy_timer = QTimer()
        self.net_daemon_copy_timer.setSingleShot(True)
        self.net_daemon_copy_timer.setInterval(3000)
        self.net_daemon_copy_timer.timeout.connect(self._net_daemon_out_of_time)

        # stock osc src_addr and src_path of respectively
        # start, open, save, save_tp, stop
        self._osc_srcs = [(None, ''), (None, ''), (None, ''),
                          (None, ''), (None, '')]

        self._open_timer = QTimer()
        self._open_timer.setSingleShot(True)
        self._open_timer.timeout.connect(self._open_timer_timeout)

        self.ray_hack = ray.RayHack()
        self.ray_net = ray.RayNet()
        self.scripter = ClientScripter(self)

        self.ray_hack_waiting_win = False

    @staticmethod
    def short_client_id(wanted:str)->str:
        if '_' in wanted:
            begin, udsc, end = wanted.rpartition('_')

            if not end:
                return wanted

            if not end.isdigit():
                return wanted

            return begin

        return wanted

    def _standard_error(self):
        standard_error = self._process.readAllStandardError().data()
        Terminal.client_message(standard_error, self.name, self.client_id)

    def _standard_output(self):
        standard_output = self._process.readAllStandardOutput().data()
        Terminal.client_message(standard_output, self.name, self.client_id)

    def _process_started(self):
        self.has_been_started = True
        self._stopped_since_long_ = False
        self.pid = self._process.pid()
        self.set_status(ray.ClientStatus.LAUNCH)

        #Terminal.message("Process has pid: %i" % self.pid)

        self.send_gui_message(_translate("GUIMSG", "  %s: launched")
                            % self.gui_msg_style())

        self.session.send_monitor_event('started', self.client_id)

        self._send_reply_to_caller(OSC_SRC_START, 'client started')

        if self.is_ray_hack():
            if self.noSaveLevel():
                self.send_gui('/ray/gui/client/no_save_level',
                              self.client_id, self.noSaveLevel())
            if self.ray_hack.config_file:
                self.pending_command = ray.Command.OPEN
                self.set_status(ray.ClientStatus.OPEN)
                QTimer.singleShot(500, self._ray_hack_near_ready)

    def _process_finished(self, exit_code, exit_status):
        self._stopped_timer.stop()
        self.is_external = False

        if self.pending_command == ray.Command.STOP:
            self.send_gui_message(_translate('GUIMSG',
                                  "  %s: terminated by server instruction")
                                  % self.gui_msg_style())
            
            self.session.send_monitor_event(
                'client_stopped_by_server', self.client_id)
        else:
            self.send_gui_message(_translate('GUIMSG',
                                           "  %s: terminated itself.")
                                    % self.gui_msg_style())
            
            self.session.send_monitor_event(
                'client_stopped_by_itself', self.client_id)

        self._send_reply_to_caller(OSC_SRC_STOP, 'client stopped')

        for osc_src in (OSC_SRC_OPEN, OSC_SRC_SAVE):
            self._send_error_to_caller(osc_src, ray.Err.GENERAL_ERROR,
                    _translate('GUIMSG', '%s died !' % self.gui_msg_style()))

        self.set_status(ray.ClientStatus.STOPPED)

        self.pending_command = ray.Command.NONE
        self.active = False
        self.pid = 0
        self.addr = None

        self.session.set_renameable(True)

        if self.scripter.pending_command() == ray.Command.STOP:
            return

        if self.session.wait_for:
            self.session.end_timer_if_last_expected(self)

    def _error_in_process(self, error: int):
        if error == QProcess.FailedToStart:
            self.send_gui_message(
                _translate('GUIMSG', "  %s: Failed to start !")
                    % self.gui_msg_style())
            self.active = False
            self.pid = 0
            self.set_status(ray.ClientStatus.STOPPED)
            self.pending_command = ray.Command.NONE

            if self.session.osc_src_addr:
                error_message = "Failed to launch process!"
                if not self.session.osc_path.startswith('/nsm/server/'):
                    error_message = _translate(
                        'client',
                        " %s: Failed to launch process !"
                            % self.gui_msg_style())

                self.session.osc_reply(
                    "/error", self.session.osc_path,
                    ray.Err.LAUNCH_FAILED, error_message)

            for osc_slot in (OSC_SRC_START, OSC_SRC_OPEN):
                self._send_error_to_caller(osc_slot, ray.Err.LAUNCH_FAILED,
                    _translate('GUIMSG', '%s failed to launch')
                        % self.gui_msg_style())

            if self.session.wait_for:
                self.session.end_timer_if_last_expected(self)
        self.session.set_renameable(True)

    def _stopped_since_long(self):
        self._stopped_since_long_ = True
        self.send_gui('/ray/gui/client/still_running', self.client_id)

    def _send_reply_to_caller(self, slot, message):
        src_addr, src_path = self._osc_srcs[slot]
        if src_addr:
            self.send(src_addr, '/reply', src_path, message)
            self._osc_srcs[slot] = (None, '')

            if (self.scripter.is_running()
                    and self.scripter.pending_command() == self.pending_command):
                self._osc_srcs[slot] = self.scripter.initial_caller()

        if slot == OSC_SRC_OPEN:
            self._open_timer.stop()

    def _send_error_to_caller(self, slot, err, message):
        src_addr, src_path = self._osc_srcs[slot]
        if src_addr:
            self.send(src_addr, '/error', src_path, err, message)
            self._osc_srcs[slot] = (None, '')

            if (self.scripter.is_running()
                    and self.scripter.pending_command() == self.pending_command):
                self._osc_srcs[slot] = self.scripter.initial_caller()

        if slot == OSC_SRC_OPEN:
            self._open_timer.stop()

    def _open_timer_timeout(self):
        self._send_error_to_caller(OSC_SRC_OPEN,
            ray.Err.GENERAL_ERROR,
            _translate('GUIMSG', '%s is started but not active')
                % self.gui_msg_style())

    def _send_status_to_gui(self):
        self.send_gui('/ray/gui/client/status', self.client_id, self.status)

    def _net_daemon_out_of_time(self):
        self.ray_net.duplicate_state = -1

        if self.session.wait_for == ray.WaitFor.DUPLICATE_FINISH:
            self.session.end_timer_if_last_expected(self)

    def _pretty_client_id(self):
        wanted = self.client_id

        if self.executable_path == 'ray-proxy':
            proxy_file = "%s/ray-proxy.xml" % self.get_project_path()

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

        return self.short_client_id(wanted)

    def _get_proxy_executable(self):
        if os.path.basename(self.executable_path) != 'ray-proxy':
            return ""
        xml_file = "%s/ray-proxy.xml" % self.get_project_path()
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

    def _ray_hack_near_ready(self):
        if not self.is_ray_hack():
            return

        if not self.is_running():
            return

        if self.ray_hack.wait_win:
            self.ray_hack_waiting_win = True
            if not self.session.window_waiter.isActive():
                self.session.window_waiter.start()
        else:
            self.ray_hack_ready()

    def _ray_hack_saved(self):
        if not self.is_ray_hack():
            return

        if self.pending_command == ray.Command.SAVE:
            self.pending_command = ray.Command.NONE
            self.set_status(ray.ClientStatus.READY)

            self.last_save_time = time.time()

            self.send_gui_message(
                _translate('GUIMSG', '  %s: saved')
                    % self.gui_msg_style())

            self._send_reply_to_caller(OSC_SRC_SAVE, 'client saved.')

        if self.session.wait_for == ray.WaitFor.REPLY:
            self.session.end_timer_if_last_expected(self)

    def _set_infos_from_desktop_contents(self, contents: str):
        lang = os.getenv('LANG')
        lang_strs = ("[%s]" % lang[0:5], "[%s]" % lang[0:2], "")
        all_data = {'Comment': ['', '', ''],
                    'Name': ['', '', ''],
                    'Icon': ['', '', '']}

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

    def _rename_files(
            self, spath, old_session_name, new_session_name,
            old_prefix, new_prefix, old_client_id, new_client_id,
            old_client_links_dir, new_client_links_dir):
        # rename client script dir
        scripts_dir = "%s/%s.%s" % (spath, ray.SCRIPTS_DIR, old_client_id)
        if os.access(scripts_dir, os.W_OK) and old_client_id != new_client_id:
            os.rename(scripts_dir,
                      "%s/%s.%s" % (spath, ray.SCRIPTS_DIR, new_client_id))

        project_path = "%s/%s.%s" % (spath, old_prefix, old_client_id)

        files_to_rename = []
        do_rename = True

        if self.is_ray_hack():
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

                    endfile = file_path.replace(
                        "%s.%s." % (old_prefix, old_client_id), '', 1)

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

                    # only for hydrogen
                    hydrogen_file = "%s/%s.%s.h2song" % (
                        project_path, old_prefix, old_client_id)
                    hydrogen_autosave = "%s/%s.%s.autosave.h2song" % (
                        project_path, old_prefix, old_client_id)

                    if (os.path.isfile(hydrogen_file)
                            and os.access(hydrogen_file, os.W_OK)):
                        new_hydro_file = "%s/%s.%s.h2song" % (
                            project_path, new_prefix, new_client_id)
                        if os.path.exists(new_hydro_file):
                            do_rename = False
                            break

                        files_to_rename.append((hydrogen_file, new_hydro_file))

                    if (os.path.isfile(hydrogen_autosave)
                            and os.access(hydrogen_autosave, os.W_OK)):
                        new_hydro_autosave = "%s/%s.%s.autosave.h2song" % (
                            project_path, new_prefix, new_client_id)
                        if os.path.exists(new_hydro_autosave):
                            do_rename = False
                            break

                        files_to_rename.append((hydrogen_autosave, new_hydro_autosave))

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

                     # change ardour session name
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

                    # for Vee One Suite
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

                elif file_path == old_client_links_dir:
                    # this section only concerns Carla links dir
                    # used to save links for convolutions files or soundfonts
                    # or any other linked resource.
                    if old_client_links_dir == new_client_links_dir:
                        continue

                    full_old_client_links_dir = os.path.join(spath, file_path)

                    if not os.path.isdir(full_old_client_links_dir):
                        continue

                    if not os.access(full_old_client_links_dir, os.W_OK):
                        do_rename = False
                        break

                    files_to_rename.append(
                        (full_old_client_links_dir,
                         os.path.join(spath, new_client_links_dir)))

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

    def _save_as_template_substep1(self, template_name):
        self.set_status(self.status) # see set_status to see why

        if self.prefix_mode != ray.PrefixMode.CUSTOM:
            self.adjust_files_after_copy(template_name,
                                         ray.Template.CLIENT_SAVE)

        xml_file = "%s/%s" % (TemplateRoots.user_clients,
                              'client_templates.xml')

        # security check
        if os.path.exists(xml_file):
            if not os.access(xml_file, os.W_OK):
                self._send_error_to_caller(
                    OSC_SRC_SAVE_TP, ray.Err.CREATE_FAILED,
                    _translate('GUIMSG', '%s is not writeable !') % xml_file)
                return

            if os.path.isdir(xml_file):
                #should not be a dir, remove it !
                shutil.rmtree(xml_file)

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

        self.write_xml_properties(rct)
        rct.setAttribute('template-name', template_name)
        rct.setAttribute('client_id', self._pretty_client_id())

        if not self.is_running():
            rct.setAttribute('launched', False)

        content.appendChild(rct)

        file = open(xml_file, 'w')
        file.write(xml.toString())
        file.close()

        self.template_origin = template_name
        self.send_gui_client_properties()

        template_data_base_users = self.get_client_templates_database('user')
        template_data_base_users.clear()

        self.send_gui_message(
            _translate('message', 'Client template %s created')
                % template_name)

        self._send_reply_to_caller(OSC_SRC_SAVE_TP, 'client template created')

    def _save_as_template_aborted(self, template_name):
        self.set_status(self.status)
        self._send_error_to_caller(OSC_SRC_SAVE_TP, ray.Err.COPY_ABORTED,
            _translate('GUIMSG', 'Copy has been aborted !'))

    def get_links_dir(self)->str:
        ''' returns the dir path used by carla for links such as
        audio convolutions or soundfonts '''
        links_dir = self.get_jack_client_name()
        for c in ('-', '.'):
            links_dir = links_dir.replace(c, '_')
        return links_dir

    def is_ray_hack(self)->bool:
        return bool(self.protocol == ray.Protocol.RAY_HACK)

    def send_to_self_address(self, *args):
        if not self.addr:
            return

        self.send(self.addr, *args)

    def message(self, message: str):
        if self.session is None:
            return
        self.session.message(message)

    def get_jack_client_name(self):
        if self.protocol == ray.Protocol.RAY_NET:
            # ray-net will use jack_client_name for template
            # quite dirty, but this is the easier way
            return self.ray_net.session_template

        # return same jack_client_name as NSM does
        # if client seems to have been made by NSM itself
        # else, jack connections could be lose
        # at NSM session import
        if self.jack_naming == ray.JackNaming.LONG:
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

    def read_xml_properties(self, ctx: QDomElement):
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

        if (ctx.attribute('from_nsm_file') == '1'
                or ctx.attribute('jack_naming') in ('1', 'long')):
            self.jack_naming = ray.JackNaming.LONG

        # ensure client has a name
        if not self.name:
            self.name = basename(self.executable_path)

        self.update_infos_from_desktop_file()

        ign_exts = ctx.attribute('ignored_extensions').split(' ')
        unign_exts = ctx.attribute('unignored_extensions').split(' ')

        global_exts = ray.GIT_IGNORED_EXTENSIONS.split(' ')
        self.ignored_extensions = ""

        for ext in global_exts:
            if ext and not ext in unign_exts:
                self.ignored_extensions += " %s" % ext

        for ext in ign_exts:
            if ext and not ext in global_exts:
                self.ignored_extensions += " %s" % ext

        open_duration = ctx.attribute('last_open_duration')
        if open_duration.replace('.', '', 1).isdigit():
            self.last_open_duration = float(open_duration)

        prefix_mode = ctx.attribute('prefix_mode')

        if (prefix_mode and prefix_mode.isdigit()
                and 0 <= int(prefix_mode) <= 2):
            self.prefix_mode = int(prefix_mode)
            if self.prefix_mode == ray.PrefixMode.CUSTOM:
                self.custom_prefix = ctx.attribute('custom_prefix')

        self.protocol = ray.protocol_from_str(ctx.attribute('protocol'))

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
                self.arguments = self.get_ray_net_arguments_line()

        if ctx.attribute('id'):
            # session uses "id" for absolutely needed client_id
            self.client_id = ctx.attribute('id')
        else:
            # template uses "client_id" for wanted client_id
            self.client_id = self.session.generate_client_id(
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

    def write_xml_properties(self, ctx: QDomElement):
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

        if self.is_capable_of(':optional-gui:'):
            ctx.setAttribute('gui_visible',
                             str(int(not self.start_gui_hidden)))

        if self.jack_naming == ray.JackNaming.LONG:
            ctx.setAttribute('jack_naming', ray.JackNaming.LONG)

        if self.template_origin:
            ctx.setAttribute('template_origin', self.template_origin)

        if self.protocol != ray.Protocol.NSM:
            ctx.setAttribute('protocol', ray.protocol_to_str(self.protocol))

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

        if self.ignored_extensions != ray.GIT_IGNORED_EXTENSIONS:
            ignored = ""
            unignored = ""
            client_exts = [e for e in self.ignored_extensions.split(' ') if e]
            global_exts = [e for e in ray.GIT_IGNORED_EXTENSIONS.split(' ') if e]

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


    def set_reply(self, errcode, message):
        self._reply_message = message
        self._reply_errcode = errcode

        if self._reply_errcode:
            self.message("Client \"%s\" replied with error: %s (%i)"
                                % (self.name, message, errcode))

            if self.pending_command == ray.Command.SAVE:
                self._send_error_to_caller(OSC_SRC_SAVE, ray.Err.GENERAL_ERROR,
                                    _translate('GUIMSG', '%s failed to save!')
                                            % self.gui_msg_style())
                
                self.session.send_monitor_event(
                    'save_error', self.client_id)

            elif self.pending_command == ray.Command.OPEN:
                self._send_error_to_caller(OSC_SRC_OPEN, ray.Err.GENERAL_ERROR,
                                    _translate('GUIMSG', '%s failed to open!')
                                            % self.gui_msg_style())
                
                self.session.send_monitor_event(
                    'open_error', self.client_id)

            self.set_status(ray.ClientStatus.ERROR)
        else:
            if self.pending_command == ray.Command.SAVE:
                self.last_save_time = time.time()

                self.send_gui_message(
                    _translate('GUIMSG', '  %s: saved')
                        % self.gui_msg_style())

                self._send_reply_to_caller(OSC_SRC_SAVE, 'client saved.')
                self.session.send_monitor_event(
                    'saved', self.client_id)

            elif self.pending_command == ray.Command.OPEN:
                self.send_gui_message(
                    _translate('GUIMSG', '  %s: project loaded')
                        % self.gui_msg_style())

                self.last_open_duration = \
                                        time.time() - self._last_announce_time

                self._send_reply_to_caller(OSC_SRC_OPEN, 'client opened')

                self.session.send_monitor_event(
                    'ready', self.client_id)

                if self.has_server_option(ray.Option.GUI_STATES):
                    if (self.session.wait_for == ray.WaitFor.NONE
                            and self.is_capable_of(':optional-gui:')
                            and not self.start_gui_hidden
                            and not self.gui_visible
                            and not self.gui_has_been_visible):
                        self.send_to_self_address('/nsm/client/show_optional_gui')

            self.set_status(ray.ClientStatus.READY)
            #self.message( "Client \"%s\" replied with: %s in %fms"
                            #% (client.name, message,
                                #client.milliseconds_since_last_command()))
        if (self.scripter.is_running()
                and self.scripter.pending_command() == self.pending_command):
            return

        self.pending_command = ray.Command.NONE

        if self.session.wait_for == ray.WaitFor.REPLY:
            self.session.end_timer_if_last_expected(self)

    def set_label(self, label:str):
        self.label = label
        self.send_gui_client_properties()

    def has_error(self)->bool:
        return bool(self._reply_errcode)

    def is_reply_pending(self)->bool:
        return bool(self.pending_command)

    def is_dumb_client(self)->bool:
        if self.is_ray_hack():
            return False

        return bool(not self.did_announce)

    def is_capable_of(self, capability: str)->bool:
        return bool(capability in self.capabilities)

    def gui_msg_style(self)->str:
        return "%s (%s)" % (self.name, self.client_id)

    def set_network_properties(self, net_daemon_url, net_session_root):
        if self.protocol != ray.Protocol.RAY_NET:
            return

        self.ray_net.daemon_url = net_daemon_url
        self.ray_net.running_daemon_url = net_daemon_url
        self.ray_net.session_root = net_session_root
        self.ray_net.running_session_root = net_session_root
        self.send_gui_client_properties()

    def get_ray_net_arguments_line(self)->str:
        if self.protocol != ray.Protocol.RAY_NET:
            return ''
        return '--daemon-url %s --net-session-root "%s"' % (
                self.ray_net.daemon_url,
                self.ray_net.session_root.replace('"', '\\"'))

    def set_status(self, status):
        # ray.ClientStatus.COPY is not a status as the other ones.
        # GUI needs to know if client is started/open/stopped while files are
        # copied, so self.status doesn't remember ray.ClientStatus.COPY,
        # although it is sent to GUI

        if status != ray.ClientStatus.COPY:
            self.status = status
            self._send_status_to_gui()

        if (status == ray.ClientStatus.COPY
                or self.session.file_copier.is_active(self.client_id)):
            self.send_gui("/ray/gui/client/status", self.client_id,
                          ray.ClientStatus.COPY)

    def get_prefix_string(self):
        if self.prefix_mode == ray.PrefixMode.SESSION_NAME:
            return self.session.name

        if self.prefix_mode == ray.PrefixMode.CLIENT_NAME:
            return self.name

        if self.prefix_mode == ray.PrefixMode.CUSTOM:
            return self.custom_prefix

        return ''

    def get_project_path(self):
        if self.protocol == ray.Protocol.RAY_NET:
            return self.session.get_short_path()

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

    def set_default_git_ignored(self, executable=""):
        executable = executable if executable else self.executable_path
        executable = os.path.basename(executable)
        if executable == 'ray-proxy':
            executable = self._get_proxy_executable()

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

    def start(self, src_addr=None, src_path='', wait_open_to_reply=False):
        if src_addr and not wait_open_to_reply:
            self._osc_srcs[OSC_SRC_START] = (src_addr, src_path)

        self.session.set_renameable(False)

        self.last_dirty = 0.00
        self.gui_has_been_visible = False
        self.gui_visible = False
        self.show_gui_ordered = False

        if self.is_dummy:
            self._send_error_to_caller(OSC_SRC_START, ray.Err.GENERAL_ERROR,
                _translate('GUIMSG', "can't start %s, it is a dummy client !")
                    % self.gui_msg_style())
            return

        if (self.protocol == ray.Protocol.RAY_NET
                and not self.session.path.startswith(self.session.root + '/')):
            self._send_error_to_caller(OSC_SRC_START, ray.Err.GENERAL_ERROR,
                _translate('GUIMSG',
                    "Impossible to run Ray-Net client when session is not in root folder"))
            return

        if self.scripter.start(ray.Command.START, src_addr,
                               self._osc_srcs[OSC_SRC_START]):
            self.set_status(ray.ClientStatus.SCRIPT)
            return

        self.pending_command = ray.Command.START

        process_env = QProcessEnvironment.systemEnvironment()
        pre_env_splitted = shlex.split(self.pre_env)
        for pes in pre_env_splitted:
            if not '=' in pes:
                continue

            envvar, egal, value = pes.partition('=')
            if envvar:
                process_env.insert(envvar, value)

        if self.protocol != ray.Protocol.RAY_HACK:
            process_env.insert('NSM_URL', self.get_server_url())

        arguments = []

        if self.protocol == ray.Protocol.RAY_NET:
            server = self.get_server()
            if not server:
                return

            arguments += ['--net-daemon-id', str(server.net_daemon_id)]
            if self.ray_net.daemon_url:
                arguments += ['--daemon-url', self.ray_net.daemon_url]
                if self.ray_net.session_root:
                    arguments += ['--session-root', self.ray_net.session_root]
            self.ray_net.running_daemon_url = self.ray_net.daemon_url
            self.ray_net.running_session_root = self.ray_net.session_root
            self._process.setProcessEnvironment(process_env)
            self._process.start(ray.RAYNET_BIN, arguments)
            return

        if self.tmp_arguments:
            arguments += shlex.split(self.tmp_arguments)

        arguments_line = self.arguments

        if self.is_ray_hack():
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
                self.get_jack_client_name())

            # The only way I found to expand vars is to set environment vars
            # globally, and remove them just after.
            # In case you see a better way, please say it.
            for env in all_envs:
                os.environ[env] = all_envs[env][1]

            os.environ['CONFIG_FILE'] = os.path.expandvars(
                                            self.ray_hack.config_file)

            back_pwd = os.getenv('PWD')
            ray_hack_pwd = self.get_project_path()
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

        if self.is_ray_hack():
            self._process.setWorkingDirectory(ray_hack_pwd)
            process_env.insert('RAY_SESSION_NAME', self.session.name)
            process_env.insert('RAY_CLIENT_ID', self.client_id)

            self.jack_client_name = self.get_jack_client_name()
            self.send_gui_client_properties()

        self.session.send_monitor_event(
            'start_request', self.client_id)

        self._process.setProcessEnvironment(process_env)
        self._process.start(self.executable_path, arguments)

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
            self._send_reply_to_caller(OSC_SRC_OPEN, 'client active')
            return

        if self.pending_command == ray.Command.STOP:
            self._send_error_to_caller(OSC_SRC_OPEN, ray.Err.GENERAL_ERROR,
                _translate('GUIMSG', '%s is exiting.') % self.gui_msg_style())

        if self.is_running() and self.is_dumb_client():
            self._send_error_to_caller(OSC_SRC_OPEN, ray.Err.GENERAL_ERROR,
                _translate('GUIMSG', '%s seems to can not open')
                    % self.gui_msg_style())

        duration = max(8000, 2 * self.last_open_duration)
        self._open_timer.setInterval(duration)
        self._open_timer.start()

        if self.pending_command == ray.Command.OPEN:
            return

        if not self.is_running():
            if self.executable_path in RS.non_active_clients:
                if src_addr:
                    self._osc_srcs[OSC_SRC_START] = (src_addr, src_path)
                    self._osc_srcs[OSC_SRC_OPEN] = (None, '')

            self.start(src_addr, src_path, True)
            return

    def terminate(self):
        if self.is_running():
            if self.is_external:
                os.kill(self.pid, 15) # 15 means signal.SIGTERM
            else:
                self._process.terminate()

    def kill(self):
        if self.is_external:
            os.kill(self.pid, 9) # 9 means signal.SIGKILL
            return

        if self.is_running():
            self._process.kill()

    def send_signal(self, sig: int, src_addr=None, src_path=""):
        try:
            tru_sig = signal.Signals(sig)
        except:
            if src_addr:
                self.send(src_addr, '/error', src_path,
                          ray.Err.GENERAL_ERROR, 'invalid signal %i' % sig)
            return

        if not self.is_running():
            if src_addr:
                self.send(src_addr, '/error', src_path,
                          ray.Err.GENERAL_ERROR,
                          'client %s is not running' % self.client_id)
            return

        os.kill(self.pid, sig)
        self.send(src_addr, '/reply', src_path, 'signal sent')

    def is_running(self):
        if self.is_external:
            return True
        return bool(self._process.state() == 2)

    def external_finished(self):
        self._process_finished(0, 0)

    def script_finished(self, exit_code):
        if self.scripter.is_asked_for_terminate():
            if self.session.wait_for == ray.WaitFor.QUIT:
                self.session.end_timer_if_last_expected(self)
            return

        scripter_pending_command = self.scripter.pending_command()

        if exit_code:
            error_text = "script %s ended with an error code" \
                            % self.scripter.get_path()
            if scripter_pending_command == ray.Command.SAVE:
                self._send_error_to_caller(OSC_SRC_SAVE, - exit_code,
                                        error_text)
            elif scripter_pending_command == ray.Command.START:
                self._send_error_to_caller(OSC_SRC_START, - exit_code,
                                        error_text)
            elif scripter_pending_command == ray.Command.STOP:
                self._send_error_to_caller(OSC_SRC_STOP, - exit_code,
                                        error_text)
        else:
            if scripter_pending_command == ray.Command.SAVE:
                self._send_reply_to_caller(OSC_SRC_SAVE, 'saved')
            elif scripter_pending_command == ray.Command.START:
                self._send_reply_to_caller(OSC_SRC_START, 'started')
            elif scripter_pending_command == ray.Command.STOP:
                self._send_reply_to_caller(OSC_SRC_STOP, 'stopped')

        if scripter_pending_command == self.pending_command:
            self.pending_command = ray.Command.NONE

        if (scripter_pending_command == ray.Command.STOP
                and self.is_running()):
            # if stop script ends with a not stopped client
            # We must stop it, else it would prevent session close
            self.stop()

        if self.session.wait_for:
            self.session.end_timer_if_last_expected(self)

    def ray_hack_ready(self):
        self.send_gui_message(
            _translate('GUIMSG', '  %s: project probably loaded')
                % self.gui_msg_style())

        self._send_reply_to_caller(OSC_SRC_OPEN, 'client opened')
        self.pending_command = ray.Command.NONE
        self.set_status(ray.ClientStatus.READY)

        if self.session.wait_for == ray.WaitFor.REPLY:
            self.session.end_timer_if_last_expected(self)

    def terminate_scripts(self):
        self.scripter.terminate()

    def tell_client_session_is_loaded(self):
        if self.active and not self.is_dumb_client():
            self.message("Telling client %s that session is loaded."
                             % self.name)
            self.send_to_self_address("/nsm/client/session_is_loaded")

    def can_save_now(self):
        if self.is_ray_hack():
            if not self.ray_hack.saveable():
                return False

            return bool(self.is_running()
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

        if self.is_running():
            if self.scripter.start(ray.Command.SAVE, src_addr,
                                   self._osc_srcs[OSC_SRC_SAVE]):
                self.set_status(ray.ClientStatus.SCRIPT)
                return

        if self.pending_command == ray.Command.SAVE:
            self._send_error_to_caller(OSC_SRC_SAVE, ray.Err.GENERAL_ERROR,
                _translate('GUIMSG', '%s is already saving, please wait!')
                    % self.gui_msg_style())

        if self.is_running():
            self.session.send_monitor_event(
                'save_request', self.client_id)

            if self.is_ray_hack():
                self.pending_command = ray.Command.SAVE
                self.set_status(ray.ClientStatus.SAVE)
                if self.ray_hack.save_sig > 0:
                    os.kill(self._process.processId(), self.ray_hack.save_sig)
                QTimer.singleShot(300, self._ray_hack_saved)

            elif self.can_save_now():
                self.message("Telling %s to save" % self.name)
                self.send_to_self_address("/nsm/client/save")

                self.pending_command = ray.Command.SAVE
                self.set_status(ray.ClientStatus.SAVE)

            elif self.is_dumb_client():
                self.set_status(ray.ClientStatus.NOOP)

            if self.is_capable_of(':optional-gui:'):
                self.start_gui_hidden = not bool(self.gui_visible)

    def stop(self, src_addr=None, src_path=''):
        if self.switch_state == ray.SwitchState.NEEDED:
            if src_addr:
                self.send(src_addr, '/error', src_path, ray.Err.NOT_NOW,
                "Stop cancelled because client is needed for opening session")
            return

        if src_addr:
            self._osc_srcs[OSC_SRC_STOP] = (src_addr, src_path)

        self.send_gui_message(_translate('GUIMSG', "  %s: stopping")
                                % self.gui_msg_style())

        if self.is_running():
            if self.scripter.start(ray.Command.STOP, src_addr,
                                   self._osc_srcs[OSC_SRC_STOP]):
                self.set_status(ray.ClientStatus.SCRIPT)
                return

            self.pending_command = ray.Command.STOP
            self.set_status(ray.ClientStatus.QUIT)

            if not self._stopped_timer.isActive():
                self._stopped_timer.start()

            self.session.send_monitor_event(
                'stop_request', self.client_id)

            if self.is_external:
                os.kill(self.pid, 15) # 15 means signal.SIGTERM
            elif self.is_ray_hack() and self.ray_hack.stop_sig != 15:
                os.kill(self._process.pid(), self.ray_hack.stop_sig)
            else:
                self._process.terminate()
        else:
            self._send_reply_to_caller(OSC_SRC_STOP, 'client stopped.')

    def quit(self):
        self.message("Commanding %s to quit" % self.name)
        if self.is_running():
            self.pending_command = ray.Command.STOP
            self.terminate()
            self.set_status(ray.ClientStatus.QUIT)
        else:
            self.send_gui("/ray/gui/client/status", self.client_id,
                          ray.ClientStatus.REMOVED)

    def eat_attributes(self, new_client: 'Client'):
        #self.client_id = new_client.client_id
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
        self.jack_naming = new_client.jack_naming

        self._desktop_label = new_client._desktop_label
        self._desktop_description = new_client._desktop_description
        self._desktop_icon = new_client._desktop_icon

        #self.gui_visible = new_client.gui_visible
        self.gui_has_been_visible = self.gui_visible

    def switch(self):
        self.jack_client_name = self.get_jack_client_name()
        client_project_path = self.get_project_path()
        self.send_gui_client_properties()
        self.message("Commanding %s to switch \"%s\""
                         % (self.name, client_project_path))

        self.send_to_self_address("/nsm/client/open", client_project_path,
                                  self.session.name, self.jack_client_name)

        self.pending_command = ray.Command.OPEN
        
        self.set_status(ray.ClientStatus.SWITCH)
        if self.is_capable_of(':optional-gui:'):
            self.send_gui('/ray/gui/client/gui_visible',
                           self.client_id, int(self.gui_visible))

    def can_switch_with(self, other_client: 'Client')->bool:
        if self.protocol == ray.Protocol.RAY_HACK:
            return False

        if self.protocol != other_client.protocol:
            return False

        if not ((self.active and self.is_capable_of(':switch:'))
                or (self.is_dumb_client() and self.is_running())):
            return False

        if self.protocol == ray.Protocol.RAY_NET:
            return bool(self.ray_net.running_daemon_url
                            == other_client.ray_net.daemon_url
                        and self.ray_net.running_session_root
                            == other_client.ray_net.session_root)

        return bool(self.running_executable == other_client.executable_path
                    and self.running_arguments == other_client.arguments)

    def send_gui_client_properties(self, removed=False):
        ad = '/ray/gui/client/update' if self.sent_to_gui else '/ray/gui/client/new'
        hack_ad = '/ray/gui/client/ray_hack_update'
        net_ad = '/ray/gui/client/ray_net_update'

        if removed:
            ad = '/ray/gui/trash/add'
            hack_ad = '/ray/gui/trash/ray_hack_update'
            net_ad = '/ray/gui/trash/ray_net_update'

        self.send_gui(ad, *ray.ClientData.spread_client(self))

        if self.protocol == ray.Protocol.RAY_HACK:
            self.send_gui(
                hack_ad, self.client_id, *self.ray_hack.spread())

        elif self.protocol == ray.Protocol.RAY_NET:
            self.send_gui(
                net_ad, self.client_id, *self.ray_net.spread())

        self.sent_to_gui = True

    def set_properties_from_message(self, message:str):
        for line in message.splitlines():
            prop, colon, value = line.partition(':')

            if prop == 'client_id':
                # do not change client_id !!!
                continue
            elif prop == 'executable':
                self.executable_path = value
            elif prop == 'environment':
                self.pre_env = value
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
            elif prop == 'jack_naming':
                if value.isdigit() and 0 <= int(value) <= 1:
                    self.jack_naming = int(value)
            elif prop == 'jack_name':
                # do not change jack name
                # only allow to change jack_naming
                continue
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

        self.send_gui_client_properties()

    def get_properties_message(self):
        message = """client_id:%s
protocol:%s
executable:%s
environment:%s
arguments:%s
name:%s
prefix_mode:%i
custom_prefix:%s
jack_naming:%i
jack_name:%s
desktop_file:%s
label:%s
icon:%s
check_last_save:%i
ignored_extensions:%s""" % (self.client_id,
                            ray.protocol_to_str(self.protocol),
                            self.executable_path,
                            self.pre_env,
                            self.arguments,
                            self.name,
                            self.prefix_mode,
                            self.custom_prefix,
                            self.jack_naming,
                            self.get_jack_client_name(),
                            self.desktop_file,
                            self.label,
                            self.icon,
                            int(self.check_last_save),
                            self.ignored_extensions)

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

    def noSaveLevel(self)->int:
        ''' This method will be renamed or deleted later
        no_save_level will be deprecated for NSM client
        it will applies only on Ray-Hack clients '''
        if self.is_ray_hack():
            return self.ray_hack.noSaveLevel()

        return self.no_save_level

    def get_project_files(self):
        ''' returns a list of full filenames '''
        client_files = []

        project_path = self.get_project_path()
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

        full_links_dir = os.path.join(self.session.path, self.get_links_dir())
        if os.path.exists(full_links_dir):
            client_files.append(full_links_dir)

        return client_files

    def update_infos_from_desktop_file(self):
        if self.icon and self.description and self.label:
            return

        desktop_file = self.desktop_file
        if desktop_file == '//not_found':
            return

        if not desktop_file:
            desktop_file = os.path.basename(self.executable_path)

        if not desktop_file.endswith('.desktop'):
            desktop_file += ".desktop"

        desk_path_list = ([Path(get_code_root()).joinpath('data', 'share')]
                          + xdg.xdg_data_dirs())

        for desk_data_path in desk_path_list:
            org_prefixs = ('', 'org.gnome.', 'org.kde.')

            for org_prefix in org_prefixs:
                desk_path = desk_data_path.joinpath(
                    'applications', org_prefix + desktop_file)
                
                if desk_path.is_file():
                    break
            else:
                continue

            try:
                contents = desk_path.read_text()
            except:
                continue

            self._set_infos_from_desktop_contents(contents)
            break

        else:
            desk_file_found = False

            for desk_data_path in desk_path_list:
                desk_app_path = desk_data_path.joinpath('applications')

                if not desk_app_path.is_dir():
                    continue

                if not os.access(desk_app_path, os.R_OK):
                    # no permission to read this applications folder
                    continue

                for desk_path in desk_app_path.iterdir():
                    if not desk_path.suffix == '.desktop':
                        continue

                    if desk_path.is_dir():
                        continue

                    try:
                        contents = desk_path.read_text()
                    except:
                        continue

                    for line in contents.splitlines():
                        if line.startswith('Exec='):
                            value = line.partition('=')[2]
                            if self.executable_path in value.split():
                                desk_file_found = True

                                self.desktop_file = desk_path.name
                                self._set_infos_from_desktop_contents(contents)
                                break

                    if desk_file_found:
                        break
                if desk_file_found:
                    break
            else:
                self.desktop_file = '//not_found'

    def save_as_template(self, template_name, src_addr=None, src_path=''):
        if src_addr:
            self._osc_srcs[OSC_SRC_SAVE_TP] = (src_addr, src_path)

        #copy files
        client_files = self.get_project_files()

        template_dir = "%s/%s" % (TemplateRoots.user_clients,
                                  template_name)

        if os.path.exists(template_dir):
            if os.access(template_dir, os.W_OK):
                shutil.rmtree(template_dir)
            else:
                self._send_error_to_caller(
                    OSC_SRC_SAVE_TP, ray.Err.CREATE_FAILED,
                    _translate('GUIMSG', 'impossible to remove %s !')
                    % highlight_text(template_dir))
                return

        os.makedirs(template_dir)

        if self.protocol == ray.Protocol.RAY_NET:
            if self.ray_net.daemon_url:
                self.ray_net.session_template = template_name
                net_session_root = self.ray_net.session_root
                if self.is_running():
                    net_session_root = self.ray_net.running_session_root

                self.send(Address(self.ray_net.daemon_url),
                          '/ray/server/save_session_template',
                          self.session.name,
                          template_name,
                          net_session_root)

        if client_files:
            self.set_status(ray.ClientStatus.COPY)
            self.session.file_copier.start_client_copy(
                self.client_id, client_files, template_dir,
                self._save_as_template_substep1,
                self._save_as_template_aborted,
                [template_name])
        else:
            self._save_as_template_substep1(template_name)

    def eat_other_session_client(self, src_addr, osc_path, client: 'Client'):
        # eat attributes but keep client_id
        self.eat_attributes(client)

        self.send_gui_client_properties()
        
        tmp_basedir = ".tmp_ray_workdir"
        while os.path.exists("%s/%s" % (self.session.path, tmp_basedir)):
            tmp_basedir += 'X'
    
        tmp_work_dir = "%s/%s" % (self.session.path, tmp_basedir)
        
        try:
            os.makedirs(tmp_work_dir)
        except:
            self.send(src_addr, '/error', osc_path, ray.Err.CREATE_FAILED,
                      "impossible to make a tmp workdir at %s. Abort." % tmp_work_dir)
            self.session._remove_client(self)
            return

        self.set_status(ray.ClientStatus.PRECOPY)
        
        self.session.file_copier.start_client_copy(
            self.client_id, client.get_project_files(), tmp_work_dir,
            self.eat_other_session_client_step_1,
            self.eat_other_session_client_aborted,
            [src_addr, osc_path, client, tmp_work_dir])

    def eat_other_session_client_step_1(self, src_addr, osc_path,
                                        client: 'Client', tmp_work_dir):
        self._rename_files(
            tmp_work_dir, client.session.name, self.session.name,
            client.get_prefix_string(), self.get_prefix_string(),
            client.client_id, self.client_id,
            client.get_links_dir(), self.get_links_dir())

        has_move_errors = False

        for file_path in os.listdir(tmp_work_dir):
            try:
                os.rename("%s/%s" % (tmp_work_dir, file_path),
                          "%s/%s" % (self.session.path, file_path))
            except:
                Terminal.message(
                    _translate(
                        'client',
                        'failed to move %s/%s to %s/%s, sorry.')
                        % (tmp_work_dir, file_path, self.session.path, file_path))
                has_move_errors = True
        
        if not has_move_errors:
            try:
                shutil.rmtree(tmp_work_dir)
            except:
                Terminal.message(
                    'client'
                    'fail to remove temp directory %s. sorry.' % tmp_work_dir)

        self.send(src_addr, '/reply', osc_path,
                  "Client copied from another session")

        if self.auto_start:
            self.start()
        else:
            self.set_status(ray.ClientStatus.STOPPED)

    def eat_other_session_client_aborted(self, src_addr, osc_path,
                                         client, tmp_work_dir):
        shutil.rmtree(tmp_work_dir)
        self.session._remove_client(self)
        self.send(src_addr, '/error', osc_path, ray.Err.COPY_ABORTED,
                  "Copy was aborted by user")

    def change_prefix(self, prefix_mode: int, custom_prefix: str):
        if self.is_running():
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

        links_dir = self.get_links_dir()

        self._rename_files(
            self.session.path,
            self.session.name, self.session.name,
            old_prefix, new_prefix,
            self.client_id, self.client_id,
            links_dir, links_dir)

        self.prefix_mode = prefix_mode
        self.custom_prefix = custom_prefix
        self.send_gui_client_properties()

    def adjust_files_after_copy(self, new_session_full_name,
                                template_save=ray.Template.NONE):
        spath = self.session.path
        old_session_name = self.session.name
        new_session_name = basename(new_session_full_name)
        new_client_id = self.client_id
        old_client_id = self.client_id
        new_client_links_dir = self.get_links_dir()
        old_client_links_dir = new_client_links_dir

        xsessionx = "XXX_SESSION_NAME_XXX"
        xclient_idx = "XXX_CLIENT_ID_XXX"
        x_client_links_dirx = "XXX_CLIENT_LINKS_DIR_XXX" # used for Carla links dir

        if template_save == ray.Template.NONE:
            if self.prefix_mode != ray.PrefixMode.SESSION_NAME:
                return

            spath = self.session.get_full_path(new_session_full_name)

        elif template_save == ray.Template.RENAME:
            spath = self.session.path

        elif template_save == ray.Template.SESSION_SAVE:
            spath = ray.get_full_path(TemplateRoots.user_sessions,
                                      new_session_full_name)
            new_session_name = xsessionx

        elif template_save == ray.Template.SESSION_SAVE_NET:
            spath = "%s/%s/%s" % (self.session.root,
                                  TemplateRoots.net_session_name,
                                  new_session_full_name)
            new_session_name = xsessionx

        elif template_save == ray.Template.SESSION_LOAD:
            spath = self.session.get_full_path(new_session_full_name)
            old_session_name = xsessionx

        elif template_save == ray.Template.SESSION_LOAD_NET:
            spath = self.session.get_full_path(new_session_full_name)
            old_session_name = xsessionx

        elif template_save == ray.Template.CLIENT_SAVE:
            spath = "%s/%s" % (TemplateRoots.user_clients,
                               new_session_full_name)
            new_session_name = xsessionx
            new_client_id = xclient_idx
            new_client_links_dir = x_client_links_dirx

        elif template_save == ray.Template.CLIENT_LOAD:
            spath = self.session.path
            old_session_name = xsessionx
            old_client_id = xclient_idx
            old_client_links_dir = x_client_links_dirx

        old_prefix = old_session_name
        new_prefix = new_session_name

        if self.prefix_mode == ray.PrefixMode.CLIENT_NAME:
            old_prefix = new_prefix = self.name
        elif self.prefix_mode == ray.PrefixMode.CUSTOM:
            old_prefix = new_prefix = self.custom_prefix

        self._rename_files(
            spath, old_session_name, new_session_name,
            old_prefix, new_prefix,
            old_client_id, new_client_id,
            old_client_links_dir, new_client_links_dir)

    def server_announce(self, path, args, src_addr, is_new):
        client_name, capabilities, executable_path, major, minor, pid = args

        if self.pending_command == ray.Command.STOP:
            # assume to not answer to a dying client.
            # He will never know, or perhaps, it depends on beliefs.
            return

        if major > NSM_API_VERSION_MAJOR:
            self.message(
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

        self.message("Process has pid: %i" % pid)
        self.message(
            "The client \"%s\" at \"%s\" " % (self.name, self.addr.url)
            + "informs us it's ready to receive commands.")

        server = self.get_server()
        if not server:
            return

        self.send_gui_message(
            _translate('GUIMSG', "  %s: announced" % self.gui_msg_style()))

        # if this daemon is under another NSM session
        # do not enable server-control
        # because new, open and duplicate are forbidden
        server_capabilities = ""
        if not server.is_nsm_locked:
            server_capabilities += ":server-control"
        server_capabilities += ":broadcast:optional-gui:no-save-level:monitor:"

        self.send(src_addr, "/reply", path,
                  "Well hello, stranger. Welcome to the party."
                  if is_new else "Howdy, what took you so long?",
                  ray.APP_TITLE,
                  server_capabilities)

        client_project_path = self.get_project_path()
        self.jack_client_name = self.get_jack_client_name()

        if self.protocol == ray.Protocol.RAY_NET:
            client_project_path = self.session.get_short_path()
            self.jack_client_name = self.ray_net.session_template

        self.send_gui_client_properties()
        self.set_status(ray.ClientStatus.OPEN)

        if ':monitor:' in self.capabilities:
            self.session.send_initial_monitor(self.addr)

        self.send(src_addr, "/nsm/client/open", client_project_path,
                  self.session.name, self.jack_client_name)

        self.pending_command = ray.Command.OPEN

        self._last_announce_time = time.time()
