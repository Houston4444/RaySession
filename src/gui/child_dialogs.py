import os
import sys
import time
import signal

from PyQt5.QtWidgets import (
    QDialog, QDialogButtonBox, QTreeWidgetItem,
    QCompleter, QMessageBox, QFileDialog, QWidget)
from PyQt5.QtGui import QIcon, QPixmap, QGuiApplication
from PyQt5.QtCore import Qt, QTimer

import ray
from gui_server_thread import GUIServerThread
from gui_tools import (default_session_root, ErrDaemon, _translate,
                       CommandLineArgs, RS, isDarkTheme)

import ui_open_session
import ui_new_session
import ui_list_snapshots
import ui_save_template_session
import ui_nsm_open_info
import ui_abort_session
import ui_about_raysession
import ui_add_application
import ui_donations
import ui_jack_config_info
import ui_new_executable
import ui_error_dialog
import ui_quit_app
import ui_client_properties
import ui_script_info
import ui_script_user_action
import ui_stop_client
import ui_stop_client_no_save
import ui_abort_copy
import ui_client_trash
import ui_daemon_url
import ui_snapshot_progress
import ui_waiting_close_user

class ChildDialog(QDialog):
    def __init__(self, parent):
        QDialog.__init__(self, parent)
        self._session = parent._session
        self._signaler = self._session._signaler

        self._daemon_manager = self._session._daemon_manager

        self._signaler.server_status_changed.connect(self.serverStatusChanged)
        self._signaler.server_copying.connect(self.serverCopying)

        self.server_copying = parent.server_copying

    def toDaemon(self, *args):
        server = GUIServerThread.instance()
        if server:
            server.toDaemon(*args)
        else:
            sys.stderr.write('Error No GUI OSC Server, can not send %s.\n'
                             % args)

    def serverStatusChanged(self, server_status):
        return

    def serverCopying(self, bool_copying):
        self.server_copying = bool_copying
        self.serverStatusChanged(self._session.server_status)
        
    def changeRootFolder(self):
        root_folder = QFileDialog.getExistingDirectory(
            self, 
            _translate("root_folder_dialogs",
                       "Choose root folder for sessions"), 
            CommandLineArgs.session_root, 
            QFileDialog.ShowDirsOnly)
        
        if not root_folder:
            return
        
        # Security, kde dialogs sends $HOME if user type a folder path
        # that doesn't already exists.
        if os.getenv('HOME') and root_folder == os.getenv('HOME'):
            return
        
        errorDialog = QMessageBox(
            QMessageBox.Critical, 
            _translate('root_folder_dialogs', 'unwritable dir'), 
            _translate(
                'root_folder_dialogs',
                '<p>You have no permissions for %s,<br>' % root_folder \
                    + 'choose another directory !</p>'))
        
        if not os.path.exists(root_folder):
            try:
                os.makedirs(root_folder)
            except:
                errorDialog.exec()
                return
        
        if not os.access(root_folder, os.W_OK):
            errorDialog.exec()
            return
        
        RS.settings.setValue('default_session_root', root_folder)
        self.toDaemon('/ray/server/change_root', root_folder)

    def leaveEvent(self, event):
        if self.isActiveWindow():
            self.parent().mouse_is_inside = False
        QDialog.leaveEvent(self, event)

    def enterEvent(self, event):
        self.parent().mouse_is_inside = True
        QDialog.enterEvent(self, event)


class SessionItem(QTreeWidgetItem):
    def __init__(self, list):
        QTreeWidgetItem.__init__(self, list)
        
    def showConditionnaly(self, string):
        show = bool(string.lower() in self.data(0, Qt.UserRole).lower())
        
        n=0
        for i in range(self.childCount()):
            if self.child(i).showConditionnaly(string.lower()):
                n+=1
        if n:
            show = True
            
        self.setExpanded(bool(n and string))
        self.setHidden(not show)
        return show
    
    def findItemWith(self, string):
        if self.data(0, Qt.UserRole) == string:
            return self
        
        item = None
        
        for i in range(self.childCount()):
            item = self.child(i).findItemWith(string)
            if item:
                break
            
        return item
        
    def __lt__(self, other):
        if self.childCount() and not other.childCount():
            return True
        
        if other.childCount() and not self.childCount():
            return False
        
        return bool(self.text(0).lower() < other.text(0).lower())

class SessionFolder:
    name = ""
    has_session = True
    path = ""
    
    def __init__(self, name):
        self.name = name
        self.subfolders = []
    
    def setPath(self, path):
        self.path = path
    
    def makeItem(self):
        item = SessionItem([self.name])
        
        item.setData(0, Qt.UserRole, self.path)
        if self.subfolders:
            item.setIcon(0, QIcon.fromTheme('folder'))
        
        if not self.path:
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
        
        for folder in self.subfolders:
            sub_item = folder.makeItem()
            item.addChild(sub_item)
            
        return item
    
class OpenSessionDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui_open_session.Ui_DialogOpenSession()
        self.ui.setupUi(self)

        self.ui.toolButtonFolder.clicked.connect(self.changeRootFolder)
        self.ui.sessionList.currentItemChanged.connect(
            self.currentItemChanged)
        self.ui.sessionList.setFocus(Qt.OtherFocusReason)
        self.ui.sessionList.itemDoubleClicked.connect(self.goIfAny)
        self.ui.sessionList.itemClicked.connect(self.deployItem)
        self.ui.filterBar.textEdited.connect(self.updateFilteredList)
        self.ui.filterBar.updownpressed.connect(self.updownPressed)
        self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(False)
        self.ui.currentSessionsFolder.setText(CommandLineArgs.session_root)
        
        self._signaler.add_sessions_to_list.connect(self.addSessions)
        self._signaler.root_changed.connect(self.rootChanged)

        self.toDaemon('/ray/server/list_sessions', 0)
        
        if not self._daemon_manager.is_local:
            self.ui.toolButtonFolder.setVisible(False)
            self.ui.currentSessionsFolder.setVisible(False)
            self.ui.labelSessionsFolder.setVisible(False)

        self.server_will_accept = False
        self.has_selection = False

        self.serverStatusChanged(self._session.server_status)
        
        self.folders = []
        self.all_items = []
        
        self._last_mouse_click = 0
        
    def serverStatusChanged(self, server_status):
        self.ui.toolButtonFolder.setEnabled(
            bool(server_status in (ray.ServerStatus.OFF,
                                   ray.ServerStatus.READY,
                                   ray.ServerStatus.CLOSE)))

        self.server_will_accept = bool(
            server_status in (
                ray.ServerStatus.OFF,
                ray.ServerStatus.READY) and not self.server_copying)
        self.preventOk()
        
    def rootChanged(self, session_root):
        self.ui.currentSessionsFolder.setText(session_root)
        self.ui.sessionList.clear()
        self.folders.clear()
        self.toDaemon('/ray/server/list_sessions', 0)

    def addSessions(self, session_names):
        for session_name in session_names:
            folder_div = session_name.split('/')
            folders = self.folders
            
            for i in range(len(folder_div)):
                f = folder_div[i]
                for g in folders:
                    if g.name == f:
                        if i+1 == len(folder_div):
                            g.setPath(session_name)
                            
                        folders = g.subfolders
                        break
                else:
                    new_folder = SessionFolder(f)
                    if i+1 == len(folder_div):
                        new_folder.setPath(session_name)
                    folders.append(new_folder)
                    folders = new_folder.subfolders
                        
        self.ui.sessionList.clear()
        
        for folder in self.folders:
            item = folder.makeItem()
            self.ui.sessionList.addTopLevelItem(item)
        
        self.ui.sessionList.sortByColumn(0, Qt.AscendingOrder)
        
        # Try to select last used session
        root_item = self.ui.sessionList.invisibleRootItem()
        for i in range(root_item.childCount()):
            item = root_item.child(i)
            last_session_item = item.findItemWith(
                RS.settings.value('last_session', type=str))
            
            if last_session_item:
                self.ui.sessionList.setCurrentItem(last_session_item)
                self.ui.sessionList.scrollToItem(last_session_item)
                break

    def updateFilteredList(self, filt):
        filter_text = self.ui.filterBar.displayText()
        root_item = self.ui.sessionList.invisibleRootItem()

        ## hide all non matching items
        for i in range(root_item.childCount()):
            root_item.child(i).showConditionnaly(filter_text)

        # if selected item not in list, then select the first visible
        if (not self.ui.sessionList.currentItem()
                or self.ui.sessionList.currentItem().isHidden()):
            for i in range(root_item.childCount()):
                item = root_item.child(i)
                if not item.isHidden():
                    self.ui.sessionList.setCurrentItem(item)
                    break

        if (not self.ui.sessionList.currentItem()
                or self.ui.sessionList.currentItem().isHidden()):
            self.ui.filterBar.setStyleSheet(
                "QLineEdit { background-color: red}")
            self.ui.sessionList.setCurrentItem(None)
        else:
            self.ui.filterBar.setStyleSheet("")
            self.ui.sessionList.scrollTo(self.ui.sessionList.currentIndex())

    def updownPressed(self, key):
        root_item = self.ui.sessionList.invisibleRootItem()
        row = self.ui.sessionList.currentIndex().row()
        
        if key == Qt.Key_Up:
            if row == 0:
                return
            row -= 1
            while root_item.child(row).isHidden():
                if row == 0:
                    return
                row -= 1
        elif key == Qt.Key_Down:
            if row == root_item.childCount() - 1:
                return
            row += 1
            while root_item.child(row).isHidden():
                if row == root_item.childCount() - 1:
                    return
                row += 1
                
        self.ui.sessionList.setCurrentItem(root_item.child(row))

    def currentItemChanged(self, item, previous_item):
        self.has_selection = bool(item and item.data(0, Qt.UserRole))
        self.preventOk()

    def preventOk(self):
        self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(
            bool(self.server_will_accept and self.has_selection))

    def getSelectedSession(self):
        if self.ui.sessionList.currentItem():
            return self.ui.sessionList.currentItem().data(0, Qt.UserRole)
    
    def deployItem(self, item, column):
        if not item.childCount():
            return 
        
        if time.time() - self._last_mouse_click > 0.35:
            item.setExpanded(not item.isExpanded())
            
        self._last_mouse_click = time.time()
        
    def goIfAny(self, item, column):
        if item.childCount():
            return 
        
        if (self.server_will_accept and self.has_selection
            and self.ui.sessionList.currentItem().data(0, Qt.UserRole)):
                self.accept()
            

