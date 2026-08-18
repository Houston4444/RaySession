
# Imports from standard library
from enum import Enum
import logging
import subprocess
from typing import TYPE_CHECKING, Any, Callable, Optional, Union
from pathlib import Path

# third party imports
from qtpy.QtCore import QProcess, QTimer

# Imports from src/shared
from osclib import Address
import ray
import osc_paths
import osc_paths.ray as r
import osc_paths.ray.gui as rg

# Local imports
from server_sender import ServerSender

if TYPE_CHECKING:
    from session import Session


_logger = logging.getLogger(__name__)


class CopyState(Enum):
    OFF = 0
    COPYING = 1
    DONE = 2


class CopyFile:
    orig_path = Path()
    dest_path = Path()
    state = CopyState.OFF
    size = 0


class FileCopier(ServerSender):
    def __init__(self, session: 'Session'):
        ServerSender.__init__(self)
        self.session = session

        self._client_id = ''
        self._src_is_factory = False
        self._abort_function: Optional[Callable] = None
        self._next_args = list[Any]()
        self._copy_files = list[CopyFile]()
        self._copy_size = 0
        self._aborted = False
        self._is_active = False

        self._process = QProcess()
        self._process.finished.connect(self._process_finished)
        self._process.errorOccurred.connect(self._error_occurred)

        self._timer = QTimer()
        self._timer.setInterval(250)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._check_progress_size)

        self._abort_src_addr: Optional[Address] = None
        self._abort_src_path = ''

    @property
    def active(self) -> bool:
        return self._is_active
    
    @property
    def aborted(self) -> bool:
        return self._aborted

    def _get_file_size(self, filepath: Path) -> int:
        if not filepath.exists():
            return 0

        try:
            du_full = subprocess.check_output(
                ['nice', '-n', '15', 'du', '-sb', filepath]).decode()
        except BaseException as e:
            _logger.error(str(e))
            _logger.error(f'unable to decode size of file {filepath}')
            du_full = ""

        if not du_full:
            return 0

        du_str = du_full.split('\t')[0]
        try:
            return int(du_str)
        except:
            return 0

    def _check_progress_size(self):
        current_size = 0
        self._timer.stop()

        for copy_file in self._copy_files:
            if copy_file.state is CopyState.DONE:
                current_size += copy_file.size
            elif copy_file.state is CopyState.COPYING:
                current_size += self._get_file_size(copy_file.dest_path)
                break

        if current_size and self._copy_size:
            progress = float(current_size/self._copy_size)

            if self._client_id:
                self.send_gui(rg.client.PROGRESS,
                              self._client_id, progress)
            elif self.session.session_id:
                self.send_gui(rg.server.PARRALLEL_COPY_PROGRESS,
                              self.session.session_id, progress)
            else:
                self.send_gui(rg.server.PROGRESS, progress)

            if self.session.steps_osp is not None:
                self.send(self.session.steps_osp.src_addr,
                          r.net_daemon.DUPLICATE_STATE, progress)

        self._timer.start()

    def _process_finished(self, exit_code: int, exit_status: int):
        self._timer.stop()

        for copy_file in self._copy_files:
            if copy_file.state is CopyState.COPYING:
                copy_file.state = CopyState.DONE
                if self._src_is_factory:
                    try:
                        subprocess.run(['chmod', '-R', '+w',
                                        copy_file.dest_path])
                    except BaseException as e:
                        _logger.error(
                            f'Failed to set path writable {copy_file.dest_path}\n'
                            f'{str(e)}')
                break

        if self._aborted:
            ##remove all created files
            for copy_file in self._copy_files:
                if copy_file.state is not CopyState.OFF:
                    file_to_remove = copy_file.dest_path

                    if file_to_remove.exists():
                        try:
                            if file_to_remove.is_file():
                                file_to_remove.unlink()
                            elif file_to_remove.is_dir():
                                file_to_remove.rmdir()
                        except:
                            if self._abort_src_addr and self._abort_src_path:
                                self.send(self._abort_src_addr,
                                          osc_paths.MINOR_ERROR,
                                          self._abort_src_path,
                                          ray.Err.SUBPROCESS_CRASH,
                                          "%s hasn't been removed !")

            self._is_active = False
            self._send_copy_state_to_gui(0)
            
            self.session.files_copy_finished()
            if self._abort_function is not None:
                self._abort_function(*self._next_args)
            return

        # run next_function if copy is terminated
        for copy_file in self._copy_files:
            if copy_file.state is not CopyState.DONE:
                break
        else:
            self._is_active = False
            self._send_copy_state_to_gui(0)
            self.session.files_copy_finished()
            return

        self._next_process()

    def _error_occurred(self):
        #todo make something else
        self._process_finished(0, 0)

    def _next_process(self):
        self._is_active = True

        for copy_file in self._copy_files:
            if copy_file.state is CopyState.OFF:
                copy_file.state = CopyState.COPYING
                self._process.start(
                    'nice',
                    ['-n', '+15', 'cp', '-R',
                     str(copy_file.orig_path), str(copy_file.dest_path)])
                break

        self._timer.start()

    def _start(
            self, src_list: Path | list[Path], dest_dir: Path) -> ray.Err:
        self._aborted = False
        self._copy_size = 0
        self._copy_files.clear()

        dest_path_exists = dest_dir.exists()
        if dest_path_exists:
            if not dest_dir.is_dir():
                return ray.Err.BAD_PROJECT

        if isinstance(src_list, Path):
            src_dir = src_list
            src_list = list[Path]()

            if not src_dir.is_dir():
                return ray.Err.BAD_PROJECT

            try:
                tmp_list = src_dir.iterdir()            
            except:
                return ray.Err.BAD_PROJECT

            for path in tmp_list:
                if path.name == '.ray-snapshots':
                    continue

                src_list.append(path)

            if not dest_path_exists:
                try:
                    dest_dir.mkdir(parents=True)
                except:
                    return ray.Err.CREATE_FAILED

        for orig_path in src_list:
            copy_file = CopyFile()
            copy_file.state = CopyState.OFF
            copy_file.orig_path = orig_path
            copy_file.size = self._get_file_size(orig_path)

            self._copy_size += copy_file.size

            if dest_path_exists:
                copy_file.dest_path = dest_dir / orig_path.name
            else:
                # WARNING works only with one file !!!
                copy_file.dest_path = dest_dir

            self._copy_files.append(copy_file)

        if self._copy_files:
            self._send_copy_state_to_gui(1)
            self._next_process()

        return ray.Err.OK

    def _send_copy_state_to_gui(self, state: int):
        if self.session.session_id:
            self.send_gui(rg.server.PARRALLEL_COPY_STATE,
                          self.session.session_id, state)
        else:
            self.send_gui(rg.server.COPYING, state)

    def start_client_copy(
            self, client_id: str, src_list: list[Path], dest_dir: Path,
            src_is_factory=False) -> ray.Err:
        self._client_id = client_id
        self._src_is_factory = src_is_factory
        return self._start(src_list, dest_dir)

    def start_session_copy(
            self, src_dir: Path, dest_dir: Path,
            src_is_factory=False) -> ray.Err:
        self._client_id = ''
        self._src_is_factory = src_is_factory
        return self._start(src_dir, dest_dir)

    def abort(self, abort_function: Optional[Callable] =None, next_args=[]):
        if abort_function:
            self._abort_function = abort_function
            self._next_args = next_args

        self._timer.stop()

        if self._process.state() == QProcess.ProcessState.Running:
            self._aborted = True
            self._process.terminate()

    def is_active(self, client_id=''):
        if client_id and client_id != self._client_id:
            return False

        return self._is_active
