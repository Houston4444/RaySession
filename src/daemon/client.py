import logging
import os
import shlex
import shutil
import signal
import time
from pathlib import Path
from enum import Enum
import xml.etree.ElementTree as ET

from qtpy.QtCore import (QCoreApplication, QProcess,
                         QProcessEnvironment, QTimer)

from osclib import Address, OscPack    
import xdg
import ray
from server_sender import ServerSender
from daemon_tools  import (
    TemplateRoots, Terminal, RS, get_code_root,
    highlight_text, exec_and_desktops)
from signaler import Signaler
from scripter import ClientScripter
from xml_tools import XmlElement


# only used to identify session functions in the IDE
# 'Session' is not importable simply because it would be
# a circular import.
from typing import TYPE_CHECKING, Optional
if TYPE_CHECKING:
    from session_signaled import SignaledSession

_logger = logging.getLogger(__name__)
_logger.parent = logging.getLogger('__main__')

NSM_API_VERSION_MAJOR = 1
NSM_API_VERSION_MINOR = 0


class OscSrc(Enum):
    START = 0
    OPEN = 1
    SAVE = 2
    SAVE_TP = 3
    STOP = 4


_translate = QCoreApplication.translate
signaler = Signaler.instance()


def basename(*args):
    return os.path.basename(*args)