class NewSessionDialog(ChildDialog):
    def __init__(self, parent, duplicate_window=False):
        ChildDialog.__init__(self, parent)
        self.ui = ui_new_session.Ui_DialogNewSession()
        self.ui.setupUi(self)

        self.is_duplicate = bool(duplicate_window)

        self.ui.currentSessionsFolder.setText(CommandLineArgs.session_root)
        self.ui.toolButtonFolder.clicked.connect(self.changeRootFolder)
        self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(False)
        self.ui.lineEdit.setFocus(Qt.OtherFocusReason)
        self.ui.lineEdit.textChanged.connect(self.textChanged)

        self.session_list = []
        self.template_list = []
        self.sub_folders = []

        self._signaler.server_status_changed.connect(self.serverStatusChanged)
        self._signaler.add_sessions_to_list.connect(self.addSessionsToList)
        self._signaler.session_template_found.connect(self.addTemplatesToList)
        self._signaler.root_changed.connect(self.rootChanged)
        
        self.toDaemon('/ray/server/list_sessions', 1)
        
        if self.is_duplicate:
            self.ui.labelTemplate.setVisible(False)
            self.ui.comboBoxTemplate.setVisible(False)
            self.ui.labelNewSessionName.setText(
                _translate('Duplicate', 'Duplicated session name :'))
            self.setWindowTitle(_translate('Duplicate', 'Duplicate Session'))
        else:
            self.toDaemon('/ray/server/list_session_templates')

        if not self._daemon_manager.is_local:
            self.ui.toolButtonFolder.setVisible(False)
            self.ui.currentSessionsFolder.setVisible(False)
            self.ui.labelSessionsFolder.setVisible(False)

        self.initTemplatesComboBox()
        self.setLastTemplateSelected()
        
        self.ui.labelSubFolder.setVisible(False)
        self.ui.comboBoxSubFolder.setVisible(False)

        self.server_will_accept = False
        self.text_is_valid = False

        self.serverStatusChanged(self._session.server_status)

    def serverStatusChanged(self, server_status):
        self.ui.toolButtonFolder.setEnabled(
            bool(server_status == ray.ServerStatus.OFF))

        self.server_will_accept = bool(
            server_status in (
                ray.ServerStatus.OFF,
                ray.ServerStatus.READY) and not self.server_copying)
        if self.is_duplicate:
            self.server_will_accept = bool(
                server_status == ray.ServerStatus.READY and not self.server_copying)

        self.preventOk()
    
    def rootChanged(self, session_root):
        self.ui.currentSessionsFolder.setText(session_root)
        self.session_list.clear()
        self.sub_folders.clear()
        self.initSubFolderCombobox()
        self.toDaemon('/ray/server/list_sessions', 1)
    
    def initTemplatesComboBox(self):
        self.ui.comboBoxTemplate.clear()
        self.ui.comboBoxTemplate.addItem(
            _translate('session_template', "empty"))
        self.ui.comboBoxTemplate.addItem(
            _translate('session_template', "with JACK patch memory"))
        self.ui.comboBoxTemplate.addItem(
            _translate('session_template', "with JACK config memory"))
        self.ui.comboBoxTemplate.addItem(
            _translate('session_template', "with basic scripts"))
        
        misscount = self.ui.comboBoxTemplate.count()  - 1 - len(
                                                ray.factory_session_templates)
        for i in range(misscount):
            self.ui.comboBoxTemplate.addItem(
                ray.factory_session_templates[-i])
            
        self.ui.comboBoxTemplate.insertSeparator(
                                    len(ray.factory_session_templates) + 1)

    def initSubFolderCombobox(self):
        self.ui.comboBoxSubFolder.clear()
        self.ui.comboBoxSubFolder.addItem(_translate('new_session', 'none'))
        
        for sub_folder in self.sub_folders:
            self.ui.comboBoxSubFolder.addItem(QIcon.fromTheme('folder'), 
                                              sub_folder)
        
        self.ui.labelSubFolder.setVisible(bool(self.sub_folders))
        self.ui.comboBoxSubFolder.setVisible(bool(self.sub_folders))
        
    def setLastTemplateSelected(self):
        last_used_template = RS.settings.value('last_used_template', type=str)

        if last_used_template.startswith('///'):
            last_factory_template = last_used_template.replace('///', '', 1)
            
            for i in range(len(ray.factory_session_templates)):
                factory_template = ray.factory_session_templates[i]
                if factory_template == last_factory_template:
                    self.ui.comboBoxTemplate.setCurrentIndex(i+1)
                    break
        else:
            if last_used_template in self.template_list:
                self.ui.comboBoxTemplate.setCurrentText(last_used_template)

        if not last_used_template:
            self.ui.comboBoxTemplate.setCurrentIndex(1)

    def setLastSubFolderSelected(self):
        last_subfolder = RS.settings.value('last_subfolder', type=str)
        
        if last_subfolder:
            self.ui.comboBoxSubFolder.setCurrentText(last_subfolder)
        else:
            self.ui.comboBoxSubFolder.setCurrentIndex(0)
    
    def addSessionsToList(self, session_names):
        self.session_list += session_names
        
        for session_name in session_names:
            if '/' in session_name:
                new_dir = os.path.dirname(session_name)
                if not new_dir in self.sub_folders:
                    self.sub_folders.append(new_dir)
        
        self.sub_folders.sort()
        self.initSubFolderCombobox()
        self.setLastSubFolderSelected()

    def addTemplatesToList(self, template_list):
        for template in template_list:
            if template not in self.template_list:
                self.template_list.append(template)

        if not self.template_list:
            return

        self.template_list.sort()

        self.initTemplatesComboBox()

        for template_name in self.template_list:
            self.ui.comboBoxTemplate.addItem(template_name)

        self.setLastTemplateSelected()

    def getSessionName(self):
        if self.ui.comboBoxSubFolder.currentIndex() > 0:
            return '%s/%s' % (self.ui.comboBoxSubFolder.currentText(),
                              self.ui.lineEdit.text())
        else:
            return self.ui.lineEdit.text()

    def getTemplateName(self):
        index = self.ui.comboBoxTemplate.currentIndex()
        
        if index == 0:
            return ""

        if index <= len(ray.factory_session_templates):
            return '///' + ray.factory_session_templates[index-1]

        return self.ui.comboBoxTemplate.currentText()
    
    def getSubFolder(self):
        if self.ui.comboBoxSubFolder.currentIndex() == 0:
            return ""
        
        return  self.ui.comboBoxSubFolder.currentText()
    
    def textChanged(self, text):
        full_session_text = text
        if self.ui.comboBoxSubFolder.currentIndex():
            full_session_text = "%s/%s" % (
                                    self.ui.comboBoxSubFolder.currentText(),
                                    text)
            
        self.text_is_valid = bool(text
                                  and full_session_text 
                                        not in self.session_list)
        self.preventOk()

    def preventOk(self):
        self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(
            bool(self.server_will_accept and self.text_is_valid))


class AbstractSaveTemplateDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui_save_template_session.Ui_DialogSaveTemplateSession()
        self.ui.setupUi(self)

        self.server_will_accept = False

        self.ui.lineEdit.textEdited.connect(self.textEdited)
        self.ui.pushButtonAccept.clicked.connect(self.verifyAndAccept)
        self.ui.pushButtonAccept.setEnabled(False)

    def textEdited(self, text):
        if '/' in text:
            self.ui.lineEdit.setText(text.replace('/', '⁄'))
        self.allowOkButton()

    def getTemplateName(self):
        return self.ui.lineEdit.text()

    def allowOkButton(self, text=''):
        self.ui.pushButtonAccept.setEnabled(
            bool(self.server_will_accept and self.ui.lineEdit.text()))

    def verifyAndAccept(self):
        template_name = self.getTemplateName()
        if template_name in self.template_list:
            ret = QMessageBox.question(
                self,
                _translate(
                    'session template',
                    'Overwrite Template ?'),
                _translate(
                    'session_template',
                    'Template <strong>%s</strong> already exists.\nOverwrite it ?') %
                template_name)
            if ret == QMessageBox.No:
                return
        self.accept()


class SaveTemplateSessionDialog(AbstractSaveTemplateDialog):
    def __init__(self, parent):
        AbstractSaveTemplateDialog.__init__(self, parent)

        self.template_list = []

        self._signaler.session_template_found.connect(self.addTemplatesToList)
        self.toDaemon('/ray/server/list_session_templates')

        self.serverStatusChanged(self._session.server_status)

    def serverStatusChanged(self, server_status):
        self.server_will_accept = bool(server_status == ray.ServerStatus.READY)

        if server_status == ray.ServerStatus.OFF:
            self.reject()

        self.allowOkButton()

    def addTemplatesToList(self, template_list):
        self.template_list += template_list


