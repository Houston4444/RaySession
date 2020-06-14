import os
import signal

from PyQt5.QtCore import Qt, QTimer, QFile
from PyQt5.QtWidgets import QFileDialog, QFrame
from PyQt5.QtGui import QIcon, QPalette

import ray

from gui_tools import RS, _translate, clientStatusString
from child_dialogs import ChildDialog

import ui_ray_hack_copy
import ui_client_properties
import ui_nsm_properties
import ui_ray_hack_properties

class RayHackCopyDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui_ray_hack_copy.Ui_Dialog()
        self.ui.setupUi(self)

        self.rename_file = False
        self.ui.pushButtonCopyRename.clicked.connect(self.setRenameFile)

    def setRenameFile(self):
        self.rename_file = True
        self.accept()

    def setFile(self, path):
        self.ui.labelFileNotInFolder.setText(
            _translate(
                'Dialog', '%s is not in client working directory')
            % ('<strong>' + os.path.basename(path) + '</strong>'))

class ClientPropertiesDialog(ChildDialog):
    def __init__(self, parent, client):
        ChildDialog.__init__(self, parent)
        self.ui = ui_client_properties.Ui_Dialog()
        self.ui.setupUi(self)

        self.client = client
        
        self.setWindowTitle(
            _translate('client_properties', "Properties of client %s")
            % client.client_id)
        
        self._acceptable_arguments = True
        self._current_status = ray.ClientStatus.STOPPED
        
        self.ui.lineEditIcon.textEdited.connect(self.changeIconwithText)
        self.ui.pushButtonSaveChanges.clicked.connect(self.saveChanges)
        
        self.ui.tabWidget.setCurrentIndex(0)
    
    @staticmethod
    def create(window, client):
        if client.protocol == ray.Protocol.NSM:
            return NsmClientPropertiesDialog(window, client)
        elif client.protocol == ray.Protocol.RAY_HACK:
            return RayHackClientPropertiesDialog(window, client)
        else:
            return ClientPropertiesDialog(window, client)
    
    def setOnSecondTab(self):
        self.ui.tabWidget.setCurrentIndex(1)
    
    def updateStatus(self, status):
        pass
    
    def updateContents(self):
        self.ui.labelId.setText(self.client.client_id)
        self.ui.labelClientName.setText(self.client.name)
        self.ui.lineEditIcon.setText(self.client.icon)
        self.ui.lineEditLabel.setText(self.client.label)
        self.ui.plainTextEditDescription.setPlainText(self.client.description)
        self.ui.checkBoxSaveStop.setChecked(self.client.check_last_save)
        self.ui.lineEditIgnoredExtensions.setText(
            self.client.ignored_extensions)
        
        self.changeIconwithText(self.client.icon)
    
    def changeIconwithText(self, text):
        icon = ray.getAppIcon(text, self)
        self.ui.toolButtonIcon.setIcon(icon)
    
    def saveChanges(self):
        self.client.label = self.ui.lineEditLabel.text()
        self.client.description = \
                                self.ui.plainTextEditDescription.toPlainText()
        self.client.icon = self.ui.lineEditIcon.text()
        self.client.check_last_save = self.ui.checkBoxSaveStop.isChecked()
        self.client.ignored_extensions = \
                                    self.ui.lineEditIgnoredExtensions.text()
                                
        self.client.sendPropertiesToDaemon()
        
        # better for user to wait a little before close the window
        QTimer.singleShot(150, self.accept)


class NsmClientPropertiesDialog(ClientPropertiesDialog):
    def __init__(self, parent, client):
        ClientPropertiesDialog.__init__(self, parent, client)
        
        self.nsmui_frame = QFrame()
        self.nsmui = ui_nsm_properties.Ui_Frame()
        self.nsmui.setupUi(self.nsmui_frame)
        
        self.ui.verticalLayoutProtocol.addWidget(self.nsmui_frame)
        
        self.ui.tabWidget.setTabText(1, 'NSM')
    
    def updateContents(self):
        ClientPropertiesDialog.updateContents(self)
        self.nsmui.lineEditExecutable.setText(self.client.executable_path)
        self.nsmui.lineEditArguments.setText(self.client.arguments)
        
    def saveChanges(self):
        self.client.executable_path = self.nsmui.lineEditExecutable.text()
        self.client.arguments = self.nsmui.lineEditArguments.text()
        ClientPropertiesDialog.saveChanges(self)
        
    def changeIconwithText(self, text):
        icon = ray.getAppIcon(text, self)
        self.ui.toolButtonIcon.setIcon(icon)
        self.nsmui.toolButtonIcon.setIcon(icon)

