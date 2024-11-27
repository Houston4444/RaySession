
# Imports from standard library
import os
import socket
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional
import xml.etree.ElementTree as ET

from qtpy.QtCore import QProcess, QObject, QDateTime
from qtpy.QtXml import QDomDocument, QDomElement

import ray
from xml_tools import XmlElement
from daemon_tools import Terminal

if TYPE_CHECKING:
    from session import Session
    
_logger = logging.getLogger(__name__)

def git_stringer(string:str) -> str:
    for char in (' ', '*', '?', '[', ']', '(', ')'):
        string = string.replace(char, "\\" + char)

    for char in ('#', '!'):
        if string.startswith(char):
            string = "\\" + string

    return string

def full_ref_for_gui(ref, name, rw_ref, rw_name='', ss_name=''):
    if ss_name:
        return "%s:%s\n%s:%s\n%s" % (ref, name, rw_ref, rw_name, ss_name)
    return "%s:%s\n%s:%s" % (ref, name, rw_ref, rw_name)


class Snapshoter(QObject):
    def __init__(self, session: 'Session'):
        QObject.__init__(self)
        self.session = session
        self._git_exec = 'git'
        self._gitdir = '.ray-snapshots'
        self._exclude_path = 'info/exclude'
        self._history_path = "session_history.xml"
        self._max_file_size = 50 #in Mb

        self._next_snapshot_name = ''
        self._rw_snapshot = ''

        self._changes_checker = QProcess()
        self._changes_checker.readyReadStandardOutput.connect(
            self._changes_checker_standard_output)

        self._adder_process = QProcess()
        self._adder_process.finished.connect(self._save_step_1)
        self._adder_process.readyReadStandardOutput.connect(
            self._adder_standard_output)

        self._adder_aborted = False

        self._git_process = QProcess()
        self._git_process.readyReadStandardOutput.connect(self._standard_output)
        self._git_process.readyReadStandardError.connect(self._standard_error)
        self._git_command = ''

        self._n_file_changed = 0
        self._n_file_treated = 0
        self._changes_counted = False

        self._next_function = None
        self._error_function = None

    def _changes_checker_standard_output(self):
        standard_output = self._changes_checker.readAllStandardOutput().data()
        self._n_file_changed += len(standard_output.splitlines()) -1

    def _adder_standard_output(self):
        standard_output = self._adder_process.readAllStandardOutput().data()
        Terminal.snapshoter_message(standard_output, ' add -A -v')

        if not self._n_file_changed:
            return

        self._n_file_treated += len(standard_output.splitlines()) -1

        self.session.send_gui('/ray/gui/server/progress',
                              self._n_file_treated / self._n_file_changed)

    def _standard_error(self):
        standard_error = self._git_process.readAllStandardError().data()
        Terminal.snapshoter_message(standard_error, self._git_command)

    def _standard_output(self):
        standard_output = self._git_process.readAllStandardOutput().data()
        Terminal.snapshoter_message(standard_output, self._git_command)

    def _run_git_process(self, *all_args) -> bool:
        return self._run_git_process_at(str(self.session.path), *all_args)

    def _run_git_process_at(self, spath: str, *all_args) -> bool:
        self._git_command = ''
        for arg in all_args:
            self._git_command += ' %s' % arg

        err = ray.Err.OK

        git_args = self._get_git_command_list_at(spath, *all_args)
        self._git_process.start(self._git_exec, git_args)
        if not self._git_process.waitForFinished(2000):
            self._git_process.kill()
            err = ray.Err.SUBPROCESS_UNTERMINATED
        else:
            if self._git_process.exitStatus() == QProcess.ExitStatus.CrashExit:
                err = ray.Err.SUBPROCESS_CRASH
            elif self._git_process.exitCode():
                err = ray.Err.SUBPROCESS_EXITCODE

        if err and self._error_function:
            self._error_function(err, ' '.join(all_args))

        return not bool(err)

    def _get_git_command_list(self, *args) -> list[str]:
        return self._get_git_command_list_at(str(self.session.path), *args)

    def _get_git_command_list_at(self, spath: str, *args) -> list[str]:
        first_args = ['--work-tree', spath, '--git-dir',
                      str(Path(spath) / self._gitdir)]
        return first_args + list(args)

    def _get_history_full_path(self) -> Path:
        return self.session.path / self._gitdir / self._history_path

    def _get_history_xml_document_element(self) -> Optional[QDomElement]:
        if not self._is_init():
            return None

        file_path = self._get_history_full_path()

        xml = QDomDocument()

        try:
            with open(file_path, 'r') as history_file:
                xml.setContent(history_file.read())
        except BaseException:
            return None

        SNS_xml = xml.documentElement()
        if SNS_xml.tagName() != 'SNAPSHOTS':
            return None

        return SNS_xml

    def _get_tag_date(self)->str:
        date_time = QDateTime.currentDateTimeUtc()
        date = date_time.date()
        time = date_time.time()

        tagdate = "%s_%s_%s_%s_%s_%s" % (
                    date.year(), date.month(), date.day(),
                    time.hour(), time.minute(), time.second())

        return tagdate

    def _write_history_file(self, date_str: str, snapshot_name='', rewind_snapshot='') -> int:
        if self.session.path is None:
            return ray.Err.NO_SESSION_OPEN

        file_path = self._get_history_full_path()

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
            
            for client_file_path in client.get_project_files():
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
            print('parlmdmmd')
            return ray.Err.CREATE_FAILED

    def _write_exclude_file(self) -> int:
        if self.session.path is None:
            return
        
        file_path = self.session.path / self._gitdir / self._exclude_path

        contents = ""
        contents += "# This file is generated by ray-daemon at each snapshot\n"
        contents += "# Don't edit this file.\n"
        contents += "# If you want to add/remove files managed by git\n"
        contents += "# Create/Edit .gitignore in the session folder\n"
        contents += "\n"
        contents += "%s\n" % self._gitdir
        contents += "\n"
        contents += "# Globally ignored extensions\n"

        session_ignored_extensions = ray.GIT_IGNORED_EXTENSIONS
        session_ign_list = session_ignored_extensions.split(' ')
        session_ign_list = tuple(filter(bool, session_ign_list))

        # write global ignored extensions
        for extension in session_ign_list:
            contents += "*%s\n" % extension

            for client in self.session.clients:
                cext_list = client.ignored_extensions.split(' ')

                if not extension in cext_list:
                    contents += "!%s.%s/**/*%s\n" % (
                        git_stringer(client.get_prefix_string()),
                        git_stringer(client.client_id),
                        extension)
                    contents += "!%s.%s.**/*%s\n" % (
                        git_stringer(client.get_prefix_string()),
                        git_stringer(client.client_id),
                        extension)

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

                contents += "%s.%s/**/*%s\n" % (
                    git_stringer(client.get_prefix_string()),
                    git_stringer(client.client_id),
                    extension)

                contents += "%s.%s.**/*%s\n" % (
                    git_stringer(client.get_prefix_string()),
                    git_stringer(client.client_id),
                    extension)

        contents += '\n'
        contents += "# Too big Files\n"

        no_check_list = (self._gitdir)
        # check too big files
        for foldername, subfolders, filenames in os.walk(self.session.path):
            subfolders[:] = [d for d in subfolders if d not in no_check_list]

            if foldername == str(self.session.path / self._gitdir):
                continue

            for filename in filenames:
                if filename.endswith(session_ign_list):
                    if os.path.islink(filename):
                        short_folder = Path(foldername).relative_to(self.session.path)
                        line = git_stringer("%s/%s" % (short_folder, filename))
                        contents += '!%s\n' % line
                    # file with extension globally ignored but
                    # unignored by its client will not be ignored
                    # and that is well as this.
                    continue

                if os.path.islink(filename):
                    continue

                try:
                    file_size = os.path.getsize(os.path.join(foldername,
                                                             filename))
                except:
                    continue

                if file_size > self._max_file_size * 1024 ** 2:
                    if foldername == str(self.session.path):
                        line = git_stringer(filename)
                    else:
                        short_folder = Path(foldername).relative_to(
                            self.session.path)
                        line = git_stringer("%s/%s" % (short_folder, filename))

                    contents += "%s\n" % line

        try:
            with open(file_path, 'w') as exclude_file:
                exclude_file.write(contents)
        except:
            return ray.Err.CREATE_FAILED

        return ray.Err.OK

    def _is_init(self) -> bool:
        if self.session.path is None:
            return False

        exclude_file = self.session.path / self._gitdir / self._exclude_path
        return exclude_file.is_file()

    def _can_save(self) -> bool:
        if self.session.path is None:
            return False

        if not self._is_init():
            if not self._run_git_process('init'):
                return False

            user_name = os.getenv('USER')
            if not user_name:
                user_name = 'someone'

            machine_name = socket.gethostname()
            if not machine_name:
                machine_name = 'somewhere'

            if not self._run_git_process(
                'config', 'user.email', '%s@%s' % (user_name, machine_name)):
                return False

            user_name = os.getenv('USER')
            if not user_name:
                user_name = 'someone'

            if not self._run_git_process('config', 'user.name', user_name):
                return False

        if not self._is_init():
            return False

        return True

    def _error_quit(self, err):
        if self._error_function:
            self._error_function(err)
        self._error_function = None

    def _save_step_1(self):
        if self._adder_aborted:
            if self._next_function:
                self._next_function(aborted=True)
            return

        if self._n_file_changed:
            if not self._run_git_process('commit', '-m', 'ray'):
                return

        if (self._n_file_changed
                or self._next_snapshot_name or self._rw_snapshot):
            ref = self._get_tag_date()

            if not self._run_git_process('tag', '-a', ref, '-m', 'ray'):
                return

            err = self._write_history_file(
                ref, self._next_snapshot_name, self._rw_snapshot)

            if err:
                if self._error_function:
                    self._error_function(err)

            # not really a reply, not strong.
            self.session.send_gui(
                '/reply',
                '/ray/session/list_snapshots',
                full_ref_for_gui(ref, self._next_snapshot_name,
                                 self._rw_snapshot))

        self._error_function = None
        self._next_snapshot_name = ''
        self._rw_snapshot = ''

        if self._next_function:
            self._next_function()

    def list(self, client_id="") -> list[str]:
        SNS_xml = self._get_history_xml_document_element()
        if not SNS_xml:
            return []

        nodes = SNS_xml.childNodes()

        all_tags = list[str]()
        all_snaps = list[tuple[str, str]]()
        prv_session_name = self.session.name

        for i in range(nodes.count()):
            node = nodes.at(i)
            el = node.toElement()

            if client_id:
                client_nodes = node.childNodes()
                for j in range(client_nodes.count()):
                    client_node = client_nodes.at(j)
                    client_el = client_node.toElement()
                    if client_el.attribute('client_id') == client_id:
                        break
                else:
                    continue

            ref = el.attribute('ref')
            name = el.attribute('name')
            rw_sn = el.attribute('rewind_snapshot')
            rw_name = ""
            session_name = el.attribute('session_name')

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
            snapsss = full_ref_for_gui(ref, name, rw_sn, rw_name, ss_name)
            all_tags.append(snapsss)

        all_tags.reverse()
        return all_tags

    def has_changes(self) -> bool:
        if self.session.path is None:
            return False

        if not self._is_init():
            return True

        if self._changes_checker.state() != QProcess.ProcessState.NotRunning:
            self._changes_checker.kill()

        self._n_file_changed = 0
        self._n_file_treated = 0
        self._changes_counted = True

        args = self._get_git_command_list(
            'ls-files', '--exclude-standard', '--others', '--modified')
        self._changes_checker.start(self._git_exec, args)
        self._changes_checker.waitForFinished(2000)

        return bool(self._n_file_changed)

    def save(self, name='', rewind_snapshot='',
             next_function=None, error_function=None):
        self._next_snapshot_name = name
        self._rw_snapshot = rewind_snapshot
        self._next_function = next_function
        self._error_function = error_function

        if not self._can_save():
            Terminal.message("can't snapshot")
            return

        err = self._write_exclude_file()
        if err:
            self._error_quit(err)
            return

        self._adder_aborted = False

        if not self._changes_counted:
            self.has_changes()

        self._changes_counted = False

        if self._n_file_changed:
            all_args = self._get_git_command_list('add', '-A', '-v')
            self._adder_process.start(self._git_exec, all_args)
        else:
            self._save_step_1()

        # self.adder_process.finished is connected to self._save_step_1

    def load(self, spath: Path, snapshot: str, error_function: Callable):
        self._error_function = error_function

        snapshot_ref = snapshot.partition('\n')[0].partition(':')[0]

        if not self._run_git_process_at(str(spath), 'reset', '--hard'):
            return False

        if not self._run_git_process_at(str(spath), 'checkout', snapshot_ref):
            return False
        return True

    def load_client_exclusive(self, client_id: str, snapshot: str,
                              error_function: Callable):
        self._error_function = error_function

        SNS_xml = self._get_history_xml_document_element()
        if not SNS_xml:
            self._error_function(ray.Err.NO_SUCH_FILE,
                                 str(self._get_history_full_path()))
            return False

        nodes = SNS_xml.childNodes()

        client_path_list = list[str]()

        for i in range(nodes.count()):
            node = nodes.at(i)
            el = node.toElement()

            if el.attribute('ref') != snapshot:
                continue

            client_nodes = node.childNodes()

            for j in range(client_nodes.count()):
                client_node = client_nodes.at(j)
                client_el = client_node.toElement()

                if client_el.attribute('client_id') != client_id:
                    continue

                file_nodes = client_node.childNodes()

                for k in range(file_nodes.count()):
                    file_node = file_nodes.at(k)
                    file_el = file_node.toElement()
                    file_path = file_el.attribute('path')
                    if file_path:
                        client_path_list.append(file_path)

        if not self._run_git_process('reset', '--hard'):
            return False

        if not self._run_git_process('checkout', snapshot, '--',
                                  *client_path_list):
            return False
        return True

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
            self.session.path / self._gitdir / 'prevent_auto_snapshot')
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
            self.session.path / self._gitdir / 'prevent_auto_snapshot')
        return auto_snap_file.exists()
        
