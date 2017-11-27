#!/usr/bin/python3

from PyQt5.QtWidgets import QApplication, QDialog, QFileDialog
from PyQt5.QtCore    import QObject, pyqtSignal
import ui_proxygui
import sys
import os
from liblo import *

#current_desktop = os.getenv('XDG_CURRENT_DESKTOP')
#if current_desktop == 'KDE':
    #import subprocess
    
#Signals Numbers
NoneSig = 0
SIGUSR1 = 10
SIGUSR2 = 12
SIGINT  = 2
SIGTERM = 15
SIGHUP  = 1

class Proxy(object):
    slots = [ 'executable',
              'arguments', 
              'config_file',
              'label',
              'save_signal',
              'stop_signal',
              'client_error' ]

class OscSignaler(QObject):
    executable   = pyqtSignal(str)
    arguments    = pyqtSignal(str)
    config_file  = pyqtSignal(str)
    label        = pyqtSignal(str)
    save_signal  = pyqtSignal(int)
    stop_signal  = pyqtSignal(int)
    client_error = pyqtSignal(str)
    
    def __init__(self):
        QObject.__init__(self)
        

class OscServerT(ServerThread):
    def __init__(self):
        ServerThread.__init__(self)
        self.qsig = OscSignaler()
        
    @make_method('/nsm/proxy/executable', None)
    def executable(self, path, args):
        print(path, args)
        executable = args[0]
        self.qsig.executable.emit(executable)
        
    @make_method('/nsm/proxy/arguments', None)
    def arguments(self, path, args):
        print(path, args)
        arguments = args[0]
        self.qsig.arguments.emit(arguments)
        
    @make_method('/nsm/proxy/config_file', None)
    def configfile(self, path, args):
        print(path, args)
        config_file = args[0]
        self.qsig.config_file.emit(config_file)
        
    @make_method('/nsm/proxy/label', None)
    def label(self, path, args):
        print(path, args)
        label = args[0]
        self.qsig.label.emit(label)
        
    @make_method('/nsm/proxy/save_signal', None)
    def saveSignal(self, path, args):
        print(path, args)
        save_signal = args[0]
        self.qsig.save_signal.emit(save_signal)
        
    @make_method('/nsm/proxy/stop_signal', None)
    def stopSignal(self, path, args):
        print(path, args)
        stop_signal = args[0]
        self.qsig.stop_signal.emit(stop_signal)
        
    @make_method('/nsm/proxy/client_error', None)
    def clientError(self, path, args):
        print(path, args)
        client_error = args[0]
        self.qsig.client_error.emit(client_error)
    
    def updateProxy(self):
        self.send(nsmp_adress, '/nsm/proxy/update')
        
    def sendAllToProxy(self):          
        self.send(nsmp_adress, '/nsm/proxy/label'      , proxy.label       )
        self.send(nsmp_adress, '/nsm/proxy/save_signal', proxy.save_signal )
        self.send(nsmp_adress, '/nsm/proxy/stop_signal', proxy.stop_signal )
        
    def startProxy(self):
        self.send(nsmp_adress, '/nsm/proxy/start', proxy.executable, proxy.arguments, proxy.config_file)
                    
                    
