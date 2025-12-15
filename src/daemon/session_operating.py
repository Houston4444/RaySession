
# Imports from standard library
import functools
from io import TextIOWrapper
import logging
import math
import os
import shutil
import subprocess
import time
from typing import Callable, Any, Optional
from pathlib import Path
import xml.etree.ElementTree as ET

# third party imports
from qtpy.QtCore import QCoreApplication, QTimer

# Imports from src/shared
from osclib import Address, MegaSend, is_valid_osc_url
from osclib.bases import OscPack
import ray
from xml_tools import XmlElement
import osc_paths
import osc_paths.ray as r
import osc_paths.ray.gui as rg
import osc_paths.nsm as nsm

# Local imports
import multi_daemon_file
from client import Client
from daemon_tools import (
    NoSessionPath, TemplateRoots, RS, Terminal, highlight_text)
import ardour_templates
from patch_rewriter import rewrite_jack_patch_files
import patchbay_dmn_mng
from session import Session
import session_op as sop
from snapshoter import Snapshoter
from file_copier import FileCopier
from scripter import StepScripter
from canvas_saver import CanvasSaver


_logger = logging.getLogger(__name__)
_translate = QCoreApplication.translate


class OperatingSession(Session):
    def __init__(self, root: Path, session_id=0):
        Session.__init__(self, root, session_id)
        self.wait_for = ray.WaitFor.NONE

        self.file_copier = FileCopier(self)
        self.step_scripter = StepScripter(self)
        self.canvas_saver = CanvasSaver(self)
        self.snapshoter = Snapshoter(self)

        self.timer = QTimer()
        self.timer_redondant = False
        self.expected_clients = list[Client]()

        self.timer_launch = QTimer()
        self.timer_launch.setInterval(100)
        self.timer_launch.timeout.connect(self._timer_launch_timeout)
        self.clients_to_launch = list[Client]()

        self.timer_quit = QTimer()
        self.timer_quit.setInterval(100)
        self.timer_quit.timeout.connect(self._timer_quit_timeout)
        self.clients_to_quit = list[Client]()

        self.timer_waituser_progress = QTimer()
        self.timer_waituser_progress.setInterval(500)
        self.timer_waituser_progress.timeout.connect(
            self._timer_wait_user_progress_timeout)
        self.timer_wu_progress_n = 0

        self.steps_osp: Optional[OscPack] = None
        'Stock the OscPack of the long operation running (if any).'

        self.steps_order = list[sop.SessionOp | Callable | tuple[Callable | Any, ...]]()

        self.terminated_yet = False

        # externals are clients not launched from the daemon
        # but with NSM_URL=...
        self.externals_timer = QTimer()
        self.externals_timer.setInterval(100)
        self.externals_timer.timeout.connect(self._check_externals_states)

        self.window_waiter = QTimer()
        self.window_waiter.setInterval(200)
        self.window_waiter.timeout.connect(self._check_windows_appears)

        self.run_step_addr = None

        self.switching_session = False

    def _wait_and_go_to(
            self, duration: int,
            follow: tuple[Callable, Any] | list[Callable] | Callable,
            wait_for: ray.WaitFor, redondant=False):
        self.timer.stop()

        # we need to delete timer to change the timeout connect
        del self.timer
        self.timer = QTimer()

        if isinstance(follow, (list, tuple)):
            if len(follow) == 0:
                return

            if len(follow) == 1:
                follow = follow[0]
            else:
                follow = functools.partial(follow[0], *follow[1:])

        # follow: Callable

        if wait_for in (ray.WaitFor.SCRIPT_QUIT,
                        ray.WaitFor.PATCHBAY_QUIT,
                        ray.WaitFor.SNAPSHOT_ADD,
                        ray.WaitFor.FILE_COPY):
            match wait_for:
                case ray.WaitFor.SCRIPT_QUIT:
                    if not self.step_scripter.is_running():
                        follow()
                        return
                case ray.WaitFor.PATCHBAY_QUIT:
                    if not patchbay_dmn_mng.is_running():
                        follow()
                        return
                case ray.WaitFor.SNAPSHOT_ADD:
                    if not self.snapshoter.adder_running:
                        follow()
                        return
                case ray.WaitFor.FILE_COPY:
                    if not self.file_copier.is_active():
                        follow()
                        return

            self.wait_for = wait_for
            self.timer.setSingleShot(True)
            self.timer.timeout.connect(follow)
            if duration >= 0:
                self.timer.start(duration)
            return

        if self.expected_clients:
            n_expected = len(self.expected_clients)

            if wait_for is ray.WaitFor.ANNOUNCE:
                if n_expected == 1:
                    message = _translate('GUIMSG',
                        'waiting announce from %s...'
                            % self.expected_clients[0].gui_msg_style)
                else:
                    message = _translate('GUIMSG',
                        'waiting announce from %i clients...' % n_expected)
                self.send_gui_message(message)
            elif wait_for is ray.WaitFor.QUIT:
                if n_expected == 1:
                    message = _translate('GUIMSG',
                        'waiting for %s to stop...'
                            % self.expected_clients[0].gui_msg_style)
                else:
                    message = _translate('GUIMSG',
                        'waiting for %i clients to stop...' % n_expected)
                self.send_gui_message(message)

            self.timer_redondant = redondant

            self.wait_for = wait_for
            self.timer.setSingleShot(True)
            self.timer.timeout.connect(follow)
            if duration >= 0:
                self.timer.start(duration)
        else:
            follow()

    def end_timer_if_last_expected(self, client: Client):
        if self.wait_for is ray.WaitFor.QUIT and client in self.clients:
            self._remove_client(client)

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

    def _clean_expected(self):
        if self.expected_clients:
            client_names = [c.gui_msg_style for c in self.expected_clients]

            match self.wait_for:
                case ray.WaitFor.ANNOUNCE:
                    self.send_gui_message(
                        _translate('GUIMSG', "%s didn't announce.")
                        % ', '.join(client_names))

                case ray.WaitFor.QUIT:
                    self.send_gui_message(
                        _translate('GUIMSG', "%s still alive !")
                        % ', '.join(client_names))

            self.expected_clients.clear()

        self.wait_for = ray.WaitFor.NONE

    def next_function(self, from_run_step=False, run_step_args=[]):
        if self.run_step_addr and not from_run_step:
            self.send(self.run_step_addr, osc_paths.REPLY,
                      r.session.RUN_STEP, 'step done')
            self.run_step_addr = None
            return

        if not self.steps_order:
            return

        next_item = self.steps_order[0]
        next_function = next_item
        arguments = []

        if isinstance(next_item, (tuple, list)):
            if not next_item:
                return

            next_function = next_item[0]
            if len(next_item) > 1:
                arguments = next_item[1:]

        elif isinstance(next_item, sop.SessionOp):
            next_function = next_item.start

        if (self.has_server_option(ray.Option.SESSION_SCRIPTS)
                and not self.step_scripter.is_running()
                and self.path is not None
                and not from_run_step):
            if isinstance(next_function, sop.SessionOp):
                if not (isinstance(next_function, sop.Load)
                        and next_function.open_off):
                    if (next_function.script_step
                            and self.steps_osp is not None
                            and self.step_scripter.start(
                                next_function.script_step, arguments,
                                self.steps_osp.src_addr,
                                self.steps_osp.path)):
                        self.set_server_status(ray.ServerStatus.SCRIPT)
                        return

        if (from_run_step and next_function
                and self.step_scripter.is_running()):
            if isinstance(next_function, sop.SessionOp):
                if next_function.script_step == self.step_scripter.get_step():
                    self.step_scripter.set_stepper_has_call(True)
                next_function.start_from_script(run_step_args)

        self.steps_order.__delitem__(0)
        _logger.debug(
            f'next_function: {next_function.__name__}')  # type: ignore
        next_function(*arguments) # type: ignore

    def _timer_launch_timeout(self):
        if self.clients_to_launch:
            self.clients_to_launch[0].start()
            self.clients_to_launch.__delitem__(0)

        if not self.clients_to_launch:
            self.timer_launch.stop()

    def _timer_quit_timeout(self):
        if self.clients_to_quit:
            client_quitting = self.clients_to_quit.pop(0)
            client_quitting.stop()

        if not self.clients_to_quit:
            self.timer_quit.stop()

    def _timer_wait_user_progress_timeout(self):
        if not self.expected_clients:
            self.timer_waituser_progress.stop()

        self.timer_wu_progress_n += 1

        ratio = float(self.timer_wu_progress_n / 240)
        self.send_gui(rg.server.PROGRESS, ratio)

    def _check_externals_states(self):
        '''check if clients started from external are still alive
        or if clients launched in terminal have still their process active'''
        has_alives = False

        # execute client.external_finished will remove the client
        # from self.clients, so we need to collect them first
        # and execute this after to avoid item remove during iteration
        clients_to_finish = list[Client]()

        for client in self.clients:
            if client.is_external:
                has_alives = True
                if not os.path.exists('/proc/%i' % client.pid):
                    clients_to_finish.append(client)
            
            elif client._internal is not None:
                if client._internal.running:
                    has_alives = True
                elif client.status is not ray.ClientStatus.STOPPED:
                    clients_to_finish.append(client)

            elif (client.is_running
                    and client.launched_in_terminal
                    and client.status is not ray.ClientStatus.LOSE):
                has_alives = True
                if (client.nsm_active
                        and not os.path.exists('/proc/%i' % client.pid_from_nsm)):
                    client.nsm_finished_terminal_alive()

        for client in clients_to_finish:
            client.external_finished()

        if not has_alives:
            self.externals_timer.stop()

    def _check_windows_appears(self):
        for client in self.clients:
            if client.is_running and client.ray_hack_waiting_win:
                break
        else:
            self.window_waiter.stop()
            return

        if self.has_server_option(ray.Option.HAS_WMCTRL):
            self.desktops_memory.set_active_window_list()
            for client in self.clients:
                if client.ray_hack_waiting_win:
                    if self.desktops_memory.has_window(client.pid):
                        client.ray_hack_waiting_win = False
                        client.ray_hack_ready()

    def patchbay_process_finished(self):
        if self.wait_for is ray.WaitFor.PATCHBAY_QUIT:
            self.timer.setSingleShot(True)
            self.timer.stop()
            self.timer.start(0)

    def snapshoter_add_finished(self):
        '`git add .` snapshoter command is finished'
        if self.wait_for is not ray.WaitFor.SNAPSHOT_ADD:
            _logger.warning(
                'git add command ended while nothing is waiting for it')
            return
        
        self.wait_for = ray.WaitFor.NONE        
        self.timer.setSingleShot(True)
        self.timer.stop()
        self.timer.start(0)

    def files_copy_finished(self):
        print('gile copy finsihed', self.wait_for)
        if self.wait_for is ray.WaitFor.FILE_COPY:
            self.wait_for = ray.WaitFor.NONE
            self.timer.setSingleShot(True)
            self.timer.stop()
            self.timer.start(0)

    def _send_reply(self, *args: str):
        if self.steps_osp is None:
            return
        
        self.send_even_dummy(*self.steps_osp.reply(), *args)
        
    def _send_error(self, err: ray.Err, error_message: str):
        # clear process order to allow other new operations
        self.steps_order.clear()

        if self.run_step_addr:
            if err is ray.Err.OK:
                self.send(self.run_step_addr, osc_paths.REPLY,
                          r.session.RUN_STEP, error_message)
            else:
                self.send(self.run_step_addr, osc_paths.ERROR,
                          r.session.RUN_STEP, err, error_message)
            
        if self.steps_osp is None:
            return
        
        self.send_even_dummy(*self.steps_osp.error(), err, error_message)

    def _send_minor_error(self, err: ray.Err, error_message: str):
        if self.steps_osp is None:
            return
        
        self.send_even_dummy(*self.steps_osp.error(), err, error_message)

    def step_scripter_finished(self):
        if self.wait_for is ray.WaitFor.SCRIPT_QUIT:
            self.timer.setSingleShot(True)
            self.timer.stop()
            self.timer.start(0)
            return

        if not self.step_scripter.stepper_has_called():
            # script has not call
            # the next_function (save, close, load)
            if self.step_scripter.get_step() in ('load', 'close'):
                self.steps_order.clear()
                self.steps_order = [
                    sop.Close(self, clear_all_clients=True),
                    self.abort_done]

                # Fake the next_function to come from run_step message
                # This way, we are sure the close step
                # is not runned with a script.
                self.next_function(True)
                return

            if self.steps_order:
                self.steps_order.__delitem__(0)

        self.next_function()

    def _new_client(self, executable: str, client_id=None) -> Client:
        client = Client(self)
        client.executable = executable
        client.name = Path(executable).name
        client.client_id = client_id
        if not client_id:
            client.client_id = self.generate_client_id(executable)

        self.clients.append(client)
        return client

    def adjust_files_after_copy(
            self, new_session_full_name: str, template_mode: ray.Template):
        new_session_short_path = Path(new_session_full_name)
        
        if new_session_short_path.is_absolute():
            spath = new_session_short_path
        else:
            spath = self.root / new_session_short_path

        # create tmp clients from raysession.xml to adjust files after copy
        session_file = spath / 'raysession.xml'

        try:
            tree = ET.parse(session_file)
        except Exception as e:
            _logger.error(str(e))
            self._send_error(
                ray.Err.BAD_PROJECT,
                _translate("error", "impossible to read %s as a XML file")
                    % session_file)
            return
        
        root = tree.getroot()
        if root.tag != 'RAYSESSION':
            self.load_error(ray.Err.BAD_PROJECT)
            return
        
        root.attrib['name'] = spath.name

        tmp_clients = list[Client]()
        
        for child in root:
            if not child.tag in ('Clients', 'RemovedClients'):
                continue

            for client_xml in child:
                client = Client(self)
                client.read_xml_properties(XmlElement(client_xml))
                if not client.executable:
                    continue
            
                tmp_clients.append(client)

        try:
            tree.write(session_file)
        except BaseException as e:
            _logger.error(str(e))
            self._send_error(
                ray.Err.CREATE_FAILED,
                _translate("error", "impossible to write XML file %s")
                    % session_file)
            return

        for client in tmp_clients:
            client.adjust_files_after_copy(new_session_full_name, template_mode)

    ############################## COMPLEX OPERATIONS ###################
    # All functions are splitted when we need to wait clients
    # for something (announce, reply, quit).
    # For example, at the end of save(), timer is launched,
    # then, when timer is timeout or when all client replied,
    # save_substep1 is launched.

    def save_done(self):
        self.message("Done.")
        self._send_reply("Saved.")
        self.set_server_status(ray.ServerStatus.READY)

    def save_error(self, err_saving: ray.Err):
        self.message("Failed")
        m = _translate('Load Error', "Unknown error")

        if err_saving == ray.Err.CREATE_FAILED:
            m = _translate(
                'GUIMSG', "Can't save session, session file is unwriteable !")

        self.message(m)
        self.send_gui_message(m)
        self._send_error(ray.Err.CREATE_FAILED, m)

        self.set_server_status(ray.ServerStatus.READY)
        self.steps_order.clear()
        self.steps_osp = None

    def snapshot_done(self):
        self.set_server_status(ray.ServerStatus.READY)
        self._send_reply("Snapshot taken.")

    def close_done(self):
        self.canvas_saver.unload_session()
        self._clean_expected()
        self.clients.clear()
        self._set_path(None)
        self.send_gui(rg.session.NAME, '', '')
        self.send_gui(rg.session.NOTES, '')
        self.send_gui(rg.session.NOTES_HIDDEN)
        self._no_future()
        self._send_reply("Closed.")
        self.message("Done")
        self.set_server_status(ray.ServerStatus.OFF)
        self.steps_osp = None

    def abort_done(self):
        self._clean_expected()
        self.clients.clear()
        self._set_path(None)
        self.send_gui(rg.session.NAME, '', '')
        self.send_gui(rg.session.NOTES, '')
        self.send_gui(rg.session.NOTES_HIDDEN)
        self._no_future()
        self._send_reply("Aborted.")
        self.message("Done")
        self.set_server_status(ray.ServerStatus.OFF)
        self.steps_osp = None

    def new_done(self):
        self.send_gui_message(_translate('GUIMSG', 'Session is ready'))
        self._send_reply("Created.")
        self.set_server_status(ray.ServerStatus.READY)
        self.steps_osp = None

    def duplicate_aborted(self, new_session_full_name: str):
        self.steps_order.clear()

        # unlock the directory of the aborted session
        multi_daemon_file.unlock_path(self.root / new_session_full_name)

        if self.steps_osp is not None:
            if self.steps_osp.path == nsm.server.DUPLICATE:
                # for nsm server control API compatibility
                # abort duplication is not possible in Non/New NSM
                # so, send the only known error
                self._send_error(ray.Err.NO_SUCH_FILE, "No such file.")

            self.send(self.steps_osp.src_addr, r.net_daemon.DUPLICATE_STATE, 1.0)

        self.set_server_status(ray.ServerStatus.READY)
        self.steps_osp = None

    def rename_done(self, new_session_name: str):
        self.send_gui_message(
            _translate('GUIMSG', 'Session %s has been renamed to %s .')
            % (self.name, new_session_name))
        self._send_reply(
            f"Session '{self.name}' has been renamed '"
            f"to '{new_session_name}'.")
        self.steps_osp = None

    def load_done(self):
        self._send_reply("Loaded.")
        self.message("Done")
        self.set_server_status(ray.ServerStatus.READY)
        self.steps_osp = None

    def load_error(self, err_loading: ray.Err):
        self.message("Failed")
        m = _translate('Load Error', "Unknown error")
        match err_loading:
            case ray.Err.CREATE_FAILED:
                m = _translate('Load Error', "Could not create session file!")
            case ray.Err.SESSION_LOCKED:
                m = _translate(
                    'Load Error', "Session is locked by another process!")
            case ray.Err.NO_SUCH_FILE:
                m = _translate(
                    'Load Error', "The named session does not exist.")
            case ray.Err.BAD_PROJECT:
                m = _translate('Load Error', "Could not load session file.")
            case ray.Err.SESSION_IN_SESSION_DIR:
                m = _translate(
                    'Load Error',
                    "Can't create session in a dir containing a session\n"
                    + "for better organization.")

        self._send_error(err_loading, m)

        if self.path:
            self.set_server_status(ray.ServerStatus.READY)
        else:
            self.set_server_status(ray.ServerStatus.OFF)

        self.steps_order.clear()

    def duplicate_only_done(self):
        if self.steps_osp is None:
            _logger.warning(
                'Impossible to reply duplicate_only_done '
                'because OscPack is None')
            return

        self.send(self.steps_osp.src_addr, r.net_daemon.DUPLICATE_STATE, 1)
        self._send_reply("Duplicated only done.")
        self.steps_osp = None

    def duplicate_done(self):
        self.message("Done")
        self._send_reply("Duplicated.")
        self.set_server_status(ray.ServerStatus.READY)
        self.steps_osp = None

    def save_client_and_patchers(self, client: Client):
        for oth_client in self.clients:
            if (oth_client is client or 
                    (oth_client.is_running and oth_client.can_patcher)):
                self.expected_clients.append(oth_client)
                oth_client.save()
        
        self._wait_and_go_to(10000, self.next_function, ray.WaitFor.REPLY)

    def rename_full_client(
            self, client: Client, new_name: str, new_client_id: str):
        if self.path is None:
            _logger.error('Impossible to rename full client, no path !!!')
            return
        
        tmp_client = Client(self)
        tmp_client.eat_attributes(client)
        tmp_client.client_id = new_client_id
        tmp_client.jack_naming = ray.JackNaming.LONG
        
        client.set_status(ray.ClientStatus.REMOVED)
        
        client._rename_files(
            self.path,
            self.name, self.name,
            client.prefix, tmp_client.prefix,
            client.client_id, tmp_client.client_id,
            client.links_dirname, tmp_client.links_dirname)

        ex_jack_name = client.jack_client_name
        ex_client_id = client.client_id
        new_jack_name = tmp_client.jack_client_name

        client.client_id = new_client_id
        client.jack_naming = ray.JackNaming.LONG
        client.label = new_name
        self._update_forbidden_ids_set()

        if new_jack_name != ex_jack_name:
            rewrite_jack_patch_files(
                self, ex_client_id, new_client_id,
                ex_jack_name, new_jack_name)
            self.canvas_saver.client_jack_name_changed(
                ex_jack_name, new_jack_name)

        client.sent_to_gui = False
        client.send_gui_client_properties()
        self.send_gui(rg.session.SORT_CLIENTS,
                      *[c.client_id for c in self.clients])

        # we need to save session file here
        # else, if session is aborted
        # client won't find its files at next restart
        self._save_session_file()

        self.send_monitor_event('id_changed_to:' + new_client_id, ex_client_id)
        self.next_function()
        
    def rename_full_client_done(self, client: Client):
        self.message("Done")
        self._send_reply("full client rename done.")
        self.set_server_status(ray.ServerStatus.READY)
        self.steps_osp = None

    def restart_client(self, client: Client):
        client.start()
        self._wait_and_go_to(0, (self.next_function, client), ray.WaitFor.NONE)

    def before_close_client_for_snapshot(self):
        self.set_server_status(ray.ServerStatus.READY)
        self.next_function()
    
    def close_client(self, client: Client):
        self.expected_clients.append(client)
        client.stop()

        self._wait_and_go_to(
            30000, (self.close_client_substep1, client),
            ray.WaitFor.STOP_ONE)

    def close_client_substep1(self, client: Client):
        if client in self.expected_clients:
            client.kill()

        self._wait_and_go_to(1000, self.next_function, ray.WaitFor.STOP_ONE)

    def switch_client(self, client: Client):
        client.switch()
        self.next_function()

    def load_client_snapshot_error(
            self, err: ray.Err, info_str='', exit_code=0):
        m = _translate('Snapshot Error', "Snapshot error")
        match err:
            case ray.Err.SUBPROCESS_UNTERMINATED:
                m = _translate(
                    'Snapshot Error',
                    "command didn't stop normally:\n%s") % info_str
            case ray.Err.SUBPROCESS_CRASH:
                m = _translate(
                    'Snapshot Error', "command crashes:\n%s") % info_str
            case ray.Err.SUBPROCESS_EXITCODE:
                m = _translate(
                    'Snapshot Error',
                    "command exit with the error code %i:\n%s") \
                        % (exit_code, info_str)
            case ray.Err.NO_SUCH_FILE:
                m = _translate(
                    'Snapshot Error', "error reading file:\n%s") % info_str

        self.message(m)
        self.send_gui_message(m)
        self._send_error(err, m)

        self.set_server_status(ray.ServerStatus.OFF)
        self.steps_order.clear()

    def load_client_snapshot_done(self):
        if self.steps_osp is None:
            return
        self.send(*self.steps_osp.reply(), 'Client snapshot loaded')

    def start_client(self, client: Client):
        client.start()
        self.next_function()

    def clear_clients(self, osp: OscPack):
        client_ids: list[str] = osp.args # type:ignore
        self.clients_to_quit.clear()
        self.expected_clients.clear()

        for client in self.clients:
            if client.client_id in client_ids or not client_ids:
                self.clients_to_quit.append(client)
                self.expected_clients.append(client)

        self.timer_quit.start()

        self._wait_and_go_to(
            5000,
            (self.clear_clients_substep2, osp),
            ray.WaitFor.QUIT)

    def clear_clients_substep2(self, osp: OscPack):
        for client in self.expected_clients:
            client.kill()

        self._wait_and_go_to(
            1000, (self.clear_clients_substep3, osp), ray.WaitFor.QUIT)

    def clear_clients_substep3(self, osp: OscPack):
        self.send(*osp.reply(), 'Clients cleared')
        
    def send_preview(self, src_addr: Address, folder_sizes: list):
        def send_state(preview_state: ray.PreviewState):
            self.send_even_dummy(
                src_addr, rg.preview.STATE,
                preview_state.value) 
        
        if self.path is None:
            return
        
        # prevent long list of OSC sends if preview order already changed
        server = self.get_server_even_dummy()
        if server and server.session_to_preview != self.short_path_name:
            return
        
        self.send_even_dummy(src_addr, rg.preview.CLEAR)        
        send_state(ray.PreviewState.STARTED)
        
        self.send_even_dummy(
            src_addr, rg.preview.NOTES, self.notes)
        send_state(ray.PreviewState.NOTES)

        ms = MegaSend('session_preview')

        for client in self.clients:
            ms.add(rg.preview.client.UPDATE,
                   *client.spread())
            
            ms.add(rg.preview.client.IS_STARTED,
                   client.client_id, int(client.auto_start))
            
            if client.is_ray_hack:
                ms.add(rg.preview.client.RAY_HACK_UPDATE,
                       client.client_id, *client.ray_hack.spread())

            elif client.is_ray_net:
                ms.add(rg.preview.client.RAY_NET_UPDATE,
                       client.client_id, *client.ray_net.spread())
                
        self.mega_send(src_addr, ms)

        send_state(ray.PreviewState.CLIENTS)

        mss = MegaSend('snapshots_preview')

        for snapshot in self.snapshoter.list():
            mss.add(rg.preview.SNAPSHOT, snapshot)
        
        self.mega_send(src_addr, mss)
        
        send_state(ray.PreviewState.SNAPSHOTS)

        # re check here if preview has not changed before calculate session size
        if server and server.session_to_preview != self.short_path_name:
            return

        total_size = 0
        size_unreadable = False

        # get last modified session folder to prevent recalculate
        # if we already know its size
        modified = int(os.path.getmtime(self.path))

        # check if size is already in memory
        for folder_size in folder_sizes:
            if folder_size['path'] == str(self.path):
                if folder_size['modified'] == modified:
                    total_size = folder_size['size']
                break

        # calculate session size
        if not total_size:
            for root, dirs, files in os.walk(self.path):
                # check each loop if it is still pertinent to walk
                if (server 
                        and (server.session_to_preview
                             != self.short_path_name)):
                    return

                # exclude symlinks directories from count
                dirs[:] = [dir for dir in dirs
                        if not os.path.islink(os.path.join(root, dir))]

                for file_path in files:
                    full_file_path = os.path.join(root, file_path)
                    
                    # ignore file if it is a symlink
                    if os.path.islink(os.path.join(root, file_path)):
                        continue

                    file_size = 0
                    try:
                        file_size = os.path.getsize(full_file_path)
                    except:
                        _logger.warning(
                            f'Unable to read {full_file_path} size')
                        size_unreadable = True
                        break

                    total_size += os.path.getsize(full_file_path)
                
                if size_unreadable:
                    total_size = -1
                    break
        
        for folder_size in folder_sizes:
            if folder_size['path'] == str(self.path):
                folder_size['modified'] = modified
                folder_size['size'] = total_size
                break
        else:
            folder_sizes.append(
                {'path': str(self.path),
                 'modified': modified,
                 'size': total_size})

        self.send_even_dummy(
            src_addr, rg.preview.SESSION_SIZE, total_size)

        send_state(ray.PreviewState.FOLDER_SIZE)

        self.send_even_dummy(
            src_addr, rg.preview.STATE, 2)

        del self
