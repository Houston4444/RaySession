import os
import sys
import time
from PyQt5.QtWidgets import (
    QDialog, QDialogButtonBox, QListWidgetItem,
    QCompleter, QMessageBox, QFileDialog)
from PyQt5.QtGui import QIcon
from PyQt5.QtCore import Qt, QTimer

import ray
from gui_server_thread import GUIServerThread
from gui_tools import (default_session_root, ErrDaemon, _translate,
                       CommandLineArgs, RS)

import ui_open_session
import ui_new_session
import ui_list_snapshots
import ui_save_template_session
import ui_nsm_open_info
import ui_abort_session
import ui_about_raysession
import ui_add_application
import ui_new_executable
import ui_error_dialog
import ui_quit_app
import ui_client_properties
import ui_stop_client
import ui_abort_copy
import ui_client_trash
import ui_daemon_url
import ui_edit_executable
import ui_snapshot_progress

class ChildDialog(QDialog):
    def __init__(self, parent):
        QDialog.__init__(self, parent)
        self._session = parent._session
        self._signaler = self._session._signaler

        daemon_manager = self._session._daemon_manager
        self.daemon_launched_before = daemon_manager.launched_before

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


class OpenSessionDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui_open_session.Ui_DialogOpenSession()
        self.ui.setupUi(self)

        self.f_last_session_item = None

        self.ui.toolButtonFolder.clicked.connect(self.changeRootFolder)
        self.ui.sessionList.currentItemChanged.connect(self.currentItemChanged)
        self.ui.sessionList.setFocus(Qt.OtherFocusReason)
        self.ui.filterBar.textEdited.connect(self.updateFilteredList)
        self.ui.filterBar.updownpressed.connect(self.updownPressed)
        self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(False)
        self.ui.currentNsmFolder.setText(CommandLineArgs.session_root)

        self._signaler.add_sessions_to_list.connect(self.addSessions)
        self._signaler.root_changed.connect(self.rootChanged)

        self.toDaemon('/ray/server/list_sessions', 0)

        if self.daemon_launched_before:
            self.ui.toolButtonFolder.setVisible(False)
            self.ui.currentNsmFolder.setVisible(False)
            self.ui.labelNsmFolder.setVisible(False)

        self.server_will_accept = False
        self.has_selection = False

        self.serverStatusChanged(self._session.server_status)

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
        self.ui.currentNsmFolder.setText(session_root)
        self.ui.sessionList.clear()
        self.toDaemon('/ray/server/list_sessions', 0)

    def addSessions(self, session_names):
        for session_name in session_names:
            if session_name == RS.settings.value('last_session', type=str):
                self.f_last_session_item = QListWidgetItem(session_name)
                self.ui.sessionList.addItem(self.f_last_session_item)
                self.ui.sessionList.setCurrentItem(self.f_last_session_item)
            else:
                self.ui.sessionList.addItem(session_name)

            self.ui.sessionList.sortItems()

            if self.f_last_session_item:
                current_index = self.ui.sessionList.currentIndex()
                self.ui.sessionList.scrollTo(current_index)
            else:
                self.ui.sessionList.setCurrentRow(0)

    def updateFilteredList(self, filt):
        filter_text = self.ui.filterBar.displayText()

        # show all items
        for i in range(self.ui.sessionList.count()):
            self.ui.sessionList.item(i).setHidden(False)

        liist = self.ui.sessionList.findItems(filter_text, Qt.MatchContains)

        # hide all non matching items
        for i in range(self.ui.sessionList.count()):
            if self.ui.sessionList.item(i) not in liist:
                self.ui.sessionList.item(i).setHidden(True)

        # if selected item not in list, then select the first visible
        if not self.ui.sessionList.currentItem(
        ) or self.ui.sessionList.currentItem().isHidden():
            for i in range(self.ui.sessionList.count()):
                if not self.ui.sessionList.item(i).isHidden():
                    self.ui.sessionList.setCurrentRow(i)
                    break

        if not self.ui.sessionList.currentItem(
        ) or self.ui.sessionList.currentItem().isHidden():
            self.ui.filterBar.setStyleSheet(
                "QLineEdit { background-color: red}")
            self.ui.sessionList.setCurrentItem(None)
        else:
            self.ui.filterBar.setStyleSheet("")
            self.ui.sessionList.scrollTo(self.ui.sessionList.currentIndex())

    def updownPressed(self, key):
        row = self.ui.sessionList.currentRow()
        if key == Qt.Key_Up:
            if row == 0:
                return
            row -= 1
            while self.ui.sessionList.item(row).isHidden():
                if row == 0:
                    return
                row -= 1
        elif key == Qt.Key_Down:
            if row == self.ui.sessionList.count() - 1:
                return
            row += 1
            while self.ui.sessionList.item(row).isHidden():
                if row == self.ui.sessionList.count() - 1:
                    return
                row += 1
        self.ui.sessionList.setCurrentRow(row)

    def currentItemChanged(self, item, previous_item):
        self.has_selection = bool(item)
        self.preventOk()

    def preventOk(self):
        self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(
            bool(self.server_will_accept and self.has_selection))

    #def changeRootFolder(self):
        #changeRootFolder(self)
        #self.ui.currentNsmFolder.setText(default_session_root)
        #self.ui.sessionList.clear()
        ## self._server.startListSession()
        #self.toDaemon('/ray/server/list_sessions', 0)

    def getSelectedSession(self):
        if self.ui.sessionList.currentItem():
            return self.ui.sessionList.currentItem().text()


