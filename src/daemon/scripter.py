import os
from PyQt5.QtCore import QProcess, QProcessEnvironment, QCoreApplication

import ray
from daemon_tools import Terminal
from server_sender import ServerSender

_translate = QCoreApplication.translate

class Scripter(ServerSender):
    def __init__(self, parent):
        ServerSender.__init__(self)
        self.parent = parent
        self.src_addr = None
        self.src_path = ''
        self._process = QProcess()
        self._process.started.connect(self.processStarted)
        self._process.finished.connect(self.processFinished)
        self._process.readyReadStandardError.connect(self.standardError)
        self._process.readyReadStandardOutput.connect(self.standardOutput)
        #if ray.QT_VERSION >= (5, 6):
            #self._process.errorOccurred.connect(self.errorInProcess)
        
        self._is_stepper = False
        self._step_str = ''
        self._stepper_has_call = False
        self._pending_command = ray.Command.NONE
        self._initial_caller = (None, '')
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
            
        if self._step_str:
            self.parent.stepperScriptFinished()
    
    def errorInProcess(self, error):
        if error == QProcess.Crashed and self._asked_for_terminate:
            return
        self.parent.scriptFinished(self.getPath(), 101)
    
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
        
        self._stepper_has_call = False
        
        process_env = QProcessEnvironment.systemEnvironment()
        process_env.insert('RAY_SCRIPTS_DIR', os.path.dirname(executable))
        if self.isStepper():
            self.parent.setScriptEnvironment(process_env)
            
        self._process.setProcessEnvironment(process_env)
        #self.parent.sendGuiMessage(
            #_translate('GUIMSG', '--- Custom script %s started...%s')
                            #% (ray.highlightText(executable), self.parent.client_id))
        #self._process.setProcessEnvironment('RAY_SCRIPTS_DIR', os.path.dirname(executable))
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

    def isStepper(self):
        return bool(self._step_str)
    
    def setStep(self, text):
        self._step_str = text
        
    def getStep(self):
        return self._step_str
    
    def stepperHasCalled(self):
        return self._stepper_has_call
    
    def setStepperHasCall(self, bool_call):
        self._stepper_has_call = bool_call
    
    def setPendingCommand(self, pending_command):
        self._pending_command = pending_command
        
    def pendingCommand(self):
        return self._pending_command
    
    def getPid(self):
        if self._process.state():
            return self._process.pid()
        return 0
    
    def stockInitialCaller(self, slot):
        self._initial_caller = slot
        
    def initialCaller(self):
        return self._initial_caller
