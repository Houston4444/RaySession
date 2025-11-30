
# Imports from standard library
import functools
from io import TextIOWrapper
import logging
import math
import os
import subprocess
import time
from typing import Callable, Any, Union, Optional
from pathlib import Path
import xml.etree.ElementTree as ET

# third party imports
from qtpy.QtCore import QCoreApplication, QTimer, QProcess

# Imports from src/shared
from osclib import Address, MegaSend, is_valid_osc_url
from osclib.bases import OscPack, OscPath
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

        self.steps_order = list[Callable| tuple[Callable | Any, ...]]()

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

        if wait_for is ray.WaitFor.SCRIPT_QUIT:
            if self.step_scripter.is_running():
                self.wait_for = wait_for
                self.timer.setSingleShot(True)
                self.timer.timeout.connect(follow)
                self.timer.start(duration)
            else:
                follow()
            return

        if wait_for is ray.WaitFor.PATCHBAY_QUIT:
            if not patchbay_dmn_mng.is_running():
                follow()
                return

            self.wait_for = wait_for
            self.timer.setSingleShot(True)
            self.timer.timeout.connect(follow)
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

            if self.wait_for is ray.WaitFor.ANNOUNCE:
                self.send_gui_message(
                    _translate('GUIMSG', "%s didn't announce.")
                    % ', '.join(client_names))

            elif self.wait_for is ray.WaitFor.QUIT:
                self.send_gui_message(
                    _translate('GUIMSG', "%s still alive !")
                    % ', '.join(client_names))

            self.expected_clients.clear()

        self.wait_for = ray.WaitFor.NONE

    def next_function(self, from_run_step=False, run_step_args=[]):
        if self.run_step_addr and not from_run_step:
            self.answer(self.run_step_addr, r.session.RUN_STEP,
                        'step done')
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

        if (self.has_server_option(ray.Option.SESSION_SCRIPTS)
                and not self.step_scripter.is_running()
                and self.path is not None
                and not from_run_step):
            for step_string in ('load', 'save', 'close'):
                if next_function == self.__getattribute__(step_string):
                    if (step_string == 'load'
                            and arguments
                            and arguments[0] == True):
                        # prevent use of load session script
                        # with open_session_off
                        break

                    if (self.steps_osp is not None
                            and self.step_scripter.start(
                                step_string, arguments,
                                self.steps_osp.src_addr,
                                self.steps_osp.path)):
                        self.set_server_status(ray.ServerStatus.SCRIPT)
                        return
                    break

        if (from_run_step and next_function
                and self.step_scripter.is_running()):
            if (next_function
                    == self.__getattribute__(
                                self.step_scripter.get_step())):
                self.step_scripter.set_stepper_has_call(True)

            if next_function == self.load:
                if 'open_off' in run_step_args:
                    arguments = [True]
            elif next_function == self.close:
                if 'close_all' in run_step_args:
                    arguments = [True]
            elif next_function == self.save:
                if 'without_clients' in run_step_args:
                    arguments = [False, False]

        self.steps_order.__delitem__(0)
        _logger.debug(f'next_function: {next_function.__name__}')  # type: ignore
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

    def _send_reply(self, *args: str):
        if self.steps_osp is None:
            return
        
        self.send_even_dummy(*self.steps_osp.reply(), *args)
        
    def _send_error(self, err: ray.Err, error_message: str):
        # clear process order to allow other new operations
        self.steps_order.clear()

        if self.run_step_addr:
            self.answer(self.run_step_addr, r.session.RUN_STEP,
                        error_message, err)

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
                self.steps_order = [(self.close, True),
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
        client.executable_path = executable
        client.name = Path(executable).name
        client.client_id = client_id
        if not client_id:
            client.client_id = self.generate_client_id(executable)

        self.clients.append(client)
        return client

    def adjust_files_after_copy(self, new_session_full_name: str,
                                template_mode: ray.Template):
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
                if not client.executable_path:
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

    def save(self, outing=False, save_clients=True):
        if self.path is None:
            self.next_function()
            return

        if outing:
            self.set_server_status(ray.ServerStatus.OUT_SAVE)
        else:
            self.set_server_status(ray.ServerStatus.SAVE)

        self.send_gui_message(_translate('GUIMSG', '-- Saving session %s --')
                                % highlight_text(self.short_path_name))

        if save_clients:
            for client in self.clients:
                if client.can_save_now():
                    self.expected_clients.append(client)
                client.save()

            if self.expected_clients:
                if len(self.expected_clients) == 1:
                    self.send_gui_message(
                        _translate('GUIMSG', 'waiting for %s to save...')
                            % self.expected_clients[0].gui_msg_style)
                else:
                    self.send_gui_message(
                        _translate('GUIMSG', 'waiting for %i clients to save...')
                            % len(self.expected_clients))

        self._wait_and_go_to(10000, (self.save_substep1, outing),
                             ray.WaitFor.REPLY)

    def save_substep1(self, outing=False, save_clients=True):
        self._clean_expected()

        if save_clients and outing:
            for client in self.clients:
                if client.has_error():
                    self._send_error(
                        ray.Err.GENERAL_ERROR,
                        "Some clients could not save")
                    break

        if self.path is None:
            self.next_function()
            return

        err = self._save_session_file()
        if err:
            self.save_error(ray.Err.CREATE_FAILED)
            return

        self.canvas_saver.save_json_session_canvas(self.path)

        full_notes_path = self.path / ray.NOTES_PATH

        if self.notes:
            try:
                with open(full_notes_path, 'w') as notes_file:
                    notes_file.write(self.notes)
            except:
                self.message("unable to save notes in %s" % full_notes_path)

        elif full_notes_path.is_file():
            try:
                full_notes_path.unlink()
            except:
                self.message("unable to remove %s" % full_notes_path)

        self.send_gui_message(_translate('GUIMSG', "Session '%s' saved.")
                                % self.short_path_name)
        self.message("Session %s saved." % self.short_path_name)

        self.next_function()

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

    def snapshot(self, snapshot_name='', rewind_snapshot='',
                 force=False, outing=False):
        if not force:
            if not (self.has_server_option(ray.Option.SNAPSHOTS)
                    and not self.snapshoter.is_auto_snapshot_prevented()
                    and self.snapshoter.has_changes()):
                self.next_function()
                return

        if outing:
            self.set_server_status(ray.ServerStatus.OUT_SNAPSHOT)
        else:
            self.set_server_status(ray.ServerStatus.SNAPSHOT)

        self.send_gui_message(_translate('GUIMSG', "snapshot started..."))
        self.snapshoter.save(snapshot_name, rewind_snapshot,
                             self.snapshot_substep1, self.snapshot_error)

    def snapshot_substep1(self, aborted=False):
        if aborted:
            self.message('Snapshot aborted')
            self.send_gui_message(_translate('GUIMSG', 'Snapshot aborted!'))

        self.send_gui_message(_translate('GUIMSG', '...Snapshot finished.'))
        self.next_function()

    def snapshot_done(self):
        self.set_server_status(ray.ServerStatus.READY)
        self._send_reply("Snapshot taken.")

    def snapshot_error(self, err_snapshot: ray.Err, info_str='', exit_code=0):
        m = _translate('Snapshot Error', "Unknown error")
        if err_snapshot == ray.Err.SUBPROCESS_UNTERMINATED:
            m = _translate('Snapshot Error',
                           "git didn't stop normally.\n%s") % info_str
        elif err_snapshot == ray.Err.SUBPROCESS_CRASH:
            m = _translate('Snapshot Error',
                           "git crashes.\n%s") % info_str
        elif err_snapshot == ray.Err.SUBPROCESS_EXITCODE:
            m = _translate('Snapshot Error',
                           "git exit with the error code %i.\n%s") \
                % (exit_code, info_str)
        self.message(m)
        self.send_gui_message(m)

        # quite dirty
        # minor error is not a fatal error
        # it's important for ray_control to not stop
        # if operation is not snapshot (ex: close or save)
        if self.next_function.__name__ == 'snapshot_done':
            self._send_error(err_snapshot, m)
            self.steps_osp = None
            return

        self._send_minor_error(err_snapshot, m)
        self.next_function()

    def close_no_save_clients(self):
        self._clean_expected()

        if self.has_server_option(ray.Option.HAS_WMCTRL):
            has_nosave_clients = False
            for client in self.clients:
                if client.is_running and client.relevant_no_save_level() == 2:
                    has_nosave_clients = True
                    break

            if has_nosave_clients:
                self.desktops_memory.set_active_window_list()
                for client in self.clients:
                    if client.is_running and client.relevant_no_save_level() == 2:
                        self.expected_clients.append(client)
                        self.desktops_memory.find_and_close(client.pid)

        if self.expected_clients:
            self.send_gui_message(
                _translate(
                    'GUIMSG',
                    'waiting for no saveable clients to be closed gracefully...'))

        duration = int(1000 * math.sqrt(len(self.expected_clients)))
        self._wait_and_go_to(duration, self.close_no_save_clients_substep1,
                             ray.WaitFor.QUIT)

    def close_no_save_clients_substep1(self):
        self._clean_expected()
        has_nosave_clients = False

        for client in self.clients:
            if (client.is_running and client.relevant_no_save_level()):
                self.expected_clients.append(client)
                has_nosave_clients = True

        if has_nosave_clients:
            self.set_server_status(ray.ServerStatus.WAIT_USER)
            self.timer_wu_progress_n = 0
            self.timer_waituser_progress.start()
            self.send_gui_message(_translate('GUIMSG',
                'waiting you to close yourself unsaveable clients...'))

        # Timer (2mn) is restarted if an expected client has been closed
        self._wait_and_go_to(120000, self.next_function, ray.WaitFor.QUIT, True)

    def close(self, clear_all_clients=False):
        self.expected_clients.clear()

        if self.path is None:
            self.next_function()
            return

        # clients we will keep alive
        keep_client_list = list[Client]()

        # stopped clients we will remove immediately
        byebye_client_list = list[Client]()

        if not clear_all_clients:
            for future_client in self.future_clients:
                if not future_client.auto_start:
                    continue

                for client in self.clients:
                    if client in keep_client_list:
                        continue

                    if client.can_switch_with(future_client):
                        client.switch_state = ray.SwitchState.RESERVED
                        keep_client_list.append(client)
                        break

        for client in self.clients:
            if client not in keep_client_list:
                # client is not capable of switch, or is not wanted
                # in the new session
                if client.is_running:
                    self.expected_clients.append(client)
                else:
                    byebye_client_list.append(client)

        if keep_client_list:
            self.set_server_status(ray.ServerStatus.CLEAR)
        else:
            self.set_server_status(ray.ServerStatus.CLOSE)

        for client in byebye_client_list:
            if client in self.clients:
                self._remove_client(client)
            else:
                raise NameError(f'no client {client.client_id} to remove')

        if self.expected_clients:
            if len(self.expected_clients) == 1:
                self.send_gui_message(
                    _translate('GUIMSG',
                               'waiting for %s to quit...')
                        % self.expected_clients[0].gui_msg_style)
            else:
                self.send_gui_message(
                    _translate('GUIMSG',
                               'waiting for %i clients to quit...')
                        % len(self.expected_clients))

            for client in self.expected_clients.__reversed__():
                self.clients_to_quit.append(client)
            self.timer_quit.start()

        self.trashed_clients.clear()
        self.send_gui(rg.trash.CLEAR)

        self._wait_and_go_to(
            30000, (self.close_substep1, clear_all_clients), ray.WaitFor.QUIT)

    def close_substep1(self, clear_all_clients=False):
        for client in self.expected_clients:
            client.kill()

        self._wait_and_go_to(1000, (self.close_substep2, clear_all_clients),
                         ray.WaitFor.QUIT)

    def close_substep2(self, clear_all_clients=False):
        self._clean_expected()

        # remember in recent sessions
        # only if session has been open at least 30 seconds
        # to prevent remember when session is open just for a little script
        if time.time() - self._time_at_open > 30:
            self.remember_as_recent()

        if clear_all_clients:
            self._set_path(None)
            
        self.next_function()

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

    def new(self, new_session_name: str):
        self.send_gui_message(
            _translate('GUIMSG', "Creating new session \"%s\"")
            % new_session_name)
        spath = self.root / new_session_name

        if self._is_path_in_a_session_dir(spath):
            self._send_error(
                ray.Err.SESSION_IN_SESSION_DIR,
                """Can't create session in a dir containing a session
for better organization.""")
            return

        try:
            spath.mkdir(parents=True)
        except:
            self._send_error(ray.Err.CREATE_FAILED,
                             "Could not create the session directory")
            return

        self.set_server_status(ray.ServerStatus.NEW)
        self._set_path(spath)
        self.send_gui(rg.session.NAME,
                      self.name, str(self.path))
        self.next_function()

    def new_done(self):
        self.send_gui_message(_translate('GUIMSG', 'Session is ready'))
        self._send_reply("Created.")
        self.set_server_status(ray.ServerStatus.READY)
        self.steps_osp = None

    def init_snapshot(self, spath: Path, snapshot: str):
        self.set_server_status(ray.ServerStatus.REWIND)
        if self.snapshoter.load(spath, snapshot, self.init_snapshot_error):
            self.next_function()

    def init_snapshot_error(self, err: ray.Err, info_str='', exit_code=0):
        m = _translate('Snapshot Error', "Snapshot error")
        if err == ray.Err.SUBPROCESS_UNTERMINATED:
            m = _translate('Snapshot Error',
                           "command didn't stop normally:\n%s") % info_str
        elif err == ray.Err.SUBPROCESS_CRASH:
            m = _translate('Snapshot Error',
                           "command crashes:\n%s") % info_str
        elif err == ray.Err.SUBPROCESS_EXITCODE:
            m = _translate('Snapshot Error',
                           "command exit with the error code %i:\n%s") \
                % (exit_code, info_str)
        elif err == ray.Err.NO_SUCH_FILE:
            m = _translate('Snapshot Error',
                           "error reading file:\n%s") % info_str
        self.message(m)
        self.send_gui_message(m)
        self._send_error(err, m)

        self.set_server_status(ray.ServerStatus.OFF)
        self.steps_order.clear()

    def duplicate(self, new_session_full_name: str):
        if self._clients_have_errors():
            self._send_error(
                ray.Err.GENERAL_ERROR,
                _translate('error', "Some clients could not save"))
            return

        self.send_gui(rg.trash.CLEAR)
        self.send_gui_message(
            _translate('GUIMSG', '-- Duplicating session %s to %s --')
            % (highlight_text(self.short_path_name),
               highlight_text(new_session_full_name)))

        for client in self.clients:
            if client.is_ray_net:
                client.ray_net.duplicate_state = -1
                if (client.ray_net.daemon_url
                        and is_valid_osc_url(client.ray_net.daemon_url)):
                    self.send(Address(client.ray_net.daemon_url),
                              r.session.DUPLICATE_ONLY,
                              self.short_path_name,
                              new_session_full_name,
                              client.ray_net.session_root)

                self.expected_clients.append(client)

        if self.expected_clients:
            self.send_gui_message(
                _translate('GUIMSG',
                           'waiting for network daemons to start duplicate...'))

        self._wait_and_go_to(
            2000,
            (self.duplicate_substep1, new_session_full_name),
            ray.WaitFor.DUPLICATE_START)

    def duplicate_substep1(self, new_session_full_name: str):
        if self.path is None:
            raise NoSessionPath
        
        spath = self.root / new_session_full_name
        self.set_server_status(ray.ServerStatus.COPY)
        self.send_gui_message(_translate('GUIMSG', 'start session copy...'))

        # lock the directory of the new session created
        multi_daemon_file.add_locked_path(spath)

        self.file_copier.start_session_copy(
            self.path, spath,
            self.duplicate_substep2, self.duplicate_aborted,
            [new_session_full_name])

    def duplicate_substep2(self, new_session_full_name: str):
        self._clean_expected()
        
        self.send_gui_message(_translate('GUIMSG', '...session copy finished.'))
        for client in self.clients:
            if (client.is_ray_net
                    and 0 <= client.ray_net.duplicate_state < 1):
                self.expected_clients.append(client)

        if self.expected_clients:
            self.send_gui_message(
                _translate('GUIMSG',
                           'waiting for network daemons to finish duplicate'))

        self._wait_and_go_to(
            3600000,  #1Hour
            (self.duplicate_substep3, new_session_full_name),
            ray.WaitFor.DUPLICATE_FINISH)

    def duplicate_substep3(self, new_session_full_name: str):
        self.adjust_files_after_copy(new_session_full_name, ray.Template.NONE)

        # unlock the directory of the new session created
        multi_daemon_file.unlock_path(self.root / new_session_full_name)
        
        self.next_function()

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

    def save_session_template(self, template_name: str, net=False):
        if self.path is None:
            raise NoSessionPath

        template_root = TemplateRoots.user_sessions

        if net:
            template_root = self.root / TemplateRoots.net_session_name

        spath = template_root / template_name

        #overwrite existing template
        if spath.is_dir():            
            if not os.access(spath, os.W_OK):
                self._send_error(
                    ray.Err.GENERAL_ERROR,
                    _translate(
                        "error",
                        "Impossible to save template, unwriteable file !"))

                self.set_server_status(ray.ServerStatus.READY)
                return

            spath.rmdir()

        if not template_root.exists():
            template_root.mkdir(parents=True)

        # For network sessions,
        # save as template the network session only
        # if there is no other server on this same machine.
        # Else, one could erase template just created by another one.
        # To prevent all confusion,
        # all seen machines are sent to prevent an erase by looping
        # (a network session can contains another network session
        # on the machine where is the master daemon, for example).

        for client in self.clients:
            if (client.is_ray_net
                    and client.ray_net.daemon_url):
                self.send(Address(client.ray_net.daemon_url),
                          r.server.SAVE_SESSION_TEMPLATE,
                          self.short_path_name,
                          template_name,
                          client.ray_net.session_root)

        self.set_server_status(ray.ServerStatus.COPY)

        self.send_gui_message(
            _translate('GUIMSG', 'start session copy to template...'))

        self.file_copier.start_session_copy(
            self.path, spath,
            self.save_session_template_substep_1,
            self.save_session_template_aborted,
            [template_name, net])

    def save_session_template_substep_1(self, template_name: str, net: bool):
        tp_mode = ray.Template.SESSION_SAVE
        if net:
            tp_mode = ray.Template.SESSION_SAVE_NET

        for client in self.clients + self.trashed_clients:
            client.adjust_files_after_copy(template_name, tp_mode)

        self.message("Done")
        self.send_gui_message(
            _translate('GUIMSG', "...session saved as template named %s")
            % highlight_text(template_name))

        self._send_reply("Saved as template.")
        self.set_server_status(ray.ServerStatus.READY)

    def save_session_template_aborted(self, template_name: str, net: bool):
        self.steps_order.clear()
        self._send_reply("Session template aborted")
        self.set_server_status(ray.ServerStatus.READY)

    def prepare_template(self, new_session_full_name: str,
                         template_name: str, net=False):
        template_root = TemplateRoots.user_sessions

        if net:
            template_root = self.root / TemplateRoots.net_session_name

        template_path = template_root / template_name
        is_factory = template_name.startswith('///')

        if is_factory:
            template_name = template_name.replace('///', '')
            template_path = TemplateRoots.factory_sessions / template_name

        if not template_path.is_dir():
            self._send_minor_error(ray.Err.GENERAL_ERROR,
                                   _translate("error", "No template named %s")
                                   % template_name)
            self.next_function()
            return

        spath = self.root / new_session_full_name

        if spath.exists():
            self._send_error(
                ray.Err.CREATE_FAILED,
                _translate("error", "Folder\n%s\nalready exists")
                % spath)
            return

        if self._is_path_in_a_session_dir(spath):
            self._send_error(
                ray.Err.SESSION_IN_SESSION_DIR,
                _translate("error",
                "Can't create session in a dir containing a session" + '\n'
                + "for better organization."))
            return

        if self.path:
            self.set_server_status(ray.ServerStatus.COPY)
        else:
            self.set_server_status(ray.ServerStatus.PRECOPY)

        self.send_gui_message(
            _translate('GUIMSG',
                       'start copy from template to session folder'))

        self.file_copier.start_session_copy(
            template_path, spath,
            self.prepare_template_substep1,
            self.prepare_template_aborted,
            [new_session_full_name],
            src_is_factory=True)

    def prepare_template_substep1(self, new_session_full_name: str):
        self.adjust_files_after_copy(new_session_full_name,
                                     ray.Template.SESSION_LOAD)
        self.next_function()

    def prepare_template_aborted(self, new_session_full_name: str):
        self.steps_order.clear()
        if self.path:
            self.set_server_status(ray.ServerStatus.READY)
        else:
            self.set_server_status(ray.ServerStatus.OFF)

            self._set_path(None)
            self.send_gui(rg.session.NAME, '', '')

    def rename(self, new_session_name: str):
        if self.path is None:
            raise NoSessionPath

        spath = self.path.parent / new_session_name
        if spath.exists():        
            self._send_error(
                ray.Err.CREATE_FAILED,
                _translate('rename', "Folder %s already exists,")
                % new_session_name
                + '\n'
                + _translate('rename', 'Impossible to rename session.'))
            return
        
        try:
            subprocess.run(['mv', self.path, spath])
        except:
            self._send_error(
                ray.Err.GENERAL_ERROR,
                "failed to rename session")
            return
        
        self._set_path(spath)

        self.send_gui_message(
            _translate('GUIMSG', 'Session directory is now: %s')
            % self.path)
        
        for client in self.clients + self.trashed_clients:
            client.adjust_files_after_copy(
                new_session_name, ray.Template.RENAME)

        self.next_function()

    def rename_done(self, new_session_name: str):
        self.send_gui_message(
            _translate('GUIMSG', 'Session %s has been renamed to %s .')
            % (self.name, new_session_name))
        self._send_reply(
            f"Session '{self.name}' has been renamed '"
            f"to '{new_session_name}'.")
        self.steps_osp = None

    def preload(self, session_full_name: str, auto_create=True):
        '''load session data in self.future*
        (clients, trashed_clients, session_path, session_name)'''

        session_short_path = Path(session_full_name)
        if session_short_path.is_absolute():
            spath = session_short_path
        else:
            spath = self.root / session_short_path

        if spath == self.path:
            self.load_error(ray.Err.SESSION_LOCKED)
            return

        session_ray_file = spath / 'raysession.xml'
        session_nsm_file = spath / 'session.nsm'

        if spath.exists():
            # session directory exists
            for sess_file in session_ray_file, session_nsm_file:
                if sess_file.exists():
                    break
            else:

                # session directory doesn't contains session file.
                # Check if it contains another session file in a subfolder
                # and in this case, prevent to create this session
                for root, dirs, files in os.walk(spath):
                    #exclude hidden files and dirs
                    files = [f for f in files if not f.startswith('.')]
                    dirs[:] = [d for d in dirs  if not d.startswith('.')]

                    if root == str(spath):
                        continue

                    for file_ in files:
                        if file_ in ('raysession.xml', 'session.nsm'):
                            # dir contains a session inside,
                            # do not try to load it
                            self.load_error(ray.Err.SESSION_IN_SESSION_DIR)
                            return
        else:
            if not auto_create:
                self.load_error(ray.Err.NO_SUCH_FILE)
                return
            
            # session directory doesn't exists,
            # create this session.            
            
            if self._is_path_in_a_session_dir(spath):
                # prevent to create a session in a session directory
                # for better user organization
                self.load_error(ray.Err.SESSION_IN_SESSION_DIR)
                return

            try:
                spath.mkdir(parents=True)
            except:
                self.load_error(ray.Err.CREATE_FAILED)
                return

        if not multi_daemon_file.is_free_for_session(spath):
            Terminal.warning(f"Session {spath} is used by another daemon")
            self.load_error(ray.Err.SESSION_LOCKED)
            return

        self.message("Attempting to open %s" % spath)

        # change session file only for raysession launched with NSM_URL env
        # Not sure that this feature is really useful.
        # Any cases, It's important to rename it
        # because we want to prevent session creation in a session folder
        if self.is_nsm_locked() and os.getenv('NSM_URL'):
            session_ray_file = spath / 'raysubsession.xml'

        nsm_file: Optional[TextIOWrapper] = None
        is_ray_file = True
        
        try:
            tree = ET.parse(session_ray_file)
        except BaseException as e:
            _logger.info(str(e))
            is_ray_file = False

        if not is_ray_file:
            try:
                nsm_file = open(session_nsm_file, 'r')
            except BaseException as e:
                _logger.info(str(e))

                root = ET.Element('RAYSESSION')
                root.attrib['VERSION'] = ray.VERSION
                if self.is_nsm_locked():
                    root.attrib['name'] = spath.name.rpartition('.')[0]
                    
                tree = ET.ElementTree(root)

                try:
                    tree.write(session_ray_file)                    
                except BaseException as e:
                    _logger.error(str(e))
                    self.load_error(ray.Err.CREATE_FAILED)
                    return
                else:
                    is_ray_file = True

        self._no_future()
        sess_name = ""

        if is_ray_file:
            try:
                tree = ET.parse(session_ray_file)
            except BaseException as e:
                _logger.error(str(e))
                self.load_error(ray.Err.BAD_PROJECT)
                return
            
            root = tree.getroot()
            if root.tag != 'RAYSESSION':
                self.load_error(ray.Err.BAD_PROJECT)
                return

            xroot = XmlElement(root)
            sess_name = xroot.string('name')
            
            if xroot.bool('notes_shown'):
                self.future_notes_shown = True

            client_ids = set[str]()
            
            for child in root:
                if child.tag in ('Clients', 'RemovedClients'):
                    for cchild in child:
                        c = XmlElement(cchild)
                        client = Client(self)
                        client.read_xml_properties(c)
                        
                        if not client.executable_path:
                            continue

                        if client.executable_path == 'ray-proxy':
                            client.transform_from_proxy_to_hack(spath, sess_name)

                        if client.client_id in client_ids:
                            # prevent double same id
                            continue
                            
                        if child.tag == 'Clients':
                            self.future_clients.append(client)
                        elif child.tag == 'RemovedClients':
                            self.future_trashed_clients.append(client)
                        else:
                            continue
                        
                        client_ids.add(client.client_id)

                elif child.tag == 'Windows':
                    if self.has_server_option(ray.Option.DESKTOPS_MEMORY):
                        self.desktops_memory.read_xml(XmlElement(child))

        else:
            # prevent to load a locked NSM session
            lock_file = spath / '.lock'
            if lock_file.is_file():
                Terminal.warning("Session %s is locked by another process")
                self.load_error(ray.Err.SESSION_LOCKED)
                return

            if nsm_file is not None:
                for line in nsm_file.read().splitlines():
                    elements = line.split(':')
                    if len(elements) >= 3:
                        client = Client(self)
                        client.name = elements[0]
                        client.executable_path = elements[1]
                        client.client_id = elements[2]
                        client.prefix_mode = ray.PrefixMode.CLIENT_NAME
                        client.auto_start = True
                        client.jack_naming = ray.JackNaming.LONG

                        self.future_clients.append(client)

                nsm_file.close()
            self.send_gui(rg.session.IS_NSM)

        if not self.is_dummy:
            self.canvas_saver.load_json_session_canvas(spath)

        full_notes_path = spath / ray.NOTES_PATH

        if (full_notes_path.is_file()
                and os.access(full_notes_path, os.R_OK)): 
            notes_file = open(full_notes_path)
            # limit notes characters to 65000 to prevent OSC message accidents
            self.future_notes = notes_file.read(65000)
            notes_file.close()

        self.future_session_path = spath
        self.future_session_name = sess_name
        self.switching_session = bool(self.path is not None)

        self.next_function()

    def take_place(self):
        self._set_path(self.future_session_path,
                       self.future_session_name)

        if self.path is None:
            raise NoSessionPath

        if self.name and self.name != self.path.name:
            # session folder has been renamed
            # so rename session to it
            for client in self.future_clients + self.future_trashed_clients:
                client.adjust_files_after_copy(str(self.path), ray.Template.RENAME)
            self._set_path(self.future_session_path)
            
            # session has been renamed and client files have been moved
            # save session file is required here, else clients could not
            # find their files at reload (after session abort).
            self._save_session_file()

        self.send_gui(rg.session.NAME, self.name, str(self.path))
        self.trashed_clients.clear()

        self.notes = self.future_notes
        self.send_gui(rg.session.NOTES, self.notes)
        self.notes_shown = self.future_notes_shown
        if self.notes_shown:
            self.send_gui(rg.session.NOTES_SHOWN)
        else:
            self.send_gui(rg.session.NOTES_HIDDEN)

        self.canvas_saver.send_session_group_positions()
        self.load_locked = True

        self._time_at_open = time.time()

        self.next_function()

    def load(self, open_off=False):
        self._clean_expected()
        self.clients_to_quit.clear()

        # first quit unneeded clients
        # It has probably been done but we can't know if during the load script
        # some clients could have been stopped.
        # Because adding client is not allowed
        # during the load script before run_step,
        # we can assume all these clients are needed if they are running.
        # 'open_off' decided during the load script
        # is a good reason to stop all clients.

        for client in self.clients.__reversed__():
            if (open_off
                    or not client.is_running
                    or (client.is_reply_pending() and not client.is_dumb_client())
                    or client.switch_state is not ray.SwitchState.RESERVED):
                self.clients_to_quit.append(client)
                self.expected_clients.append(client)
            else:
                client.switch_state = ray.SwitchState.NEEDED

        self.timer_quit.start()
        self._wait_and_go_to(
            5000, (self.load_substep2, open_off), ray.WaitFor.QUIT)

    def load_substep2(self, open_off: bool):
        for client in self.expected_clients:
            client.kill()

        self._wait_and_go_to(
            1000, (self.load_substep3, open_off), ray.WaitFor.QUIT)

    def load_substep3(self, open_off: bool):
        self._clean_expected()

        self.load_locked = False
        self.send_gui_message(_translate('GUIMSG', "-- Opening session %s --")
                              % highlight_text(self.short_path_name))

        for trashed_client in self.future_trashed_clients:
            self.trashed_clients.append(trashed_client)
            trashed_client.send_gui_client_properties(removed=True)

        self.message("Commanding smart clients to switch")
        has_switch = False
        new_client_id_list = list[str]()

        # remove stopped clients
        rm_indexes = list[int]()
        for i, client in enumerate(self.clients):
            if not client.is_running:
                rm_indexes.append(i)

        rm_indexes.reverse()
        for i in rm_indexes:
            self._remove_client(self.clients[i])

        # Lie to the GUIs saying all clients are removed.
        # Clients will reappear just in a few time
        # It prevents GUI to have 2 clients with the same client_id
        # in the same time
        for client in self.clients:
            client.set_status(ray.ClientStatus.REMOVED)
            client.sent_to_gui = False

        for future_client in self.future_clients:
            client = None

            # This part needs care
            # we add future_clients to clients.
            # At this point,
            # running clients waiting for switch have SwitchState NEEDED,
            # running clients already choosen for switch have SwitchState DONE,
            # clients just added from future clients without switch
            # have SwitchState NONE.

            if future_client.auto_start:
                for client in self.clients:
                    if (client.switch_state is ray.SwitchState.NEEDED
                            and client.client_id == future_client.client_id
                            and client.can_switch_with(future_client)):
                        # we found the good existing client
                        break
                else:
                    for client in self.clients:
                        if (client.switch_state is ray.SwitchState.NEEDED
                                and client.can_switch_with(future_client)):
                            # we found a switchable client
                            break
                    else:
                        client = None

            if client:
                client.switch_state = ray.SwitchState.DONE
                self.send_monitor_event(
                    f"switched_to:{future_client.client_id}", client.client_id)
                client.client_id = future_client.client_id
                client.eat_attributes(future_client)
                has_switch = True
            else:
                if not self._add_client(future_client):
                    continue

                if future_client.auto_start and not (self.is_dummy or open_off):
                    self.clients_to_launch.append(future_client)

                    if (not future_client.executable_path
                            in RS.non_active_clients):
                        self.expected_clients.append(future_client)

            new_client_id_list.append(future_client.client_id)

        for client in self.clients:
            if client.switch_state is ray.SwitchState.DONE:
                client.switch()

        self._re_order_clients(new_client_id_list)
        self.send_gui(rg.session.SORT_CLIENTS, *new_client_id_list)
        
        # send initial monitor infos for all monitors
        # Note that a monitor client starting here with the session
        # will not receive theses messages, because it is not known as capable
        # of ':monitor:' yet.
        # However, a monitor client capable of :switch: will get theses messages.
        # An outside monitor (saved in server.monitor_list) will get theses messages
        # in all cases. 
        server = self.get_server()
        if server is not None:
            for monitor_addr in server.monitor_list:
                self.send_initial_monitor(monitor_addr, False)
                
            for client in self.clients:
                if client.addr and client.is_running and client.can_monitor:
                    self.send_initial_monitor(client.addr, True)

        self._no_future()

        if has_switch:
            self.set_server_status(ray.ServerStatus.SWITCH)
        else:
            self.set_server_status(ray.ServerStatus.LAUNCH)

        #* this part is a little tricky... the clients need some time to
        #* send their 'announce' messages before we can send them 'open'
        #* and know that a reply is pending and we should continue waiting
        #* until they finish.

        #* dumb clients will never send an 'announce message', so we need
        #* to give up waiting on them fairly soon. */

        self.timer_launch.start()

        wait_time = 4000 + len(self.expected_clients) * 1000

        self._wait_and_go_to(wait_time, self.load_substep4, ray.WaitFor.ANNOUNCE)

    def load_substep4(self):
        for client in self.expected_clients:
            if not client.executable_path in RS.non_active_clients:
                RS.non_active_clients.append(client.executable_path)

        RS.settings.setValue('daemon/non_active_list', RS.non_active_clients)

        self._clean_expected()

        self.set_server_status(ray.ServerStatus.OPEN)

        for client in self.clients:
            if client.nsm_active and client.is_reply_pending():
                self.expected_clients.append(client)
            elif client.is_running and client.is_dumb_client():
                client.set_status(ray.ClientStatus.NOOP)

        if self.expected_clients:
            n_expected = len(self.expected_clients)
            if n_expected == 1:
                self.send_gui_message(
                    _translate('GUIMSG',
                               'waiting for %s to load its project...')
                    % self.expected_clients[0].gui_msg_style)
            else:
                self.send_gui_message(
                    _translate('GUIMSG',
                               'waiting for %s clients to load their project...')
                    % n_expected)

        wait_time = 8000 + len(self.expected_clients) * 2000
        for client in self.expected_clients:
            wait_time = int(max(2 * 1000 * client.last_open_duration, wait_time))

        self._wait_and_go_to(wait_time, self.load_substep5, ray.WaitFor.REPLY)

    def load_substep5(self):
        self._clean_expected()

        if self.has_server_option(ray.Option.DESKTOPS_MEMORY):
            self.desktops_memory.replace()

        self.message("Telling all clients that session is loaded...")
        for client in self.clients:
            client.tell_client_session_is_loaded()

        self.message('Loaded')
        self.send_gui_message(
            _translate('GUIMSG', 'session %s is loaded.')
            % highlight_text(self.short_path_name))
        self.send_gui(rg.session.NAME, self.name, str(self.path))

        self.switching_session = False

        # display optional GUIs we want to be shown now
        if self.has_server_option(ray.Option.GUI_STATES):
            for client in self.clients:
                if (client.is_running
                        and client.can_optional_gui
                        and not client.start_gui_hidden
                        and not client.gui_has_been_visible):
                    client.send_to_self_address(nsm.client.SHOW_OPTIONAL_GUI)

        self.next_function()

    def load_done(self):
        self._send_reply("Loaded.")
        self.message("Done")
        self.set_server_status(ray.ServerStatus.READY)
        self.steps_osp = None

    def load_error(self, err_loading):
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
        elif err_loading == ray.Err.SESSION_IN_SESSION_DIR:
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

    def exit_now(self):
        self._wait_and_go_to(1000, self.exit_now_step_2, ray.WaitFor.PATCHBAY_QUIT)
        
    def exit_now_step_2(self):
        self.set_server_status(ray.ServerStatus.OFF)
        self._set_path(None)
        self.message("Bye Bye...")
        self._send_reply("Bye Bye...")
        self.send_gui(rg.server.DISANNOUNCE)
        QCoreApplication.quit()

    def add_client_template(self, src_addr, src_path,
                            template_name: str, factory=False, auto_start=True,
                            unique_id=''):
        if self.path is None:
            return
        
        base = 'factory' if factory else 'user'
        templates_database = self.get_client_templates_database(base)

        # if this client template is not present in the database
        # first, rebuild the database
        if template_name not in [t.template_name for t in templates_database]:
            self._rebuild_templates_database(base)

        for t in templates_database:
            if t.template_name == template_name:
                file_paths = list[Path]()
                template_path = t.templates_root / template_name

                if t.templates_root.name and template_path.is_dir():
                    for file_path in template_path.iterdir():
                        file_paths.append(file_path)

                template_client = t.template_client
                client = Client(self)
                client.protocol = template_client.protocol
                client.ray_hack = template_client.ray_hack
                client.ray_net = template_client.ray_net
                client.template_origin = template_name
                if t.display_name:
                    client.template_origin = t.display_name
                client.eat_attributes(template_client)
                client.auto_start = auto_start

                if unique_id:
                    client.client_id = unique_id
                    client.label = unique_id.replace('_', ' ')
                    client.jack_naming = ray.JackNaming.LONG
                else:
                    client.client_id = self.generate_client_id(
                        template_client.client_id)
                
                # If It is an Ardour template
                if t.template_name.startswith('/ardour_tp/'):
                    ard_tp_name = t.template_name.rpartition('/')[2]
                    ard_tp_path = ardour_templates.get_template_path_from_name(
                        ard_tp_name, client.executable_path)
                    if ard_tp_path is None:
                        self.answer(src_addr, src_path, "Failed to copy Ardour template",
                                    ray.Err.BAD_PROJECT)
                        return
                    
                    ard_tp_copyed = ardour_templates.copy_template_to_session(
                        ard_tp_path,
                        self.path,
                        client.prefix,
                        client.client_id
                    )
                    if not ard_tp_copyed:
                        self.answer(src_addr, src_path, "Failed to copy Ardour template",
                                    ray.Err.BAD_PROJECT)
                        return
                
                if not self._add_client(client):
                    self.answer(src_addr, src_path,
                                "Session does not accept any new client now",
                                ray.Err.NOT_NOW)
                    return
                
                if file_paths:
                    client.set_status(ray.ClientStatus.PRECOPY)
                    self.file_copier.start_client_copy(
                        client.client_id, file_paths, self.path,
                        self.add_client_template_step_1,
                        self.add_client_template_aborted,
                        [src_addr, src_path, client],
                        src_is_factory=factory)
                else:
                    self.add_client_template_step_1(src_addr, src_path,
                                                    client)
                return

        # no template found with that name
        for favorite in RS.favorites:
            if (favorite.name == template_name
                    and favorite.factory == factory):
                self.send_gui(rg.favorites.REMOVED,
                              favorite.name, int(favorite.factory))
                RS.favorites.remove(favorite)
                break

        self.send(src_addr, osc_paths.ERROR, src_path, ray.Err.NO_SUCH_FILE,
                  _translate('GUIMSG', "%s is not an existing template !")
                  % highlight_text(template_name))

    def add_client_template_step_1(self, src_addr, src_path, client: Client):
        client.adjust_files_after_copy(self.name, ray.Template.CLIENT_LOAD)

        if client.auto_start:
            client.start()
        else:
            client.set_status(ray.ClientStatus.STOPPED)

        self.answer(src_addr, src_path, client.client_id)

    def add_client_template_aborted(self, src_addr, src_path, client: Client):
        self._remove_client(client)
        self.send(src_addr, osc_paths.ERROR, src_path, ray.Err.COPY_ABORTED,
                  _translate('GUIMSG', 'Copy has been aborted !'))

    def save_client_and_patchers(self, client: Client):
        for oth_client in self.clients:
            if (oth_client is client or 
                    (oth_client.is_running
                        and oth_client.can_monitor
                        and oth_client.executable_path.startswith('ray-')
                        and oth_client.executable_path.endswith('patch'))):
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
            client.get_links_dirname(), tmp_client.get_links_dirname())

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

    def load_client_snapshot(self, client_id, snapshot):
        self.set_server_status(ray.ServerStatus.REWIND)
        if self.snapshoter.load_client_exclusive(
                client_id, snapshot, self.load_client_snapshot_error):
            self.set_server_status(ray.ServerStatus.READY)
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

    def terminate_step_scripter(self):
        if self.step_scripter.is_running():
            self.step_scripter.terminate()

        self._wait_and_go_to(5000, self.terminate_step_scripter_substep2,
                             ray.WaitFor.SCRIPT_QUIT)

    def terminate_step_scripter_substep2(self):
        if self.step_scripter.is_running():
            self.step_scripter.kill()

        self._wait_and_go_to(1000, self.terminate_step_scripter_substep3,
                             ray.WaitFor.SCRIPT_QUIT)

    def terminate_step_scripter_substep3(self):
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