class Client(ServerSender, ray.ClientData):
    _reply_errcode = 0
    _reply_message = None

    # can be directly changed by OSC thread
    gui_visible = False
    gui_has_been_visible = False
    show_gui_ordered = False
    dirty = 0
    progress = 0

    # have to be modified by main thread for security
    addr: Address = None
    pid = 0
    pid_from_nsm = 0
    pending_command = ray.Command.NONE
    nsm_active = False
    did_announce = False

    status = ray.ClientStatus.STOPPED

    running_executable = ''
    running_arguments = ''

    auto_start = True
    start_gui_hidden = False
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

    launched_in_terminal = False
    process_drowned = False
    _process_start_time = 0.0

    def __init__(self, parent_session: 'SignaledSession'):
        ServerSender.__init__(self)
        self.session = parent_session
        self.is_dummy = self.session.is_dummy

        self.custom_data = {}
        self.custom_tmp_data = {}

        self._process = QProcess()
        self._process.started.connect(self._process_started)
        self._process.errorOccurred.connect(self._error_in_process)
        self._process.finished.connect(self._process_finished)
        self._process.readyReadStandardError.connect(self._standard_error)
        self._process.readyReadStandardOutput.connect(self._standard_output)

        # if client is'n't stopped 2secs after stop,
        # another stop becames a kill!
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
        # self._osc_srcs = [(None, ''), (None, ''), (None, ''),
        #                   (None, ''), (None, '')]
        self._osc_srcs = dict[OscSrc, Optional[OscPack]]()
        # for osc_src in OscSrc:
        #     self._osc_srcs[osc_src] = None

        self._open_timer = QTimer()
        self._open_timer.setSingleShot(True)
        self._open_timer.timeout.connect(self._open_timer_timeout)

        self.ray_hack = ray.RayHack()
        self.ray_net = ray.RayNet()
        self.scripter = ClientScripter(self)

        self.ray_hack_waiting_win = False

    @staticmethod
    def short_client_id(wanted: str) -> str:
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
        self.process_drowned = False
        self._process_start_time = time.time()

        self.pid = self._process.processId()

        self.set_status(ray.ClientStatus.LAUNCH)

        self.send_gui_message(_translate("GUIMSG", "  %s: launched")
                            % self.gui_msg_style())

        self.session.send_monitor_event('started', self.client_id)

        self._send_reply_to_caller(OscSrc.START, 'client started')

        if self.is_ray_hack():
            if self.ray_hack.config_file:
                self.pending_command = ray.Command.OPEN
                self.set_status(ray.ClientStatus.OPEN)
                QTimer.singleShot(500, self._ray_hack_near_ready)

    def _process_finished(self, exit_code: int, exit_status: QProcess.ExitStatus):
        if (self.launched_in_terminal
                and self.pending_command is ray.Command.START
                and not exit_code
                and time.time() - self._process_start_time < 1.0):
            # when launched in terminal
            # with some terminals (mate-terminal, gnome-terminal)
            # if the terminal is already launched for another process,
            # the launched process finishs fastly because
            # the program is 'linked' in the current terminal process.
            self.process_drowned = True
            self.set_status(ray.ClientStatus.STOPPED)
            return

        self._stopped_timer.stop()
        self.is_external = False

        if self.pending_command is ray.Command.STOP:
            self.send_gui_message(_translate('GUIMSG',
                                  "  %s: terminated by server instruction")
                                  % self.gui_msg_style())
            
            self.session.send_monitor_event(
                'stopped_by_server', self.client_id)
        else:
            self.send_gui_message(_translate('GUIMSG',
                                           "  %s: terminated itself.")
                                    % self.gui_msg_style())
            
            self.session.send_monitor_event(
                'stopped_by_itself', self.client_id)

        self._send_reply_to_caller(OscSrc.STOP, 'client stopped')

        for osc_src in (OscSrc.OPEN, OscSrc.SAVE):
            self._send_error_to_caller(osc_src, ray.Err.GENERAL_ERROR,
                    _translate('GUIMSG', '%s died !' % self.gui_msg_style()))

        self.set_status(ray.ClientStatus.STOPPED)

        self.pending_command = ray.Command.NONE
        self.nsm_active = False
        self.pid = 0
        self.addr = None

        self.session.set_renameable(True)

        if self.scripter.pending_command() is ray.Command.STOP:
            return

        if self.session.wait_for:
            self.session.end_timer_if_last_expected(self)

    def _error_in_process(self, error: int):
        if error == QProcess.ProcessError.FailedToStart:
            self.send_gui_message(
                _translate('GUIMSG', "  %s: Failed to start !")
                    % self.gui_msg_style())
            self.nsm_active = False
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

            for osc_slot in (OscSrc.START, OscSrc.OPEN):
                self._send_error_to_caller(osc_slot, ray.Err.LAUNCH_FAILED,
                    _translate('GUIMSG', '%s failed to launch')
                        % self.gui_msg_style())

            if self.session.wait_for:
                self.session.end_timer_if_last_expected(self)
        self.session.set_renameable(True)

    def _stopped_since_long(self):
        self._stopped_since_long_ = True
        self.send_gui('/ray/gui/client/still_running', self.client_id)

    def _send_reply_to_caller(self, slot: OscSrc, message: str):
        osp = self._osc_srcs.get(slot)
        if osp is not None:
            self.send(*osp.reply(), message)
            self._osc_srcs[slot] = None

            if (self.scripter.is_running()
                    and self.scripter.pending_command() == self.pending_command):
                self._osc_srcs[slot] = self.scripter.initial_caller()

        if slot is OscSrc.OPEN:
            self._open_timer.stop()

    def _send_error_to_caller(self, slot: OscSrc, err: int, message: str):
        osp = self._osc_srcs.get(slot)
        if osp is not None:
            self.send(*osp.error(), err, message)
            self._osc_srcs[slot] = None

            if (self.scripter.is_running()
                    and self.scripter.pending_command() == self.pending_command):
                self._osc_srcs[slot] = self.scripter.initial_caller()

        if slot is OscSrc.OPEN:
            self._open_timer.stop()

    def _open_timer_timeout(self):
        self._send_error_to_caller(OscSrc.OPEN,
            ray.Err.GENERAL_ERROR,
            _translate('GUIMSG', '%s is started but not active')
                % self.gui_msg_style())

    def _send_status_to_gui(self):
        self.send_gui('/ray/gui/client/status', self.client_id, self.status.value)

    def _net_daemon_out_of_time(self):
        self.ray_net.duplicate_state = -1

        if self.session.wait_for is ray.WaitFor.DUPLICATE_FINISH:
            self.session.end_timer_if_last_expected(self)

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

        if self.pending_command is ray.Command.SAVE:
            self.pending_command = ray.Command.NONE
            self.set_status(ray.ClientStatus.READY)

            self.last_save_time = time.time()

            self.send_gui_message(
                _translate('GUIMSG', '  %s: saved')
                    % self.gui_msg_style())

            self._send_reply_to_caller(OscSrc.SAVE, 'client saved.')

        if self.session.wait_for is ray.WaitFor.REPLY:
            self.session.end_timer_if_last_expected(self)

    def _set_infos_from_desktop_contents(self, contents: str):
        lang = os.getenv('LANG', default="C")
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
            self, spath_str: str,
            old_session_name: str, new_session_name: str,
            old_prefix: str, new_prefix: str,
            old_client_id: str, new_client_id: str,
            old_client_links_dir: str, new_client_links_dir: str):
        spath = Path(spath_str)

        # rename client script dir
        scripts_dir = spath / f"{ray.SCRIPTS_DIR}.{old_client_id}"
        if os.access(scripts_dir, os.W_OK) and old_client_id != new_client_id:
            scripts_dir = scripts_dir.rename(f"{ray.SCRIPTS_DIR}.{new_client_id}")

        project_path = spath / f"{old_prefix}.{old_client_id}"

        files_to_rename = list[tuple[Path, Path]]()
        do_rename = True

        if self.is_ray_hack():
            if project_path.is_dir():
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

                    full_pre_config_file = project_path / pre_config_file
                    full_post_config_file = project_path / post_config_file

                    if full_pre_config_file.exists():
                        files_to_rename.append((full_pre_config_file,
                                                full_post_config_file))

                    files_to_rename.append(
                        (project_path, spath / f"{new_prefix}.{new_client_id}"))
        else:
            for file_path in spath.iterdir():
                if file_path.name.startswith(f"{old_prefix}.{old_client_id}."):
                    if not os.access(file_path, os.W_OK):
                        do_rename = False
                        break

                    endfile = file_path.name.replace(
                        f"{old_prefix}.{old_client_id}.", '', 1)

                    next_path = spath / f"{new_prefix}.{new_client_id}.{endfile}"

                    if next_path != file_path:
                        if next_path.exists():
                            do_rename = False
                            break
                        
                        files_to_rename.append((file_path, next_path))

                elif file_path.name == f"{old_prefix}.{old_client_id}":
                    if not os.access(file_path, os.W_OK):
                        do_rename = False
                        break

                    next_path = spath / f"{new_prefix}.{new_client_id}"
                    
                    if next_path.exists():
                        do_rename = False
                        break

                    # only for hydrogen
                    hydrogen_file = (
                        project_path / f"{old_prefix}.{old_client_id}.h2song")
                    hydrogen_autosave = (
                        project_path / f"{old_prefix}.{old_client_id}.autosave.h2song")

                    if hydrogen_file.is_file() and os.access(hydrogen_file, os.W_OK):
                        new_hydro_file = (
                            project_path / f"{new_prefix}.{new_client_id}.h2song")
                        
                        if new_hydro_file != hydrogen_file:
                            if new_hydro_file.exists():
                                do_rename = False
                                break

                            files_to_rename.append((hydrogen_file, new_hydro_file))

                    if (hydrogen_autosave.is_file()
                            and os.access(hydrogen_autosave, os.W_OK)):
                        new_hydro_autosave = (
                            project_path
                            / f"{new_prefix}.{new_client_id}.autosave.h2song")

                        if new_hydro_autosave != hydrogen_autosave:
                            if new_hydro_autosave.exists():
                                do_rename = False
                                break

                            files_to_rename.append((hydrogen_autosave, new_hydro_autosave))

                    # only for ardour
                    ardour_file = project_path / f"{old_prefix}.ardour"
                    ardour_bak = project_path / f"{old_prefix}.ardour.bak"
                    ardour_audio = project_path / 'interchange' / project_path.name

                    if ardour_file.is_file() and os.access(ardour_file, os.W_OK):
                        new_ardour_file = project_path / f"{new_prefix}.ardour"
                        if new_ardour_file != ardour_file:
                            if new_ardour_file.exists():
                                do_rename = False
                                break

                            files_to_rename.append((ardour_file, new_ardour_file))

                            # change ardour session name
                            try:
                                tree = ET.parse(ardour_file)
                                root = tree.getroot()
                                if root.tag == 'Session':
                                    root.attrib['name'] = new_prefix

                                # write the file
                                ET.indent(tree, level=0)
                                tree.write(ardour_file)

                            except:
                                _logger.warning(
                                    'Failed to change ardour session '
                                    f'name to "{new_prefix}"')

                    if ardour_bak.is_file() and os.access(ardour_bak, os.W_OK):
                        new_ardour_bak = project_path / f"{new_prefix}.ardour.bak"
                        if new_ardour_bak != ardour_bak:
                            if new_ardour_bak.exists():
                                do_rename = False
                                break

                            files_to_rename.append((ardour_bak, new_ardour_bak))

                    if ardour_audio.is_dir() and os.access(ardour_audio, os.W_OK):
                        new_ardour_audio = (
                            project_path / 'interchange' / f"{new_prefix}.{new_client_id}")
                        
                        if new_ardour_audio != ardour_audio:
                            if new_ardour_audio.exists():
                                do_rename = False
                                break

                            files_to_rename.append((ardour_audio, new_ardour_audio))

                    # for Vee One Suite
                    for extfile in ('samplv1', 'synthv1', 'padthv1', 'drumkv1'):
                        old_veeone_file = project_path / f"{old_session_name}.{extfile}"
                        new_veeone_file = project_path / f"{new_session_name}.{extfile}"
                        if new_veeone_file == old_veeone_file:
                            continue

                        if (old_veeone_file.is_file()
                                and os.access(old_veeone_file, os.W_OK)):
                            if new_veeone_file.exists():
                                do_rename = False
                                break

                            files_to_rename.append((old_veeone_file,
                                                    new_veeone_file))

                    files_to_rename.append((spath / file_path, next_path))                    

                elif file_path.name == old_client_links_dir:
                    # this section only concerns Carla links dir
                    # used to save links for convolutions files or soundfonts
                    # or any other linked resource.
                    if old_client_links_dir == new_client_links_dir:
                        continue

                    if not file_path.is_dir():
                        continue
                    
                    if not os.access(file_path, os.W_OK):
                        do_rename = False
                        break

                    full_new_links_dir = spath / new_client_links_dir
                    if full_new_links_dir.exists():
                        do_rename = False
                        break

                    files_to_rename.append((file_path, full_new_links_dir))

        if not do_rename:
            self.prefix_mode = ray.PrefixMode.CUSTOM
            self.custom_prefix = old_prefix
            _logger.warning(
                f"daemon choose to not rename files for client_id {self.client_id}")
            # it should not be a client_id problem here
            return

        # change last_used snapshot of ardour
        instant_file = project_path / 'instant.xml'
        if instant_file.is_file() and os.access(instant_file, os.W_OK):
            try:
                tree = ET.parse(instant_file)
                root = tree.getroot()
                if root.tag == 'instant':
                    for child in root:
                        if child.tag == 'LastUsedSnapshot':
                            if child.attrib.get('name') == old_prefix:
                                child.attrib['name'] = new_prefix
                            break
                
                ET.indent(tree, level=0)
                tree.write(instant_file)
                
            except:
                _logger.warning(
                    f'Failed to change Ardour LastUsedSnapshot in {instant_file}')

        for now_path, next_path in files_to_rename:
            _logger.info(f'renaming\n\tfile: {now_path}\n\tto:   {next_path}')
            os.rename(now_path, next_path)

    def _save_as_template_substep1(self, template_name: str):
        self.set_status(self.status) # see set_status to see why

        if self.prefix_mode is not ray.PrefixMode.CUSTOM:
            self.adjust_files_after_copy(template_name,
                                         ray.Template.CLIENT_SAVE)

        user_clients_path = TemplateRoots.user_clients
        xml_file = user_clients_path / 'client_templates.xml'

        # security check
        if xml_file.exists():
            if not os.access(xml_file, os.W_OK):
                self._send_error_to_caller(
                    OscSrc.SAVE_TP, ray.Err.CREATE_FAILED,
                    _translate('GUIMSG', '%s is not writeable !') % xml_file)
                return

            if xml_file.is_dir():
                # should not be a dir, remove it !
                _logger.info(
                    'removing {xml_file} because it is a dir, it must be a file')
                try:
                    shutil.rmtree(xml_file)
                except:
                    self._send_error_to_caller(
                        OscSrc.SAVE_TP, ray.Err.CREATE_FAILED,
                        _translate('GUIMSG', 'Failed to remove %s directory !') % xml_file)
                    return

        if not user_clients_path.is_dir():
            try:
                user_clients_path.mkdir(parents=True)
            except BaseException as e:
                _logger.error(str(e))
                self._send_error_to_caller(
                    OscSrc.SAVE_TP, ray.Err.CREATE_FAILED,
                    _translate('GUIMSG', 'Failed to create directories for %s')
                        % user_clients_path)
                return

        # create client_templates.xml if it does not exists
        if not xml_file.is_file():
            root = ET.Element('RAY-CLIENT-TEMPLATES')
            tree = ET.ElementTree(root)
            try:
                tree.write(xml_file)
            except:
                _logger.error(
                    'Failed to create user client templates xml file')
                self._send_error_to_caller(
                    OscSrc.SAVE_TP, ray.Err.CREATE_FAILED,
                    _translate('GUIMSG', 'Failed to write xml file  %s')
                        % str(xml_file))
                return

        try:
            tree = ET.parse(xml_file)
        except BaseException as e:
            _logger.error(str(e))
            self._send_error_to_caller(
                OscSrc.SAVE_TP, ray.Err.CREATE_FAILED,
                _translate('GUIMSG', '%s seems to not be a valid XML file.')
                    % str(xml_file))
            return

        root = tree.getroot()
        
        if root.tag != 'RAY-CLIENT-TEMPLATES':
            self._send_error_to_caller(
                OscSrc.SAVE_TP, ray.Err.CREATE_FAILED,
                _translate('GUIMSG', '%s is not a client templates XML file.')
                    % str(xml_file))
            return
        
        # remove the existant templates with the same name
        to_rm_childs = list[ET.Element]()
        for child in root:
            if child.tag != 'Client-Template':
                continue
            
            c = XmlElement(child)
            if c.str('template-name') == template_name:
                to_rm_childs.append(child)
                
        for child in to_rm_childs:
            root.remove(child)

        # create the client template item in xml file
        c = XmlElement(ET.SubElement(root, 'Client-Template'))
        self.write_xml_properties(c)
        c.set_str('template-name', template_name)
        c.set_str('client_id', self.short_client_id())
        
        if not self.is_running():
            c.set_bool('launched', False)
        
        # write the file
        ET.indent(tree, level=0)
        
        try:
            tree.write(xml_file)
        except Exception as e:
            _logger.error(str(e))
            self._send_error_to_caller(
                OscSrc.SAVE_TP, ray.Err.CREATE_FAILED,
                _translate('GUIMSG', 'Failed to write XML file %s.')
                    % str(xml_file))
            return

        self.template_origin = template_name
        self.send_gui_client_properties()

        template_data_base_users = self.get_client_templates_database('user')
        template_data_base_users.clear()

        self.send_gui_message(
            _translate('message', 'Client template %s created')
                % template_name)

        self._send_reply_to_caller(OscSrc.SAVE_TP, 'client template created')

    def _save_as_template_aborted(self, template_name):
        self.set_status(self.status)
        self._send_error_to_caller(OscSrc.SAVE_TP, ray.Err.COPY_ABORTED,
            _translate('GUIMSG', 'Copy has been aborted !'))

    def get_links_dirname(self) -> str:
        ''' returns the dir path used by carla for links such as
        audio convolutions or soundfonts '''
        links_dir = self.get_jack_client_name()
        for c in ('-', '.'):
            links_dir = links_dir.replace(c, '_')
        return links_dir

    def is_ray_hack(self) -> bool:
        return self.protocol is ray.Protocol.RAY_HACK

    def send_to_self_address(self, *args):
        if not self.addr:
            return

        self.send(self.addr, *args)

    def message(self, message: str):
        if self.session is None:
            return
        self.session.message(message)

    def get_jack_client_name(self):
        if self.protocol is ray.Protocol.RAY_NET:
            # ray-net will use jack_client_name for template
            # quite dirty, but this is the easier way
            return self.ray_net.session_template

        # return same jack_client_name as NSM does
        # if client seems to have been made by NSM itself
        # else, jack connections could be lose
        # at NSM session import
        if self.jack_naming is ray.JackNaming.LONG:
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

    def read_xml_properties(self, c: XmlElement):
        self.executable_path = c.str('executable')
        self.arguments = c.str('arguments')
        self.pre_env = c.str('pre_env')
        self.name = c.str('name')
        self.desktop_file = c.str('desktop_file')
        self.label = c.str('label')
        self.description = c.str('description')
        self.icon = c.str('icon')
        self.in_terminal = c.bool('in_terminal')
        self.auto_start = c.bool('launched', True)
        self.check_last_save = c.bool('check_last_save', True)
        self.start_gui_hidden = not c.bool('gui_visible', True)
        self.template_origin = c.str('template_origin')

        if c.bool('from_nsm_file') or c.bool('jack_naming'):
            self.jack_naming = ray.JackNaming.LONG

        # ensure client has a name
        if not self.name:
            self.name = basename(self.executable_path)

        self.update_infos_from_desktop_file()

        ign_exts = c.str('ignored_extensions').split(' ')
        unign_exts = c.str('unignored_extensions').split(' ')

        global_exts = ray.GIT_IGNORED_EXTENSIONS.split(' ')
        self.ignored_extensions = ""

        for ext in global_exts:
            if ext and not ext in unign_exts:
                self.ignored_extensions += " %s" % ext

        for ext in ign_exts:
            if ext and not ext in global_exts:
                self.ignored_extensions += " %s" % ext

        open_duration = c.str('last_open_duration')
        if open_duration.replace('.', '', 1).isdigit():
            self.last_open_duration = float(open_duration)

        self.prefix_mode = ray.PrefixMode(
            c.int('prefix_mode', ray.PrefixMode.SESSION_NAME.value))

        if self.prefix_mode is ray.PrefixMode.CUSTOM:
            self.custom_prefix = c.str('custom_prefix')

        self.protocol = ray.Protocol.from_string(c.str('protocol'))

        if self.protocol is ray.Protocol.RAY_HACK:
            self.ray_hack.config_file = c.str('config_file')
            self.ray_hack.save_sig = c.int('save_signal')
            self.ray_hack.stop_sig = c.int('stop_signal')
            self.ray_hack.wait_win = c.bool('wait_window')
            no_save_level = c.int('no_save_level')
            if 0 <= no_save_level <= 2:
                self.ray_hack.no_save_level = no_save_level

        # backward compatibility with network session
        if (self.protocol is ray.Protocol.NSM
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
            self.ray_net.session_template = c.str('net_session_template')

        elif self.protocol is ray.Protocol.RAY_NET:
            self.ray_net.daemon_url = c.str('net_daemon_url')
            self.ray_net.session_root = c.str('net_session_root')
            self.ray_net.session_template = c.str('net_session_template')
            self.ray_net.daemon_url = c.str('net_daemon_url')
            self.ray_net.session_root = c.str('net_session_root')
            self.ray_net.session_template = c.str('net_session_template')

        if self.protocol is ray.Protocol.RAY_NET:
            # neeeded only to know if RAY_NET client is capable of switch
            self.executable_path = ray.RAYNET_BIN
            if self.ray_net.daemon_url and self.ray_net.session_root:
                self.arguments = self.get_ray_net_arguments_line()

        if c.str('id'):
            # session uses "id" for absolutely needed client_id
            self.client_id = c.str('id')
        else:
            # template uses "client_id" for wanted client_id
            self.client_id = self.session.generate_client_id(
                c.str('client_id'))

        for cc in c.el:
            if cc.tag == 'custom_data':
                self.custom_data = c.el.attrib.copy()

    def write_xml_properties(self, c: XmlElement):
        if self.protocol is not ray.Protocol.RAY_NET:
            c.set_str('executable', self.executable_path)
            if self.arguments:
                c.set_str('arguments', self.arguments)

        if self.pre_env:
            c.set_str('pre_env', self.pre_env)

        c.set_str('name', self.name)
        if self.desktop_file:
            c.set_str('desktop_file', self.desktop_file)
        if self.label != self._desktop_label:
            c.set_str('label', self.label)
        if self.description != self._desktop_description:
            c.set_str('description', self.description)
        if self.icon != self._desktop_icon:
            c.set_str('icon', self.icon)
        if not self.check_last_save:
            c.set_bool('check_last_save', False)

        if self.prefix_mode is not ray.PrefixMode.SESSION_NAME:
            c.set_int('prefix_mode', self.prefix_mode.value)
            if self.prefix_mode is ray.PrefixMode.CUSTOM:
                c.set_str('custom_prefix', self.custom_prefix)

        if self.is_capable_of(':optional-gui:'):
            c.set_bool('gui_visible', not self.start_gui_hidden)

        if self.jack_naming is ray.JackNaming.LONG:
            c.set_bool('jack_naming', True)

        if self.in_terminal:
            c.set_bool('in_terminal', True)

        if self.template_origin:
            c.set_str('template_origin', self.template_origin)

        if self.protocol is not ray.Protocol.NSM:
            c.set_str('protocol', self.protocol.to_string())

            if self.protocol is ray.Protocol.RAY_HACK:
                c.set_str('config_file', self.ray_hack.config_file)
                c.set_int('save_signal', self.ray_hack.save_sig)
                c.set_int('stop_signal', self.ray_hack.stop_sig)
                c.set_bool('wait_win', self.ray_hack.wait_win)
                c.set_int('no_save_level', self.ray_hack.no_save_level)

            elif self.protocol is ray.Protocol.RAY_NET:
                c.set_str('net_daemon_url', self.ray_net.daemon_url)
                c.set_str('net_session_root', self.ray_net.session_root)
                c.set_str('net_session_template', self.ray_net.session_template)

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
                c.set_str('ignored_extensions', ignored)
            else:
                c.remove_attr('ignored_extensions')

            if unignored:
                c.set_str('unignored_extensions', unignored)
            else:
                c.remove_attr('unignored_extensions')

        if self.last_open_duration >= 5.0:
            c.set_float('last_open_duration', self.last_open_duration)

        if self.custom_data:
            sub_child = ET.SubElement(c.el, 'custom_data')
            for data in self.custom_data:
                sub_child[data] = self.custom_data[data]
            ET.dump(c.el)

    def transform_from_proxy_to_hack(
            self, spath: Path, sess_name: str) -> bool:
        '''before to load a session, if a client has for executable_path
        'ray-proxy', transform it directly to RayHack client.
        'ray-proxy' is a very old tool, replaced with RayHack,
        and I don't want to maintain it anymore.
        
        spath: the session Path of the future session.
        sess_name: the future session name'''

        if self.executable_path != 'ray-proxy':
            return
        
        if self.prefix_mode == ray.PrefixMode.CLIENT_NAME:
            project_path = spath / f'{self.name}.{self.client_id}'
        elif self.prefix_mode == ray.PrefixMode.SESSION_NAME:
            project_path = spath / f'{sess_name}.{self.client_id}'
        else:
            project_path = spath / f'{self.custom_prefix}.{self.client_id}'
        
        proxy_file = project_path / 'ray-proxy.xml'

        try:
            proxy_tree = ET.parse(proxy_file)
        except:
            _logger.warning(
                f'Failed to find {proxy_file} for client {self.client_id}')
            return
        
        root = proxy_tree.getroot()
        if root.tag != 'RAY-PROXY':
            _logger.warning(f'wrong RAY-PROXY xml document: {proxy_file}')
            return

        xroot = XmlElement(root)
        executable = xroot.str('executable')
        arguments = xroot.str('arguments')
        config_file = xroot.str('config_file')
        save_signal = xroot.int('save_signal')
        stop_signal = xroot.int('stop_signal')
        wait_window = xroot.bool('wait_window')
        no_save_level = xroot.int('no_save_level')
        
        if not executable:
            return False

        self.protocol = ray.Protocol.RAY_HACK
        self.executable_path = executable
        self.arguments = arguments
        self.ray_hack.config_file = config_file
        self.ray_hack.no_save_level = no_save_level
        if signal.Signals(save_signal):
            self.ray_hack.save_sig = save_signal
        if signal.Signals(stop_signal):
            self.ray_hack.stop_sig = stop_signal
        self.ray_hack.wait_win = wait_window
                
        if self.prefix_mode == ray.PrefixMode.CLIENT_NAME:
            self.prefix_mode = ray.PrefixMode.CUSTOM
            self.custom_prefix = self.name

        return True

    def set_reply(self, errcode: int, message: str):
        self._reply_message = message
        self._reply_errcode = errcode

        if self._reply_errcode:
            self.message("Client \"%s\" replied with error: %s (%i)"
                                % (self.name, message, errcode))

            if self.pending_command is ray.Command.SAVE:
                self._send_error_to_caller(OscSrc.SAVE, ray.Err.GENERAL_ERROR,
                                    _translate('GUIMSG', '%s failed to save!')
                                            % self.gui_msg_style())
                
                self.session.send_monitor_event(
                    'save_error', self.client_id)

            elif self.pending_command is ray.Command.OPEN:
                self._send_error_to_caller(OscSrc.OPEN, ray.Err.GENERAL_ERROR,
                                    _translate('GUIMSG', '%s failed to open!')
                                            % self.gui_msg_style())
                
                self.session.send_monitor_event(
                    'open_error', self.client_id)

            self.set_status(ray.ClientStatus.ERROR)
        else:
            if self.pending_command is ray.Command.SAVE:
                self.last_save_time = time.time()

                self.send_gui_message(
                    _translate('GUIMSG', '  %s: saved')
                        % self.gui_msg_style())

                self._send_reply_to_caller(OscSrc.SAVE, 'client saved.')
                self.session.send_monitor_event(
                    'saved', self.client_id)

            elif self.pending_command is ray.Command.OPEN:
                self.send_gui_message(
                    _translate('GUIMSG', '  %s: project loaded')
                        % self.gui_msg_style())

                self.last_open_duration = \
                    time.time() - self._last_announce_time

                self._send_reply_to_caller(OscSrc.OPEN, 'client opened')

                self.session.send_monitor_event(
                    'ready', self.client_id)

                if self.has_server_option(ray.Option.GUI_STATES):
                    if (self.session.wait_for is ray.WaitFor.NONE
                            and self.is_capable_of(':optional-gui:')
                            and not self.start_gui_hidden
                            and not self.gui_visible
                            and not self.gui_has_been_visible):
                        self.send_to_self_address('/nsm/client/show_optional_gui')

            self.set_status(ray.ClientStatus.READY)

        if (self.scripter.is_running()
                and self.scripter.pending_command() is self.pending_command):
            return

        self.pending_command = ray.Command.NONE

        if self.session.wait_for is ray.WaitFor.REPLY:
            self.session.end_timer_if_last_expected(self)

    def set_label(self, label:str):
        self.label = label
        self.send_gui_client_properties()

    def has_error(self) -> bool:
        return bool(self._reply_errcode)

    def is_reply_pending(self) -> bool:
        return self.pending_command is not ray.Command.NONE

    def is_dumb_client(self) -> bool:
        if self.is_ray_hack():
            return False

        return bool(not self.did_announce)

    def is_capable_of(self, capability: str)->bool:
        return bool(capability in self.capabilities)

    def gui_msg_style(self)->str:
        return "%s (%s)" % (self.name, self.client_id)

    def set_network_properties(self, net_daemon_url, net_session_root):
        if self.protocol is not ray.Protocol.RAY_NET:
            return

        self.ray_net.daemon_url = net_daemon_url
        self.ray_net.running_daemon_url = net_daemon_url
        self.ray_net.session_root = net_session_root
        self.ray_net.running_session_root = net_session_root
        self.send_gui_client_properties()

    def get_ray_net_arguments_line(self)->str:
        if self.protocol is not ray.Protocol.RAY_NET:
            return ''
        return '--daemon-url %s --net-session-root "%s"' % (
                self.ray_net.daemon_url,
                self.ray_net.session_root.replace('"', '\\"'))

    def set_status(self, status: ray.ClientStatus):
        # ray.ClientStatus.COPY is not a status as the other ones.
        # GUI needs to know if client is started/open/stopped while files are
        # copied, so self.status doesn't remember ray.ClientStatus.COPY,
        # although it is sent to GUI

        if status is not ray.ClientStatus.COPY:
            self.status = status
            self._send_status_to_gui()

        if (status is ray.ClientStatus.COPY
                or self.session.file_copier.is_active(self.client_id)):
            self.send_gui("/ray/gui/client/status", self.client_id,
                          ray.ClientStatus.COPY.value)

    def get_prefix_string(self) -> str:
        if self.prefix_mode is ray.PrefixMode.SESSION_NAME:
            return self.session.name

        if self.prefix_mode is ray.PrefixMode.CLIENT_NAME:
            return self.name

        if self.prefix_mode is ray.PrefixMode.CUSTOM:
            return self.custom_prefix

        return ''

    def get_project_path(self) -> Path:
        if self.protocol is ray.Protocol.RAY_NET:
            return Path(self.session.get_short_path())

        spath = self.session.path

        if self.prefix_mode is ray.PrefixMode.SESSION_NAME:
            return spath / f'{self.session.name}.{self.client_id}'

        if self.prefix_mode is ray.PrefixMode.CLIENT_NAME:
            return spath / f'{self.name}.{self.client_id}'

        if self.prefix_mode is ray.PrefixMode.CUSTOM:
            return spath / f'{self.custom_prefix}.{self.client_id}'

        # should not happens
        return spath / f'{self.session.name}.{self.client_id}'

    def set_default_git_ignored(self, executable=""):
        executable = executable if executable else self.executable_path
        executable = os.path.basename(executable)

        if executable.startswith(('ardour', 'Ardour')):
            if len(executable) == 6:
                self.ignored_extensions += " .mid"
            elif len(executable) <= 8:
                rest = executable[6:]
                if rest.isdigit():
                    self.ignored_extensions += " .mid"
        elif executable == 'qtractor':
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

    def start(self, osp: Optional[OscPack]=None, wait_open_to_reply=False):
        if osp is not None and not wait_open_to_reply:
            self._osc_srcs[OscSrc.START] = osp

        self.session.set_renameable(False)

        self.last_dirty = 0.00
        self.gui_has_been_visible = False
        self.gui_visible = False
        self.show_gui_ordered = False

        if self.is_dummy:
            self._send_error_to_caller(OscSrc.START, ray.Err.GENERAL_ERROR,
                _translate('GUIMSG', "can't start %s, it is a dummy client !")
                    % self.gui_msg_style())
            return

        if (self.protocol is ray.Protocol.RAY_NET
                and not self.session.path.is_relative_to(self.session.root)):
            self._send_error_to_caller(OscSrc.START, ray.Err.GENERAL_ERROR,
                _translate('GUIMSG',
                    "Impossible to run Ray-Net client when session is not in root folder"))
            return

        if self.scripter.start(ray.Command.START, osp,
                               self._osc_srcs.get(OscSrc.START)):
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

        if self.protocol is not ray.Protocol.RAY_HACK:
            process_env.insert('NSM_URL', self.get_server_url())

        arguments = list[str]()
        terminal_args = list[str]()
        
        if self.in_terminal:
            server = self.get_server()
            if server is not None:
                terminal_args = [
                    a.replace('RAY_TERMINAL_TITLE',
                              f"{self.client_id} {self.executable_path}")
                    for a in shlex.split(server.terminal_command)]

        if self.protocol is ray.Protocol.RAY_NET:
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
            os.environ['PWD'] = str(ray_hack_pwd)

            if not ray_hack_pwd.exists():
                try:
                    ray_hack_pwd.mkdir(parents=True)
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
            self._process.setWorkingDirectory(str(ray_hack_pwd))
            process_env.insert('RAY_SESSION_NAME', self.session.name)
            process_env.insert('RAY_CLIENT_ID', self.client_id)

            self.jack_client_name = self.get_jack_client_name()
            self.send_gui_client_properties()

        self.launched_in_terminal = self.in_terminal
        if self.launched_in_terminal:
            self.session.externals_timer.start()

        self.session.send_monitor_event(
            'start_request', self.client_id)

        self._process.setProcessEnvironment(process_env)
        prog, *other_args = terminal_args + [self.executable_path] + arguments        
        self._process.start(prog, other_args)

    def load(self, osp: Optional[OscPack]=None):
        if osp is not None:
            self._osc_srcs[OscSrc.OPEN] = osp

        if self.nsm_active:
            self._send_reply_to_caller(OscSrc.OPEN, 'client active')
            return

        if self.pending_command is ray.Command.STOP:
            self._send_error_to_caller(OscSrc.OPEN, ray.Err.GENERAL_ERROR,
                _translate('GUIMSG', '%s is exiting.') % self.gui_msg_style())

        if self.is_running() and self.is_dumb_client():
            self._send_error_to_caller(OscSrc.OPEN, ray.Err.GENERAL_ERROR,
                _translate('GUIMSG', '%s seems to can not open')
                    % self.gui_msg_style())

        duration = max(8000, 2 * self.last_open_duration)
        self._open_timer.setInterval(duration)
        self._open_timer.start()

        if self.pending_command is ray.Command.OPEN:
            return

        if not self.is_running():
            if self.executable_path in RS.non_active_clients:
                if osp.src_addr:
                    self._osc_srcs[OscSrc.START] = osp
                    self._osc_srcs[OscSrc.OPEN] = None

            self.start(osp, wait_open_to_reply=True)
            return

    def terminate(self):
        if self.is_running():
            if self.is_external:
                os.kill(self.pid, signal.SIGTERM)
            else:
                self._process.terminate()

    def kill(self):
        if self.is_external:
            os.kill(self.pid, signal.SIGKILL)
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
        
        return self._process.state() == QProcess.ProcessState.Running

    def external_finished(self):
        self._process_finished(0, 0)

    def nsm_finished_terminal_alive(self):
        # the client is not more alive
        # but it has been launched from terminal
        # and this terminal is not closed.
        self.nsm_active = False
        self.set_status(ray.ClientStatus.LOSE)

    def script_finished(self, exit_code: int):
        if self.scripter.is_asked_for_terminate():
            if self.session.wait_for is ray.WaitFor.QUIT:
                self.session.end_timer_if_last_expected(self)
            return

        scripter_pending_command = self.scripter.pending_command()

        if exit_code:
            error_text = "script %s ended with an error code" \
                            % self.scripter.get_path()
            if scripter_pending_command is ray.Command.SAVE:
                self._send_error_to_caller(OscSrc.SAVE, - exit_code,
                                        error_text)
            elif scripter_pending_command is ray.Command.START:
                self._send_error_to_caller(OscSrc.START, - exit_code,
                                        error_text)
            elif scripter_pending_command is ray.Command.STOP:
                self._send_error_to_caller(OscSrc.STOP, - exit_code,
                                        error_text)
        else:
            if scripter_pending_command is ray.Command.SAVE:
                self._send_reply_to_caller(OscSrc.SAVE, 'saved')
            elif scripter_pending_command is ray.Command.START:
                self._send_reply_to_caller(OscSrc.START, 'started')
            elif scripter_pending_command is ray.Command.STOP:
                self._send_reply_to_caller(OscSrc.STOP, 'stopped')

        if scripter_pending_command is self.pending_command:
            self.pending_command = ray.Command.NONE

        if (scripter_pending_command is ray.Command.STOP
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

        self._send_reply_to_caller(OscSrc.OPEN, 'client opened')
        self.pending_command = ray.Command.NONE
        self.set_status(ray.ClientStatus.READY)

        if self.session.wait_for is ray.WaitFor.REPLY:
            self.session.end_timer_if_last_expected(self)

    def terminate_scripts(self):
        self.scripter.terminate()

    def tell_client_session_is_loaded(self):
        if self.nsm_active and not self.is_dumb_client():
            self.message("Telling client %s that session is loaded."
                         % self.name)
            self.send_to_self_address("/nsm/client/session_is_loaded")

    def can_save_now(self):
        if self.is_ray_hack():
            if not self.ray_hack.saveable():
                return False

            return bool(self.is_running()
                        and self.pending_command is ray.Command.NONE)

        return self.nsm_active

    def save(self, osp: Optional[OscPack]=None):
        if self.switch_state in (ray.SwitchState.RESERVED,
                                 ray.SwitchState.NEEDED):
            if osp is not None:
                self.send(*osp.error(), ray.Err.NOT_NOW,
                "Save cancelled because client has not switch yet !")
            return

        if osp is not None:
            self._osc_srcs[OscSrc.SAVE] = osp

        if self.is_running():
            if self.scripter.start(ray.Command.SAVE, osp,
                                   self._osc_srcs.get(OscSrc.SAVE)):
                self.set_status(ray.ClientStatus.SCRIPT)
                return

        if self.pending_command is ray.Command.SAVE:
            self._send_error_to_caller(OscSrc.SAVE, ray.Err.GENERAL_ERROR,
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

    def stop(self, osp: Optional[OscPack]=None):
        if self.switch_state is ray.SwitchState.NEEDED:
            if osp is not None:
                self.send(*osp.error(), ray.Err.NOT_NOW,
                "Stop cancelled because client is needed for opening session")
            return

        if osp is not None:
            self._osc_srcs[OscSrc.STOP] = osp

        self.send_gui_message(_translate('GUIMSG', "  %s: stopping")
                                % self.gui_msg_style())

        if self.is_running():
            if self.scripter.start(ray.Command.STOP, osp,
                                   self._osc_srcs.get(OscSrc.STOP)):
                self.set_status(ray.ClientStatus.SCRIPT)
                return

            self.pending_command = ray.Command.STOP
            self.set_status(ray.ClientStatus.QUIT)

            if not self._stopped_timer.isActive():
                self._stopped_timer.start()

            self.session.send_monitor_event(
                'stop_request', self.client_id)

            if self.launched_in_terminal and self.pid_from_nsm:
                try:
                    os.kill(self.pid_from_nsm, signal.SIGTERM)
                except ProcessLookupError:
                    self.pid_from_nsm = 0
                except:
                    self.pid_from_nsm = 0

            if self.is_external:
                os.kill(self.pid, signal.SIGTERM)
            elif self.is_ray_hack() and self.ray_hack.stop_sig != signal.SIGTERM.value:
                os.kill(self._process.pid(), self.ray_hack.stop_sig)
            else:
                self._process.terminate()
        else:
            self._send_reply_to_caller(OscSrc.STOP, 'client stopped.')

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
        self.message(
            f'Commanding {self.name} to switch "{client_project_path}"')

        self.send_to_self_address(
            "/nsm/client/open", str(client_project_path),
            self.session.name, self.jack_client_name)

        self.pending_command = ray.Command.OPEN
        
        self.set_status(ray.ClientStatus.SWITCH)
        if self.is_capable_of(':optional-gui:'):
            self.send_gui('/ray/gui/client/gui_visible',
                           self.client_id, int(self.gui_visible))

    def can_switch_with(self, other_client: 'Client')->bool:
        if self.protocol is ray.Protocol.RAY_HACK:
            return False

        if self.protocol is not other_client.protocol:
            return False

        if not ((self.nsm_active and self.is_capable_of(':switch:'))
                or (self.is_dumb_client() and self.is_running())):
            return False

        if self.protocol is ray.Protocol.RAY_NET:
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

        if self.protocol is ray.Protocol.RAY_HACK:
            self.send_gui(
                hack_ad, self.client_id, *self.ray_hack.spread())

        elif self.protocol is ray.Protocol.RAY_NET:
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
                if value.isdigit():
                    self.prefix_mode = ray.PrefixMode(int(value))
            elif prop == 'custom_prefix':
                self.custom_prefix = value
            elif prop == 'jack_naming':
                if value.isdigit():
                    self.jack_naming = ray.JackNaming(int(value))
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

            if self.protocol is ray.Protocol.RAY_HACK:
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

            elif self.protocol is ray.Protocol.RAY_NET:
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
                            self.protocol.to_string(),
                            self.executable_path,
                            self.pre_env,
                            self.arguments,
                            self.name,
                            self.prefix_mode.value,
                            self.custom_prefix,
                            self.jack_naming.value,
                            self.get_jack_client_name(),
                            self.desktop_file,
                            self.label,
                            self.icon,
                            int(self.check_last_save),
                            self.ignored_extensions)

        if self.protocol is ray.Protocol.NSM:
            message += "\ncapabilities:%s" % self.capabilities
        elif self.protocol is ray.Protocol.RAY_HACK:
            message += """\nconfig_file:%s
save_sig:%i
stop_sig:%i
wait_win:%i
no_save_level:%i""" % (self.ray_hack.config_file,
                       self.ray_hack.save_sig,
                       self.ray_hack.stop_sig,
                       int(self.ray_hack.wait_win),
                       self.ray_hack.no_save_level)
        elif self.protocol is ray.Protocol.RAY_NET:
            message += """\nnet_daemon_url:%s
net_session_root:%s
net_session_template:%s""" % (self.ray_net.daemon_url,
                              self.ray_net.session_root,
                              self.ray_net.session_template)
        return message

    def relevant_no_save_level(self) -> int:
        '''This method will be renamed or deleted later
        no_save_level will be deprecated for NSM client
        it will applies only on Ray-Hack clients'''
        if self.is_ray_hack():
            return self.ray_hack.relevant_no_save_level()

        return 0

    def get_project_files(self) -> list[Path]:
        client_files = list[Path]()
        project_path = self.get_project_path()
        spath = self.session.path

        if project_path.exists():
            client_files.append(project_path)

        if project_path.is_relative_to(spath):
            for file_path in spath.iterdir():
                if file_path == project_path:
                    if not file_path in client_files:
                        client_files.append(file_path)
                        
                elif file_path.name.startswith(project_path.name + '.'):
                    client_files.append(file_path)

        scripts_dir = spath / ray.SCRIPTS_DIR / self.client_id
        if scripts_dir.exists():
            client_files.append(scripts_dir)

        full_links_dir = spath / self.get_links_dirname()
        if full_links_dir.exists():
            client_files.append(full_links_dir)

        return client_files

    def update_infos_from_desktop_file(self):
        if self.icon and self.description and self.label:
            return

        desktop_file = self.desktop_file
        if desktop_file == '//not_found':
            return

        if not desktop_file:
            desktop_file = exec_and_desktops.get(self.executable_path)

        if not desktop_file:
            desktop_file = os.path.basename(self.executable_path)

        if not desktop_file.endswith('.desktop'):
            desktop_file += ".desktop"

        desk_path_list = ([get_code_root() / 'data' / 'share']
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
            
            # alter_exec is used for Mixbus but could be used by others
            # if the executable is a symlink, we can search desktop file
            # finding the symlink target as executable in desktop file.
            alter_exec = None
            full_exec = shutil.which(self.executable_path)

            if full_exec is not None:
                if Path(full_exec).is_symlink():
                    try:
                        alter_exec = str(Path(full_exec).readlink())
                    except BaseException as e:
                        _logger.warning(str(e))

            for desk_data_path in desk_path_list:
                desk_app_path = desk_data_path / 'applications'

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
                            if (self.executable_path in value.split()
                                    or (alter_exec is not None
                                        and alter_exec in value.split())):
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

    def save_as_template(self, template_name: str, osp: Optional[OscPack]=None):
        if osp is not None:
            self._osc_srcs[OscSrc.SAVE_TP] = osp

        #copy files
        client_files = self.get_project_files()

        template_dir = TemplateRoots.user_clients / template_name
        if template_dir.exists():
            if os.access(template_dir, os.W_OK):
                template_dir.rmdir()
            else:
                self._send_error_to_caller(
                    OscSrc.SAVE_TP, ray.Err.CREATE_FAILED,
                    _translate('GUIMSG', 'impossible to remove %s !')
                    % highlight_text(template_dir))
                return

        template_dir.mkdir(parents=True)

        if self.protocol is ray.Protocol.RAY_NET:
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
        spath = self.session.path
        
        while Path(spath / tmp_basedir).exists():
            tmp_basedir += 'X'
        tmp_work_dir = spath / tmp_basedir
        
        try:
            tmp_work_dir.mkdir(parents=True)
        except:
            self.send(
                src_addr, '/error', osc_path, ray.Err.CREATE_FAILED,
                f"impossible to make a tmp workdir at {tmp_work_dir}. Abort.")
            self.session._remove_client(self)
            return

        self.set_status(ray.ClientStatus.PRECOPY)
        
        self.session.file_copier.start_client_copy(
            self.client_id,
            client.get_project_files(),
            tmp_work_dir,
            self.eat_other_session_client_step_1,
            self.eat_other_session_client_aborted,
            [src_addr, osc_path, client, tmp_work_dir])

    def eat_other_session_client_step_1(self, src_addr: Address, osc_path: str,
                                        client: 'Client', tmp_work_dir: str):
        self._rename_files(
            Path(tmp_work_dir), client.session.name, self.session.name,
            client.get_prefix_string(), self.get_prefix_string(),
            client.client_id, self.client_id,
            client.get_links_dirname(), self.get_links_dirname())

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
        if self.prefix_mode is ray.PrefixMode.CLIENT_NAME:
            old_prefix = self.name
        elif self.prefix_mode is ray.PrefixMode.CUSTOM:
            old_prefix = self.custom_prefix

        new_prefix = self.session.name
        if prefix_mode is ray.PrefixMode.CLIENT_NAME:
            new_prefix = self.name
        elif prefix_mode is ray.PrefixMode.CUSTOM:
            new_prefix = custom_prefix

        links_dir = self.get_links_dirname()

        self._rename_files(
            self.session.path,
            self.session.name, self.session.name,
            old_prefix, new_prefix,
            self.client_id, self.client_id,
            links_dir, links_dir)

        self.prefix_mode = ray.PrefixMode(prefix_mode)
        self.custom_prefix = custom_prefix
        self.send_gui_client_properties()

    def adjust_files_after_copy(self, new_session_full_name: str,
                                template_save=ray.Template.NONE):
        spath = self.session.path
        old_session_name = self.session.name
        new_session_name = Path(new_session_full_name).name
        new_client_id = self.client_id
        old_client_id = self.client_id
        new_client_links_dir = self.get_links_dirname()
        old_client_links_dir = new_client_links_dir

        X_SESSION_X = "XXX_SESSION_NAME_XXX"
        X_CLIENT_ID_X = "XXX_CLIENT_ID_XXX"
        X_CLIENT_LINKS_DIR_X = "XXX_CLIENT_LINKS_DIR_XXX" # used for Carla links dir

        if template_save is ray.Template.NONE:
            if self.prefix_mode is not ray.PrefixMode.SESSION_NAME:
                return

            spath = self.session.root / new_session_full_name

        elif template_save is ray.Template.RENAME:
            pass

        elif template_save is ray.Template.SESSION_SAVE:
            spath = Path(new_session_full_name)
            if not spath.is_absolute():
                spath = TemplateRoots.user_sessions / new_session_full_name
            new_session_name = X_SESSION_X

        elif template_save is ray.Template.SESSION_SAVE_NET:
            spath = (self.session.root
                     / TemplateRoots.net_session_name
                     / new_session_full_name)
            new_session_name = X_SESSION_X

        elif template_save is ray.Template.SESSION_LOAD:
            spath = self.session.root / new_session_full_name
            old_session_name = X_SESSION_X

        elif template_save is ray.Template.SESSION_LOAD_NET:
            spath = self.session.root / new_session_full_name
            old_session_name = X_SESSION_X

        elif template_save is ray.Template.CLIENT_SAVE:
            spath = TemplateRoots.user_clients / new_session_full_name
            new_session_name = X_SESSION_X
            new_client_id = X_CLIENT_ID_X
            new_client_links_dir = X_CLIENT_LINKS_DIR_X

        elif template_save is ray.Template.CLIENT_LOAD:
            spath = self.session.path
            old_session_name = X_SESSION_X
            old_client_id = X_CLIENT_ID_X
            old_client_links_dir = X_CLIENT_LINKS_DIR_X

        old_prefix = old_session_name
        new_prefix = new_session_name
        if self.prefix_mode is ray.PrefixMode.CLIENT_NAME:
            old_prefix = new_prefix = self.name
        elif self.prefix_mode is ray.PrefixMode.CUSTOM:
            old_prefix = new_prefix = self.custom_prefix

        self._rename_files(
            str(spath),
            old_session_name, new_session_name,
            old_prefix, new_prefix,
            old_client_id, new_client_id,
            old_client_links_dir, new_client_links_dir)

    def server_announce(self, osp: OscPack, is_new: bool):
        client_name, capabilities, executable_path, \
            major, minor, pid = osp.args

        if self.pending_command is ray.Command.STOP:
            # assume to not answer to a dying client.
            # He will never know, or perhaps, it depends on beliefs.
            return

        if major > NSM_API_VERSION_MAJOR:
            self.message(
                "Client is using incompatible and more recent "
                + "API version %i.%i" % (major, minor))
            self.send(*osp.error(), ray.Err.INCOMPATIBLE_API,
                      "Server is using an incompatible API version.")
            return

        self.capabilities = capabilities
        self.addr = osp.src_addr
        self.name = client_name
        self.nsm_active = True
        self.did_announce = True
        self.process_drowned = False
        self.pid_from_nsm = pid

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

        self.send(*osp.reply(),
                  "Well hello, stranger. Welcome to the party."
                  if is_new else "Howdy, what took you so long?",
                  ray.APP_TITLE,
                  server_capabilities)

        client_project_path = str(self.get_project_path())
        self.jack_client_name = self.get_jack_client_name()

        if self.protocol is ray.Protocol.RAY_NET:
            client_project_path = self.session.get_short_path()
            self.jack_client_name = self.ray_net.session_template

        self.send_gui_client_properties()
        self.set_status(ray.ClientStatus.OPEN)

        if ':monitor:' in self.capabilities:
            self.session.send_initial_monitor(self.addr)
        self.session.send_monitor_client_update(self)

        self.send(osp.src_addr, "/nsm/client/open", client_project_path,
                  self.session.name, self.jack_client_name)

        self.pending_command = ray.Command.OPEN

        self._last_announce_time = time.time()
