
# Imports from standard library
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Optional

# third party imports
from qtpy.QtCore import QProcess, QProcessEnvironment, QCoreApplication

# Imports from src/shared
from osclib import OscPack
import ray
import osc_paths

# Local imports
from daemon_tools import Terminal, highlight_text
from server_sender import ServerSender

if TYPE_CHECKING:
    from session import Session
    from client import Client


_logger = logging.getLogger(__name__)
_translate = QCoreApplication.translate


class Scripter(ServerSender):
    '''Abstract scripts manager,
    inherited by StepScripter and ClientScripter.'''

    def __init__(self):
        ServerSender.__init__(self)
        self._src_addr = None
        self._src_path = ''

        self._process = QProcess()
        self._process.started.connect(self._process_started)
        self._process.finished.connect(self._process_finished)
        self._process.readyReadStandardError.connect(self._standard_error)
        self._process.readyReadStandardOutput.connect(self._standard_output)

        self._asked_for_terminate = False

    def _process_started(self):
        pass

    def _process_finished(self, exit_code, exit_status):
        if exit_code:
            if exit_code == 101:
                message = _translate('GUIMSG',
                            'script %s failed to start !') % (
                                highlight_text(self.get_path()))
            else:
                message = _translate('GUIMSG',
                        'script %s terminated with exit code %i') % (
                            highlight_text(self.get_path()), exit_code)

            if self._src_addr:
                self.send(self._src_addr, osc_paths.ERROR, self._src_path,
                          - exit_code, message)
        else:
            self.send_gui_message(
                _translate('GUIMSG', '...script %s finished. ---')
                    % highlight_text(self.get_path()))

            if self._src_addr:
                self.send(self._src_addr, osc_paths.REPLY,
                          self._src_path, 'script finished')

    def _standard_error(self):
        standard_error = self._process.readAllStandardError().data()
        Terminal.scripter_message(standard_error, self._get_command_name())

    def _standard_output(self):
        standard_output = self._process.readAllStandardOutput().data()
        Terminal.scripter_message(standard_output, self._get_command_name())

    def is_running(self):
        return not bool(
            self._process.state() == QProcess.ProcessState.NotRunning)

    def terminate(self):
        self._asked_for_terminate = True
        self._process.terminate()

    def is_asked_for_terminate(self):
        return self._asked_for_terminate

    def kill(self):
        self._process.kill()

    def get_path(self):
        return self._process.program()

    def _get_command_name(self):
        return self.get_path().rpartition('/')[2]


class StepScripter(Scripter):
    '''Scripts manager for sessions operations.
    Scripts are executable shell scripts in ray-scripts/
    (load.sh, save.sh, close.sh).'''
    
    def __init__(self, session: 'Session'):
        Scripter.__init__(self)
        self.session = session
        self.step = ''
        "Can be `load`, `save` or `close`"
        self.called_run_step = False
        """True if the script called `ray_control run_step` since the start
        of its execution."""

    def _get_script_dirs(self, spath: Path) -> tuple[Path, Path]:
        base_path = spath
        scripts_dir = Path()
        parent_scripts_dir = Path()

        while base_path.name:
            tmp_scripts_dir = base_path / ray.SCRIPTS_DIR
            if tmp_scripts_dir.is_dir():
                if not scripts_dir.name:
                    scripts_dir = tmp_scripts_dir
                else:
                    parent_scripts_dir = tmp_scripts_dir
                    break
            
            base_path = base_path.parent
            
        return (scripts_dir, parent_scripts_dir)

    def _process_started(self):
        pass

    def _process_finished(self, exit_code: int, exit_status):
        _logger.debug(f'step scripter {self.step} process finished')
        Scripter._process_finished(self, exit_code, exit_status)
        self.session.step_scripter_finished()
        self.called_run_step = False

    def start(self, step: str) -> bool:
        if self.is_running():
            return False

        if self.session.path is None:
            return False

        scripts_dir, parent_scripts_dir = \
            self._get_script_dirs(self.session.path)
        future_scripts_dir, future_parent_scripts_dir = \
            self._get_script_dirs(self.session.future_session_path)

        script_path = scripts_dir / f'{step}.sh'
        
        if not os.access(script_path, os.X_OK):
            return False

        self.called_run_step = False
        self.step = step

        self.send_gui_message(
            _translate('GUIMSG', '--- Custom step script %s started...')
            % highlight_text(script_path))

        process_env = QProcessEnvironment.systemEnvironment()
        process_env.insert('RAY_CONTROL_PORT', str(self.get_server_port()))
        process_env.insert('RAY_SCRIPTS_DIR', str(scripts_dir))
        process_env.insert('RAY_PARENT_SCRIPTS_DIR', str(parent_scripts_dir))
        process_env.insert('RAY_FUTURE_SESSION_PATH',
                           str(self.session.future_session_path))
        process_env.insert('RAY_FUTURE_SCRIPTS_DIR', str(future_scripts_dir))
        process_env.insert('RAY_SWITCHING_SESSION',
                           str(self.session.switching_session).lower())
        process_env.insert('RAY_SESSION_PATH', str(self.session.path))

        self._process.setProcessEnvironment(process_env)
        self._process.start(str(script_path), [])
        return True


class ClientScripter(Scripter):
    '''Scripts manager for client operations.
    Scripts are executable shell scripts in ray-scripts.CLIENT_ID/
    (start.sh, save.sh, close.sh).'''
    
    def __init__(self, client: 'Client'):
        Scripter.__init__(self)
        self._client = client
        self._pending_command = ray.Command.NONE
        self._initial_caller: Optional[OscPack] = None

    def _process_finished(self, exit_code, exit_status):
        Scripter._process_finished(self, exit_code, exit_status)
        self._client.script_finished(exit_code)
        self._pending_command = ray.Command.NONE
        self._initial_caller = None
        self._src_addr = None

    def start(self, command: ray.Command, osp: Optional[OscPack]=None,
              previous_slot: Optional[OscPack]=None):
        if self.is_running():
            return False

        if self._client.session.path is None:
            return False

        if not command in (
                ray.Command.START, ray.Command.SAVE, ray.Command.STOP):
            return False
        
        scripts_dir = (self._client.session.path
                       / f'{ray.SCRIPTS_DIR}.{self._client.client_id}')
        script_path = scripts_dir / f'{command.name.lower()}.sh'

        if not os.access(script_path, os.X_OK):
            return False

        self._pending_command = command

        if osp is not None:
            # Remember the caller of the function calling the script
            # Then, when script is finished
            # We could reply to this (address, path)
            self._initial_caller = previous_slot
            self._src_addr = osp.src_addr
        else:
            self._src_addr = None

        process_env = QProcessEnvironment.systemEnvironment()
        process_env.insert('RAY_CONTROL_PORT', str(self.get_server_port()))
        process_env.insert('RAY_CLIENT_SCRIPTS_DIR', str(scripts_dir))
        process_env.insert('RAY_CLIENT_ID', self._client.client_id)
        process_env.insert('RAY_CLIENT_EXECUTABLE',
                           self._client.executable)
        process_env.insert('RAY_CLIENT_ARGUMENTS', self._client.arguments)
        self._process.setProcessEnvironment(process_env)

        self.send_gui_message(
            _translate('GUIMSG', '--- Custom script %s started...%s')
                    % (highlight_text(script_path), self._client.client_id))

        self._process.start(str(script_path), [])
        return True

    def pending_command(self):
        return self._pending_command

    def initial_caller(self) -> Optional[OscPack]:
        return self._initial_caller