class MainDialog(QDialog):
    def __init__(self):
        QDialog.__init__(self)
        self.ui = ui_proxygui.Ui_Dialog()
        self.ui.setupUi(self)
        
        self.f_config_file = None
        
        self.ui.toolButtonBrowse.clicked.connect(self.browseConfigFile)
        self.ui.comboSaveSig.addItems(['None', 'SIGUSR1','SIGUSR2', 'SIGINT'])
        self.ui.comboStopSig.addItems(['SIGTERM', 'SIGINT', 'SIGHUP'])
        
        serverOSC.qsig.executable.connect(self.proxyUpdatesExecutable)
        serverOSC.qsig.arguments.connect(self.proxyUpdatesArguments)
        serverOSC.qsig.config_file.connect(self.proxyUpdatesConfigFile)
        serverOSC.qsig.label.connect(self.proxyUpdatesLabel)
        serverOSC.qsig.save_signal.connect(self.proxyUpdatesSaveSignal)
        serverOSC.qsig.stop_signal.connect(self.proxyUpdatesStopSignal)
        serverOSC.qsig.client_error.connect(self.proxyUpdatesClientError)
        
    #QFileDialog.DontUseNativeDialog
    def browseConfigFile(self):
        self.f_config_file = QFileDialog.getOpenFileName(self, 'Choose config file', os.getcwd(), "", "", QFileDialog.DontUseNativeDialog)[0]
        if self.f_config_file:
            self.ui.lineEditConfigFile.setText(os.path.relpath(self.f_config_file))
            
    def proxyUpdatesExecutable(self, executable):
        print(executable)
        self.ui.lineEditExecutable.setText(executable)
        
    def proxyUpdatesArguments(self, arguments):
        print(arguments)
        self.ui.lineEditArguments.setText(arguments)
        
    def proxyUpdatesConfigFile(self, config_file):
        print(config_file)
        self.ui.lineEditConfigFile.setText(config_file)
        
    def proxyUpdatesLabel(self, label):
        print(label)
        self.ui.lineEditLabel.setText(label)
        
        
        
        
    def proxyUpdatesSaveSignal(self, save_signal):
        print(save_signal)
        if save_signal == NoneSig:
            self.ui.comboSaveSig.setCurrentIndex(0)
        elif save_signal == SIGUSR1:
            self.ui.comboSaveSig.setCurrentIndex(1)
        elif save_signal == SIGUSR2:
            self.ui.comboSaveSig.setCurrentIndex(2)
        elif save_signal == SIGINT:
            self.ui.comboSaveSig.setCurrentIndex(3)
        
    def proxyUpdatesStopSignal(self, stop_signal):
        print(stop_signal)
        if stop_signal == SIGTERM:
            self.ui.comboStopSig.setCurrentIndex(0)
        elif stop_signal == SIGINT:
            self.ui.comboStopSig.setCurrentIndex(1)
        elif stop_signal == SIGHUP:
            self.ui.comboStopSig.setCurrentIndex(2)
        
    def proxyUpdatesClientError(self, client_error):
        print(client_error)
        
    def updateAllParameters(self):
        proxy.executable   = self.ui.lineEditExecutable.text()
        proxy.arguments    = self.ui.lineEditArguments.text()
        proxy.config_file  = self.ui.lineEditConfigFile.text()
        proxy.label        = self.ui.lineEditLabel.text()
        
        save_signal = NoneSig
        if   self.ui.comboSaveSig.currentIndex == 1:
            save_signal = SIGUSR1
        elif self.ui.comboSaveSig.currentIndex == 2:
            save_signal = SIGUSR2
        elif self.ui.comboSaveSig.currentIndex == 3:
            save_signal = SIGINT
        proxy.save_signal = save_signal
        
        stop_signal = SIGTERM
        if   self.ui.comboStopSig.currentIndex == 1:
            stop_signal = SIGINT
        elif self.ui.comboStopSig.currentIndex == 2:
            stop_signal = SIGHUP
        proxy.stop_signal = stop_signal
        
if __name__ == '__main__':
    if len(sys.argv) <= 2:
        print("Usage: %s --connect-to url" % sys.argv[0], file=sys.stderr)
        sys.exit(1)
        
    nsmp_adress = sys.argv[2]
    
    app = QApplication(sys.argv)
    proxy = Proxy()
    
    serverOSC = OscServerT()
    win = MainDialog()
    
    serverOSC.start()
    serverOSC.updateProxy()
    win.show()
    app.exec()
    
    if win.accepted:
        win.updateAllParameters()
        serverOSC.sendAllToProxy()
        serverOSC.startProxy()
    
    
    

    del win
    del app
