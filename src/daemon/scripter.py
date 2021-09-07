import os
from PyQt5.QtCore import QProcess, QProcessEnvironment, QCoreApplication

import ray
from daemon_tools import Terminal, dirname
from server_sender import ServerSender

_translate = QCoreApplication.translate

class Scripter(ServerSender):
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
                                ray.highlightText(self.get_path()))
            else:
                message = _translate('GUIMSG',
                        'script %s terminated with exit code %i') % (
                            ray.highlightText(self.get_path()), exit_code)

            if self._src_addr:
                self.send(self._src_addr, '/error', self._src_path,
                          - exit_code, message)
        else:
            self.send_gui_message(
                _translate('GUIMSG', '...script %s finished. ---')
                    % ray.highlightText(self.get_path()))

            if self._src_addr:
                self.send(self._src_addr, '/reply',
                          self._src_path, 'script finished')

    def _standard_error(self):
        standard_error = self._process.readAllStandardError().data()
        Terminal.scripter_message(standard_error, self._get_command_name())

    def _standard_output(self):
        standard_output = self._process.readAllStandardOutput().data()
        Terminal.scripter_message(standard_output, self._get_command_name())

    def is_running(self):
        return bool(self._process.state())

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

    def get_pid(self):
        if self._process.state():
            return self._process.pid()
        return 0


class StepScripter(Scripter):
    def __init__(self, session):
        Scripter.__init__(self)
        self.session = session
        self._step_str = ''
        self._stepper_has_call = False

    def _get_script_dirs(self, spath):
        base_path = spath
        scripts_dir = ''
        parent_scripts_dir = ''

        while base_path not in ('/', ''):
            tmp_scripts_dir = "%s/%s" % (base_path, ray.SCRIPTS_DIR)
            if os.path.isdir(tmp_scripts_dir):
                if not scripts_dir:
                    scripts_dir = tmp_scripts_dir
                else:
                    parent_scripts_dir = tmp_scripts_dir
                    break

            base_path = dirname(base_path)

        return (scripts_dir, parent_scripts_dir)

    def _process_started(self):
        pass

    def _process_finished(self, exit_code, exit_status):
        Scripter._process_finished(self, exit_code, exit_status)
        #self.session.endTimerIfScriptFinished()
        self.session.stepScripterFinished()
        self._stepper_has_call = False

    def start(self, step_str, arguments, src_addr=None, src_path=''):
        if self.is_running():
            return False

        if not self.session.path:
            return False

        scripts_dir, parent_scripts_dir = self._get_script_dirs(
                                                            self.session.path)
        future_scripts_dir, future_parent_scripts_dir = self._get_script_dirs(
                                            self.session.future_session_path)

        script_path = "%s/%s.sh" % (scripts_dir, step_str)
        if not os.access(script_path, os.X_OK):
            return False

        self._src_addr = src_addr
        self._src_path = src_path

        self._stepper_has_call = False
        self._step_str = step_str

        self.send_gui_message(_translate('GUIMSG',
                            '--- Custom step script %s started...')
                            % ray.highlightText(script_path))

        process_env = QProcessEnvironment.systemEnvironment()
        process_env.insert('RAY_CONTROL_PORT', str(self.get_server_port()))
        process_env.insert('RAY_SCRIPTS_DIR', scripts_dir)
        process_env.insert('RAY_PARENT_SCRIPTS_DIR', parent_scripts_dir)
        process_env.insert('RAY_FUTURE_SESSION_PATH',
                           self.session.future_session_path)
        process_env.insert('RAY_FUTURE_SCRIPTS_DIR', future_scripts_dir)
        process_env.insert('RAY_SWITCHING_SESSION',
                           str(self.session.switching_session).lower())
        process_env.insert('RAY_SESSION_PATH', self.session.path)

        self._process.setProcessEnvironment(process_env)
        self._process.start(script_path, [str(a) for a in arguments])
        return True

    def get_step(self):
        return self._step_str

    def stepper_has_called(self):
        return self._stepper_has_call

    def set_stepper_has_call(self, call: bool):
        self._stepper_has_call = call


class ClientScripter(Scripter):
    def __init__(self, client):
        Scripter.__init__(self)
        self._client = client
        self._pending_command = ray.Command.NONE
        self._initial_caller = (None, '')

    def _process_finished(self, exit_code, exit_status):
        Scripter._process_finished(self, exit_code, exit_status)
        self._client.script_finished(exit_code)
        self._pending_command = ray.Command.NONE
        self._initial_caller = (None, '')
        self._src_addr = None

    def start(self, command, src_addr=None, previous_slot=(None, '')):
        if self.is_running():
            return False

        command_string = ''
        if command == ray.Command.START:
            command_string = 'start'
        elif command == ray.Command.SAVE:
            command_string = 'save'
        elif command == ray.Command.STOP:
            command_string = 'stop'
        else:
            return False

        scripts_dir = "%s/%s.%s" % \
            (self._client.session.path, ray.SCRIPTS_DIR, self._client.client_id)
        script_path = "%s/%s.sh" % (scripts_dir, command_string)

        if not os.access(script_path, os.X_OK):
            return False

        self._pending_command = command

        if src_addr:
            # Remember the caller of the function calling the script
            # Then, when script is finished
            # We could reply to this (address, path)
            self._initial_caller = previous_slot

        self._src_addr = src_addr

        process_env = QProcessEnvironment.systemEnvironment()
        process_env.insert('RAY_CONTROL_PORT', str(self.get_server_port()))
        process_env.insert('RAY_CLIENT_SCRIPTS_DIR', scripts_dir)
        process_env.insert('RAY_CLIENT_ID', self._client.client_id)
        process_env.insert('RAY_CLIENT_EXECUTABLE',
                           self._client.executable_path)
        process_env.insert('RAY_CLIENT_ARGUMENTS', self._client.arguments)
        self._process.setProcessEnvironment(process_env)

        self.send_gui_message(
            _translate('GUIMSG', '--- Custom script %s started...%s')
                    % (ray.highlightText(script_path), self._client.client_id))

        self._process.start(script_path, [])
        return True

    def pending_command(self):
        return self._pending_command

    def initial_caller(self):
        return self._initial_caller
