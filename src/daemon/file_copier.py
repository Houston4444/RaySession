import os
import subprocess
import warnings

from PyQt5.QtCore import QProcess, QTimer
from osc_server_thread import OscServerThread
from server_sender import ServerSender
import ray

class CopyFile:
    orig_path = ""
    dest_path = ""
    state = 0
    size = 0

class FileCopier(ServerSender):
    def __init__(self, session):
        ServerSender.__init__(self)
        self.session = session
        self._client_id = ''
        self._next_function = None
        self._abort_function = None
        self._next_args = []
        self._copy_files = []
        self._copy_size = 0
        self._aborted = False
        self._is_active = False

        self._process = QProcess()
        self._process.finished.connect(self._process_finished)
        if ray.QT_VERSION >= (5, 6):
            self._process.errorOccurred.connect(self._error_occurred)

        self._timer = QTimer()
        self._timer.setInterval(250)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._check_progress_size)

        self._abort_src_addr = None
        self._abort_src_path = ''

    def _inform_copy_to_gui(self, copy_state):
        server = OscServerThread.getInstance()
        if not server:
            return

        server.inform_copy_to_gui(copy_state)

    def _get_file_size(self, filepath):
        if not os.path.exists(filepath):
            return 0

        try:
            du_full = subprocess.check_output(
                ['nice', '-n', '15', 'du', '-sb', filepath]).decode()
        except:
            warnings.warn('unable to decode size of file %s' % filepath)
            du_full = ""

        if not du_full:
            return 0

        du_str = du_full.split('\t')[0]
        if not du_str.isdigit():
            return 0

        return int(du_str)

    def _check_progress_size(self):
        current_size = 0
        self._timer.stop()

        for copy_file in self._copy_files:
            if copy_file.state == 2:
                current_size += copy_file.size
            elif copy_file.state == 1:
                current_size += self._get_file_size(copy_file.dest_path)
                break

        if current_size and self._copy_size:
            progress = float(current_size/self._copy_size)

            if self._client_id:
                self.send_gui('/ray/gui/client/progress', self._client_id, progress)
            else:
                self.send_gui('/ray/gui/server/progress', progress)

            self.session.osc_reply('/ray/net_daemon/duplicate_state', progress)

        self._timer.start()

    def _process_finished(self, exit_code, exit_status):
        self._timer.stop()

        for copy_file in self._copy_files:
            if copy_file.state == 1:
                copy_file.state = 2
                break

        if self._aborted:
            ##remove all created files
            for copy_file in self._copy_files:
                if copy_file.state > 0:
                    file_to_remove = copy_file.dest_path

                    if os.path.exists(file_to_remove):
                        try:
                            subprocess.run(['rm', '-R', file_to_remove])
                        except:
                            if self._abort_src_addr and self._abort_src_path:
                                self.send(self._abort_src_addr,
                                          '/error_minor',
                                          self._abort_src_path,
                                          ray.Err.SUBPROCESS_CRASH,
                                          "%s hasn't been removed !")


            self._is_active = False
            self._inform_copy_to_gui(False)
            self._abort_function(*self._next_args)
            return

        #run next_function if copy is terminated
        for copy_file in self._copy_files:
            if copy_file.state != 2:
                break
        else:
            self._is_active = False
            self._inform_copy_to_gui(False)

            if self._next_function:
                self._next_function(*self._next_args)

            return

        self._next_process()

    def _error_occurred(self):
        #todo make something else
        self._process_finished(0, 0)

    def _next_process(self):
        self._is_active = True

        for copy_file in self._copy_files:
            if copy_file.state == 0:
                copy_file.state = 1
                self._process.start('nice',
                                   ['-n', '+15', 'cp', '-R',
                                    copy_file.orig_path, copy_file.dest_path])
                break

        self._timer.start()

    def _start(self, src_list, dest_dir, next_function,
              abort_function, next_args=[]):
        self._abort_function = abort_function
        self._next_function = next_function
        self._next_args = next_args

        self._aborted = False
        self._copy_size = 0
        self._copy_files.clear()

        dest_path_exists = bool(os.path.exists(dest_dir))
        if dest_path_exists:
            if not os.path.isdir(dest_dir):
                #TODO send error, but it should not append
                self._abort_function(*self._next_args)
                return

        if isinstance(src_list, str):
            src_dir = src_list
            src_list = []

            if not os.path.isdir(src_dir):
                self._abort_function(*self._next_args)
                return

            try:
                tmp_list = os.listdir(src_dir)
            except:
                self._abort_function(*self._next_args)
                return

            for path in tmp_list:
                if path == '.ray-snapshots':
                    continue

                full_path = "%s/%s" % (src_dir, path)
                src_list.append(full_path)

            if not dest_path_exists:
                try:
                    os.makedirs(dest_dir)
                except:
                    self._abort_function(*self._next_args)
                    return

        for orig_path in src_list:
            copy_file = CopyFile()
            copy_file.state = 0
            copy_file.orig_path = orig_path
            copy_file.size = self._get_file_size(orig_path)

            self._copy_size += copy_file.size

            if dest_path_exists:
                copy_file.dest_path = "%s/%s" % (dest_dir,
                                                 os.path.basename(orig_path))
            else:
                #WARNING works only with one file !!!
                copy_file.dest_path = dest_dir

            self._copy_files.append(copy_file)


        if self._copy_files:
            self._inform_copy_to_gui(True)
            self._next_process()
        else:
            self._next_function(*self._next_args)

    def start_client_copy(self, client_id, src_list, dest_dir, next_function,
                        abort_function, next_args=[]):
        self._client_id = client_id
        self._start(src_list, dest_dir, next_function,
                   abort_function, next_args)

    def start_session_copy(self, src_dir, dest_dir, next_function,
                         abort_function, next_args=[]):
        self._client_id = ''
        self._start(src_dir, dest_dir, next_function,
                   abort_function, next_args)

    def abort(self, abort_function=None, next_args=[]):
        if abort_function:
            self._abort_function = abort_function
            self._next_args = next_args

        self._timer.stop()

        if self._process.state() == QProcess.Running:
            self._aborted = True
            self._process.terminate()

    def is_active(self, client_id=''):
        if client_id and client_id != self._client_id:
            return False

        return self._is_active