class NewSessionDialog(ChildDialog):
    def __init__(self, parent, duplicate_window=False):
        ChildDialog.__init__(self, parent)
        self.ui = ui_new_session.Ui_DialogNewSession()
        self.ui.setupUi(self)

        self.is_duplicate = bool(duplicate_window)

        self.ui.currentNsmFolder.setText(CommandLineArgs.session_root)
        self.ui.toolButtonFolder.clicked.connect(self.changeRootFolder)
        self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(False)
        self.ui.lineEdit.setFocus(Qt.OtherFocusReason)
        self.ui.lineEdit.textChanged.connect(self.textChanged)

        self.session_list = []
        self.template_list = []

        self._signaler.server_status_changed.connect(self.serverStatusChanged)

        self._signaler.add_sessions_to_list.connect(self.addSessionsToList)
        
        self.toDaemon('/ray/server/list_sessions', 1)

        self._signaler.session_template_found.connect(self.addTemplatesToList)

        if self.is_duplicate:
            self.ui.labelTemplate.setVisible(False)
            self.ui.comboBoxTemplate.setVisible(False)
            self.ui.labelNewSessionName.setText(
                _translate('Duplicate', 'Duplicated session name :'))
            self.setWindowTitle(_translate('Duplicate', 'Duplicate Session'))
        else:
            self.toDaemon('/ray/server/list_session_templates')

        if self.daemon_launched_before:
            self.ui.toolButtonFolder.setVisible(False)
            self.ui.currentNsmFolder.setVisible(False)
            self.ui.labelNsmFolder.setVisible(False)

        self.initComboBox()
        self.setLastTemplateSelected()

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
        self.ui.currentNsmFolder.setText(session_root)
        self.ui.sessionList.clear()
        self.toDaemon('/ray/server/list_sessions', 1)
    
    def initComboBox(self):
        self.ui.comboBoxTemplate.clear()
        self.ui.comboBoxTemplate.addItem(
            _translate('session_template', "empty"))
        self.ui.comboBoxTemplate.addItem(
            _translate(
                'session_template',
                "with JACK patch memory"))
        self.ui.comboBoxTemplate.insertSeparator(2)

    def setLastTemplateSelected(self):
        last_used_template = RS.settings.value('last_used_template', type=str)

        if last_used_template.startswith('///'):
            if last_used_template == '///withJACKPATCH':
                self.ui.comboBoxTemplate.setCurrentIndex(1)
        else:
            if last_used_template in self.template_list:
                self.ui.comboBoxTemplate.setCurrentText(last_used_template)

        if not last_used_template:
            self.ui.comboBoxTemplate.setCurrentIndex(1)

    def addSessionsToList(self, session_names):
        self.session_list += session_names

    def addTemplatesToList(self, template_list):
        for template in template_list:
            if template not in self.template_list:
                self.template_list.append(template)

        if not self.template_list:
            return

        self.template_list.sort()

        self.initComboBox()

        for template_name in self.template_list:
            self.ui.comboBoxTemplate.addItem(template_name)

        self.setLastTemplateSelected()

    def getSessionName(self):
        return self.ui.lineEdit.text()

    def getTemplateName(self):
        if self.ui.comboBoxTemplate.currentIndex() == 0:
            return ""

        if self.ui.comboBoxTemplate.currentIndex() == 1:
            return '///withJACKPATCH'

        return self.ui.comboBoxTemplate.currentText()

    def textChanged(self, text):
        self.text_is_valid = bool(text and text not in self.session_list)
        self.preventOk()

    def changeRootFolder(self):
        self.ui.currentNsmFolder.setText(default_session_root)
        self.session_list.clear()
        # self._server.startListSession()
        self.toDaemon('/ray/server/list_sessions', 0)

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


