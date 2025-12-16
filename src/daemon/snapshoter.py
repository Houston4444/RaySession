
# Imports from standard library
import os
import socket
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Optional
import xml.etree.ElementTree as ET
from xml.etree.ElementTree import Element

# third party imports
from qtpy.QtCore import Slot, QProcess, QObject, QDateTime # type:ignore

# Imports from src/shared
import ray
from xml_tools import XmlElement
import osc_paths.ray.gui as rg

# Local imports
from daemon_tools import NoSessionPath, Terminal

if TYPE_CHECKING:
    from session_operating import OperatingSession


_logger = logging.getLogger(__name__)

_GIT_EXEC = 'git'
_GIT_DIR = '.ray-snapshots'
_EXCLUDE_PATH = 'info/exclude'
_HISTORY_PATH = 'session_history.xml'
_MAX_FILE_SIZE = 50 # in Mb


def git_stringer(string: str | Path) -> str:
    if isinstance(string, Path):
        string = str(string)

    for char in ' *?[]()':
        string = string.replace(char, "\\" + char)

    for char in '#!':
        if string.startswith(char):
            string = "\\" + string

    return string

def full_ref_for_gui(ref, name: str, rw_ref: str, rw_name='', ss_name=''):
    if ss_name:
        return f'{ref}:{name}\n{rw_ref}:{rw_name}\n{ss_name}'
    return f'{ref}:{name}\n{rw_ref}:{rw_name}'


