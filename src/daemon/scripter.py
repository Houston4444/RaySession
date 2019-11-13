
from PyQt5.QtCore import QProcess

import ray
from daemon_tools import Terminal

class Scripter:
    def __init__(self, session, signaler, src_addr, src_path):
        self.session = session
        self.signaler = signaler
        self.src_addr = src_addr
        self.src_path = src_path
        self._process = QProcess()
        self._process.started.connect(self.processStarted)
        self._process.finished.connect(self.processFinished)
        self._process.readyReadStandardError.connect(self.standardError)
        self._process.readyReadStandardOutput.connect(self.standardOutput)
        if ray.QT_VERSION >= (5, 6):
            self._process.errorOccurred.connect(self.errorInProcess)
        
    def processStarted(self):
        pass
    
    def processFinished(self, exit_code, exit_status):
        self.signaler.script_finished.emit(self.getPath(), exit_code)
    
    def errorInProcess(self):
        self.signaler.script_finished.emit(self.getPath(), 101)
    
    def standardError(self):
        standard_error = self._process.readAllStandardError().data()
        Terminal.scripterMessage(standard_error, self.getCommandName())
        
    def standardOutput(self):
        standard_output = self._process.readAllStandardOutput().data()
        Terminal.scripterMessage(standard_output, self.getCommandName())
    
    def start(self, executable, arguments):
        self._process.start(executable, arguments)
        
    def getPath(self):
        return self._process.program()
    
    def getCommandName(self):
        return self.getPath().rpartition('/')[2]