class EditExecutableDialog(ChildDialog):
    def __init__(self, parent, client):
        ChildDialog.__init__(self, parent)
        self.ui = ui_edit_executable.Ui_Dialog()
        self.ui.setupUi(self)

        self.ui.lineEditExecutable.setText(client.executable_path)
        self.ui.lineEditArguments.setText(client.arguments)

    def getExecutable(self):
        return self.ui.lineEditExecutable.text()

    def getArguments(self):
        return self.ui.lineEditArguments.text()


class ClientPropertiesDialog(ChildDialog):
    def __init__(self, parent, client):
        ChildDialog.__init__(self, parent)
        self.ui = ui_client_properties.Ui_Dialog()
        self.ui.setupUi(self)

        self.client = client

        self.ui.lineEditIcon.textEdited.connect(self.changeIconwithText)
        self.ui.pushButtonSaveChanges.clicked.connect(self.saveChanges)
        self.ui.toolButtonEditExecutable.clicked.connect(self.editExecutable)

    def updateContents(self):
        self.ui.labelExecutable.setText(self.client.executable_path)
        self.ui.labelArguments.setText(self.client.arguments)
        self.ui.labelId.setText(self.client.client_id)
        self.ui.labelClientName.setText(self.client.name)
        self.ui.lineEditIcon.setText(self.client.icon_name)
        self.ui.lineEditLabel.setText(self.client.label)
        self.ui.checkBoxSaveStop.setChecked(self.client.check_last_save)
        self.ui.toolButtonIcon.setIcon(
            ray.getAppIcon(self.client.icon_name, self))
        self.ui.lineEditIgnoredExtensions.setText(self.client.ignored_extensions)

    def changeIconwithText(self, text):
        self.ui.toolButtonIcon.setIcon(ray.getAppIcon(text, self))

    def editExecutable(self):
        dialog = EditExecutableDialog(self, self.client)
        dialog.exec()
        if dialog.result():
            self.ui.labelExecutable.setText(dialog.getExecutable())
            self.ui.labelArguments.setText(dialog.getArguments())

    def saveChanges(self):
        self.client.executable_path = self.ui.labelExecutable.text()
        self.client.arguments = self.ui.labelArguments.text()
        self.client.label = self.ui.lineEditLabel.text()
        self.client.icon_name = self.ui.lineEditIcon.text()
        self.client.check_last_save = self.ui.checkBoxSaveStop.isChecked()
        self.client.ignored_extensions = self.ui.lineEditIgnoredExtensions.text()
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
        if server_status in (ray.ServerStatus.CLOSE, ray.ServerStatus.OFF):
            self.reject()

    def removeClient(self):
        self.toDaemon(
            '/ray/trash/remove_definitely',
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


class AboutRaySessionDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui_about_raysession.Ui_DialogAboutRaysession()
        self.ui.setupUi(self)
        all_text = self.ui.labelRayAndVersion.text()
        self.ui.labelRayAndVersion.setText(all_text % ray.VERSION)


class AddApplicationDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui_add_application.Ui_DialogAddApplication()
        self.ui.setupUi(self)

        self.ui.checkBoxFactory.setChecked(RS.settings.value(
            'AddApplication/factory_box', True, type=bool))
        self.ui.checkBoxUser.setChecked(RS.settings.value(
            'AddApplication/user_box', True, type=bool))

        self.ui.checkBoxFactory.stateChanged.connect(self.factoryBoxChanged)
        self.ui.checkBoxUser.stateChanged.connect(self.userBoxChanged)

        self.ui.templateList.currentItemChanged.connect(
            self.currentItemChanged)
        self.ui.templateList.setFocus(Qt.OtherFocusReason)
        self.ui.filterBar.textEdited.connect(self.updateFilteredList)
        self.ui.filterBar.updownpressed.connect(self.updownPressed)
        self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(False)

        self._signaler.user_client_template_found.connect(
            self.addUserTemplates)
        self._signaler.factory_client_template_found.connect(
            self.addFactoryTemplates)
        self.toDaemon('/ray/server/list_user_client_templates')
        self.toDaemon('/ray/server/list_factory_client_templates')

        self.user_template_list = []
        self.factory_template_list = []

        self.server_will_accept = False
        self.has_selection = False

        self.serverStatusChanged(self._session.server_status)
        
        self.toDaemon('/ray/server/list_sessions', 'opre', 'pof')

    def factoryBoxChanged(self, state):
        if not state:
            self.ui.checkBoxUser.setChecked(True)

        self.updateFilteredList()

    def userBoxChanged(self, state):
        if not state:
            self.ui.checkBoxFactory.setChecked(True)

        self.updateFilteredList()

    def serverStatusChanged(self, server_status):
        self.server_will_accept = bool(
            server_status not in (
                ray.ServerStatus.OFF,
                ray.ServerStatus.CLOSE) and not self.server_copying)
        self.preventOk()

    def addUserTemplates(self, template_list):
        for template in template_list:
            template_name = template
            icon_name = ''

            if '/' in template:
                template_name = template.split('/')[0]
                icon_name = template.split('/')[1]

            self.user_template_list.append(template_name)

            self.ui.templateList.addItem(
                QListWidgetItem(
                    ray.getAppIcon(
                        icon_name,
                        self),
                    template_name,
                    self.ui.templateList))

            self.ui.templateList.sortItems()

        self.updateFilteredList()

    def addFactoryTemplates(self, template_list):
        for template in template_list:
            template_name = template
            icon_name = ''

            if '/' in template:
                template_name = template.split('/')[0]
                icon_name = template.split('/')[1]

            self.factory_template_list.append(template_name)

            self.ui.templateList.addItem(
                QListWidgetItem(
                    ray.getAppIcon(
                        icon_name,
                        self),
                    template_name,
                    self.ui.templateList))

            self.ui.templateList.sortItems()

        self.updateFilteredList()

    def updateFilteredList(self, filt=''):
        filter_text = self.ui.filterBar.displayText()

        # show all items
        for i in range(self.ui.templateList.count()):
            self.ui.templateList.item(i).setHidden(False)

        liist = self.ui.templateList.findItems(filter_text, Qt.MatchContains)

        seen_template_list = []

        # hide all non matching items
        for i in range(self.ui.templateList.count()):
            template_name = self.ui.templateList.item(i).text()

            if self.ui.templateList.item(i) not in liist:
                self.ui.templateList.item(i).setHidden(True)
                continue

            if self.ui.checkBoxFactory.isChecked() and self.ui.checkBoxUser.isChecked():
                if template_name in seen_template_list:
                    self.ui.templateList.item(i).setHidden(True)
                else:
                    seen_template_list.append(template_name)

            elif self.ui.checkBoxFactory.isChecked():
                if template_name not in self.factory_template_list:
                    self.ui.templateList.item(i).setHidden(True)
                    continue

                if template_name in seen_template_list:
                    self.ui.templateList.item(i).setHidden(True)
                else:
                    seen_template_list.append(template_name)

            elif self.ui.checkBoxUser.isChecked():
                if template_name not in self.user_template_list:
                    self.ui.templateList.item(i).setHidden(True)

                if template_name in seen_template_list:
                    self.ui.templateList.item(i).setHidden(True)
                else:
                    seen_template_list.append(template_name)

        # if selected item not in list, then select the first visible
        if not self.ui.templateList.currentItem(
        ) or self.ui.templateList.currentItem().isHidden():
            for i in range(self.ui.templateList.count()):
                if not self.ui.templateList.item(i).isHidden():
                    self.ui.templateList.setCurrentRow(i)
                    break

        if not self.ui.templateList.currentItem(
        ) or self.ui.templateList.currentItem().isHidden():
            self.ui.filterBar.setStyleSheet(
                "QLineEdit { background-color: red}")
            self.ui.templateList.setCurrentItem(None)
        else:
            self.ui.filterBar.setStyleSheet("")
            self.ui.templateList.scrollTo(self.ui.templateList.currentIndex())

    def updownPressed(self, key):
        row = self.ui.templateList.currentRow()
        if key == Qt.Key_Up:
            if row == 0:
                return
            row -= 1
            while self.ui.templateList.item(row).isHidden():
                if row == 0:
                    return
                row -= 1
        elif key == Qt.Key_Down:
            if row == self.ui.templateList.count() - 1:
                return
            row += 1
            while self.ui.templateList.item(row).isHidden():
                if row == self.ui.templateList.count() - 1:
                    return
                row += 1
        self.ui.templateList.setCurrentRow(row)

    def currentItemChanged(self, item, previous_item):
        self.has_selection = bool(item)
        self.preventOk()

    def preventOk(self):
        self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(
            bool(self.server_will_accept and self.has_selection))

    def getSelectedTemplate(self):
        if self.ui.templateList.currentItem():
            return self.ui.templateList.currentItem().text()

    def isTemplateFactory(self, template_name):
        if not self.ui.checkBoxUser.isChecked():
            return True

        # If both factory and user boxes are checked, priority to user template
        if template_name in self.user_template_list:
            return False

        return True

    def saveCheckBoxes(self):
        RS.settings.setValue(
            'AddApplication/factory_box',
            self.ui.checkBoxFactory.isChecked())
        RS.settings.setValue(
            'AddApplication/user_box',
            self.ui.checkBoxUser.isChecked())
        RS.settings.sync()


class NewExecutableDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui_new_executable.Ui_DialogNewExecutable()
        self.ui.setupUi(self)
        self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(False)
        self.ui.lineEdit.setFocus(Qt.OtherFocusReason)
        self.ui.lineEdit.textChanged.connect(self.textChanged)

        self.ui.checkBoxProxy.stateChanged.connect(self.proxyStateChanged)
        self._signaler.new_executable.connect(self.addExecutableToCompleter)
        self.toDaemon('/ray/server/list_path')

        self.exec_list = []

        self.completer = QCompleter(self.exec_list)
        self.ui.lineEdit.setCompleter(self.completer)

        self.ui.lineEdit.returnPressed.connect(self.closeNow)

        self.serverStatusChanged(self._session.server_status)

        self.text_will_accept = False

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

    def proxyStateChanged(self, state):
        self.ui.buttonBox.button(
            QDialogButtonBox.Ok).setEnabled(
            state or self.text_will_accept)

    def textChanged(self, text):
        self.text_will_accept = bool(text)
        self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(
            self.ui.checkBoxProxy.isChecked() or self.text_will_accept)

    def closeNow(self):
        if self.ui.lineEdit.text() in self.exec_list or self.ui.checkBoxProxy.isChecked():
            self.accept()

    def serverStatusChanged(self, server_status):
        if server_status in (ray.ServerStatus.CLOSE, ray.ServerStatus.OFF):
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
                    "<strong>%s</strong> seems to has not been saved for %i minute(s).<br />Do you really want to stop it ?") % (self.client.prettierName(),
                                                                                                                                 minutes)

            self.ui.label.setText(text)

        self.ui.pushButtonSaveStop.clicked.connect(self.saveAndStop)
        self.ui.checkBox.stateChanged.connect(self.checkBoxClicked)

        self._signaler.client_status_changed.connect(
            self.serverUpdatesClientStatus)

    def saveAndStop(self):
        self.wait_for_save = True
        # self._server.saveClient(self.client_id)
        self.toDaemon('/ray/client/save', self.client_id)

    def checkBoxClicked(self, state):
        self.client.check_last_save = not bool(state)
        self.client.sendPropertiesToDaemon()

    def serverUpdatesClientStatus(self, client_id, status):
        if client_id != self.client_id:
            return

        if status in (ray.ClientStatus.STOPPED, ray.ClientStatus.REMOVED):
            self.reject()
            return

        if status == ray.ClientStatus.READY and self.wait_for_save:
            self.wait_for_save = False
            self.accept()

class SnapShotProgressDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui_snapshot_progress.Ui_Dialog()
        self.ui.setupUi(self)
        
        self._signaler.server_progress.connect(self.serverProgress)
        
    def serverStatusChanged(self, server_status):
        self.close()
        
    def serverProgress(self, value):
        self.ui.progressBar.setValue(value)

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
                "<p>daemon at<br><strong>%s</strong><br>uses an other Ray Session version.<.p>") % ex_url
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


class ErrorDialog(ChildDialog):
    def __init__(self, parent, osc_args):
        ChildDialog.__init__(self, parent)
        self.ui = ui_error_dialog.Ui_Dialog()
        self.ui.setupUi(self)

        self.ui.label.setText(osc_args[2])
