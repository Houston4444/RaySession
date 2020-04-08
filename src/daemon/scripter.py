import os
from PyQt5.QtCore import QProcess, QProcessEnvironment, QCoreApplication

import ray
from daemon_tools import Terminal
from server_sender import ServerSender

_translate = QCoreApplication.translate

class Scripter(ServerSender):
    def __init__(self):
        ServerSender.__init__(self)
        self.src_adrr = None
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
                        'script %s terminate whit exit code %i') % (
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
    
    def start(self, executable, arguments, src_addr=None, src_path=''):
        if self.isRunning():
            return
        
        self.src_addr = src_addr
        self.src_path = src_path
        
        process_env = QProcessEnvironment.systemEnvironment()
        process_env.insert('RAY_SCRIPTS_DIR', os.path.dirname(executable))
        self._process.setProcessEnvironment(process_env)
        self._process.start(executable, arguments)
    
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
    
    def getScriptsDir(self, spath):
        if not spath:
            return ''
        
        base_path = spath
        while not os.path.isdir("%s/%s" % (base_path, ray.SCRIPTS_DIR)):
            base_path = os.path.dirname(base_path)
            if base_path == "/":
                return ''
        
        return "%s/%s" % (base_path, ray.SCRIPTS_DIR)
    

class StepScripter(Scripter):
    def __init__(self, session):
        Scripter.__init__(self)
        self.session = session
        self._step_str = ''
        self._stepper_has_call = False
        
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
        
        scripts_dir = self.getScriptsDir(self.session.path)
        if not scripts_dir:
            return False
        
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
        process_env.insert('RAY_SCRIPTS_DIR', scripts_dir)
        process_env.insert('RAY_FUTURE_SESSION_PATH',
                           self.session.future_session_path)
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
    
    def start(self, executable, arguments, src_addr=None, src_path=''):
        if self.isRunning():
            return
        
        self.src_addr = src_addr
        self.src_path = src_path
        
        process_env = QProcessEnvironment.systemEnvironment()
        process_env.insert('RAY_SCRIPTS_DIR', os.path.dirname(executable))
        
        # TODO set client env vars
        #self.client.setScriptEnvironment(process_env)
            
        self._process.setProcessEnvironment(process_env)
        self.client.sendGuiMessage(
            _translate('GUIMSG', '--- Custom script %s started...%s')
                            % (ray.highlightText(executable), self.parent.client_id))
        self._process.start(executable, arguments)
        
    def setPendingCommand(self, pending_command):
        self._pending_command = pending_command
        
    def pendingCommand(self):
        return self._pending_command
    
    def stockInitialCaller(self, slot):
        self._initial_caller = slot
        
    def initialCaller(self):
        return self._initial_caller
    