class RayHackClientPropertiesDialog(ClientPropertiesDialog):
    def __init__(self, parent, client):
        ClientPropertiesDialog.__init__(self, parent, client)
        
        self.ray_hack_frame = QFrame()
        self.rhack = ui_ray_hack_properties.Ui_Frame()
        self.rhack.setupUi(self.ray_hack_frame)
        
        self.ui.verticalLayoutProtocol.addWidget(self.ray_hack_frame)
        
        self.ui.tabWidget.setTabText(1, 'Ray-Hack')
        #self.ui.tabWidget.setCurrentIndex(1)
        #widget = self.ui.tabWidget.
        
        self.rhack.labelWorkingDir.setText(self.getWorkDirBase())
            
        self.rhack.toolButtonBrowse.setEnabled(self._daemon_manager.is_local)
        self.rhack.toolButtonBrowse.clicked.connect(self.browseConfigFile)
        self.rhack.lineEditExecutable.textEdited.connect(
            self.lineEditExecutableEdited)
        self.rhack.lineEditArguments.textChanged.connect(
            self.lineEditArgumentsChanged)
        self.rhack.lineEditConfigFile.textChanged.connect(
            self.lineEditConfigFileChanged)
        
        self.rhack.pushButtonStart.clicked.connect(self.startClient)
        self.rhack.pushButtonStop.clicked.connect(self.stopClient)
        self.rhack.pushButtonSave.clicked.connect(self.saveClient)
        self.rhack.comboSaveSig.addItem(_translate('ray_hack', 'None'), 0)
        self.rhack.comboSaveSig.addItem('SIGUSR1', 10)
        self.rhack.comboSaveSig.addItem('SIGUSR2', 12)
        
        self.rhack.comboStopSig.addItem('SIGTERM', 15)
        self.rhack.comboStopSig.addItem('SIGINT', 2)
        self.rhack.comboStopSig.addItem('SIGHUP', 1)
        self.rhack.comboStopSig.addItem('SIGKILL', 9)
        
        self.rhack.labelError.setVisible(False)
        self.rhack.pushButtonStart.setEnabled(True)
        self.rhack.pushButtonStop.setEnabled(False)
        self.rhack.pushButtonSave.setEnabled(False)
        
        self.rhack.groupBoxTestZone.setChecked(False)
        #self.rhack.groupBoxTestZone.setEnabled(False)
        
    def updateStatus(self, status):
        self._current_status = status
        self.rhack.lineEditClientStatus.setText(clientStatusString(status))
        
        if status in (ray.ClientStatus.LAUNCH,
                      ray.ClientStatus.OPEN,
                      ray.ClientStatus.SWITCH,
                      ray.ClientStatus.NOOP):
            self.rhack.pushButtonStart.setEnabled(False)
            self.rhack.pushButtonStop.setEnabled(True)
            self.rhack.pushButtonSave.setEnabled(False)
        elif status == ray.ClientStatus.READY:
            self.rhack.pushButtonStart.setEnabled(False)
            self.rhack.pushButtonStop.setEnabled(True)
            self.rhack.pushButtonSave.setEnabled(True)
        elif status == ray.ClientStatus.STOPPED:
            self.rhack.pushButtonStart.setEnabled(self.isAllowed())
            self.rhack.pushButtonStop.setEnabled(False)
            self.rhack.pushButtonSave.setEnabled(False)
        elif status == ray.ClientStatus.PRECOPY:
            self.ui.pushButtonStart.setEnabled(False)
            self.ui.pushButtonStart.setEnabled(False)
            self.ui.pushButtonSave.setEnabled(False)
            
    def changeIconwithText(self, text):
        icon = ray.getAppIcon(text, self)
        self.ui.toolButtonIcon.setIcon(icon)
        self.rhack.toolButtonIcon.setIcon(icon)
        
    def updateContents(self):
        ClientPropertiesDialog.updateContents(self)
        self.rhack.lineEditExecutable.setText(self.client.executable_path)
        self.rhack.lineEditArguments.setText(self.client.arguments)
        self.rhack.lineEditConfigFile.setText(
            self.client.ray_hack.config_file)
        
        save_sig = self.client.ray_hack.save_sig
        
        for i in range(self.rhack.comboSaveSig.count()):
            if self.rhack.comboSaveSig.itemData(i) == save_sig:
                self.rhack.comboSaveSig.setCurrentIndex(i)
                break
        else:
            try:
                signal_text = str(
                    signal.Signals(save_sig)).rpartition('.')[2]
                self.rhack.comboSaveSig.addItem(signal_text, save_sig)
                self.rhack.comboSaveSig.setCurrentIndex(i+1)
            except:
                self.rhack.comboSaveSig.setCurrentIndex(0)
        
        stop_sig = self.client.ray_hack.stop_sig
        
        for i in range(self.rhack.comboStopSig.count()):
            if self.rhack.comboStopSig.itemData(i) == stop_sig:
                self.rhack.comboStopSig.setCurrentIndex(i)
                break
        else:
            try:
                signal_text = str(signal.Signals(
                    stop_sig)).rpartition('.')[2]
                self.rhack.comboStopSig.addItem(signal_text, stop_sig)
                self.rhack.comboStopSig.setCurrentIndex(i+1)
            except:
                self.rhack.comboStopSig.setCurrentIndex(0)
    
    def saveChanges(self):
        self.client.executable_path = self.rhack.lineEditExecutable.text()
        self.client.arguments = self.rhack.lineEditArguments.text()
        self.client.ray_hack.config_file = self.rhack.lineEditConfigFile.text()
        self.client.ray_hack.save_sig = self.rhack.comboSaveSig.currentData()
        self.client.ray_hack.stop_sig = self.rhack.comboStopSig.currentData()
        self.client.ray_hack.wait_win = self.rhack.checkBoxWaitWindow.isChecked()
        
        ClientPropertiesDialog.saveChanges(self)
    
    def getWorkDirBase(self)->str:
        prefix = self._session.name
        if self.client.prefix_mode == ray.PrefixMode.CLIENT_NAME:
            prefix = self.client.name
        elif self.client.prefix_mode == ray.PrefixMode.CUSTOM:
            prefix = self.client.custom_prefix
        
        return "%s.%s" % (prefix, self.client.client_id)
    
    def browseConfigFile(self):
        work_dir_base = self.getWorkDirBase()
        work_dir = "%s/%s" % (self._session.path, work_dir_base)
        
        config_file, ok = QFileDialog.getOpenFileName(
            self,
            _translate('Dialog', 'Select File to use as CONFIG_FILE'),
            work_dir)
        
        if not ok:
            return

        if not config_file.startswith(work_dir + '/'):
            qfile = QFile(config_file)
            if qfile.size() < 20971520:  # if file < 20Mb
                copy_dialog = RayHackCopyDialog(self)
                copy_dialog.setFile(config_file)
                copy_dialog.exec()

                if copy_dialog.result():
                    if copy_dialog.rename_file:
                        base, pt, extension = os.path.basename(
                            config_file).rpartition('.')

                        config_file = "%s.%s" % (self._session.name,
                                                 extension)
                        if not base:
                            config_file = self._session.name
                    else:
                        config_file = os.path.basename(config_file)

                    qfile.copy(config_file)

        self.config_file = os.path.relpath(config_file, work_dir)
        
        if (self._session.name
            and (self.config_file == self._session.name
                 or self.config_file.startswith("%s." % self._session.name))):
            self.config_file = self.config_file.replace(self._session.name,
                                                        "$RAY_SESSION_NAME")
        self.rhack.lineEditConfigFile.setText(self.config_file)
    
    def isAllowed(self):
        return self._acceptable_arguments
    
    def lineEditExecutableEdited(self, text):
        pass

    def lineEditArgumentsChanged(self, text):
        if ray.shellLineToArgs(text) is not None:
            self._acceptable_arguments = True
            self.rhack.lineEditArguments.setStyleSheet('')
        else:
            self._acceptable_arguments = False
            self.rhack.lineEditArguments.setStyleSheet(
                'QLineEdit{background: red}')
        
        self.rhack.pushButtonStart.setEnabled(
            bool(self._acceptable_arguments
                 and self._current_status == ray.ClientStatus.STOPPED))
        self.ui.pushButtonSaveChanges.setEnabled(self.isAllowed())

    def lineEditConfigFileChanged(self, text):
        if text and not self.rhack.lineEditArguments.text():
            self.rhack.lineEditArguments.setText('"$CONFIG_FILE"')
        elif (not text 
              and self.rhack.lineEditArguments.text() == '"$CONFIG_FILE"'):
            self.rhack.lineEditArguments.setText('')
    
    def startClient(self):
        executable = self.client.executable_path
        arguments = self.client.arguments
        config_file = self.client.ray_hack.config_file
        
        self.client.executable_path = self.rhack.lineEditExecutable.text()
        self.client.arguments = self.rhack.lineEditArguments.text()
        self.client.ray_hack.config_file = self.rhack.lineEditConfigFile.text()
        
        self.client.sendPropertiesToDaemon()
        self.toDaemon('/ray/client/resume', self.client.client_id)
        
        self.client.executable_path = executable
        self.client.arguments = arguments
        self.client.ray_hack.config_file = config_file
        
        self.client.sendPropertiesToDaemon()

    def stopClient(self):
        stop_sig = self.client.ray_hack.stop_sig
        self.client.ray_hack.stop_sig = self.rhack.comboStopSig.currentData()
        self.client.sendRayHack()
        
        self.toDaemon('/ray/client/stop', self.client.client_id)
        
        self.client.ray_hack.stop_sig = stop_sig
        self.client.sendRayHack()
        
    def saveClient(self):
        save_sig = self.client.ray_hack.save_sig
        self.client.ray_hack.save_sig = self.rhack.comboSaveSig.currentData()
        self.client.sendRayHack()
        
        self.toDaemon('/ray/client/save', self.client.client_id)
        
        self.client.ray_hack.save_sig = save_sig
        self.client.sendRayHack()
