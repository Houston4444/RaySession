
# Imports from standard library
import functools
import logging
import os
from typing import Callable, Any, Optional
from pathlib import Path
import xml.etree.ElementTree as ET

# third party imports
from qtpy.QtCore import QCoreApplication, QTimer

# Imports from src/shared
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
    steps_order: list[sop.SessionOp]
    
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

        self.steps_order = list[sop.SessionOp]()

        self.terminated_yet = False

        # externals are clients not launched from the daemon
        # but with NSM_URL=...
        self.externals_timer = QTimer()
        self.externals_timer.setInterval(100)
        self.externals_timer.timeout.connect(self._check_externals_states)

        self.window_waiter = QTimer()
        self.window_waiter.setInterval(200)
        self.window_waiter.timeout.connect(self._check_windows_appears)

        self.script_osp: OscPack | None = None

        self.switching_session = False

    def wait_and_go_to(
            self, session_op: sop.SessionOp, wait_for: ray.WaitFor,
            timeout: int | None =None, redondant=False):
        self.timer.stop()

        # we need to delete timer to change the timeout connect
        del self.timer
        self.timer = QTimer()

        if wait_for in (ray.WaitFor.SCRIPT_QUIT,
                        ray.WaitFor.PATCHBAY_QUIT,
                        ray.WaitFor.SNAPSHOT_ADD,
                        ray.WaitFor.FILE_COPY):
            match wait_for:
                case ray.WaitFor.SCRIPT_QUIT:
                    if not self.step_scripter.is_running():
                        session_op.run_next()
                        return
                case ray.WaitFor.PATCHBAY_QUIT:
                    if not patchbay_dmn_mng.is_running():
                        session_op.run_next()
                        return
                case ray.WaitFor.SNAPSHOT_ADD:
                    if not self.snapshoter.adder_running:
                        session_op.run_next()
                        return
                case ray.WaitFor.FILE_COPY:
                    if not self.file_copier.is_active():
                        session_op.run_next()
                        return

            self.wait_for = wait_for
            self.timer.setSingleShot(True)
            self.timer.timeout.connect(session_op.run_next)
            if timeout is not None:
                self.timer.start(timeout)
            return

        if self.expected_clients:
            n_expected = len(self.expected_clients)

            if wait_for is ray.WaitFor.ANNOUNCE:
                if n_expected == 1:
                    message = _translate(
                        'GUIMSG',
                        'waiting announce from %s...'
                            % self.expected_clients[0].gui_msg_style)
                else:
                    message = _translate(
                        'GUIMSG',
                        'waiting announce from %i clients...' % n_expected)
                self.send_gui_message(message)
            elif wait_for is ray.WaitFor.QUIT:
                if n_expected == 1:
                    message = _translate(
                        'GUIMSG',
                        'waiting for %s to stop...'
                            % self.expected_clients[0].gui_msg_style)
                else:
                    message = _translate(
                        'GUIMSG',
                        'waiting for %i clients to stop...' % n_expected)
                self.send_gui_message(message)

            self.timer_redondant = redondant

            self.wait_for = wait_for
            self.timer.setSingleShot(True)
            self.timer.timeout.connect(session_op.run_next)
            if timeout is not None:
                self.timer.start(timeout)
        else:
            session_op.run_next()

    def _forget_timer(self):
        self.timer.setSingleShot(True)
        self.timer.stop()
        self.timer.start(0)

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
            self._forget_timer()
            self.timer_waituser_progress.stop()

    def clean_expected(self):
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

    def next_session_op(self, script_osp: OscPack | None =None,
                        script_forbidden=False):
        if self.script_osp is not None and script_osp is None:
            self.set_server_status(ray.ServerStatus.SCRIPT)
            self.send(*self.script_osp.reply(), 'step done')
            self.script_osp = None
            return

        if script_osp is not None:
            self.script_osp = script_osp

        if not self.steps_order:
            return

        next_sop = self.steps_order[0]
        if script_osp is not None:
            self.script_osp = script_osp
                
        if (self.has_server_option(ray.Option.SESSION_SCRIPTS)
                and not script_forbidden
                and not self.step_scripter.is_running()
                and self.path is not None
                and script_osp is None
                and not (isinstance(next_sop, sop.Load)
                         and next_sop.open_off)
                and next_sop.script_step
                and self.steps_osp is not None
                and self.step_scripter.start(next_sop.script_step)):
            self.set_server_status(ray.ServerStatus.SCRIPT)
            return

        self.steps_order.__delitem__(0)

        if (script_osp is not None
                and self.step_scripter.is_running()
                and next_sop.script_step == self.step_scripter.get_step()):
            self.step_scripter.set_stepper_has_call(True)
            next_sop.start_from_script(script_osp)
            return

        _logger.debug(
            f'next session operation: {next_sop.__class__.__name__}')
        next_sop.start()

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
            self._forget_timer()

    def snapshoter_add_finished(self):
        '`git add .` snapshoter command is finished'
        if self.wait_for is not ray.WaitFor.SNAPSHOT_ADD:
            _logger.warning(
                'git add command ended while nothing is waiting for it')
            return
        
        self.wait_for = ray.WaitFor.NONE
        self._forget_timer()        

    def files_copy_finished(self):
        if self.wait_for is ray.WaitFor.FILE_COPY:
            self.wait_for = ray.WaitFor.NONE
            self._forget_timer()

    def _send_reply(self, *args: str):
        if self.steps_osp is None:
            return
        
        self.send_even_dummy(*self.steps_osp.reply(), *args)
        
    def _send_error(self, err: ray.Err, error_message: str):
        # clear process order to allow other new operations
        self.steps_order.clear()

        if self.script_osp is not None:
            if err is ray.Err.OK:
                self.send(*self.script_osp.reply(), error_message)
            else:
                self.send(*self.script_osp.error(), err, error_message)
            
        if self.steps_osp is None:
            return
        
        self.send_even_dummy(*self.steps_osp.error(), err, error_message)

    def step_scripter_finished(self):
        if self.wait_for is ray.WaitFor.SCRIPT_QUIT:
            self.wait_for = ray.WaitFor.NONE
            self._forget_timer()
            return

        if not self.step_scripter.stepper_has_called():
            # script has not call
            # the next_function (save, close, load)
            if self.step_scripter.get_step() in ('load', 'close'):
                self.steps_order.clear()
                self.steps_order = [
                    sop.Close(self, clear_all_clients=True),
                    sop.Success(self, msg='Aborted')]

                self.next_session_op(script_forbidden=True)
                return

            if self.steps_order:
                self.steps_order.__delitem__(0)

        self.next_session_op()

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
            self, new_session_name: str, template_mode: ray.Template):
        new_session_short_path = Path(new_session_name)
        
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
            client.adjust_files_after_copy(new_session_name, template_mode)

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

            self.send(self.steps_osp.src_addr,
                      r.net_daemon.DUPLICATE_STATE, 1.0)

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