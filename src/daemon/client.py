
# Imports from standard library
import logging
import os
import shlex
import shutil
import signal
import time
from pathlib import Path
from enum import Enum
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING, Optional

# third party imports
from qtpy.QtCore import (QCoreApplication, QProcess,
                         QProcessEnvironment, QTimer)
from ruamel.yaml.comments import CommentedMap

# Imports from src/shared
from osclib import Address, OscPack
import ray
import xdg
from xml_tools import XmlElement
from expand_vars import expand_vars
import osc_paths
import osc_paths.ray as r
import osc_paths.ray.gui as rg
import osc_paths.nsm as nsm

# Local imports
import client_tools
from server_sender import ServerSender
from daemon_tools  import (
    NoSessionPath, Terminal, RS, get_code_root, exec_and_desktops)
from signaler import Signaler
from scripter import ClientScripter
from internal_client import InternalClient
from yaml_tools import YamlMap

# only used to identify session functions in the IDE
# 'Session' is not importable simply because it would be
# a circular import.
if TYPE_CHECKING:
    from .session import Session


class OscSrc(Enum):
    START = 0
    OPEN = 1
    SAVE = 2
    STOP = 3


NSM_API_VERSION_MAJOR = 1
NSM_API_VERSION_MINOR = 0

INTERNAL_EXECS = {'ray-jackpatch', 'ray-alsapatch', 'sooperlooper_nsm'}

_logger = logging.getLogger(__name__)
_translate = QCoreApplication.translate
signaler = Signaler.instance()


