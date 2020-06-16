#!/usr/bin/python3 -u

import argparse
import os
import sys
import time
import signal
import shutil
import subprocess
from liblo import ServerThread, Address, make_method, Message
from PyQt5.QtCore import (pyqtSignal, QObject, QTimer, QProcess, QSettings,
                          QLocale, QTranslator, QFile)
from PyQt5.QtWidgets import (QApplication, QDialog, QFileDialog, QMessageBox,
                             QMainWindow)
from PyQt5.QtXml import QDomDocument

import ray
import nsm_client
import ui_proxy_gui
import ui_proxy_copy

ERR_OK = 0
ERR_NO_PROXY_FILE = -1
ERR_NOT_ENOUGHT_LINES = -2
ERR_NO_EXECUTABLE = -3
ERR_WRONG_ARGUMENTS = -4
ERR_WRONG_SAVE_SIGNAL = -5
ERR_WRONG_STOP_SIGNAL = -6



def signalHandler(sig, frame):
    if sig in (signal.SIGINT, signal.SIGTERM):
        if proxy.isRunning():
            proxy.waitForStop()
            proxy.stopProcess()
        else:
            #sys.exit()
            app.quit()
        


def ifDebug(string):
    if debug:
        sys.stderr.write(string + '\n')


class ProxyCopyDialog(QDialog):
    def __init__(self):
        QDialog.__init__(self)
        self.ui = ui_proxy_copy.Ui_Dialog()
        self.ui.setupUi(self)

        self.rename_file = False
        self.ui.pushButtonCopyRename.clicked.connect(self.setRenameFile)

    def setRenameFile(self):
        self.rename_file = True
        self.accept()

    def setFile(self, path):
        self.ui.labelFileNotInFolder.setText(
            _translate(
                'Dialog', '%s is not in proxy directory') %
            ('<strong>' + os.path.basename(path) + '</strong>'))


