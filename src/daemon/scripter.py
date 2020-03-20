
from PyQt5.QtCore import QProcess, QCoreApplication

import ray
from daemon_tools import Terminal

_translate = QCoreApplication.translate

class Scripter:
    def __init__(self, parent, src_addr, src_path):
        self.parent = parent
        self.src_addr = src_addr
        self.src_path = src_path
        self._process = QProcess()
        self._process.started.connect(self.processStarted)
        self._process.finished.connect(self.processFinished)
        self._process.readyReadStandardError.connect(self.standardError)
        self._process.readyReadStandardOutput.connect(self.standardOutput)
        if ray.QT_VERSION >= (5, 6):
            self._process.errorOccurred.connect(self.errorInProcess)
        
        self._is_stepper = False
        self._stepper_process = ''
        self._stepper_has_call = False
        self._client_id = ''
        self._pending_command = ray.Command.NONE
        self._initial_caller = (None, '')
        
    def processStarted(self):
        pass
    
    def processFinished(self, exit_code, exit_status):
        #self.signaler.script_finished.emit(self.getPath(), exit_code, self._client_id)
        self.parent.scriptFinished(self.getPath(), exit_code)
    
    def errorInProcess(self):
        #self.signaler.script_finished.emit(self.getPath(), 101)
        self.parent.scriptFinished(self.getPath(), 101)
    
    def standardError(self):
        standard_error = self._process.readAllStandardError().data()
        Terminal.scripterMessage(standard_error, self.getCommandName())
        
    def standardOutput(self):
        standard_output = self._process.readAllStandardOutput().data()
        Terminal.scripterMessage(standard_output, self.getCommandName())
    
    def start(self, executable, arguments):
        self.parent.sendGuiMessage(
            _translate('GUIMSG', '--- Custom script %s started...%s')
                            % (ray.highlightText(executable), self.parent.client_id))
        self._process.start(executable, arguments)
    
    def isFinished(self):
        return not bool(self._process.state())
    
    def getPath(self):
        return self._process.program()
    
    def getCommandName(self):
        return self.getPath().rpartition('/')[2]
    
    def setAsStepper(self, stepper):
        self._is_stepper = bool(stepper)

    def isStepper(self):
        return self._is_stepper
    
    def setStepperProcess(self, text):
        self._stepper_process = text
        
    def getStepperProcess(self):
        return self._stepper_process
    
    def stepperHasCalled(self):
        return self._stepper_has_call
    
    def setStepperHasCall(self, bool_call):
        self._stepper_has_call = bool_call
        
    def setClientId(self, client_id):
        self._client_id = client_id
        
    def clientId(self):
        return self._client_id
    
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
