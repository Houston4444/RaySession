import os
from PyQt5.QtCore import QProcess, QProcessEnvironment, QCoreApplication

import ray
from daemon_tools import Terminal
from server_sender import ServerSender

_translate = QCoreApplication.translate

class Scripter(ServerSender):
    def __init__(self):
        ServerSender.__init__(self)
        self.src_addr = None
        self.src_path = ''
        
        self._process = QProcess()
        self._process.started.connect(self.processStarted)
        self._process.finished.connect(self.processFinished)
        self._process.readyReadStandardError.connect(self.standardError)
        self._process.readyReadStandardOutput.connect(self.standardOutput)
        
        self._asked_for_terminate = False
        
    def processStarted(self):
        pass
    
    def processFinished(self, exit_code, exit_status):
        if exit_code:
            if exit_code == 101:
                message = _translate('GUIMSG', 
                            'script %s failed to start !') % (
                                ray.highlightText(self.getPath()))
            else:
                message = _translate('GUIMSG', 
                        'script %s terminated with exit code %i') % (
                            ray.highlightText(self.getPath()), exit_code)
            
            if self.src_addr:
                self.send(self.src_addr, '/error', self.src_path,
                          - exit_code, message)
        else:
            self.sendGuiMessage(
                _translate('GUIMSG', '...script %s finished. ---')
                    % ray.highlightText(self.getPath()))
            
            if self.src_addr:
                self.send(self.src_addr, '/reply',
                          self.src_path, 'script finished')
    
    def standardError(self):
        standard_error = self._process.readAllStandardError().data()
        Terminal.scripterMessage(standard_error, self.getCommandName())
        
    def standardOutput(self):
        standard_output = self._process.readAllStandardOutput().data()
        Terminal.scripterMessage(standard_output, self.getCommandName())
    
    def isRunning(self):
        return bool(self._process.state())
    
    def isFinished(self):
        return not bool(self._process.state())
    
    def terminate(self):
        self._asked_for_terminate = True
        self._process.terminate()
    
    def isAskedForTerminate(self):
        return self._asked_for_terminate
    
    def kill(self):
        self._process.kill()
    
    def getPath(self):
        return self._process.program()
    
    def getCommandName(self):
        return self.getPath().rpartition('/')[2]
    
    def getPid(self):
        if self._process.state():
            return self._process.pid()
        return 0
    

class StepScripter(Scripter):
    def __init__(self, session):
        Scripter.__init__(self)
        self.session = session
        self._step_str = ''
        self._stepper_has_call = False
    
    def getScriptDirs(self, spath):
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
                
            base_path = os.path.dirname(base_path)
        
        return (scripts_dir, parent_scripts_dir)
    
    def processStarted(self):
        pass
    
    def processFinished(self, exit_code, exit_status):
        Scripter.processFinished(self, exit_code, exit_status)
        #self.session.endTimerIfScriptFinished()
        self.session.stepScripterFinished()
        self._stepper_has_call = False
    
    def start(self, step_str, arguments, src_addr=None, src_path=''):
        if self.isRunning():
            return False
        
        if not self.session.path:
            return False
        
        scripts_dir, parent_scripts_dir = self.getScriptDirs(
                                                            self.session.path)
        future_scripts_dir, future_parent_scripts_dir = self.getScriptDirs(
                                            self.session.future_session_path)
        
        script_path = "%s/%s.sh" % (scripts_dir, step_str)        
        if not os.access(script_path, os.X_OK):
            return False
        
        self.src_addr = src_addr
        self.src_path = src_path
        
        self._stepper_has_call = False
        self._step_str = step_str
        
        self.sendGuiMessage(_translate('GUIMSG',
                            '--- Custom step script %s started...')
                            % ray.highlightText(script_path))
        
        process_env = QProcessEnvironment.systemEnvironment()
        process_env.insert('RAY_CONTROL_PORT', str(self.getServerPort()))
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
    
    def setStep(self, text):
        self._step_str = text
        
    def getStep(self):
        return self._step_str
    
    def stepperHasCalled(self):
        return self._stepper_has_call
    
    def setStepperHasCall(self, bool_call):
        self._stepper_has_call = bool_call


class ClientScripter(Scripter):
    def __init__(self, client):
        Scripter.__init__(self)
        self.client = client
        self._pending_command = ray.Command.NONE
        self._initial_caller = (None, '')
    
    def processFinished(self, exit_code, exit_status):
        Scripter.processFinished(self, exit_code, exit_status)
        self.client.scriptFinished(exit_code)
        self._pending_command = ray.Command.NONE
        self._initial_caller = (None, '')
        self.src_addr = None
    
    def start(self, command, src_addr=None, previous_slot=(None, '')):
        if self.isRunning():
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
            (self.client.session.path, ray.SCRIPTS_DIR, self.client.client_id)
        script_path = "%s/%s.sh" % (scripts_dir, command_string)
        
        if not os.access(script_path, os.X_OK):
            return False
        
        self._pending_command = command
        
        if src_addr:
            # Remember the caller of the function calling the script
            # Then, when script is finished
            # We could reply to this (address, path)
            self._initial_caller = previous_slot
        
        self.src_addr = src_addr
        
        process_env = QProcessEnvironment.systemEnvironment()
        process_env.insert('RAY_CONTROL_PORT', str(self.getServerPort()))
        process_env.insert('RAY_CLIENT_SCRIPTS_DIR', scripts_dir)
        process_env.insert('RAY_CLIENT_ID', self.client.client_id)
        process_env.insert('RAY_CLIENT_EXECUTABLE',
                           self.client.executable_path)
        process_env.insert('RAY_CLIENT_ARGUMENTS', self.client.arguments)
        self._process.setProcessEnvironment(process_env)
        
        self.client.sendGuiMessage(
            _translate('GUIMSG', '--- Custom script %s started...%s')
                    % (ray.highlightText(script_path), self.client.client_id))
        
        self._process.start(script_path, [])
        return True
        
    def pendingCommand(self):
        return self._pending_command
        
    def initialCaller(self):
        return self._initial_caller
    