class ProxyDialog(QMainWindow):
    def __init__(self, executable=''):
        QMainWindow.__init__(self)
        self.ui = ui_proxy_gui.Ui_MainWindow()
        self.ui.setupUi(self)
        
        self.server = server
        self.proxy = proxy

        self.config_file = ''
        self.args_edited = False
        self.fields_allow_start = False
        self.process_is_running = False

        
        self.ui.toolButtonBrowse.clicked.connect(self.browseFile)

        self.ui.lineEditExecutable.textEdited.connect(
            self.lineEditExecutableEdited)
        self.ui.lineEditArguments.textChanged.connect(
            self.lineEditArgumentsChanged)
        self.ui.lineEditConfigFile.textChanged.connect(
            self.lineEditConfigFileChanged)
        
        self.ui.comboSaveSig.addItem(_translate('proxy', 'None'), 0)
        self.ui.comboSaveSig.addItem('SIGUSR1', int(signal.SIGUSR1))
        self.ui.comboSaveSig.addItem('SIGUSR2', int(signal.SIGUSR2))
        self.ui.comboSaveSig.addItem('SIGINT',  int(signal.SIGINT))
        self.ui.comboSaveSig.activated.connect(self.comboSaveSigChanged)
        self.ui.comboSaveSig.setCurrentIndex(0)
        
        self.ui.comboNoSave.addItem(
            _translate('proxy', "0 - Ignore missing save"))
        self.ui.comboNoSave.addItem(
            _translate('proxy', "1 - Transmit missing save"))
        self.ui.comboNoSave.addItem(
            _translate('proxy', "2 - Accept windows close"))
        self.ui.comboNoSave.setCurrentIndex(2)
        self.ui.comboNoSave.activated.connect(self.comboNoSaveChanged)
        self.ui.labelNoSaveLevel.setToolTip(self.ui.comboNoSave.toolTip())
        
        self.ui.comboStopSig.addItem('SIGTERM', int(signal.SIGTERM))
        self.ui.comboStopSig.addItem('SIGINT', int(signal.SIGINT))
        self.ui.comboStopSig.addItem('SIGHUP', int(signal.SIGHUP))
        self.ui.comboStopSig.activated.connect(self.comboStopSigChanged)
        self.ui.comboStopSig.setCurrentIndex(0)
        
        self.ui.comboSaveSig.currentTextChanged.connect(self.allowSaveTest)
        self.ui.toolButtonTestSave.clicked.connect(self.testSave)
        self.ui.toolButtonTestSave.setEnabled(False)

        self.ui.pushButtonStart.clicked.connect(self.startProcess)
        self.ui.pushButtonStop.clicked.connect(self.stopProcess)
        self.ui.pushButtonStop.setEnabled(False)

        self.ui.lineEditExecutable.setText(executable)
        self.lineEditExecutableEdited(executable)

        self.ui.labelError.setText('')

        proxy.process.started.connect(self.proxyStarted)
        proxy.process.finished.connect(self.proxyFinished)
        if ray.QT_VERSION >= (5, 6):
            proxy.process.errorOccurred.connect(self.proxyErrorInProcess)

    def checkAllowStart(self):
        self.fields_allow_start = True
        if not self.ui.lineEditExecutable.text():
            self.fields_allow_start = False
        
        if ray.shellLineToArgs(self.ui.lineEditArguments.text()) is None:
            self.fields_allow_start = False

        self.ui.pushButtonStart.setEnabled(
            bool(not self.process_is_running and self.fields_allow_start))

    def updateValuesFromProxyFile(self):
        self.ui.lineEditExecutable.setText(proxy.executable)
        self.ui.lineEditConfigFile.setText(proxy.config_file)
        self.ui.lineEditArguments.setText(proxy.arguments_line)
                
        save_index = self.ui.comboSaveSig.findData(proxy.save_signal)
        self.ui.comboSaveSig.setCurrentIndex(save_index)

        self.ui.comboNoSave.setCurrentIndex(proxy.no_save_level)
        self.ui.comboNoSave.setEnabled(not bool(proxy.save_signal))
        
        stop_index = self.ui.comboStopSig.findData(proxy.stop_signal)
        self.ui.comboStopSig.setCurrentIndex(stop_index)

        self.ui.checkBoxWaitWindow.setChecked(proxy.wait_window)

        self.checkAllowStart()

    def browseFile(self):
        config_file, ok = QFileDialog.getOpenFileName(
            self, _translate('Dialog', 'Select File to use as CONFIG_FILE'))
        if not ok:
            return

        if not config_file.startswith(os.getcwd() + '/'):
            qfile = QFile(config_file)
            if qfile.size() < 20971520:  # if file < 20Mb
                copy_dialog = ProxyCopyDialog()
                copy_dialog.setFile(config_file)
                copy_dialog.exec()

                if copy_dialog.result():
                    if copy_dialog.rename_file:
                        base, pt, extension = os.path.basename(
                            config_file).rpartition('.')

                        config_file = "%s.%s" % (proxy.session_name, extension)
                        if not base:
                            config_file = proxy.session_name
                    else:
                        config_file = os.path.basename(config_file)

                    qfile.copy(config_file)

        self.config_file = os.path.relpath(config_file)
        if (proxy.session_name
            and (self.config_file == proxy.session_name
                 or self.config_file.startswith("%s." % proxy.session_name))):
            self.config_file = self.config_file.replace(proxy.session_name,
                                                        "$RAY_SESSION_NAME")
        self.ui.lineEditConfigFile.setText(self.config_file)

    def lineEditExecutableEdited(self, text):
        self.checkAllowStart()

    def lineEditArgumentsChanged(self, text):
        self.checkAllowStart()
        if ray.shellLineToArgs(text) is not None:
            self.ui.lineEditArguments.setStyleSheet('')
        else:
            self.ui.lineEditArguments.setStyleSheet(
                'QLineEdit{background: red}')
            self.ui.pushButtonStart.setEnabled(False)

    def lineEditConfigFileChanged(self, text):
        if text and not self.ui.lineEditArguments.text():
            self.ui.lineEditArguments.setText('"$CONFIG_FILE"')
        elif (not text 
              and self.ui.lineEditArguments.text() == '"$CONFIG_FILE"'):
            self.ui.lineEditArguments.setText('')

    def comboSaveSigChanged(self, index):
        self.ui.comboNoSave.setEnabled(bool(index == 0))
        
        save_signal = 0
        
        if index == 1:
            save_signal = signal.SIGUSR1
        elif index == 2:
            save_signal = signal.SIGUSR2
        elif index == 3:
            save_signal = signal.SIGINT
            
        save_signal = int(save_signal)
        self.proxy.setSaveSignal(save_signal)
    
    def comboStopSigChanged(self, index):
        stop_signal = signal.SIGTERM
        
        if index == 1:
            stop_signal = signal.SIGINT
        elif index == 2:
            stop_signal = signal.SIGTERM
            
        stop_signal = int(stop_signal)
        self.proxy.setStopSignal(stop_signal)
    
    def comboNoSaveChanged(self, index):
        self.proxy.no_save_level = index
        self.proxy.sendNoSaveLevel()
    
    def allowSaveTest(self, text=None):
        if text is None:
            text = self.ui.comboSaveSig.currentText()

        self.ui.toolButtonTestSave.setEnabled(
            bool(self.process_is_running and text != 'None'))

    def testSave(self):
        save_signal = self.ui.comboSaveSig.currentData()
        proxy.saveProcess(save_signal)

    def saveProxy(self):
        executable = self.ui.lineEditExecutable.text()
        config_file = self.ui.lineEditConfigFile.text()
        arguments_line = self.ui.lineEditArguments.text()
        save_signal = self.ui.comboSaveSig.currentData()
        no_save_level = self.ui.comboNoSave.currentIndex()
        stop_signal = self.ui.comboStopSig.currentData()
        wait_window = self.ui.checkBoxWaitWindow.isChecked()

        proxy.updateAndSave(
            executable,
            config_file,
            arguments_line,
            save_signal,
            no_save_level,
            stop_signal,
            wait_window)

    def startProcess(self):
        self.saveProxy()

        if proxy.is_launchable:
            proxy.startProcess()

    def stopProcess(self):
        proxy.stopProcess(self.ui.comboStopSig.currentData())

    def proxyStarted(self):
        self.process_is_running = True
        self.ui.pushButtonStart.setEnabled(False)
        self.ui.pushButtonStop.setEnabled(True)
        self.allowSaveTest()
        self.ui.labelError.setText('')

    def processTerminateShortly(self, duration):
        self.ui.labelError.setText('Process terminate in %f ms')

    def proxyFinished(self):
        self.process_is_running = False
        self.ui.pushButtonStart.setEnabled(self.fields_allow_start)
        self.ui.pushButtonStop.setEnabled(False)
        self.allowSaveTest()
        self.ui.labelError.setText('')

    def proxyErrorInProcess(self):
        self.ui.labelError.setText(
            _translate(
                'Dialog',
                'Executable failed to launch ! It\'s maybe not present on system.'))
        if not self.isVisible():
            self.show()

    def closeEvent(self, event):
        server.sendToDaemon('/nsm/client/gui_is_hidden')
        settings.setValue(
            'ProxyGui%s/geometry' %
            self.proxy.client_id,
            self.saveGeometry())
        settings.setValue(
            'ProxyGui%s/WindowState' %
            self.proxy.client_id, self.saveState())
        settings.sync()

        if self.fields_allow_start:
            self.saveProxy()

        QMainWindow.closeEvent(self, event)

        # Quit if process is not running yet
        if not proxy.process.state() == QProcess.Running:
            sys.exit(0)

    def showEvent(self, event):
        self.server.sendToDaemon('/nsm/client/gui_is_shown')

        if settings.value('ProxyGui%s/geometry' % self.proxy.client_id):
            self.restoreGeometry(
                settings.value(
                    'ProxyGui%s/geometry' %
                    self.proxy.client_id))
        if settings.value('ProxyGui%s/WindowState' % self.proxy.client_id):
            self.restoreState(
                settings.value(
                    'ProxyGui%s/WindowState' %
                    self.proxy.client_id))

        self.updateValuesFromProxyFile()

        QMainWindow.showEvent(self, event)