class SaveTemplateClientDialog(AbstractSaveTemplateDialog):
    def __init__(self, parent):
        AbstractSaveTemplateDialog.__init__(self, parent)

        self.template_list = []
        self.ui.pushButtonAccept.setEnabled(False)

        self.ui.labelNewTemplateName.setText(
            _translate(
                'new client template',
                "New application template name :"))

        self._signaler.user_client_template_found.connect(
            self.addTemplatesToList)

        self.toDaemon('/ray/server/list_user_client_templates')

        self.serverStatusChanged(self._session.server_status)

    def serverStatusChanged(self, server_status):
        self.server_will_accept = bool(
            server_status not in (
                ray.ServerStatus.OFF,
                ray.ServerStatus.CLOSE) and not self.server_copying)

        if server_status == ray.ServerStatus.OFF:
            self.reject()

        self.allowOkButton()

    def addTemplatesToList(self, template_list):
        for template in template_list:
            self.template_list.append(template.split('/')[0])


class ClientPropertiesDialog(ChildDialog):
    def __init__(self, parent, client):
        ChildDialog.__init__(self, parent)
        self.ui = ui_client_properties.Ui_Dialog()
        self.ui.setupUi(self)

        self.client = client

        self.ui.lineEditIcon.textEdited.connect(self.changeIconwithText)
        self.ui.pushButtonSaveChanges.clicked.connect(self.saveChanges)
        
        if self.client.non_nsm:
            self.ui.tabWidget.removeTab(1)
            
            self.ui.comboSaveSig.addItem(_translate('non_nsm', 'None'), 0)
            self.ui.comboSaveSig.addItem('SIGUSR1', 10)
            self.ui.comboSaveSig.addItem('SIGUSR2', 12)
            
            self.ui.comboStopSig.addItem('SIGTERM', 15)
            self.ui.comboStopSig.addItem('SIGINT', 2)
            self.ui.comboStopSig.addItem('SIGHUP', 1)
        else:
            self.ui.tabWidget.removeTab(2)

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
    
class ClientTrashDialog(ChildDialog):
    def __init__(self, parent, client_data):
        ChildDialog.__init__(self, parent)
        self.ui = ui_client_trash.Ui_Dialog()
        self.ui.setupUi(self)

        self.client_data = client_data

        self.ui.labelExecutable.setText(self.client_data.executable_path)
        self.ui.labelId.setText(self.client_data.client_id)
        self.ui.labelClientName.setText(self.client_data.name)
        self.ui.labelClientIcon.setText(self.client_data.icon)
        self.ui.labelClientLabel.setText(self.client_data.label)
        self.ui.checkBoxSaveStop.setChecked(self.client_data.check_last_save)
        self.ui.toolButtonIcon.setIcon(QIcon.fromTheme(self.client_data.icon))

        self.ui.pushButtonRemove.clicked.connect(self.removeClient)

    def serverStatusChanged(self, server_status):
        if server_status in (ray.ServerStatus.CLOSE,
                             ray.ServerStatus.OFF,
                             ray.ServerStatus.OUT_SAVE,
                             ray.ServerStatus.OUT_SNAPSHOT,
                             ray.ServerStatus.WAIT_USER):
            self.reject()

    def removeClient(self):
        self.toDaemon(
            '/ray/trashed_client/remove_definitely',
            self.client_data.client_id)
        self.reject()


class AbortSessionDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui_abort_session.Ui_AbortSession()
        self.ui.setupUi(self)

        self.ui.pushButtonAbort.clicked.connect(self.accept)
        self.ui.pushButtonCancel.clicked.connect(self.reject)
        self.ui.pushButtonCancel.setFocus(Qt.OtherFocusReason)

        self.serverStatusChanged(self._session.server_status)

    def serverStatusChanged(self, server_status):
        self.ui.pushButtonAbort.setEnabled(
            not bool(
                server_status in (
                    ray.ServerStatus.CLOSE,
                    ray.ServerStatus.OFF,
                    ray.ServerStatus.COPY)))
        if server_status == ray.ServerStatus.OFF:
            self.reject()


class AbortServerCopyDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui_abort_copy.Ui_Dialog()
        self.ui.setupUi(self)

        self._signaler.server_progress.connect(self.setProgress)

        self.serverStatusChanged(self._session.server_status)

    def serverStatusChanged(self, server_status):
        if server_status not in (
                ray.ServerStatus.PRECOPY,
                ray.ServerStatus.COPY):
            self.reject()

    def setProgress(self, progress):
        self.ui.progressBar.setValue(progress * 100)


class AbortClientCopyDialog(ChildDialog):
    def __init__(self, parent, client_id):
        ChildDialog.__init__(self, parent)
        self.ui = ui_abort_copy.Ui_Dialog()
        self.ui.setupUi(self)

        self.client_id = client_id

        self._signaler.client_progress.connect(self.setProgress)

    def setProgress(self, client_id, progress):
        if client_id != self.client_id:
            return

        self.ui.progressBar.setValue(progress * 100)

    def serverStatusChanged(self, server_status):
        if not self.server_copying:
            self.reject()


class OpenNsmSessionInfoDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui_nsm_open_info.Ui_Dialog()
        self.ui.setupUi(self)

        self.ui.checkBox.stateChanged.connect(self.showThis)

    def showThis(self, state):
        RS.settings.setValue('OpenNsmSessionInfo', not bool(state))


class QuitAppDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui_quit_app.Ui_DialogQuitApp()
        self.ui.setupUi(self)
        self.ui.pushButtonCancel.setFocus(Qt.OtherFocusReason)
        self.ui.pushButtonSaveQuit.clicked.connect(self.closeSession)
        self.ui.pushButtonQuitNoSave.clicked.connect(self.abortSession)
        self.ui.pushButtonDaemon.clicked.connect(self.leaveDaemonRunning)
        
        original_text = self.ui.labelExecutable.text()
        self.ui.labelExecutable.setText(
            original_text %
            ('<strong>%s</strong>' %
             self._session.name))

        self.serverStatusChanged(self._session.server_status)

    def serverStatusChanged(self, server_status):
        if server_status == ray.ServerStatus.OFF:
            self.accept()
            return

        self.ui.pushButtonSaveQuit.setEnabled(
            bool(server_status == ray.ServerStatus.READY))
        self.ui.pushButtonQuitNoSave.setEnabled(
            bool(server_status != ray.ServerStatus.CLOSE))

    def closeSession(self):
        self.toDaemon('/ray/session/close')

    def abortSession(self):
        self.toDaemon('/ray/session/abort')
        
    def leaveDaemonRunning(self):
        self._daemon_manager.disannounce()
        QTimer.singleShot(10, QGuiApplication.quit)


class AboutRaySessionDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui_about_raysession.Ui_DialogAboutRaysession()
        self.ui.setupUi(self)
        all_text = self.ui.labelRayAndVersion.text()
        self.ui.labelRayAndVersion.setText(all_text % ray.VERSION)


class NewExecutableDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui_new_executable.Ui_DialogNewExecutable()
        self.ui.setupUi(self)
        
        self.ui.groupBoxAdvanced.setVisible(False)
        self.resize(0, 0)
        self.ui.labelPrefixMode.setToolTip(
            self.ui.comboBoxPrefixMode.toolTip())
        self.ui.labelClientId.setToolTip(self.ui.lineEditClientId.toolTip())
        
        self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(False)
        self.ui.lineEdit.setFocus(Qt.OtherFocusReason)
        self.ui.lineEdit.textChanged.connect(self.textChanged)

        self.ui.checkBoxProxy.stateChanged.connect(self.proxyStateChanged)
        
        self.ui.lineEditPrefix.setEnabled(False)
        self.ui.toolButtonAdvanced.clicked.connect(self.showAdvanced)
        
        self.ui.comboBoxPrefixMode.addItem(
            _translate('new_executable', 'Custom'))
        self.ui.comboBoxPrefixMode.addItem(
            _translate('new_executable', 'Client Name'))
        self.ui.comboBoxPrefixMode.addItem(
            _translate('new_executable', 'Session Name'))
        self.ui.comboBoxPrefixMode.setCurrentIndex(2)
        
        self.ui.comboBoxPrefixMode.currentIndexChanged.connect(
            self.prefixModeChanged)
        
        self._signaler.new_executable.connect(self.addExecutableToCompleter)
        self.toDaemon('/ray/server/list_path')

        self.exec_list = []

        self.completer = QCompleter(self.exec_list)
        self.ui.lineEdit.setCompleter(self.completer)

        self.ui.lineEdit.returnPressed.connect(self.closeNow)
        
        self.serverStatusChanged(self._session.server_status)
        
        self.text_will_accept = False

    def showAdvanced(self):
        self.ui.groupBoxAdvanced.setVisible(True)
        self.ui.toolButtonAdvanced.setVisible(False)
    
    def prefixModeChanged(self, index):
        self.ui.lineEditPrefix.setEnabled(bool(index == 0))
    
    def addExecutableToCompleter(self, executable_list):
        self.exec_list += executable_list
        self.exec_list.sort()

        del self.completer
        self.completer = QCompleter(self.exec_list)
        self.ui.lineEdit.setCompleter(self.completer)

    def getExecutableSelected(self):
        return self.ui.lineEdit.text()

    def runViaProxy(self):
        return bool(self.ui.checkBoxProxy.isChecked())
    
    def getSelection(self):
        return (self.ui.lineEdit.text(),
                self.ui.checkBoxStartClient.isChecked(),
                self.ui.checkBoxProxy.isChecked(),
                self.ui.comboBoxPrefixMode.currentIndex(),
                self.ui.lineEditPrefix.text(),
                self.ui.lineEditClientId.text())
    
    def proxyStateChanged(self, state):
        self.ui.buttonBox.button(
            QDialogButtonBox.Ok).setEnabled(
            state or self.text_will_accept)

    def textChanged(self, text):
        self.text_will_accept = bool(text)
        self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(
            self.ui.checkBoxProxy.isChecked() or self.text_will_accept)

    def closeNow(self):
        if (self.ui.lineEdit.text() in self.exec_list
                or self.ui.checkBoxProxy.isChecked()):
            self.accept()

    def serverStatusChanged(self, server_status):
        if server_status in (ray.ServerStatus.OUT_SAVE,
                             ray.ServerStatus.OUT_SNAPSHOT,
                             ray.ServerStatus.WAIT_USER,
                             ray.ServerStatus.CLOSE,
                             ray.ServerStatus.OFF):
            self.reject()