class Client(ServerSender, ray.ClientData):
    _reply_errcode = 0
    _reply_message = None

    # can be directly changed by OSC thread
    gui_visible = False
    gui_has_been_visible = False
    dirty = 0
    progress = 0.0

    # have to be modified by main thread for security
    addr: Optional[Address] = None
    pid = 0
    pid_from_nsm = 0
    pending_command = ray.Command.NONE
    nsm_active = False
    did_announce = False
    protocol_orig = ray.Protocol.NSM
    '''Only used when ray.InternalMode is not FOLLOW_PROTOCOL
    to keep the protocol when saving'''

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
    _last_open_time = 0.00
    last_open_duration = 0.00

    has_been_started = False

    _desktop_label = ""
    _desktop_icon = ""
    _desktop_description = ""

    jack_naming = ray.JackNaming.LONG

    launched_in_terminal = False
    
    process_drowned = False
    '''when launched in terminal
    with some terminals (mate-terminal, gnome-terminal)
    if the terminal is already launched for another process,
    the launched process finishs fastly because
    the program is 'linked' in the current terminal process.'''
    
    _process_start_time = 0.0
    
    ray_hack: ray.RayHack
    ray_net: ray.RayNet

    def __init__(self, parent_session: 'Session'):
        ServerSender.__init__(self)
        self.session = parent_session
        self.is_dummy = self.session.is_dummy

        self.custom_data = dict[str, str]()
        self.custom_tmp_data = dict[str, str]()

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
        self._osc_srcs = dict[OscSrc, Optional[OscPack]]()

        self._open_timer = QTimer()
        self._open_timer.setSingleShot(True)
        self._open_timer.timeout.connect(self._open_timer_timeout)

        self.ray_hack = ray.RayHack()
        self.ray_net = ray.RayNet()
        self.scripter = ClientScripter(self)

        self.ray_hack_waiting_win = False
        
        self._internal: Optional[InternalClient] = None

    def __repr__(self) -> str:
        return f'Client({self.client_id})'

    @staticmethod
    def short_client_id(wanted: str) -> str:
        if '_' in wanted:
            begin, _, end = wanted.rpartition('_')

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

        self.send_gui_message(
            _translate("GUIMSG", "  %s: launched") % self.gui_msg_style)

        self.session.send_monitor_event('started', self.client_id)

        self._send_reply_to_caller(OscSrc.START, 'client started')

        if self.is_ray_hack:
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
                                  % self.gui_msg_style)
            
            self.session.send_monitor_event(
                'stopped_by_server', self.client_id)
        else:
            self.send_gui_message(_translate('GUIMSG',
                                           "  %s: terminated itself.")
                                    % self.gui_msg_style)
            
            self.session.send_monitor_event(
                'stopped_by_itself', self.client_id)

        self._send_reply_to_caller(OscSrc.STOP, 'client stopped')

        for osc_src in (OscSrc.OPEN, OscSrc.SAVE):
            self._send_error_to_caller(osc_src, ray.Err.GENERAL_ERROR,
                    _translate('GUIMSG', '%s died !' % self.gui_msg_style))

        self.set_status(ray.ClientStatus.STOPPED)

        self.pending_command = ray.Command.NONE
        self.nsm_active = False
        self.pid = 0
        self.addr = None

        self.session.set_renameable(True)

        if self.scripter.pending_command() is ray.Command.STOP:
            return

        if self.session.wait_for is not ray.WaitFor.NONE:
            self.session.end_timer_if_last_expected(self)

    def _error_in_process(self, error: int):
        if error == QProcess.ProcessError.FailedToStart:
            self.send_gui_message(
                _translate('GUIMSG', "  %s: Failed to start !")
                    % self.gui_msg_style)
            self.nsm_active = False
            self.pid = 0
            self.set_status(ray.ClientStatus.STOPPED)
            self.pending_command = ray.Command.NONE

            if (self.session.steps_osp is not None
                    and self.session.steps_osp.src_addr): 
                error_message = "Failed to launch process!"
                if not self.session.steps_osp.path.startswith('/nsm/server/'): 
                    error_message = _translate(
                        'client',
                        " %s: Failed to launch process !"
                            % self.gui_msg_style)

                self.session._send_error(ray.Err.LAUNCH_FAILED, error_message)

            for osc_slot in (OscSrc.START, OscSrc.OPEN):
                self._send_error_to_caller(osc_slot, ray.Err.LAUNCH_FAILED,
                    _translate('GUIMSG', '%s failed to launch')
                        % self.gui_msg_style)

            if self.session.wait_for is not ray.WaitFor.NONE:
                self.session.end_timer_if_last_expected(self)
        self.session.set_renameable(True)

    def _stopped_since_long(self):
        self._stopped_since_long_ = True
        self.send_gui(rg.client.STILL_RUNNING, self.client_id)

    def _send_reply_to_caller(self, slot: OscSrc, message: str):
        osp = self._osc_srcs.get(slot)
        if osp is not None:
            self.send(*osp.reply(), message)
            self._osc_srcs[slot] = None

            if (self.scripter.is_running()
                    and self.scripter.pending_command()
                        == self.pending_command):
                self._osc_srcs[slot] = self.scripter.initial_caller()

        if slot is OscSrc.OPEN:
            self._open_timer.stop()

    def _send_error_to_caller(self, slot: OscSrc, err: int, message: str):
        osp = self._osc_srcs.get(slot)
        if osp is not None:
            self.send(*osp.error(), err, message)
            self._osc_srcs[slot] = None

            if (self.scripter.is_running()
                    and self.scripter.pending_command() is self.pending_command):
                self._osc_srcs[slot] = self.scripter.initial_caller()

        if slot is OscSrc.OPEN:
            self._open_timer.stop()

    def _open_timer_timeout(self):
        self._send_error_to_caller(OscSrc.OPEN,
            ray.Err.GENERAL_ERROR,
            _translate('GUIMSG', '%s is started but not active')
                % self.gui_msg_style)

    def _send_status_to_gui(self):
        self.send_gui(rg.client.STATUS, self.client_id, self.status.value)

    def _net_daemon_out_of_time(self):
        self.ray_net.duplicate_state = -1.0

        if self.session.wait_for is ray.WaitFor.DUPLICATE_FINISH:
            self.session.end_timer_if_last_expected(self)

    def _ray_hack_near_ready(self):
        if not self.is_ray_hack:
            return

        if not self.is_running:
            return

        if self.ray_hack.wait_win:
            self.ray_hack_waiting_win = True
            if not self.session.window_waiter.isActive():
                self.session.window_waiter.start()
        else:
            self.ray_hack_ready()

    def _ray_hack_saved(self):
        if not self.is_ray_hack:
            return

        if self.pending_command is ray.Command.SAVE:
            self.pending_command = ray.Command.NONE
            self.set_status(ray.ClientStatus.READY)

            self.last_save_time = time.time()

            self.send_gui_message(
                _translate('GUIMSG', '  %s: saved')
                    % self.gui_msg_style)

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
                for i, lang_str in enumerate(lang_strs):
                    if var == searched + lang_str:
                        all_data[searched][i] = value
                        found = True
                        break

                if found:
                    break

        for data in all_data:
            for str_value in all_data[data]:
                match data:
                    case 'Comment':
                        if str_value and not self.description:
                            self._desktop_description = str_value
                            self.description = str_value
                            break
                    case 'Name':
                        if str_value and not self.label:
                            self._desktop_label = str_value
                            self.label = str_value
                            break
                    case 'Icon':
                        if str_value and not self.icon:
                            self._desktop_icon = str_value
                            self.icon = str_value
                            break

    def _rename_files(
            self, spath: Path,
            old_session_name: str, new_session_name: str,
            old_prefix: str, new_prefix: str,
            old_client_id: str, new_client_id: str,
            old_client_links_dir: str, new_client_links_dir: str):
        client_tools.rename_client_files(
            self, spath, old_session_name, new_session_name,
            old_prefix, new_prefix, old_client_id, new_client_id,
            old_client_links_dir, new_client_links_dir)

    @property
    def links_dirname(self) -> str:
        '''return the dir path used by carla for links such as
        audio convolutions or soundfonts'''
        return self.jack_client_name.replace('-', '_').replace('.', '_')

    def send_to_self_address(self, *args):
        if self.addr is None:
            return

        self.send(self.addr, *args)

    def message(self, message: str):
        self.session.message(message)

    @property
    def jack_client_name(self) -> str:
        if self.is_ray_net:
            # ray-net will use jack_client_name for template
            # quite dirty, but this is the easier way
            return self.ray_net.session_template

        # return same jack_client_name as NSM does
        # if client seems to have been made by NSM itself
        # else, jack connections could be lose
        # at NSM session import
        if self.jack_naming is ray.JackNaming.LONG:
            return f'{self.name}.{self.client_id}'

        jack_client_name = self.name

        # Mostly for ray_hack
        if not jack_client_name:
            jack_client_name = os.path.basename(self.executable)
            jack_client_name.capitalize()

        if '_' in self.client_id:
            numid = self.client_id.rpartition('_')[2]
            if numid.isdigit():
                jack_client_name += f'_{numid}'

        return jack_client_name

    def read_xml_properties(self, c: XmlElement):
        self.executable = c.string('executable')
        self.arguments = c.string('arguments')
        self.pre_env = c.string('pre_env')
        self.name = c.string('name')
        self.desktop_file = c.string('desktop_file')
        self.label = c.string('label')
        self.description = c.string('description')
        self.icon = c.string('icon')
        self.in_terminal = c.bool('in_terminal')
        self.auto_start = c.bool('launched', True)
        self.check_last_save = c.bool('check_last_save', True)
        self.start_gui_hidden = not c.bool('gui_visible', True)
        self.template_origin = c.string('template_origin')

        self.jack_naming = ray.JackNaming.SHORT
        self.prefix_mode = ray.PrefixMode.SESSION_NAME

        if c.string('jack_naming'):
            self.jack_naming = ray.JackNaming(int(c.bool('jack_naming')))
        elif c.string('from_nsm_file'):
            self.jack_naming = ray.JackNaming(int(c.bool('from_nsm_file')))

        # ensure client has a name
        if not self.name:
            self.name = Path(self.executable).name

        self.update_infos_from_desktop_file()

        ign_exts = c.string('ignored_extensions').split(' ')
        unign_exts = c.string('unignored_extensions').split(' ')

        global_exts = ray.GIT_IGNORED_EXTENSIONS.split(' ')
        self.ignored_extensions = ""

        for ext in global_exts:
            if ext and not ext in unign_exts:
                self.ignored_extensions += " %s" % ext

        for ext in ign_exts:
            if ext and not ext in global_exts:
                self.ignored_extensions += " %s" % ext

        open_duration = c.string('last_open_duration')
        if open_duration.replace('.', '', 1).isdigit():
            self.last_open_duration = float(open_duration)

        self.prefix_mode = ray.PrefixMode(
            c.int('prefix_mode', ray.PrefixMode.SESSION_NAME.value))

        if self.prefix_mode is ray.PrefixMode.CUSTOM:
            self.custom_prefix = c.string('custom_prefix')

        self.protocol = ray.Protocol.from_string(c.string('protocol'))

        if self.protocol is ray.Protocol.RAY_HACK:
            self.ray_hack.config_file = c.string('config_file')
            self.ray_hack.save_sig = c.int('save_signal')
            self.ray_hack.stop_sig = c.int('stop_signal')
            self.ray_hack.wait_win = c.bool('wait_window')
            no_save_level = c.int('no_save_level')
            if 0 <= no_save_level <= 2:
                self.ray_hack.no_save_level = no_save_level

        # backward compatibility with network session
        if (self.protocol is ray.Protocol.NSM
                and Path(self.executable).name == 'ray-network'):
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
            self.ray_net.session_template = c.string('net_session_template')

        elif self.protocol is ray.Protocol.RAY_NET:
            self.ray_net.daemon_url = c.string('net_daemon_url')
            self.ray_net.session_root = c.string('net_session_root')
            self.ray_net.session_template = c.string('net_session_template')

        if self.is_ray_net:
            # neeeded only to know if RAY_NET client is capable of switch
            self.executable = ray.RAYNET_BIN
            if self.ray_net.daemon_url and self.ray_net.session_root:
                self.arguments = self.get_ray_net_arguments_line()

        if c.string('id'):
            # session uses "id" for absolutely needed client_id
            self.client_id = c.string('id')
        else:
            # template uses "client_id" for wanted client_id
            self.client_id = self.session.generate_client_id(
                c.string('client_id'))

        for cc in c.el:
            if cc.tag == 'custom_data':
                self.custom_data = c.el.attrib.copy()

    def write_xml_properties(self, c: XmlElement):
        if not self.is_ray_net:
            c.set_str('executable', self.executable)
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

        if self.can_optional_gui:
            c.set_bool('gui_visible', not self.start_gui_hidden)

        if self.jack_naming is ray.JackNaming.LONG:
            c.set_bool('jack_naming', True)

        if self.in_terminal:
            c.set_bool('in_terminal', True)

        if self.template_origin:
            c.set_str('template_origin', self.template_origin)

        protocol = self.protocol
        internal_mode = ray.InternalMode.FOLLOW_PROTOCOL
        server = self.get_server()
        if server is not None:
            internal_mode = server.internal_mode
        if internal_mode is not ray.InternalMode.FOLLOW_PROTOCOL:
            protocol = self.protocol_orig

        if protocol is not ray.Protocol.NSM:
            c.set_str('protocol', self.protocol.to_string())

            if self.is_ray_hack:
                c.set_str('config_file', self.ray_hack.config_file)
                c.set_int('save_signal', self.ray_hack.save_sig)
                c.set_int('stop_signal', self.ray_hack.stop_sig)
                c.set_bool('wait_win', self.ray_hack.wait_win)
                c.set_int('no_save_level', self.ray_hack.no_save_level)

            elif self.is_ray_net:
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
                sub_child[data] = self.custom_data[data] # type:ignore
            ET.dump(c.el)

    def read_yaml_properties(self, map: CommentedMap):
        ymap = YamlMap(map)
        self.executable = ymap.string('executable')
        self.arguments = ymap.string('arguments')
        self.pre_env = ymap.string('pre_env')
        self.name = ymap.string('name')
        self.desktop_file = ymap.string('desktop_file')
        self.label = ymap.string('label')
        self.description = ymap.string('description')
        self.icon = ymap.string('icon')
        self.in_terminal = ymap.bool('in_terminal')
        self.auto_start = ymap.bool('launched', True)
        self.check_last_save = ymap.bool('check_last_save', True)
        self.start_gui_hidden = not ymap.bool('gui_visible', True)
        self.template_origin = ymap.string('template_origin')

        self.jack_naming = ray.JackNaming(
            int(ymap.bool('long_jack_naming', True)))
        self.prefix_mode = ray.PrefixMode(
            ymap.string('prefix_mode', 'client_name'))

        # ensure client has a name
        if not self.name:
            self.name = Path(self.executable).name

        self.update_infos_from_desktop_file()

        ign_exts = ymap.string('ignored_extensions').split(' ')
        unign_exts = ymap.string('unignored_extensions').split(' ')

        global_exts = ray.GIT_IGNORED_EXTENSIONS.split(' ')
        self.ignored_extensions = ""

        for ext in global_exts:
            if ext and not ext in unign_exts:
                self.ignored_extensions += f' {ext}'

        for ext in ign_exts:
            if ext and not ext in global_exts:
                self.ignored_extensions += f' {ext}'

        self.last_open_duration = ymap.float('last_open_duration')

        if self.prefix_mode is ray.PrefixMode.CUSTOM:
            self.custom_prefix = ymap.string('custom_prefix')

        self.protocol = ray.Protocol.from_string(
            ymap.string('protocol', 'NSM'))

        if self.protocol is ray.Protocol.RAY_HACK:
            self.ray_hack.config_file = ymap.string('config_file')
            self.ray_hack.save_sig = ymap.int('save_signal')
            self.ray_hack.stop_sig = ymap.int(
                'stop_signal', signal.SIGTERM.value)
            self.ray_hack.wait_win = ymap.bool('wait_window')
            no_save_level = ymap.int('no_save_level')
            if 0 <= no_save_level <= 2:
                self.ray_hack.no_save_level = no_save_level

        if self.protocol is ray.Protocol.RAY_NET:
            self.ray_net.daemon_url = ymap.string('net_daemon_url')
            self.ray_net.session_root = ymap.string('net_daemon_url')
            self.ray_net.session_template = ymap.string(
                'net_session_template')

            # neeeded only to know if RAY_NET client is capable of switch
            self.executable = ray.RAYNET_BIN
            if self.ray_net.daemon_url and self.ray_net.session_root:
                self.arguments = self.get_ray_net_arguments_line()

        # template uses "client_id" for wanted client_id
        self.client_id = self.session.generate_client_id(
            ymap.string('client_id'))

        custom_data = map.get('custom_data')
        if isinstance(custom_data, CommentedMap):
            self.custom_data = custom_data.copy()

    def write_yaml_properties(self, map: CommentedMap, for_template=False):
        protocol = self.protocol
        internal_mode = ray.InternalMode.FOLLOW_PROTOCOL
        server = self.get_server()
        if server is not None:
            internal_mode = server.internal_mode
        if internal_mode is not ray.InternalMode.FOLLOW_PROTOCOL:
            protocol = self.protocol_orig

        # map.clear()
        if protocol is not ray.Protocol.NSM:
            map['protocol'] = self.protocol.to_string()
        
        if not self.is_ray_net:
            map['executable'] = self.executable
            if self.arguments:
                map['arguments'] = self.arguments

        if self.pre_env:
            map['pre_env'] = self.pre_env

        map['name'] = self.name
        if self.desktop_file:
            map['desktop_file'] = self.desktop_file
        if self.label != self._desktop_label:
            map['label'] = self.label
        if self.description != self._desktop_description:
            map['description'] = self.description
        if self.icon != self._desktop_icon:
            map['icon'] = self.icon
        if not self.check_last_save:
            map['check_last_save'] = False

        if self.prefix_mode is not ray.PrefixMode.CLIENT_NAME:
            map['prefix_mode'] = self.prefix_mode.name
            if self.prefix_mode is ray.PrefixMode.CUSTOM:
                map['custom_prefix'] = self.custom_prefix
        
        if self.can_optional_gui:
            map['gui_visible'] = not self.start_gui_hidden

        if self.jack_naming is not ray.JackNaming.LONG:
            map['long_jack_naming'] = False

        if self.in_terminal:
            map['in_terminal'] = True

        if not for_template and self.template_origin:
            map['template_origin'] = self.template_origin

        match protocol:
            case ray.Protocol.RAY_HACK:
                if self.ray_hack.config_file:
                    map['config_file'] = self.ray_hack.config_file
                if self.ray_hack.save_sig:
                    map['save_signal'] = self.ray_hack.save_sig
                if self.ray_hack.stop_sig != signal.SIGTERM.value:
                    map['stop_signal'] = self.ray_hack.stop_sig
                if self.ray_hack.wait_win:
                    map['wait_win'] = self.ray_hack.wait_win
                if self.ray_hack.no_save_level:
                    map['no_save_level'] = self.ray_hack.no_save_level

            case ray.Protocol.RAY_NET:
                map['net_daemon_url'] = self.ray_net.daemon_url
                map['net_session_root'] = self.ray_net.session_root
                map['net_session_template'] = self.ray_net.session_template

        if self.ignored_extensions != ray.GIT_IGNORED_EXTENSIONS:
            ignored = ' '.join(
                [c for c in self.ignored_extensions.split(' ')
                 if c and c not in ray.GIT_IGNORED_EXTENSIONS.split(' ')])
            unignored = ' '.join(
                [g for g in ray.GIT_IGNORED_EXTENSIONS.split(' ')
                 if g and g not in self.ignored_extensions.split(' ')])

            if ignored:
                map['ignored_extensions'] = ignored

            if unignored:
                map['unignored_extensions'] = unignored

        if not for_template and self.last_open_duration >= 5.0:
            map['last_open_duration'] = float(
                '%.3f' % self.last_open_duration)

        if self.custom_data:
            map['custom_data'] = self.custom_data

    def transform_from_proxy_to_hack(
            self, spath: Path, sess_name: str) -> bool:
        '''before to load a session, if a client has for executable_path
        'ray-proxy', transform it directly to RayHack client.
        'ray-proxy' is a very old tool, replaced with RayHack,
        and I don't want to maintain it anymore.
        
        spath: the session Path of the future session.
        sess_name: the future session name'''

        if self.executable != 'ray-proxy':
            return False
        
        match self.prefix_mode:
                
            case ray.PrefixMode.CLIENT_NAME:
                project_path = spath / f'{self.name}.{self.client_id}'
            case ray.PrefixMode.SESSION_NAME:
                project_path = spath / f'{sess_name}.{self.client_id}'
            case _:
                project_path = spath / f'{self.custom_prefix}.{self.client_id}'
        
        proxy_file = project_path / 'ray-proxy.xml'

        try:
            proxy_tree = ET.parse(proxy_file)
        except:
            _logger.warning(
                f'Failed to find {proxy_file} for client {self.client_id}')
            return False
        
        root = proxy_tree.getroot()
        if root.tag != 'RAY-PROXY':
            _logger.warning(f'wrong RAY-PROXY xml document: {proxy_file}')
            return False

        xroot = XmlElement(root)
        executable = xroot.string('executable')
        arguments = xroot.string('arguments')
        config_file = xroot.string('config_file')
        save_signal = xroot.int('save_signal')
        stop_signal = xroot.int('stop_signal')
        wait_window = xroot.bool('wait_window')
        no_save_level = xroot.int('no_save_level')
        
        if not executable:
            return False

        self.protocol = ray.Protocol.RAY_HACK
        self.executable = executable
        self.arguments = arguments
        self.ray_hack.config_file = config_file
        self.ray_hack.no_save_level = no_save_level
        if signal.Signals(save_signal):
            self.ray_hack.save_sig = save_signal
        if signal.Signals(stop_signal):
            self.ray_hack.stop_sig = stop_signal
        self.ray_hack.wait_win = wait_window
                
        if self.prefix_mode is ray.PrefixMode.CLIENT_NAME:
            self.prefix_mode = ray.PrefixMode.CUSTOM
            self.custom_prefix = self.name

        return True

    def set_reply(self, errcode: int, message: str):
        self._reply_message = message
        self._reply_errcode = errcode

        if self._reply_errcode:
            self.message(
                f'Client "{self.name}" replied with error: '
                f'{message} ({errcode})')

            if self.pending_command is ray.Command.SAVE:
                self._send_error_to_caller(
                    OscSrc.SAVE, ray.Err.GENERAL_ERROR,
                    _translate('GUIMSG', '%s failed to save!')
                        % self.gui_msg_style)
                
                self.session.send_monitor_event(
                    'save_error', self.client_id)

            elif self.pending_command is ray.Command.OPEN:
                self._send_error_to_caller(
                    OscSrc.OPEN, ray.Err.GENERAL_ERROR,
                    _translate('GUIMSG', '%s failed to open!')
                        % self.gui_msg_style)
                
                self.session.send_monitor_event(
                    'open_error', self.client_id)

            self.set_status(ray.ClientStatus.ERROR)
        else:
            if self.pending_command is ray.Command.SAVE:
                self.last_save_time = time.time()

                self.send_gui_message(
                    _translate('GUIMSG', '  %s: saved')
                        % self.gui_msg_style)

                self._send_reply_to_caller(OscSrc.SAVE, 'client saved.')
                self.session.send_monitor_event(
                    'saved', self.client_id)

            elif self.pending_command is ray.Command.OPEN:
                self.send_gui_message(
                    _translate('GUIMSG', '  %s: project loaded')
                        % self.gui_msg_style)

                self.last_open_duration = \
                    time.time() - self._last_open_time

                self._send_reply_to_caller(OscSrc.OPEN, 'client opened')

                self.session.send_monitor_event(
                    'ready', self.client_id)

                if self.has_server_option(ray.Option.GUI_STATES):
                    if (self.session.wait_for is ray.WaitFor.NONE
                            and self.can_optional_gui
                            and not self.start_gui_hidden
                            and not self.gui_visible
                            and not self.gui_has_been_visible):
                        self.send_to_self_address(nsm.client.SHOW_OPTIONAL_GUI)

            self.set_status(ray.ClientStatus.READY)

        if (self.scripter.is_running()
                and self.scripter.pending_command() is self.pending_command):
            return

        self.pending_command = ray.Command.NONE

        if self.session.wait_for is ray.WaitFor.REPLY:
            self.session.end_timer_if_last_expected(self)

    def set_label(self, label: str):
        self.label = label
        self.send_gui_client_properties()

    def has_error(self) -> bool:
        return bool(self._reply_errcode)

    def is_reply_pending(self) -> bool:
        return self.pending_command is not ray.Command.NONE

    def is_dumb_client(self) -> bool:
        if self.is_ray_hack:
            return False

        return bool(not self.did_announce)

    @property
    def can_monitor(self):
        return ':monitor:' in self.capabilities
    
    @property
    def can_patcher(self):
        return ':patcher:' in self.capabilities 
    
    @property
    def can_switch(self):
        return ':switch:' in self.capabilities
    
    @property
    def can_dirty(self):
        return ':dirty:' in self.capabilities
    
    @property
    def can_optional_gui(self):
        return ':optional-gui:' in self.capabilities

    @property
    def gui_msg_style(self) -> str:
        return f'{self.name} ({self.client_id})'

    def set_network_properties(
            self, net_daemon_url: str, net_session_root: str):
        if not self.is_ray_net:
            return

        self.ray_net.daemon_url = net_daemon_url
        self.ray_net.running_daemon_url = net_daemon_url
        self.ray_net.session_root = net_session_root
        self.ray_net.running_session_root = net_session_root
        self.send_gui_client_properties()

    def get_ray_net_arguments_line(self) -> str:
        if not self.is_ray_net:
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
            self.send_gui(rg.client.STATUS, self.client_id,
                          ray.ClientStatus.COPY.value)

    @property
    def prefix(self) -> str:
        match self.prefix_mode:
            case ray.PrefixMode.SESSION_NAME:
                return self.session.name
            case ray.PrefixMode.CLIENT_NAME:
                return self.name
            case ray.PrefixMode.CUSTOM:
                return self.custom_prefix
        return ''

    @property
    def project_path(self) -> Path:
        '''Absolute Path of client possible project.
        Raise NoSessionPath if client has no session path.'''
        if self.is_ray_net:
            return Path(self.session.short_path_name)

        spath = self.session.path
        if spath is None:
            raise NoSessionPath

        if self.prefix_mode is ray.PrefixMode.SESSION_NAME:
            return spath / f'{self.session.name}.{self.client_id}'

        if self.prefix_mode is ray.PrefixMode.CLIENT_NAME:
            return spath / f'{self.name}.{self.client_id}'

        if self.prefix_mode is ray.PrefixMode.CUSTOM:
            return spath / f'{self.custom_prefix}.{self.client_id}'

        # should not happens
        return spath / f'{self.session.name}.{self.client_id}'

    def set_default_git_ignored(self, executable=""):
        executable = executable if executable else self.executable
        executable = Path(executable).name

        match executable:
            case s if s.startswith(('ardour', 'Ardour')):
                if len(executable) == 6:
                    self.ignored_extensions += " .mid"
                elif len(executable) <= 8:
                    rest = executable[6:]
                    if rest.isdigit():
                        self.ignored_extensions += " .mid"
            case 'qtractor':
                self.ignored_extensions += " .mid"

            case 'luppp' | 'sooperlooper' | 'sooperlooper_nsm':
                if '.wav' in self.ignored_extensions:
                    self.ignored_extensions = \
                        self.ignored_extensions.replace('.wav', '')

            case 'samplv1_jack':
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

        if self.is_dummy:
            self._send_error_to_caller(OscSrc.START, ray.Err.GENERAL_ERROR,
                _translate('GUIMSG', "can't start %s, it is a dummy client !")
                    % self.gui_msg_style)
            return

        if (self.is_ray_net
                and self.session.path is not None
                and not self.session.root in self.session.path.parents):
            self._send_error_to_caller(OscSrc.START, ray.Err.GENERAL_ERROR,
                _translate(
                    'GUIMSG',
                    "Impossible to run Ray-Net client "
                    "when session is not in root folder"))
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
                              f"{self.client_id} {self.executable}")
                    for a in shlex.split(server.terminal_command)]

        if self.is_ray_net:
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
        ray_hack_pwd = None

        if self.is_ray_hack:
            env = os.environ.copy()
            env['RAY_SESSION_NAME'] = self.session.name
            env['RAY_CLIENT_ID'] = self.client_id
            env['RAY_JACK_CLIENT_NAME'] = self.jack_client_name
            env['CONFIG_FILE'] = expand_vars(env, self.ray_hack.config_file)
            env['PWD'] = str(self.project_path)
            
            ray_hack_pwd = self.project_path
            if ray_hack_pwd is None:
                _logger.error(
                    f"Ray-Hack client {self.client_id} can not have "
                    "project path, won't start")
                return

            env['PWD'] = str(ray_hack_pwd)
            
            arguments_line = expand_vars(env, self.arguments)

            if not ray_hack_pwd.exists():
                try:
                    ray_hack_pwd.mkdir(parents=True)
                except BaseException as e:
                    _logger.error(
                        f'Fail to create directory {ray_hack_pwd} '
                        f'for Ray-Hack client {self.client_id}.\n'
                        + str(e))
                    return

        if self.arguments:
            arguments += shlex.split(arguments_line)

        self.running_executable = self.executable
        self.running_arguments = self.arguments

        if self.is_ray_hack:
            self._process.setWorkingDirectory(str(ray_hack_pwd))
            process_env.insert('RAY_SESSION_NAME', self.session.name)
            process_env.insert('RAY_CLIENT_ID', self.client_id)
            self.send_gui_client_properties()

        self.launched_in_terminal = self.in_terminal
        if self.launched_in_terminal or self.executable in INTERNAL_EXECS:
            self.session.externals_timer.start()

        self.session.send_monitor_event(
            'start_request', self.client_id)

        self._process.setProcessEnvironment(process_env)
        prog, *other_args = terminal_args + [self.executable] + arguments
        
        internal_mode = ray.InternalMode.FOLLOW_PROTOCOL
        server = self.get_server()
        if server is not None:
            internal_mode = server.internal_mode

        if self.executable in INTERNAL_EXECS:
            self.protocol_orig = self.protocol

            if internal_mode is ray.InternalMode.FORCE_INTERNAL:
                self.protocol = ray.Protocol.INTERNAL
            elif internal_mode is ray.InternalMode.FORCE_NSM:
                self.protocol = ray.Protocol.NSM

            if self.protocol is ray.Protocol.INTERNAL:
                self._internal = InternalClient(
                    self.executable, tuple(arguments),
                    self.get_server_url())
                self._internal.start()
                self.session.externals_timer.start()
                
                self._process_started()
            else:
                self._process.start(prog, other_args)
        else:
            self._process.start(prog, other_args)

    def load(self, osp: Optional[OscPack]=None):
        if osp is not None:
            self._osc_srcs[OscSrc.OPEN] = osp

        if self.nsm_active:
            self._send_reply_to_caller(OscSrc.OPEN, 'client active')
            return

        if self.pending_command is ray.Command.STOP:
            self._send_error_to_caller(OscSrc.OPEN, ray.Err.GENERAL_ERROR,
                _translate('GUIMSG', '%s is exiting.') % self.gui_msg_style)

        if self.is_running and self.is_dumb_client():
            self._send_error_to_caller(
                OscSrc.OPEN, ray.Err.GENERAL_ERROR,
                _translate('GUIMSG', '%s seems to can not open')
                    % self.gui_msg_style)

        duration = max(8000, int(2 * self.last_open_duration))
        self._open_timer.setInterval(duration)
        self._open_timer.start()

        if self.pending_command is ray.Command.OPEN:
            return

        if not self.is_running:
            if self.executable in RS.non_active_clients:
                if osp is not None and osp.src_addr:
                    self._osc_srcs[OscSrc.START] = osp
                    self._osc_srcs[OscSrc.OPEN] = None

            self.start(osp, wait_open_to_reply=True)
            return

    def terminate(self):
        if self.is_running:
            if self.is_external:
                os.kill(self.pid, signal.SIGTERM)
            else:
                self._process.terminate()

    def kill(self):
        if (self.protocol is ray.Protocol.INTERNAL
                and self._internal is not None):
            self._internal.kill()
            return

        if self.is_external:
            os.kill(self.pid, signal.SIGKILL)
            return

        if self.is_running:
            self._process.kill()

    def send_signal(self, sig: int, src_addr=None, src_path=""):
        try:
            tru_sig = signal.Signals(sig)
        except:
            if src_addr:
                self.send(src_addr, osc_paths.ERROR, src_path,
                          ray.Err.GENERAL_ERROR, f'invalid signal {sig}')
            return

        if not self.is_running:
            if src_addr:
                self.send(src_addr, osc_paths.ERROR, src_path,
                          ray.Err.GENERAL_ERROR,
                          f'client {self.client_id} is not running')
            return

        os.kill(self.pid, sig)
        self.send(src_addr, osc_paths.REPLY, src_path, 'signal sent')

    @property
    def is_running(self) -> bool:
        if self.is_external:
            return True
        
        if self._internal is not None:
            return self._internal.running
        
        return self._process.state() == QProcess.ProcessState.Running

    def external_finished(self):
        self._process_finished(0, 0) # type:ignore

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
            error_text = \
                f'script {self.scripter.get_path()} ended with an error code'
            match scripter_pending_command:
                case ray.Command.SAVE:
                    self._send_error_to_caller(
                        OscSrc.SAVE, - exit_code, error_text)
                case ray.Command.START:
                    self._send_error_to_caller(
                        OscSrc.START, - exit_code, error_text)
                case ray.Command.STOP:
                    self._send_error_to_caller(
                        OscSrc.STOP, - exit_code, error_text)
        else:
            match scripter_pending_command:
                case ray.Command.SAVE:
                    self._send_reply_to_caller(OscSrc.SAVE, 'saved')
                case ray.Command.START:
                    self._send_reply_to_caller(OscSrc.START, 'started')
                case ray.Command.STOP:
                    self._send_reply_to_caller(OscSrc.STOP, 'stopped')

        if scripter_pending_command is self.pending_command:
            self.pending_command = ray.Command.NONE

        if scripter_pending_command is ray.Command.STOP and self.is_running:
            # if stop script ends with a not stopped client
            # We must stop it, else it would prevent session close
            self.stop()

        if self.session.wait_for is not ray.WaitFor.NONE:
            self.session.end_timer_if_last_expected(self)

    def ray_hack_ready(self):
        self.send_gui_message(
            _translate('GUIMSG', '  %s: project probably loaded')
                % self.gui_msg_style)

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
            self.send_to_self_address(nsm.client.SESSION_IS_LOADED)

    def can_save_now(self):
        if self.is_ray_hack:
            if not self.ray_hack.saveable():
                return False

            return bool(self.is_running
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

        if self.is_running:
            if self.scripter.start(ray.Command.SAVE, osp,
                                   self._osc_srcs.get(OscSrc.SAVE)):
                self.set_status(ray.ClientStatus.SCRIPT)
                return

        if self.pending_command is ray.Command.SAVE:
            self._send_error_to_caller(OscSrc.SAVE, ray.Err.GENERAL_ERROR,
                _translate('GUIMSG', '%s is already saving, please wait!')
                    % self.gui_msg_style)

        if self.is_running:
            self.session.send_monitor_event(
                'save_request', self.client_id)

            if self.is_ray_hack:
                self.pending_command = ray.Command.SAVE
                self.set_status(ray.ClientStatus.SAVE)
                if self.ray_hack.save_sig > 0:
                    os.kill(self._process.processId(), self.ray_hack.save_sig)
                QTimer.singleShot(300, self._ray_hack_saved)

            elif self.can_save_now():
                self.message(f'Telling {self.client_id} to save')
                self.send_to_self_address(nsm.client.SAVE)

                self.pending_command = ray.Command.SAVE
                self.set_status(ray.ClientStatus.SAVE)

            elif self.is_dumb_client():
                self.set_status(ray.ClientStatus.NOOP)

            if self.can_optional_gui:
                self.start_gui_hidden = not bool(self.gui_visible)

    def stop(self, osp: OscPack | None =None):
        if self.switch_state is ray.SwitchState.NEEDED:
            if osp is not None:
                self.send(*osp.error(), ray.Err.NOT_NOW,
                "Stop cancelled because client is needed for opening session")
            return

        if osp is not None:
            self._osc_srcs[OscSrc.STOP] = osp

        self.send_gui_message(
            _translate('GUIMSG', "  %s: stopping") % self.gui_msg_style)

        if self.is_running:
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

            if (self.protocol is ray.Protocol.NSM
                    and self.launched_in_terminal
                    and self.pid_from_nsm):
                try:
                    os.kill(self.pid_from_nsm, signal.SIGTERM)
                except ProcessLookupError:
                    self.pid_from_nsm = 0
                except:
                    self.pid_from_nsm = 0

            if self._internal is not None:
                self._internal.stop()
            elif self.is_external:
                os.kill(self.pid, signal.SIGTERM)
            elif (self.is_ray_hack
                    and self.ray_hack.stop_sig != signal.SIGTERM.value):
                os.kill(self._process.processId(), self.ray_hack.stop_sig)
            else:
                self._process.terminate()
        else:
            self._send_reply_to_caller(OscSrc.STOP, 'client stopped.')

    def quit(self):
        self.message(f'Commanding {self.name} to quit')
        if self.is_running:
            self.pending_command = ray.Command.STOP
            self.terminate()
            self.set_status(ray.ClientStatus.QUIT)
        else:
            self.send_gui(rg.client.STATUS, self.client_id,
                          ray.ClientStatus.REMOVED)

    def eat_attributes(self, new_client: 'Client'):
        #self.client_id = new_client.client_id
        self.executable = new_client.executable
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
        project_path = self.project_path
        self.send_gui_client_properties()
        self.message(
            f'Commanding {self.name} to switch "{project_path}"')

        self._last_open_time = time.time()

        self.send_to_self_address(
            nsm.client.OPEN, str(project_path),
            self.session.name, self.jack_client_name)

        self.pending_command = ray.Command.OPEN
        
        self.set_status(ray.ClientStatus.SWITCH)
        if self.can_optional_gui:
            self.send_gui(rg.client.GUI_VISIBLE,
                          self.client_id, int(self.gui_visible))

    def can_switch_with(self, other_client: 'Client') -> bool:
        if self.protocol is ray.Protocol.RAY_HACK:
            return False

        if self.protocol is not other_client.protocol:
            return False

        if not ((self.nsm_active and self.can_switch)
                or (self.is_dumb_client() and self.is_running)):
            return False

        if self.is_ray_net:
            return bool(self.ray_net.running_daemon_url
                            == other_client.ray_net.daemon_url
                        and self.ray_net.running_session_root
                            == other_client.ray_net.session_root)

        return bool(self.running_executable == other_client.executable
                    and self.running_arguments == other_client.arguments)

    def send_gui_client_properties(self, removed=False):
        ad = rg.client.UPDATE if self.sent_to_gui else rg.client.NEW
        hack_ad = rg.client.RAY_HACK_UPDATE
        net_ad = rg.client.RAY_NET_UPDATE

        if removed:
            ad = rg.trash.ADD
            hack_ad = rg.trash.RAY_HACK_UPDATE
            net_ad = rg.trash.RAY_NET_UPDATE

        self.send_gui(ad, *ray.ClientData.spread_client(self))

        if self.is_ray_hack:
            self.send_gui(
                hack_ad, self.client_id, *self.ray_hack.spread())

        elif self.is_ray_net:
            self.send_gui(
                net_ad, self.client_id, *self.ray_net.spread())

        self.sent_to_gui = True

    def set_properties_from_message(self, message:str):
        for line in message.splitlines():
            prop, colon, value = line.partition(':')

            match prop:
                case 'client_id':
                    # do not change client_id !!!
                    continue
                case 'executable':
                    self.executable = value
                case 'environment':
                    self.pre_env = value
                case 'arguments':
                    self.arguments = value
                case 'name':
                    # do not change client name,
                    # It will be re-sent by client itself
                    continue
                case 'prefix_mode':
                    if value.isdigit():
                        self.prefix_mode = ray.PrefixMode(int(value))
                case 'custom_prefix':
                    self.custom_prefix = value
                case 'jack_naming':
                    if value.isdigit():
                        self.jack_naming = ray.JackNaming(int(value))
                case 'jack_name':
                    # do not change jack name
                    # only allow to change jack_naming
                    continue
                case 'label':
                    self.label = value
                case 'desktop_file':
                    self.desktop_file = value
                case 'description':
                    # description could contains many lines
                    continue
                case 'icon':
                    self.icon = value
                case 'capabilities':
                    # do not change capabilities, no sense !
                    continue
                case 'check_last_save':
                    if value.isdigit():
                        self.check_last_save = bool(int(value))
                case 'ignored_extensions':
                    self.ignored_extensions = value
                case 'protocol':
                    # do not change protocol value
                    continue

            if self.is_ray_hack:
                match prop:
                    case 'config_file':
                        self.ray_hack.config_file = value
                    case 'save_sig':
                        try:
                            sig = signal.Signals(int(value))
                        except ValueError:
                            continue
                        self.ray_hack.save_sig = int(value)
                    case 'stop_sig':
                        try:
                            sig = signal.Signals(int(value))
                        except ValueError:
                            continue
                        self.ray_hack.stop_sig = int(value)
                    case 'wait_win':
                        self.ray_hack.wait_win = bool(
                            value.lower() in ('1', 'true'))
                    case 'no_save_level':
                        if value.isdigit() and 0 <= int(value) <= 2:
                            self.ray_hack.no_save_level = int(value)

            elif self.is_ray_net:
                match prop:
                    case 'net_daemon_url':
                        self.ray_net.daemon_url = value
                    case 'net_session_root':
                        self.ray_net.session_root = value
                    case 'net_session_template':
                        self.ray_net.session_template = value

        self.send_gui_client_properties()

    def get_properties_message(self) -> str:
        message = (
            f'client_id:{self.client_id}\n'
            f'protocol:{self.protocol.to_string()}\n'
            f'executable:{self.executable}\n'
            f'environment:{self.pre_env}\n'
            f'arguments:{self.arguments}\n'
            f'name:{self.name}\n'
            f'prefix_mode:{self.prefix_mode.value}\n'
            f'custom_prefix:{self.custom_prefix}\n'
            f'jack_naming:{self.jack_naming.value}\n'
            f'jack_name:{self.jack_client_name}\n'
            f'desktop_file:{self.desktop_file}\n'
            f'label:{self.label}\n'
            f'icon:{self.icon}\n'
            f'check_last_save:{int(self.check_last_save)}\n'
            f'ignored_extensions:{self.ignored_extensions}'
        )

        match self.protocol:
            case ray.Protocol.NSM | ray.Protocol.INTERNAL:
                message += f'\ncapabilities:{self.capabilities}'

            case ray.Protocol.RAY_HACK:
                message += (
                    '\n'
                    f'config_file:{self.ray_hack.config_file}\n'
                    f'save_sig:{self.ray_hack.save_sig}\n'
                    f'stop_sig:{self.ray_hack.stop_sig}\n'
                    f'wait_win:{int(self.ray_hack.wait_win)}\n'
                    f'no_save_level:{self.ray_hack.no_save_level}'
                )

            case ray.Protocol.RAY_NET:
                message += (
                    '\n'
                    f'net_daemon_url:{self.ray_net.daemon_url}\n'
                    f'net_session_root:{self.ray_net.session_root}\n'
                    f'net_session_template:{self.ray_net.session_template}'
                )

        return message

    def relevant_no_save_level(self) -> int:
        '''return no_save_level (1 or 2) only if it uses RayHack protocol
        and if it takes sense, else 0'''
        if self.is_ray_hack:
            return self.ray_hack.relevant_no_save_level()

        return 0

    @property
    def project_files(self) -> list[Path]:
        '''list of client project files or directories currently existing'''
        spath = self.session.path
        if spath is None:
            return []

        client_files = list[Path]()
        project_path = self.project_path

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

        full_links_dir = spath / self.links_dirname
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
            desktop_file = exec_and_desktops.get(self.executable)

        if not desktop_file:
            desktop_file = os.path.basename(self.executable)

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
            full_exec = shutil.which(self.executable)

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
                            if (self.executable in value.split()
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

    def change_prefix(self, prefix_mode: ray.PrefixMode, custom_prefix: str):
        if self.is_running:
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

        links_dir = self.links_dirname

        if self.session.path is None:
            _logger.warning(
                f'Attempting to change prefix of client {self.client_id} '
                'while there is no session path')
            return

        self._rename_files(
            self.session.path,
            self.session.name, self.session.name,
            old_prefix, new_prefix,
            self.client_id, self.client_id,
            links_dir, links_dir)

        self.prefix_mode = ray.PrefixMode(prefix_mode)
        self.custom_prefix = custom_prefix
        self.send_gui_client_properties()

    def adjust_files_after_copy(
            self, new_session_full_name: str,
            template_save=ray.Template.NONE):
        client_tools.adjust_files_after_copy(
            self, new_session_full_name, template_save)

    def server_announce(self, osp: OscPack, is_new: bool):
        client_name, capabilities, executable_path, \
            major, minor, pid = osp.args # type:ignore

        client_name: str
        capabilities: str
        executable_path: str
        major: int
        minor: int
        pid: int

        _logger.debug(
            f'Client server announce "{client_name}" {executable_path} {pid}')

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

        if self.executable in RS.non_active_clients:
            RS.non_active_clients.remove(self.executable)

        if self.protocol is ray.Protocol.NSM:
            self.message( 
                f"'{self.client_id}' has announced itself "
                f"(name: {client_name}, port: {self.addr.port}, pid: {pid})")

        server = self.get_server()
        if not server:
            return

        self.send_gui_message(
            _translate('GUIMSG', "  %s: announced") % self.gui_msg_style)

        # if this daemon is under another NSM session
        # do not enable server-control
        # because new, open and duplicate are forbidden
        server_capabilities = ""
        if not server.is_nsm_locked:
            server_capabilities += ":server-control"
        server_capabilities += ":broadcast:optional-gui:monitor:"

        self.send(*osp.reply(),
                  "Well hello, stranger. Welcome to the party."
                  if is_new else "Howdy, what took you so long?",
                  ray.APP_TITLE,
                  server_capabilities)

        client_project_path = str(self.project_path)
        if self.is_ray_net:
            client_project_path = self.session.short_path_name

        self.send_gui_client_properties()
        self.set_status(ray.ClientStatus.OPEN)

        if self.can_patcher:
            self.send(self.addr, nsm.client.PATCH_KEYWORD,
                      server.patcher_keyword)
        if self.can_monitor:
            self.session.send_initial_monitor(self.addr)
        self.session.send_monitor_client_update(self)

        self.send(osp.src_addr, nsm.client.OPEN, client_project_path,
                  self.session.name, self.jack_client_name)

        self.pending_command = ray.Command.OPEN

        self._last_open_time = time.time()