class Snapshoter(QObject):
    def __init__(self, session: 'OperatingSession'):
        QObject.__init__(self)
        self.session = session

        self._changes_checker = QProcess()
        self._changes_checker.readyReadStandardOutput.connect(
            self._changes_checker_standard_output)

        self._adder_process = QProcess()
        # self._adder_process.finished.connect(self._save_step_1)
        self._adder_process.finished.connect(self._adder_finished)
        self._adder_process.readyReadStandardOutput.connect(
            self._adder_standard_output)

        self._adder_aborted = False

        self._git_process = QProcess()
        self._git_process.readyReadStandardOutput.connect(
            self._standard_output)
        self._git_process.readyReadStandardError.connect(
            self._standard_error)
        self._git_command = ''
        self._last_git_error = (ray.Err.OK, '', 0)
        '''contains the last git command error.
        (ray.Err, command with args, exit_code)'''

        self._n_file_changed = 0
        self._n_file_treated = 0
        self._changes_counted = False

    def _changes_checker_standard_output(self):
        standard_output = self._changes_checker.readAllStandardOutput().data()
        self._n_file_changed += len(standard_output.splitlines())

    def _adder_standard_output(self):
        standard_output = self._adder_process.readAllStandardOutput().data()
        Terminal.snapshoter_message(standard_output, ' add -A -v')

        if not self._n_file_changed:
            return

        self._n_file_treated += len(standard_output.splitlines())

        self.session.send_gui(
            rg.server.PROGRESS,
            (self._n_file_treated + 1) / self._n_file_changed)

    @Slot()
    def _adder_finished(self):
        self.session.snapshoter_add_finished()

    def _standard_error(self):
        standard_error = self._git_process.readAllStandardError().data()
        Terminal.snapshoter_message(standard_error, self._git_command)

    def _standard_output(self):
        standard_output = self._git_process.readAllStandardOutput().data()
        Terminal.snapshoter_message(standard_output, self._git_command)

    @property
    def adder_running(self) -> bool:
        'True if `git add .` is running'
        return self._adder_process.state() != QProcess.ProcessState.NotRunning

    @property
    def adder_aborted(self) -> bool:
        'True if last `git add .` has been aborted by user'
        return self._adder_aborted

    @property
    def last_git_error(self) -> tuple[ray.Err, str, int]:
        return self._last_git_error

    @property
    def exclude_file(self) -> Path:
        if self.session.path is None:
            raise NoSessionPath
        return self.session.path / _GIT_DIR / _EXCLUDE_PATH

    @property
    def history_file(self) -> Path:
        if self.session.path is None:
            raise NoSessionPath
        return self.session.path / _GIT_DIR / _HISTORY_PATH

    def _run_git_process(self, *all_args) -> bool:
        if self.session.path is None:
            raise NoSessionPath
        return self._run_git_process_at(self.session.path, *all_args)

    def _run_git_process_at(
            self, spath: Path, *all_args: str) -> bool:
        if all_args:
            self._git_command = ' ' + ' '.join(all_args)
        else:
            self._git_command = ''

        err = ray.Err.OK
        exit_code = 0

        git_args = self._get_git_command_list_at(spath, *all_args)
        self._git_process.start(_GIT_EXEC, git_args)
        if not self._git_process.waitForFinished(2000):
            self._git_process.kill()
            err = ray.Err.SUBPROCESS_UNTERMINATED
        else:
            exit_code = self._git_process.exitCode()
            if self._git_process.exitStatus() == QProcess.ExitStatus.CrashExit:
                err = ray.Err.SUBPROCESS_CRASH
            elif exit_code:
                err = ray.Err.SUBPROCESS_EXITCODE

        self._last_git_error = (err, self._git_command, exit_code)

        return not bool(err)

    def _get_git_command_list(self, *args) -> list[str]:
        if self.session.path is None:
            raise NoSessionPath
        return self._get_git_command_list_at(self.session.path, *args)

    def _get_git_command_list_at(self, spath: Path, *args: str) -> list[str]:
        first_args = [
            '--work-tree', str(spath), '--git-dir', str(spath / _GIT_DIR)]
        return first_args + list(args)

    def _get_history_xml_root(self) -> Optional[Element]:
        if not self._is_init():
            return None
        
        file_path = self.history_file
        if not file_path.exists():
            return None
        
        try:
            with open(file_path, 'r') as file:
                tree = ET.parse(file)
        except BaseException as e:
            _logger.error(f'Failed to parse {file_path} as an XML file')
            _logger.error(str(e))
            return None
        
        root = tree.getroot()
        if root.tag != 'SNAPSHOTS':
            return None
        return root            

    def _get_tag_date(self) -> str:
        date_time = QDateTime.currentDateTimeUtc()
        date = date_time.date()
        time = date_time.time()

        return (f'{date.year()}_{date.month()}_{date.day()}_'
                f'{time.hour()}_{time.minute()}_{time.second()}')

    def _write_history_file(
            self, date_str: str, snapshot_name='', rewind_snapshot='') -> ray.Err:
        if self.session.path is None:
            return ray.Err.NO_SESSION_OPEN

        file_path = self.history_file

        try:
            tree = ET.parse(file_path)
            root = tree.getroot()
        except BaseException as e:
            _logger.info(str(e))
            root = ET.Element('SNAPSHOTS')
            tree = ET.ElementTree(root)

        root.tag = 'SNAPSHOTS'
        snapshot_el = ET.SubElement(root, 'Snapshot')
        s = XmlElement(snapshot_el)
        s.set_str('ref', date_str)
        s.set_str('name', snapshot_name)
        s.set_str('rewind_snapshot', rewind_snapshot)
        s.set_str('session_name', self.session.name)
        s.set_str('VERSION', ray.VERSION)
        
        for client in self.session.clients + self.session.trashed_clients:
            client_el = ET.SubElement(snapshot_el, 'client')
            c = XmlElement(client_el)
            client.write_xml_properties(c)
            c.set_str('client_id', client.client_id)
            
            for client_file_path in client.project_files:
                base_path = str(
                    client_file_path.relative_to(self.session.path))
                file_xml = ET.SubElement(client_el, 'file')
                fxl = XmlElement(file_xml)
                fxl.set_str('path', base_path)
                
        try:
            tree.write(str(file_path))
            return ray.Err.OK
        except BaseException as e:
            _logger.error(str(e))
            return ray.Err.CREATE_FAILED

    def _write_exclude_file(self) -> ray.Err:
        if self.session.path is None:
            raise NoSessionPath
        
        file_path = self.session.path / _GIT_DIR / _EXCLUDE_PATH

        contents = (
            "# This file is generated by ray-daemon at each snapshot\n"
            "# Don't edit this file.\n"
            "# If you want to add/remove files managed by git\n"
            "# Create/Edit .gitignore in the session folder\n"
            "\n"
            f"{_GIT_DIR}\n"
            "\n"
            "# Globally ignored extensions\n"
        )

        session_ignored_extensions = ray.GIT_IGNORED_EXTENSIONS
        session_ign_list = session_ignored_extensions.split(' ')
        session_ign_list = tuple(filter(bool, session_ign_list))

        # write global ignored extensions
        for extension in session_ign_list:
            contents += f'*{extension}\n'

            for client in self.session.clients:
                cext_list = client.ignored_extensions.split(' ')

                if not extension in cext_list:
                    contents += \
                        f'!{git_stringer(client.project_path)}/**/*{extension}\n'
                    contents += \
                        f'!{git_stringer(client.project_path)}.**/*{extension}\n'

        contents += '\n'
        contents += "# Extensions ignored by clients\n"

        # write client specific ignored extension
        for client in self.session.clients:
            cext_list = client.ignored_extensions.split(' ')
            for extension in cext_list:
                if not extension:
                    continue

                if extension in session_ignored_extensions:
                    continue

                contents += \
                    f'{git_stringer(client.project_path)}/**/*{extension}\n'
                contents += \
                    f'{git_stringer(client.project_path)}.**/*{extension}\n'

        contents += '\n'
        contents += "# Too big Files\n"

        no_check_list = (_GIT_DIR,)

        # check too big files
        for foldername, subfolders, filenames in os.walk(self.session.path):
            subfolders[:] = [d for d in subfolders if d not in no_check_list]
            folder = Path(foldername)

            if folder == self.session.path / _GIT_DIR:
                continue

            for filename in filenames:
                if filename.endswith(session_ign_list):
                    if os.path.islink(filename):
                        short_folder = folder.relative_to(self.session.path)
                        contents += \
                            f'!{git_stringer(short_folder / filename)}\n'

                    # file with extension globally ignored but
                    # unignored by its client will not be ignored
                    # and that is well as this.
                    continue

                if os.path.islink(filename):
                    continue

                try:
                    file_size = os.path.getsize(folder / filename)
                except:
                    continue

                if file_size > _MAX_FILE_SIZE * 1024 ** 2:
                    if folder == self.session.path:
                        line = git_stringer(filename)
                    else:
                        short_folder = folder.relative_to(self.session.path)
                        line = git_stringer(short_folder / filename)

                    contents += f'{line}\n'

        try:
            with open(file_path, 'w') as exclude_file:
                exclude_file.write(contents)
        except:
            return ray.Err.CREATE_FAILED

        return ray.Err.OK

    def _is_init(self) -> bool:
        if self.session.path is None:
            return False

        exclude_file = self.session.path / _GIT_DIR / _EXCLUDE_PATH
        return exclude_file.is_file()

    def _can_save(self) -> bool:
        if self.session.path is None:
            return False

        if not self._is_init():
            if self._run_git_process('init'):
                return False

            user_name = os.getenv('USER')
            if not user_name:
                user_name = 'someone'

            machine_name = socket.gethostname()
            if not machine_name:
                machine_name = 'somewhere'

            if not self._run_git_process(
                'config', 'user.email', f'{user_name}@{machine_name}'):
                return False

            if not self._run_git_process('config', 'user.name', user_name):
                return False

        if not self._is_init():
            return False

        return True

    def commit(self, snapshot_name: str,
               rw_snapshot: str) -> tuple[ray.Err, str]:
        if self._n_file_changed:
            if not self._run_git_process('commit', '-m', 'ray'):
                return ray.Err.GIT_ERROR, ''

        ref = ''
        if self._n_file_changed or snapshot_name or rw_snapshot:
            ref = self._get_tag_date()

            if not self._run_git_process('tag', '-a', ref, '-m', 'ray'):
                return ray.Err.GIT_ERROR, ''

            err = self._write_history_file(ref, snapshot_name, rw_snapshot)

            if err:
                return ray.Err.CREATE_FAILED, ref

        return ray.Err.OK, ref

    def list(self, client_id="") -> list[str]:
        root = self._get_history_xml_root()
        if root is None:
            return list[str]()

        all_tags = list[str]()
        all_snaps = list[tuple[str, str]]()
        prv_session_name = self.session.name
        
        for child in root:
            if client_id:
                for client_ch in child:
                    if client_ch.attrib.get('client_id') == client_id:
                        break
                else:
                    continue
            
            ref = child.attrib.get('ref', '')
            name = child.attrib.get('name', '')
            rw_sn = child.attrib.get('rewind_snapshot', '')
            rw_name = ''
            session_name = child.attrib.get('session_name', '')
            
            # don't list snapshot from client before session renamed
            if client_id and session_name != self.session.name:
                client = self.session.get_client(client_id)
                if (client
                        and (client.prefix_mode
                             is ray.PrefixMode.SESSION_NAME)):
                    continue
                
            ss_name = ""
            if session_name != prv_session_name:
                ss_name = session_name

            prv_session_name = session_name

            if not ref.replace('_', '').isdigit():
                continue

            if '\n' in name:
                name = ""

            if not rw_sn.replace('_', '').isdigit():
                rw_sn = ""

            if rw_sn:
                for snap in all_snaps:
                    if snap[0] == rw_sn and not '\n' in snap[1]:
                        rw_name = snap[1]
                        break
                    
            all_snaps.append((ref, name))
            all_tags.append(
                full_ref_for_gui(ref, name, rw_sn, rw_name, ss_name))

        all_tags.reverse()
        return all_tags

    def has_changes(self) -> bool:
        if self.session.path is None:
            return False

        if not self._is_init():
            _logger.info('session git project is not init.')
            return True

        if self._changes_checker.state() != QProcess.ProcessState.NotRunning:
            self._changes_checker.kill()

        self._n_file_changed = 0
        self._n_file_treated = 0
        self._changes_counted = True

        args = self._get_git_command_list(
            'ls-files', '--exclude-standard', '--others', '--modified')
        self._changes_checker.start(_GIT_EXEC, args)
        self._changes_checker.waitForFinished(2000)

        return bool(self._n_file_changed)

    def save(self) -> ray.Err:
        if not self._can_save():
            self.session.message("can't snapshot")
            return ray.Err.GIT_ERROR

        err = self._write_exclude_file()
        if err:
            return err

        self._adder_aborted = False

        if not self._changes_counted:
            self.has_changes()

        self._changes_counted = False

        if self._n_file_changed:
            all_args = self._get_git_command_list('add', '-A', '-v')
            self._adder_process.start(_GIT_EXEC, all_args)
        
        return ray.Err.OK

    def load(self, spath: Path, snapshot: str) -> ray.Err:
        snapshot_ref = snapshot.partition('\n')[0].partition(':')[0]

        if not self._run_git_process_at(spath, 'reset', '--hard'):
            return ray.Err.GIT_ERROR

        if not self._run_git_process_at(spath, 'checkout', snapshot_ref):
            return ray.Err.GIT_ERROR
        return ray.Err.OK

    def load_client_exclusive(self, client_id: str, snapshot: str) -> ray.Err:
        '''load a snapshot only for a client,
        it will change files affected by the client'''
        root = self._get_history_xml_root()
        if root is None:
            return ray.Err.NO_SUCH_FILE
        
        client_path_list = list[str]()
        
        for child in root:
            if child.attrib.get('ref') != snapshot:
                continue
            
            for client_ch in child:
                if client_ch.attrib.get('client_id') != client_id:
                    continue
                
                for file_ch in client_ch:
                    file_path = file_ch.attrib.get('path')
                    if file_path:
                        client_path_list.append(file_path)

        if not self._run_git_process('reset', '--hard'):
            return ray.Err.GIT_ERROR

        if not self._run_git_process(
                'checkout', snapshot, '--', *client_path_list):
            return ray.Err.GIT_ERROR
        return ray.Err.OK

    def abort(self):
        if self._adder_process.state() == QProcess.ProcessState.NotRunning:
            return

        self.set_auto_snapshot(False)

        self._adder_aborted = True
        self._adder_process.terminate()

    def set_auto_snapshot(self, bool_snapshot: bool):
        if self.session.path is None:
            return
        
        auto_snap_file = (
            self.session.path / _GIT_DIR / 'prevent_auto_snapshot')
        file_exists = auto_snap_file.exists()

        if bool_snapshot:
            if file_exists:
                try:
                    os.remove(auto_snap_file)
                except PermissionError:
                    return
        else:
            if not file_exists:
                contents = "# This file prevent auto snapshots for this session (RaySession)\n"
                contents += "# remove it if you want auto snapshots back"

                try:
                    with open(auto_snap_file, 'w') as file:
                        file.write(contents)
                except PermissionError:
                    return

    def is_auto_snapshot_prevented(self) -> bool:
        if self.session.path is None:
            return False

        auto_snap_file = (
            self.session.path / _GIT_DIR / 'prevent_auto_snapshot')
        return auto_snap_file.exists()
        