class StopClientDialog(ChildDialog):
    def __init__(self, parent, client_id):
        ChildDialog.__init__(self, parent)
        self.ui = ui_stop_client.Ui_Dialog()
        self.ui.setupUi(self)

        self.client_id = client_id
        self.wait_for_save = False

        self.client = self._session.getClient(client_id)

        if self.client:
            text = self.ui.label.text() % self.client.prettierName()

            if not self.client.has_dirty:
                minutes = int((time.time() - self.client.last_save) / 60)
                text = _translate(
                    'client_stop',
                    "<strong>%s</strong> seems to has not been saved for %i minute(s).<br />Do you really want to stop it ?") \
                        % (self.client.prettierName(), minutes)

            self.ui.label.setText(text)
            
            self.client.status_changed.connect(self.serverUpdatesClientStatus)

        self.ui.pushButtonSaveStop.clicked.connect(self.saveAndStop)
        self.ui.checkBox.stateChanged.connect(self.checkBoxClicked)

    def saveAndStop(self):
        self.wait_for_save = True
        self.toDaemon('/ray/client/save', self.client_id)

    def checkBoxClicked(self, state):
        self.client.check_last_save = not bool(state)
        self.client.sendPropertiesToDaemon()

    def serverUpdatesClientStatus(self, status):
        if status in (ray.ClientStatus.STOPPED, ray.ClientStatus.REMOVED):
            self.reject()
            return

        if status == ray.ClientStatus.READY and self.wait_for_save:
            self.wait_for_save = False
            self.accept()


class StopClientNoSaveDialog(ChildDialog):
    def __init__(self, parent, client_id):
        ChildDialog.__init__(self, parent)
        self.ui = ui_stop_client_no_save.Ui_Dialog()
        self.ui.setupUi(self)
        
        self.client_id = client_id
        self.client = self._session.getClient(client_id)

        if self.client:
            text = self.ui.label.text() % self.client.prettierName()
            self.ui.label.setText(text)
            self.client.status_changed.connect(self.serverUpdatesClientStatus)
        
        self.ui.checkBox.stateChanged.connect(self.checkBoxClicked)
        self.ui.pushButtonCancel.setFocus(True)
        
    def serverUpdatesClientStatus(self, status):
        if status in (ray.ClientStatus.STOPPED, ray.ClientStatus.REMOVED):
            self.reject()
            return
        
    def checkBoxClicked(self, state):
        self.client.check_last_save = not bool(state)
        self.client.sendPropertiesToDaemon()


class SnapShotProgressDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui_snapshot_progress.Ui_Dialog()
        self.ui.setupUi(self)
        self._signaler.server_progress.connect(self.serverProgress)
        
    def serverStatusChanged(self, server_status):
        self.close()
        
    def serverProgress(self, value):
        self.ui.progressBar.setValue(value * 100)
        

class ScriptInfoDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui_script_info.Ui_Dialog()
        self.ui.setupUi(self)
        
    def setInfoLabel(self, text):
        self.ui.infoLabel.setText(text)
        
    def shouldBeRemoved(self):
        return False


class ScriptUserActionDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui_script_user_action.Ui_Dialog()
        self.ui.setupUi(self)
        
        self.ui.buttonBox.clicked.connect(self.buttonBoxClicked)
        self.ui.infoLabel.setVisible(False)
        self.ui.infoLine.setVisible(False)
        
        self._is_terminated = False
        
    def setMainText(self, text):
        self.ui.label.setText(text)
    
    def setInfoLabel(self, text):
        self.ui.infoLabel.setText(text)
        self.ui.infoLabel.setVisible(True)
        self.ui.infoLine.setVisible(True)
    
    def validate(self):
        self.toDaemon('/reply', '/ray/gui/script_user_action',
                      'Dialog window validated')
        self._is_terminated = True
        self.accept()
        
    def abort(self):
        self.toDaemon('/error', '/ray/gui/script_user_action', 
                      ray.Err.ABORT_ORDERED, 'Script user action aborted!')
        self._is_terminated = True
        self.accept()
    
    def buttonBoxClicked(self, button):
        if button == self.ui.buttonBox.button(QDialogButtonBox.Yes):
            self.validate()
        elif button == self.ui.buttonBox.button(QDialogButtonBox.Ignore):
            self.abort()
            
    def shouldBeRemoved(self):
        return self._is_terminated

class JackConfigInfoDialog(ChildDialog):
    def __init__(self, parent, session_path):
        ChildDialog.__init__(self, parent)
        self.ui = ui_jack_config_info.Ui_Dialog()
        self.ui.setupUi(self)
        
        scripts_dir = "%s/%s" % (session_path, ray.SCRIPTS_DIR)
        parent_path = os.path.dirname(session_path)
        parent_scripts = "%s/%s" % (parent_path, ray.SCRIPTS_DIR)
        
        tooltip_text = self.ui.label.toolTip().text()
        
        self.ui.label.toolTip().setText(
            tooltip_text % (scripts_dir, parent_scripts, parent_path))
    

