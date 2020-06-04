import os
import signal

from PyQt5.QtCore import Qt, QTimer, QFile
from PyQt5.QtWidgets import QFileDialog
from PyQt5.QtGui import QIcon, QPalette

import ray

from gui_tools import RS, _translate
from child_dialogs import ChildDialog

import ui_non_nsm_copy
import ui_client_properties

class NonNsmCopyDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui_non_nsm_copy.Ui_Dialog()
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

        self.ui.lineEditIcon.textEdited.connect(self.changeIconwithText)
        self.ui.pushButtonSaveChanges.clicked.connect(self.saveChanges)
        
        if self.client.non_nsm:
            self.ui.tabWidget.removeTab(1)
            
            self.ui.toolButtonBrowse.setEnabled(self._daemon_manager.is_local)
            self.ui.toolButtonBrowse.clicked.connect(self.browseConfigFile)
            self.ui.lineEditExecutable.textEdited.connect(
                self.lineEditExecutableEdited)
            self.ui.lineEditArguments.textChanged.connect(
                self.lineEditArgumentsChanged)
            self.ui.lineEditConfigFile.textChanged.connect(
                self.lineEditConfigFileChanged)
            
            self.ui.comboSaveSig.addItem(_translate('non_nsm', 'None'), 0)
            self.ui.comboSaveSig.addItem('SIGUSR1', 10)
            self.ui.comboSaveSig.addItem('SIGUSR2', 12)
            
            self.ui.comboStopSig.addItem('SIGTERM', 15)
            self.ui.comboStopSig.addItem('SIGINT', 2)
            self.ui.comboStopSig.addItem('SIGHUP', 1)
            self.ui.comboStopSig.addItem('SIGKILL', 9)
        else:
            self.ui.tabWidget.removeTab(2)
            
        self.ui.tabWidget.setCurrentIndex(0)

    def updateContents(self):
        self.ui.labelId.setText(self.client.client_id)
        self.ui.labelClientName.setText(self.client.name)
        self.ui.lineEditIcon.setText(self.client.icon_name)
        self.ui.lineEditLabel.setText(self.client.label)
        self.ui.plainTextEditDescription.setPlainText(self.client.description)
        self.ui.checkBoxSaveStop.setChecked(self.client.check_last_save)
        self.ui.lineEditIgnoredExtensions.setText(
            self.client.ignored_extensions)
        
        self.changeIconwithText(self.client.icon_name)
        
        if self.client.non_nsm:
            self.ui.lineEditExecutable.setText(self.client.executable_path)
            self.ui.lineEditArguments.setText(self.client.arguments)
            self.ui.lineEditConfigFile.setText(self.client.non_nsm_config_file)
            
            save_sig = self.client.non_nsm_save_sig
            
            for i in range(self.ui.comboSaveSig.count()):
                if self.ui.comboSaveSig.itemData(i) == save_sig:
                    self.ui.comboSaveSig.setCurrentIndex(i)
                    break
            else:
                try:
                    signal_text = str(
                        signal.Signals(save_sig)).rpartition('.')[2]
                    self.ui.comboSaveSig.addItem(signal_text, save_sig)
                    self.ui.comboSaveSig.setCurrentIndex(i+1)
                except:
                    self.ui.comboSaveSig.setCurrentIndex(0)
            
            stop_sig = self.client.non_nsm_stop_sig
            
            for i in range(self.ui.comboStopSig.count()):
                if self.ui.comboStopSig.itemData(i) == stop_sig:
                    self.ui.comboStopSig.setCurrentIndex(i)
                    break
            else:
                try:
                    signal_text = str(signal.Signals(
                        stop_sig)).rpartition('.')[2]
                    self.ui.comboStopSig.addItem(signal_text, stop_sig)
                    self.ui.comboStopSig.setCurrentIndex(i+1)
                except:
                    self.ui.comboStopSig.setCurrentIndex(0)
                
        else:
            self.ui.lineEditExecutableNSM.setText(self.client.executable_path)
            self.ui.lineEditArgumentsNSM.setText(self.client.arguments)
    
    def browseConfigFile(self):
        prefix = self._session.name
        if self.client.prefix_mode == ray.PrefixMode.CLIENT_NAME:
            prefix = self.client.name
        elif self.client.prefix_mode == ray.PrefixMode.CUSTOM:
            prefix = self.client.custom_prefix
        
        work_dir = "%s/%s.%s" % (self._session.path, prefix,
                                 self.client.client_id)
        
        config_file, ok = QFileDialog.getOpenFileName(
            self,
            _translate('Dialog', 'Select File to use as CONFIG_FILE'),
            work_dir)
        
        if not ok:
            return

        if not config_file.startswith(work_dir + '/'):
            qfile = QFile(config_file)
            if qfile.size() < 20971520:  # if file < 20Mb
                copy_dialog = NonNsmCopyDialog(self)
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
        self.ui.lineEditConfigFile.setText(self.config_file)
    
    def lineEditExecutableEdited(self, text):
        #self.checkAllowStart()
        pass

    def lineEditArgumentsChanged(self, text):
        #self.checkAllowStart()
        if ray.shellLineToArgs(text) is not None:
            self.ui.lineEditArguments.setStyleSheet('')
        else:
            self.ui.lineEditArguments.setStyleSheet(
                'QLineEdit{background: red}')
            #self.ui.pushButtonStart.setEnabled(False)

    def lineEditConfigFileChanged(self, text):
        if text and not self.ui.lineEditArguments.text():
            self.ui.lineEditArguments.setText('"$CONFIG_FILE"')
        elif (not text 
              and self.ui.lineEditArguments.text() == '"$CONFIG_FILE"'):
            self.ui.lineEditArguments.setText('')
    
    def changeIconwithText(self, text):
        icon = ray.getAppIcon(text, self)
        self.ui.toolButtonIcon.setIcon(icon)
        self.ui.toolButtonIconNsm.setIcon(icon)
        self.ui.toolButtonIconNonNsm.setIcon(icon)

    def saveChanges(self):
        if self.client.non_nsm:
            self.client.executable_path = self.ui.lineEditExecutable.text()
            self.client.arguments = self.ui.lineEditArguments.text()
            self.client.non_nsm_config_file = self.ui.lineEditConfigFile.text()
            self.client.non_nsm_save_sig = self.ui.comboSaveSig.currentData()
            self.client.non_nsm_stop_sig = self.ui.comboStopSig.currentData()
            self.client.non_nsm_wait_win = self.ui.checkBoxWaitWindow.isChecked()
        else:
            self.client.executable_path = self.ui.lineEditExecutableNSM.text()
            self.client.arguments = self.ui.lineEditArgumentsNSM.text()
            
        self.client.label = self.ui.lineEditLabel.text()
        self.client.description = \
                                self.ui.plainTextEditDescription.toPlainText()
        self.client.icon_name = self.ui.lineEditIcon.text()
        self.client.check_last_save = self.ui.checkBoxSaveStop.isChecked()
        self.client.ignored_extensions = \
                                    self.ui.lineEditIgnoredExtensions.text()
        self.client.sendPropertiesToDaemon()
        # better for user to wait a little before close the window
        QTimer.singleShot(150, self.accept)