##########################


class Proxy(QObject):
    def __init__(self, executable=''):
        QObject.__init__(self)
        self.process = QProcess()
        self.process.setProcessChannelMode(QProcess.ForwardedChannels)
        self.process.finished.connect(self.processFinished)

        #self.proxy_file = None
        self.is_launchable = False
        self.project_path = ""
        self.path = ""
        self.session_name = ""
        self.client_id = ""

        self.executable = executable
        self.arguments = []
        self.arguments_line = ''
        self.config_file = ""
        self.save_signal = 0
        self.no_save_level = 2
        self.stop_signal = int(signal.SIGTERM)
        self.label = ""
        
        self.wait_window = False

        self._config_file_used = False
        self._wait_for_stop = False
        
        self.timer_save = QTimer()
        self.timer_save.setSingleShot(True)
        self.timer_save.setInterval(300)
        self.timer_save.timeout.connect(self.timerSaveFinished)

        self.timer_open = QTimer()
        self.timer_open.setSingleShot(True)
        self.timer_open.setInterval(500)
        self.timer_open.timeout.connect(self.timerOpenFinished)

        self.is_finishable = False
        self.timer_close = QTimer()
        self.timer_close.setSingleShot(True)
        self.timer_close.setInterval(2500)
        self.timer_close.timeout.connect(self.timerCloseFinished)
        self.timer_close.start()
        self.process_start_time = time.time()

        self.timer_window = QTimer()
        self.timer_window.setInterval(100)
        self.timer_window.timeout.connect(self.checkWindow)
        self.timer_window_n = 0

        signaler.server_sends_open.connect(self.initialize)
        signaler.server_sends_save.connect(self.saveProcess)
        signaler.show_optional_gui.connect(self.showOptionalGui)
        signaler.hide_optional_gui.connect(self.hideOptionalGui)

    def isRunning(self):
        return bool(self.process.state() == QProcess.Running)

    def waitForStop(self):
        self._wait_for_stop = True
    
    def setSaveSignal(self, int_signal):
        self.save_signal = int_signal
        self.sendNoSaveLevel()
        
    def setStopSignal(self, int_signal):
        self.stop_signal = int_signal
    
    def readFile(self):
        self.is_launchable = False
        try:
            file = open(self.path, 'r')
        except BaseException:
            return

        xml = QDomDocument()
        xml.setContent(file.read())

        content = xml.documentElement()

        if content.tagName() != "RAY-PROXY":
            file.close()
            return

        cte = content.toElement()
        file_version = cte.attribute('VERSION')
        self.executable = cte.attribute('executable')
        self.config_file = cte.attribute('config_file')
        self.arguments_line = cte.attribute('arguments')
        save_signal = cte.attribute('save_signal')
        no_save_level = cte.attribute('no_save_level')
        stop_signal = cte.attribute('stop_signal')

        wait_window = cte.attribute('wait_window')

        if wait_window.isdigit():
            self.wait_window = bool(int(wait_window))
        else:
            self.wait_window = False

        file.close()

        if save_signal.isdigit():
            self.save_signal = int(save_signal)
        
        if no_save_level.isdigit():
            self.no_save_level = int(no_save_level)
        else:
            self.no_save_level = 2
        
        versions = [file_version, '0.7.1']
        versions.sort()
        
        if file_version != versions[0]:
            # something was wrong in old version,
            # save signal was saved as stop signal too.
            # so don't read stop signal if this is an old file.
            if stop_signal.isdigit():
                self.stop_signal = int(stop_signal)

        if not self.executable:
            return

        arguments = ray.shellLineToArgs(self.arguments_line)
        if arguments is None:
            return

        self.is_launchable = True

    def saveFile(
            self,
            executable,
            config_file,
            arguments_line,
            save_signal,
            no_save_level,
            stop_signal,
            wait_window):
        try:
            file = open(self.path, 'w')
        except BaseException:
            return

        if not save_signal:
            save_signal = 0

        xml = QDomDocument()
        p = xml.createElement('RAY-PROXY')
        p.setAttribute('VERSION', ray.VERSION)
        p.setAttribute('executable', executable)
        p.setAttribute('arguments', arguments_line)
        p.setAttribute('config_file', config_file)
        p.setAttribute('save_signal', str(int(save_signal)))
        p.setAttribute('no_save_level', str(no_save_level))
        p.setAttribute('stop_signal', str(int(stop_signal)))
        p.setAttribute('wait_window', wait_window)

        xml.appendChild(p)

        contents = "<?xml version='1.0' encoding='UTF-8'?>\n"
        contents += "<!DOCTYPE RAY-PROXY>\n"
        contents += xml.toString()

        file.write(contents)
        file.close()

        self.readFile()
    
    def updateValues(self, executable, config_file, arguments_line,
                     save_signal, no_save_level, stop_signal, wait_window):
        self.executable = executable
        self.config_file = config_file
        self.arguments_line = arguments_line
        self.save_signal = save_signal
        self.no_save_level = no_save_level
        self.stop_signal = stop_signal
        self.wait_window = wait_window
    
    def saveProxyFile(self):
        self.saveFile(
            self.executable,
            self.config_file,
            self.arguments_line,
            self.save_signal,
            self.no_save_level,
            self.stop_signal,
            self.wait_window)
    
    def updateAndSave(self, executable, config_file, arguments_line,
                      save_signal, no_save_level, stop_signal, wait_window):
        self.updateValues(executable, config_file, arguments_line, 
                          save_signal, no_save_level,
                          stop_signal, wait_window)
        self.saveProxyFile()
    
    def processFinished(self, exit_code):
        if self._wait_for_stop:
            app.quit()
            
        if self.is_finishable:
            if not proxy_dialog.isVisible():
                app.quit()
        else:
            duration = time.time() - self.process_start_time
            proxy_dialog.processTerminateShortly(duration)
            # proxy_dialog.show()
    
    def checkWindow(self):
        self.timer_window_n += 1

        if self.timer_window_n > 600:
            # 600 x 50ms = 30s max until ray-proxy
            # replyOpen to Session Manager
            self.checkWindowEnded()
            return

        try:
            # get all windows and their PID with wmctrl
            wmctrl_all = subprocess.check_output(
                ['wmctrl', '-l', '-p']).decode()
        except BaseException:
            self.checkWindowEnded()
            return

        if not wmctrl_all:
            self.checkWindowEnded()
            return

        all_lines = wmctrl_all.split('\n')
        pids = []

        # get all windows pids
        for line in all_lines:
            if not line:
                continue

            line_sep = line.split(' ')
            non_empt = []
            for el in line_sep:
                if el:
                    non_empt.append(el)

            if len(non_empt) >= 3 and non_empt[2].isdigit():
                pids.append(int(non_empt[2]))
            else:
                # window manager seems to not work correctly with wmctrl, so
                # replyOpen now
                self.checkWindowEnded()
                return

        parent_pid = self.process.pid()

        # check in pids if one comes from this ray-proxy
        for pid in pids:
            if pid < parent_pid:
                continue

            ppid = pid

            while ppid != parent_pid and ppid > 1:
                try:
                    proc_file = open('/proc/%i/status' % ppid, 'r')
                    proc_contents = proc_file.read()
                except BaseException:
                    self.checkWindowEnded()
                    return
                    
                for line in proc_contents.split('\n'):
                    if line.startswith('PPid:'):
                        ppid_str = line.rpartition('\t')[2]
                        if ppid_str.isdigit():
                            ppid = int(ppid_str)
                            break
                else:
                    self.checkWindowEnded()
                    return
                
            if ppid == parent_pid:
                # a window appears with a pid child of this ray-proxy,
                # replyOpen
                QTimer.singleShot(200, self.checkWindowEnded)
                break

    def checkWindowEnded(self):
        self.timer_window.stop()
        server.openReply()

    def initialize(self, project_path, session_name, jack_client_name):
        self.project_path = project_path
        self.session_name = session_name
        self.client_id = project_path.rpartition('.')[2]

        server.sendGuiState(False)

        if not os.path.exists(project_path):
            os.mkdir(project_path)

        os.chdir(project_path)

        proxy_dialog.setWindowTitle("Ray Proxy - %s" % self.client_id)
        
        self.path = os.path.join(project_path, "ray-proxy.xml")
        self.readFile()

        proxy_dialog.updateValuesFromProxyFile()

        if not self.is_launchable:
            server.openReply()
            proxy_dialog.show()
            return

        self.startProcess()
    
    def sendNoSaveLevel(self):
        if ':no-save-level:' in server.getServerCapabilities():
            nsl = self.no_save_level
            if self.save_signal:
                nsl = 0
            server.sendToDaemon('/nsm/client/no_save_level', nsl)
    
    def startProcess(self):
        os.environ['NSM_CLIENT_ID'] = self.client_id
        os.environ['RAY_SESSION_NAME'] = self.session_name

        # enable environment vars in config_file
        config_file = os.path.expandvars(self.config_file)
        os.environ['CONFIG_FILE'] = config_file
        
        # because that is not done by python itself
        os.environ['PWD'] = os.getcwd()
        
        # Useful for launching NSM compatible clients with specifics arguments
        nsm_url = os.getenv('NSM_URL')
        ray_port_str = nsm_url.rpartition(':')[2]
        if ray_port_str.endswith('/'):
            ray_port_str = ray_port_str[:-1]
        if ray_port_str.isdigit():    
            os.environ['RAY_CONTROL_PORT'] = ray_port_str
        
        os.unsetenv('NSM_URL')

        arguments_line = os.path.expandvars(self.arguments_line)
        arguments = ray.shellLineToArgs(arguments_line)
        
        self._config_file_used = bool(config_file
                                      and config_file in arguments)
        self.sendNoSaveLevel()
        
        self.process.start(self.executable, arguments)
        self.timer_open.start()

    def saveProcess(self, save_signal=0):
        if not save_signal:
            save_signal = self.save_signal

        if self.isRunning() and save_signal:
            os.kill(self.process.processId(), save_signal)

        self.timer_save.start()

    def stopProcess(self, signal=signal.SIGTERM):
        if signal is None:
            return

        if not self.isRunning():
            return

        os.kill(self.process.processId(), signal)

    def timerSaveFinished(self):
        server.saveReply()

    def timerOpenFinished(self):
        if self.wait_window:
            self.timer_window.start()
        else:
            server.openReply()

        if self.isRunning() and proxy_dialog.isVisible():
            proxy_dialog.close()

    def timerCloseFinished(self):
        self.is_finishable = True

    def stop(self):
        if self.process.state:
            self.process.terminate()

    def showOptionalGui(self):
        proxy_dialog.show()

    def hideOptionalGui(self):
        if not proxy_dialog.isHidden():
            proxy_dialog.close()