class DaemonUrlWindow(ChildDialog):
    def __init__(self, parent, err_code, ex_url):
        ChildDialog.__init__(self, parent)
        self.ui = ui_daemon_url.Ui_Dialog()
        self.ui.setupUi(self)

        self.ui.lineEdit.textChanged.connect(self.allowUrl)

        error_text = ''
        if err_code == ErrDaemon.NO_ANNOUNCE:
            error_text = _translate(
                "url_window",
                "<p>daemon at<br><strong>%s</strong><br>didn't announce !<br></p>") % ex_url
        elif err_code == ErrDaemon.NOT_OFF:
            error_text = _translate(
                "url_window",
                "<p>daemon at<br><strong>%s</strong><br>has a loaded self._session.<br>It can't be used for slave session</p>") % ex_url
        elif err_code == ErrDaemon.WRONG_ROOT:
            error_text = _translate(
                "url_window",
                "<p>daemon at<br><strong>%s</strong><br>uses an other session root folder !<.p>") % ex_url
        elif err_code == ErrDaemon.FORBIDDEN_ROOT:
            error_text = _translate(
                "url_window",
                "<p>daemon at<br><strong>%s</strong><br>uses a forbidden session root folder !<.p>") % ex_url
        elif err_code == ErrDaemon.WRONG_VERSION:
            error_text = _translate(
                "url_window",
                "<p>daemon at<br><strong>%s</strong><br>uses another %s version.<.p>") % (ex_url, ray.APP_TITLE)
        else:
            error_text = _translate("url window", "<p align=\"left\">To run a network session,<br>open a terminal on another computer of this network.<br>Launch ray-daemon on port 1234 (for example)<br>by typing the command :</p><p align=\"left\"><code>ray-daemon -p 1234</code></p><p align=\"left\">Then paste below the first url<br>that ray-daemon gives you at startup.</p><p></p>")

        self.ui.labelError.setText(error_text)
        self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(False)

        self.tried_urls = ray.getListInSettings(RS.settings, 'network/tried_urls')
        last_tried_url = RS.settings.value('network/last_tried_url', '', type=str)

        self.completer = QCompleter(self.tried_urls)
        self.ui.lineEdit.setCompleter(self.completer)

        if ex_url:
            self.ui.lineEdit.setText(ex_url)
        elif last_tried_url:
            self.ui.lineEdit.setText(last_tried_url)

    def getDaemonUrl(self):
        return self.ui.lineEdit.text()

    def allowUrl(self, text):
        if not text:
            self.ui.lineEdit.completer().complete()
            self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(False)
            return

        if not text.startswith('osc.udp://'):
            self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(False)
            return

        try:
            addr = ray.getLibloAddress(text)
            self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(True)
        except BaseException:
            self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(False)

    def getUrl(self):
        return self.ui.lineEdit.text()


class WaitingCloseUserDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui_waiting_close_user.Ui_Dialog()
        self.ui.setupUi(self)
        
        if isDarkTheme(self):
            self.ui.labelSaveIcon.setPixmap(
                QPixmap(':scalable/breeze-dark/document-nosave.svg'))
        
        self.ui.pushButtonOk.setFocus(True)
        self.ui.pushButtonUndo.clicked.connect(self.undoClose)
        self.ui.pushButtonSkip.clicked.connect(self.skip)
        self.ui.checkBox.setChecked(
            bool(RS.settings.value(
                'hide_wait_close_user_dialog', False, type=bool)))
        
        self.ui.checkBox.clicked.connect(self.checkBoxClicked)
        
    def serverStatusChanged(self, server_status):
        if server_status != ray.ServerStatus.WAIT_USER:
            self.accept()
    
    def undoClose(self):
        self.toDaemon('/ray/session/cancel_close')
    
    def skip(self):
        self.toDaemon('/ray/session/skip_wait_user')
        
    def checkBoxClicked(self, state):
        RS.settings.setValue('hide_wait_close_user_dialog',
                             bool(state), type=bool)

class DonationsDialog(ChildDialog):
    def __init__(self, parent, display_no_again):
        ChildDialog.__init__(self, parent)
        self.ui = ui_donations.Ui_Dialog()
        self.ui.setupUi(self)
        
        self.ui.checkBox.setVisible(display_no_again)
        self.ui.checkBox.clicked.connect(self.checkBoxClicked)
        
    def checkBoxClicked(self, state):
        RS.settings.setValue('hide_donations', state)
        

class ErrorDialog(ChildDialog):
    def __init__(self, parent, message):
        ChildDialog.__init__(self, parent)
        self.ui = ui_error_dialog.Ui_Dialog()
        self.ui.setupUi(self)

        self.ui.label.setText(message)

