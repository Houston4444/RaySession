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
        self.client_id = ''
        self.next_function = None
        self.abort_function = None
        self.next_args = []
        self.copy_files = []
        self.copy_size = 0
        self.aborted = False
        self.is_active = False

        self.process = QProcess()
        self.process.finished.connect(self.processFinished)
        if ray.QT_VERSION >= (5, 6):
            self.process.errorOccurred.connect(self.errorOccurred)

        self.timer = QTimer()
        self.timer.setInterval(250)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.checkProgressSize)

        self._abort_src_addr = None
        self._abort_src_path = ''

    def informCopytoGui(self, copy_state):
        server = OscServerThread.getInstance()
        if not server:
            return

        server.informCopytoGui(copy_state)

    def getFileSize(self, filepath):
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

    def checkProgressSize(self):
        current_size = 0
        self.timer.stop()

        for copy_file in self.copy_files:
            if copy_file.state == 2:
                current_size += copy_file.size
            elif copy_file.state == 1:
                current_size += self.getFileSize(copy_file.dest_path)
                break

        if current_size and self.copy_size:
            progress = float(current_size/self.copy_size)

            if self.client_id:
                self.sendGui('/ray/gui/client/progress', self.client_id, progress)
            else:
                self.sendGui('/ray/gui/server/progress', progress)

            self.session.oscReply('/ray/net_daemon/duplicate_state', progress)

        self.timer.start()

    def processFinished(self, exit_code, exit_status):
        self.timer.stop()

        for copy_file in self.copy_files:
            if copy_file.state == 1:
                copy_file.state = 2
                break

        if self.aborted:
            ##remove all created files
            for copy_file in self.copy_files:
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


            self.is_active = False
            self.informCopytoGui(False)
            self.abort_function(*self.next_args)
            return

        #run next_function if copy is terminated
        for copy_file in self.copy_files:
            if copy_file.state != 2:
                break
        else:
            self.is_active = False
            self.informCopytoGui(False)

            if self.next_function:
                self.next_function(*self.next_args)

            return

        self.nextProcess()

    def errorOccurred(self):
        #todo make something else
        self.processFinished(0, 0)

    def nextProcess(self):
        self.is_active = True

        for copy_file in self.copy_files:
            if copy_file.state == 0:
                copy_file.state = 1
                self.process.start('nice',
                                   ['-n', '+15', 'cp', '-R',
                                    copy_file.orig_path, copy_file.dest_path])
                break

        self.timer.start()

    def start(self, src_list, dest_dir, next_function,
              abort_function, next_args=[]):
        self.abort_function = abort_function
        self.next_function = next_function
        self.next_args = next_args

        self.aborted = False
        self.copy_size = 0
        self.copy_files.clear()

        dest_path_exists = bool(os.path.exists(dest_dir))
        if dest_path_exists:
            if not os.path.isdir(dest_dir):
                #TODO send error, but it should not append
                self.abort_function(*self.next_args)
                return

        if isinstance(src_list, str):
            src_dir = src_list
            src_list = []

            if not os.path.isdir(src_dir):
                self.abort_function(*self.next_args)
                return

            try:
                tmp_list = os.listdir(src_dir)
            except:
                self.abort_function(*self.next_args)
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
                    self.abort_function(*self.next_args)
                    return

        for orig_path in src_list:
            copy_file = CopyFile()
            copy_file.state = 0
            copy_file.orig_path = orig_path
            copy_file.size = self.getFileSize(orig_path)

            self.copy_size += copy_file.size

            if dest_path_exists:
                copy_file.dest_path = "%s/%s" % (dest_dir,
                                                 os.path.basename(orig_path))
            else:
                #WARNING works only with one file !!!
                copy_file.dest_path = dest_dir

            self.copy_files.append(copy_file)


        if self.copy_files:
            self.informCopytoGui(True)
            self.nextProcess()
        else:
            self.next_function(*self.next_args)

    def startClientCopy(self, client_id, src_list, dest_dir, next_function,
                        abort_function, next_args=[]):
        self.client_id = client_id
        self.start(src_list, dest_dir, next_function,
                   abort_function, next_args)

    def startSessionCopy(self, src_dir, dest_dir, next_function,
                         abort_function, next_args=[]):
        self.client_id = ''
        self.start(src_dir, dest_dir, next_function,
                   abort_function, next_args)

    def abort(self, abort_function=None, next_args=[]):
        if abort_function:
            self.abort_function = abort_function
            self.next_args = next_args

        self.timer.stop()

        if self.process.state() == QProcess.Running:
            self.aborted = True
            self.process.terminate()

    def abortFrom(self, src_addr, src_path):
        self.abort()

    def isActive(self, client_id=''):
        if client_id and client_id != self.client_id:
            return False

        return self.is_active