class ProxyFile(object):
    def __init__(self, project_path, executable=''):
        

        self.executable = executable
        self.arguments_line = ''
        self.config_file = ''
        self.args_line = ''
        self.save_signal = 0
        self.stop_signal = int(signal.SIGTERM)
        self.wait_window = False

        

    
    

if __name__ == '__main__':
    NSM_URL = os.getenv('NSM_URL')
    if not NSM_URL:
        sys.stderr.write('Could not register as NSM client.\n')
        sys.exit()

    daemon_address = ray.getLibloAddress(NSM_URL)

    parser = argparse.ArgumentParser()
    parser.add_argument('--executable', default='')
    parser.add_argument('--debug',
                        '-d',
                        action='store_true',
                        help='see all OSC messages')
    parser.add_argument('-v', '--version', action='version',
                        version=ray.VERSION)
    parsed_args = parser.parse_args()

    debug = parsed_args.debug
    executable = parsed_args.executable

    app = QApplication(sys.argv)
    app.setApplicationName("RaySession")
    # app.setApplicationVersion(ray.VERSION)
    app.setOrganizationName("RaySession")
    app.setQuitOnLastWindowClosed(False)
    settings = QSettings()
    
    signal.signal(signal.SIGINT, signalHandler)
    signal.signal(signal.SIGTERM, signalHandler)

    # Translation process
    locale = QLocale.system().name()
    appTranslator = QTranslator()
    
    if appTranslator.load(
        "%s/locale/raysession_%s" %
        (os.path.dirname(
            os.path.dirname(
                os.path.dirname(
                    sys.argv[0]))),
         locale)):
        app.installTranslator(appTranslator)
    _translate = app.translate

    timer = QTimer()
    timer.setInterval(200)
    timer.timeout.connect(lambda: None)
    timer.start()

    signaler = nsm_client.NSMSignaler()
    
    server = nsm_client.NSMThread('ray-proxy', signaler,
                                  daemon_address, debug)
    server.start()
    
    proxy = Proxy(executable)
    proxy_dialog = ProxyDialog()

    
    server.announce('Ray Proxy', ':optional-gui:warning-no-save:', 'ray-proxy')

    app.exec()

    settings.sync()
    server.stop()

    del server
    del proxy
    del app
