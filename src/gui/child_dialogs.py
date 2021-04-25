import os
import sys
import time

from PyQt5.QtWidgets import (
    QDialog, QDialogButtonBox, QTreeWidget, QTreeWidgetItem,
    QCompleter, QMessageBox, QFileDialog)
from PyQt5.QtGui import QIcon, QPixmap, QGuiApplication
from PyQt5.QtCore import Qt, QTimer

import client_properties_dialog
import ray
from gui_server_thread import GUIServerThread
from gui_tools import (ErrDaemon, _translate,
                       CommandLineArgs, RS, isDarkTheme)

from patchcanvas import patchcanvas

import ui.open_session
import ui.new_session
import ui.save_template_session
import ui.nsm_open_info
import ui.abort_session
import ui.about_raysession
import ui.donations
import ui.jack_config_info
import ui.new_executable
import ui.error_dialog
import ui.quit_app
import ui.script_info
import ui.script_user_action
import ui.session_notes
import ui.session_scripts_info
import ui.stop_client
import ui.stop_client_no_save
import ui.abort_copy
import ui.client_trash
import ui.daemon_url
import ui.snapshot_progress
import ui.waiting_close_user
import ui.client_rename
import ui.canvas_port_info

class ChildDialog(QDialog):
    def __init__(self, parent):
        QDialog.__init__(self, parent)
        self._session = parent._session
        self._signaler = self._session._signaler

        self._daemon_manager = self._session._daemon_manager

        self._signaler.server_status_changed.connect(self.serverStatusChanged)
        self._signaler.server_copying.connect(self.serverCopying)

        self.root_folder_file_dialog = None
        self.root_folder_message_box = QMessageBox(
            QMessageBox.Critical,
            _translate('root_folder_dialogs', 'unwritable dir'),
            '',
            QMessageBox.NoButton,
            self)

        self.server_copying = parent.server_copying

    @classmethod
    def toDaemon(cls, *args):
        server = GUIServerThread.instance()
        if server:
            server.toDaemon(*args)
        else:
            sys.stderr.write('Error No GUI OSC Server, can not send %s.\n'
                             % args)

    def serverStatusChanged(self, server_status):
        pass

    def serverCopying(self, bool_copying):
        self.server_copying = bool_copying
        self.serverStatusChanged(self._session.server_status)

    def changeRootFolder(self):
        # construct this here only because it can be quite long
        if self.root_folder_file_dialog is None:
            self.root_folder_file_dialog = QFileDialog(
                self,
                _translate("root_folder_dialogs",
                        "Choose root folder for sessions"),
                CommandLineArgs.session_root)
            self.root_folder_file_dialog.setFileMode(QFileDialog.Directory)
            self.root_folder_file_dialog.setOption(QFileDialog.ShowDirsOnly)
        else:
            self.root_folder_file_dialog.setDirectory(CommandLineArgs.session_root)

        self.root_folder_file_dialog.exec()
        if not self.root_folder_file_dialog.result():
            return

        selected_files = self.root_folder_file_dialog.selectedFiles()
        if not selected_files:
            return

        root_folder = selected_files[0]

        # Security, kde dialogs sends $HOME if user type a folder path
        # that doesn't already exists.
        if os.getenv('HOME') and root_folder == os.getenv('HOME'):
            return

        self.root_folder_message_box.setText(
            _translate('root_folder_dialogs',
                "<p>You have no permissions for %s,<br>choose another directory !</p>")
                    % root_folder)

        if not os.path.exists(root_folder):
            try:
                os.makedirs(root_folder)
            except:
                self.root_folder_message_box.exec()
                return

        if not os.access(root_folder, os.W_OK):
            self.root_folder_message_box.exec()
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
    def __init__(self, l_list):
        QTreeWidgetItem.__init__(self, l_list)

    def showConditionnaly(self, string: str)->bool:
        show = bool(string.lower() in self.data(0, Qt.UserRole).lower())

        n = 0
        for i in range(self.childCount()):
            if self.child(i).showConditionnaly(string.lower()):
                n += 1
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
        self.ui = ui.open_session.Ui_DialogOpenSession()
        self.ui.setupUi(self)

        self.timer_progress = QTimer()
        self.timer_progress.setInterval(50)
        self.timer_progress_n = 0
        self.timer_progress.timeout.connect(self.timerProgress)
        self.timer_progress.start()
        self.progress_inverted = False
        self.ui.widgetSpacer.setVisible(False)

        self.ui.toolButtonFolder.clicked.connect(self.changeRootFolder)
        self.ui.sessionList.currentItemChanged.connect(
            self.currentItemChanged)
        self.ui.sessionList.setFocus(Qt.OtherFocusReason)
        self.ui.sessionList.itemDoubleClicked.connect(self.goIfAny)
        self.ui.sessionList.itemClicked.connect(self.deployItem)
        self.ui.filterBar.textEdited.connect(self.updateFilteredList)
        #self.ui.filterBar.updownpressed.connect(self.updownPressed)
        self.ui.filterBar.key_event.connect(self.updownPressed)
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
        self._last_session_item = None

        self.ui.filterBar.setFocus(Qt.OtherFocusReason)

    def serverStatusChanged(self, server_status):
        self.ui.toolButtonFolder.setEnabled(
            bool(server_status in (ray.ServerStatus.OFF,
                                   ray.ServerStatus.READY,
                                   ray.ServerStatus.CLOSE)))

        self.server_will_accept = bool(
            server_status in (
                ray.ServerStatus.OFF,
                ray.ServerStatus.READY) and not self.server_copying)

        if server_status != ray.ServerStatus.OFF:
            if self.root_folder_file_dialog is not None:
                self.root_folder_file_dialog.reject()
            self.root_folder_message_box.reject()

        self.preventOk()

    def timerProgress(self):
        self.ui.progressBar.setValue(self.timer_progress_n)
        if self.timer_progress_n >= 100:
            self.timer_progress_n = 0
            self.progress_inverted = not self.progress_inverted
            self.ui.progressBar.setInvertedAppearance(
                self.progress_inverted)
        self.timer_progress_n += 5

    def rootChanged(self, session_root):
        self.ui.currentSessionsFolder.setText(session_root)
        self.ui.sessionList.clear()
        self.folders.clear()
        self.toDaemon('/ray/server/list_sessions', 0)

    def addSessions(self, session_names):
        if not session_names:
            self.timer_progress.stop()
            height = self.ui.progressBar.size().height()
            self.ui.progressBar.setVisible(False)
            self.ui.widgetSpacer.setVisible(True)

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
            return


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

    def updownPressed(self, event):
        start_item = self.ui.sessionList.currentItem()
        QTreeWidget.keyPressEvent(self.ui.sessionList, event)
        if not start_item:
            return

        current_item = self.ui.sessionList.currentItem()
        if current_item == start_item:
            return

        ex_item = current_item

        while not current_item.flags() & Qt.ItemIsSelectable:
            ex_item = current_item
            QTreeWidget.keyPressEvent(self.ui.sessionList, event)
            current_item = self.ui.sessionList.currentItem()
            if current_item == ex_item:
                self.ui.sessionList.setCurrentItem(start_item)
                return

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
        self.ui = ui.new_session.Ui_DialogNewSession()
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

        self.server_will_accept = False
        self.text_is_valid = False

        self.completer = QCompleter(self.sub_folders)
        self.ui.lineEdit.setCompleter(self.completer)

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

        if server_status != ray.ServerStatus.OFF:
            if self.root_folder_file_dialog is not None:
                self.root_folder_file_dialog.reject()
            self.root_folder_message_box.reject()

        self.preventOk()

    def rootChanged(self, session_root):
        self.ui.currentSessionsFolder.setText(session_root)
        self.session_list.clear()
        self.sub_folders.clear()
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
        if last_subfolder and not self.ui.lineEdit.text():
            self.ui.lineEdit.setText(last_subfolder + '/')

    def addSessionsToList(self, session_names):
        self.session_list += session_names

        for session_name in session_names:
            if '/' in session_name:
                new_dir = os.path.dirname(session_name)
                if not new_dir in self.sub_folders:
                    self.sub_folders.append(new_dir)

        self.sub_folders.sort()
        del self.completer
        self.completer = QCompleter([f + '/' for f in self.sub_folders])
        self.ui.lineEdit.setCompleter(self.completer)

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

    def getSessionShortPath(self)->str:
        return self.ui.lineEdit.text()

    def getTemplateName(self)->str:
        index = self.ui.comboBoxTemplate.currentIndex()

        if index == 0:
            return ""

        if index <= len(ray.factory_session_templates):
            return '///' + ray.factory_session_templates[index-1]

        return self.ui.comboBoxTemplate.currentText()

    def textChanged(self, text):
        self.text_is_valid = bool(text
                                  and not text.endswith('/')
                                  and text not in self.session_list)
        self.preventOk()

    def preventOk(self):
        self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(
            bool(self.server_will_accept and self.text_is_valid))


class AbstractSaveTemplateDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui.save_template_session.Ui_DialogSaveTemplateSession()
        self.ui.setupUi(self)

        self.server_will_accept = False

        self.update_template_text = _translate(
            "session template", "Update the template")
        self.create_template_text = self.ui.pushButtonAccept.text()
        self.ui.lineEdit.textEdited.connect(self.textEdited)
        self.ui.pushButtonAccept.clicked.connect(self.verifyAndAccept)
        self.ui.pushButtonAccept.setEnabled(False)

        self.overwrite_message_box = QMessageBox(
            QMessageBox.Question,
            _translate(
                    'session template',
                    'Overwrite Template ?'),
            '',
            QMessageBox.Yes | QMessageBox.No,
            self)

    def textEdited(self, text):
        if '/' in text:
            self.ui.lineEdit.setText(text.replace('/', '⁄'))
        if self.ui.lineEdit.text() in self.template_list:
            self.ui.pushButtonAccept.setText(self.update_template_text)
        else:
            self.ui.pushButtonAccept.setText(self.create_template_text)
        self.allowOkButton()

    def getTemplateName(self):
        return self.ui.lineEdit.text()

    def allowOkButton(self, text=''):
        self.ui.pushButtonAccept.setEnabled(
            bool(self.server_will_accept and self.ui.lineEdit.text()))

    def verifyAndAccept(self):
        template_name = self.getTemplateName()
        if template_name in self.template_list:
            self.overwrite_message_box.setText(
                _translate(
                    'session_template',
                    'Template <strong>%s</strong> already exists.\nOverwrite it ?') %
                template_name)

            self.overwrite_message_box.exec()

            if (self.overwrite_message_box.clickedButton()
                    == self.overwrite_message_box.button(QMessageBox.No)):
                return
        self.accept()

    def addTemplatesToList(self, template_list):
        self.template_list += template_list

        for template in template_list:
            if template == self.ui.lineEdit.text():
                self.ui.pushButtonAccept.setText(self.update_template_text)
                break

class SaveTemplateSessionDialog(AbstractSaveTemplateDialog):
    def __init__(self, parent):
        AbstractSaveTemplateDialog.__init__(self, parent)
        self.ui.toolButtonClientIcon.setVisible(False)
        self.ui.labelLabel.setText(self._session.path)
        self.template_list = []

        self._signaler.session_template_found.connect(self.addTemplatesToList)
        self.toDaemon('/ray/server/list_session_templates')

        self.serverStatusChanged(self._session.server_status)

    def serverStatusChanged(self, server_status):
        self.server_will_accept = bool(server_status == ray.ServerStatus.READY)

        if server_status == ray.ServerStatus.OFF:
            self.overwrite_message_box.reject()
            self.reject()

        self.allowOkButton()


class SaveTemplateClientDialog(AbstractSaveTemplateDialog):
    def __init__(self, parent, client):
        AbstractSaveTemplateDialog.__init__(self, parent)
        self.ui.labelSessionTitle.setVisible(False)
        self.ui.toolButtonClientIcon.setIcon(
            ray.getAppIcon(client.icon, self))
        self.ui.labelLabel.setText(client.prettier_name())

        self.template_list = []
        self.ui.pushButtonAccept.setEnabled(False)

        self.ui.labelNewTemplateName.setText(
            _translate(
                'new client template',
                "New application template name :"))

        self._signaler.user_client_template_found.connect(
            self.addTemplatesToList)

        self.toDaemon('/ray/server/list_user_client_templates')
        self.ui.lineEdit.setText(client.template_origin)
        self.ui.lineEdit.selectAll()
        self.ui.lineEdit.setFocus()
        self.serverStatusChanged(self._session.server_status)

    def serverStatusChanged(self, server_status):
        self.server_will_accept = bool(
            server_status not in (
                ray.ServerStatus.OFF,
                ray.ServerStatus.CLOSE) and not self.server_copying)

        if server_status in (ray.ServerStatus.OFF, ray.ServerStatus.CLOSE):
            self.overwrite_message_box.reject()
            self.reject()

        self.allowOkButton()


class ClientTrashDialog(ChildDialog):
    def __init__(self, parent, client_data):
        ChildDialog.__init__(self, parent)
        self.ui = ui.client_trash.Ui_Dialog()
        self.ui.setupUi(self)

        self.client_data = client_data

        self.ui.labelPrettierName.setText(self.client_data.prettier_name())
        self.ui.labelDescription.setText(self.client_data.description)
        self.ui.labelExecutable.setText(self.client_data.executable_path)
        self.ui.labelId.setText(self.client_data.client_id)
        self.ui.toolButtonIcon.setIcon(QIcon.fromTheme(self.client_data.icon))

        self.ui.toolButtonAdvanced.clicked.connect(self.showProperties)
        self.ui.pushButtonRemove.clicked.connect(self.removeClient)
        self.ui.pushButtonCancel.setFocus()

        self.remove_client_message_box = QMessageBox(
            QMessageBox.Warning,
            _translate('trashed_client', 'Remove definitely'),
            _translate('trashed_client',
                "Are you sure to want to remove definitely this client and all its files ?"),
            QMessageBox.Ok | QMessageBox.Cancel,
            self
            )
        self.remove_client_message_box.setDefaultButton(QMessageBox.Cancel)

    def serverStatusChanged(self, server_status):
        if server_status in (ray.ServerStatus.CLOSE,
                             ray.ServerStatus.OFF,
                             ray.ServerStatus.OUT_SAVE,
                             ray.ServerStatus.OUT_SNAPSHOT,
                             ray.ServerStatus.WAIT_USER):
            self.remove_client_message_box.reject()
            self.reject()

    def removeClient(self):
        self.remove_client_message_box.exec()

        if (self.remove_client_message_box.clickedButton()
                != self.remove_client_message_box.button(QMessageBox.Ok)):
            return

        self.toDaemon(
            '/ray/trashed_client/remove_definitely',
            self.client_data.client_id)
        self.reject()

    def showProperties(self):
        properties_dialog = client_properties_dialog.ClientPropertiesDialog.create(
            self, self.client_data)
        properties_dialog.updateContents()
        properties_dialog.lockWidgets()
        properties_dialog.show()

class AbortSessionDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui.abort_session.Ui_AbortSession()
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
        self.ui = ui.abort_copy.Ui_Dialog()
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
        self.ui = ui.abort_copy.Ui_Dialog()
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


class SessionNotesDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui.session_notes.Ui_Dialog()
        self.ui.setupUi(self)

        if RS.settings.value('SessionNotes/geometry'):
            self.restoreGeometry(RS.settings.value('SessionNotes/geometry'))
        if RS.settings.value('SessionNotes/position'):
            self.move(RS.settings.value('SessionNotes/position'))

        self.message_box = None
        self.updateSession()
        self.ui.plainTextEdit.textChanged.connect(self.textEdited)

        # use a timer to prevent osc message each time a letter is written
        # here, a message is sent when user made not change during 400ms
        self.timer_text = QTimer()
        self.timer_text.setInterval(400)
        self.timer_text.setSingleShot(True)
        self.timer_text.timeout.connect(self.sendNotes)

        self.server_off = False

        self.anti_timer = False
        self.notesUpdated()

    def serverStatusChanged(self, server_status):
        if server_status == ray.ServerStatus.OFF:
            self.server_off = True
            if self.message_box is not None:
                self.message_box.close()
            self.close()
        else:
            self.server_off = False

    def updateSession(self):
        self.setWindowTitle(_translate('notes_dialog', "%s Notes - %s")
                            % (ray.APP_TITLE, self._session.name))
        self.ui.labelSessionName.setText(self._session.name)

    def textEdited(self):
        if not self.anti_timer:
            self.timer_text.start()
        self.anti_timer = False

    def sendNotes(self):
        notes = self.ui.plainTextEdit.toPlainText()
        if len(notes) >= 65000:
            self.message_box = QMessageBox(
                QMessageBox.Critical,
                _translate('session_notes', 'Too long notes'),
                _translate('session_notes',
                           "<p>Because notes are spread to the OSC server,<br>they can't be longer than 65000 characters.<br>Sorry !</p>"),
                QMessageBox.Cancel,
                self)
            self.message_box.exec()
            self.ui.plainTextEdit.setPlainText(notes[:64999])
            return

        self._session.notes = notes
        self.toDaemon('/ray/session/set_notes', self._session.notes)

    def notesUpdated(self):
        self.anti_timer = True
        self.ui.plainTextEdit.setPlainText(self._session.notes)

    def closeEvent(self, event):
        RS.settings.setValue('SessionNotes/geometry', self.saveGeometry())
        RS.settings.setValue('SessionNotes/position', self.pos())
        if not self.server_off:
            self.toDaemon('/ray/session/hide_notes')
        ChildDialog.closeEvent(self, event)

class OpenNsmSessionInfoDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui.nsm_open_info.Ui_Dialog()
        self.ui.setupUi(self)
        self.ui.checkBox.stateChanged.connect(self.showThis)

    @classmethod
    def showThis(cls, state):
        RS.setHidden(RS.HD_OpenNsmSession, bool(state))


class QuitAppDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui.quit_app.Ui_DialogQuitApp()
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

        if CommandLineArgs.under_nsm:
            self.ui.pushButtonDaemon.setVisible(False)
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
        if CommandLineArgs.under_nsm:
            return

        self._daemon_manager.disannounce()
        QTimer.singleShot(10, QGuiApplication.quit)


class AboutRaySessionDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui.about_raysession.Ui_DialogAboutRaysession()
        self.ui.setupUi(self)
        all_text = self.ui.labelRayAndVersion.text()
        self.ui.labelRayAndVersion.setText(all_text % ray.VERSION)


class NewExecutableDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui.new_executable.Ui_DialogNewExecutable()
        self.ui.setupUi(self)

        self.ui.groupBoxAdvanced.setVisible(False)
        self.resize(0, 0)
        self.ui.labelPrefixMode.setToolTip(
            self.ui.comboBoxPrefixMode.toolTip())
        self.ui.labelClientId.setToolTip(self.ui.lineEditClientId.toolTip())

        self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(False)

        self.ui.lineEdit.setFocus(Qt.OtherFocusReason)
        self.ui.lineEdit.textChanged.connect(self.checkAllow)
        self.ui.checkBoxNsm.stateChanged.connect(self.checkAllow)

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

    def getSelection(self):
        return (self.ui.lineEdit.text(),
                self.ui.checkBoxStartClient.isChecked(),
                not self.ui.checkBoxNsm.isChecked(),
                self.ui.comboBoxPrefixMode.currentIndex(),
                self.ui.lineEditPrefix.text(),
                self.ui.lineEditClientId.text())

    def isAllowed(self):
        nsm = self.ui.checkBoxNsm.isChecked()
        text = self.ui.lineEdit.text()
        allow = bool(bool(text) and (not nsm
                                     or text in self.exec_list))
        return allow

    def checkAllow(self):
        allow = self.isAllowed()
        self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(allow)

    def closeNow(self):
        if self.isAllowed():
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
        self.ui = ui.stop_client.Ui_Dialog()
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
        self.ui = ui.stop_client_no_save.Ui_Dialog()
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


class ClientRenameDialog(ChildDialog):
    def __init__(self, parent, client):
        ChildDialog.__init__(self, parent)
        self.ui = ui.client_rename.Ui_Dialog()
        self.ui.setupUi(self)

        self.client = client
        self.ui.toolButtonIcon.setIcon(ray.getAppIcon(client.icon, self))
        self.ui.labelClientLabel.setText(client.prettier_name())
        self.ui.lineEdit.setText(client.prettier_name())
        self.ui.lineEdit.selectAll()
        self.ui.lineEdit.setFocus()

    def getNewLabel(self)->str:
        return self.ui.lineEdit.text()


class SnapShotProgressDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui.snapshot_progress.Ui_Dialog()
        self.ui.setupUi(self)
        self._signaler.server_progress.connect(self.serverProgress)

    def serverStatusChanged(self, server_status):
        self.close()

    def serverProgress(self, value):
        self.ui.progressBar.setValue(value * 100)


class ScriptInfoDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui.script_info.Ui_Dialog()
        self.ui.setupUi(self)

    def setInfoLabel(self, text):
        self.ui.infoLabel.setText(text)

    def shouldBeRemoved(self):
        return False


class ScriptUserActionDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui.script_user_action.Ui_Dialog()
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


class SessionScriptsInfoDialog(ChildDialog):
    def __init__(self, parent, session_path):
        ChildDialog.__init__(self, parent)
        self.ui = ui.session_scripts_info.Ui_Dialog()
        self.ui.setupUi(self)

        scripts_dir = "%s/%s" % (session_path, ray.SCRIPTS_DIR)
        parent_path = os.path.dirname(session_path)
        parent_scripts = "%s/%s" % (parent_path, ray.SCRIPTS_DIR)

        session_scripts_text = self.ui.textSessionScripts.toHtml()

        self.ui.textSessionScripts.setHtml(
            session_scripts_text % (scripts_dir, parent_scripts, parent_path))

    def notAgainValue(self)->bool:
        return self.ui.checkBoxNotAgain.isChecked()

class JackConfigInfoDialog(ChildDialog):
    def __init__(self, parent, session_path):
        ChildDialog.__init__(self, parent)
        self.ui = ui.jack_config_info.Ui_Dialog()
        self.ui.setupUi(self)

        scripts_dir = "%s/%s" % (session_path, ray.SCRIPTS_DIR)
        parent_path = os.path.dirname(session_path)
        parent_scripts = "%s/%s" % (parent_path, ray.SCRIPTS_DIR)

        session_scripts_text = self.ui.textSessionScripts.toHtml()

        self.ui.textSessionScripts.setHtml(
            session_scripts_text % (scripts_dir, parent_scripts, parent_path))

    def notAgainValue(self)->bool:
        return self.ui.checkBoxNotAgain.isChecked()

    def autostartValue(self)->bool:
        return self.ui.checkBoxAutoStart.isChecked()


class DaemonUrlWindow(ChildDialog):
    def __init__(self, parent, err_code, ex_url):
        ChildDialog.__init__(self, parent)
        self.ui = ui.daemon_url.Ui_Dialog()
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
        self.ui = ui.waiting_close_user.Ui_Dialog()
        self.ui.setupUi(self)

        if isDarkTheme(self):
            self.ui.labelSaveIcon.setPixmap(
                QPixmap(':scalable/breeze-dark/document-nosave.svg'))

        self.ui.pushButtonOk.setFocus(True)
        self.ui.pushButtonUndo.clicked.connect(self.undoClose)
        self.ui.pushButtonSkip.clicked.connect(self.skip)
        self.ui.checkBox.setChecked(not RS.isHidden(RS.HD_WaitCloseUser))
        self.ui.checkBox.clicked.connect(self.checkBoxClicked)

    def serverStatusChanged(self, server_status):
        if server_status != ray.ServerStatus.WAIT_USER:
            self.accept()

    def undoClose(self):
        self.toDaemon('/ray/session/cancel_close')

    def skip(self):
        self.toDaemon('/ray/session/skip_wait_user')

    def checkBoxClicked(self, state):
        RS.setHidden(RS.HD_WaitCloseUser, bool(state))


class CanvasPortInfoDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui.canvas_port_info.Ui_Dialog()
        self.ui.setupUi(self)

    def set_infos(self, port_full_name: str, port_uuid: int, 
                  port_type: str, port_flags: str):
        self.ui.lineEditFullPortName.setText(port_full_name)
        self.ui.lineEditUuid.setText(str(port_uuid))
        self.ui.labelPortType.setText(port_type)
        self.ui.labelPortFlags.setText(port_flags)

class DonationsDialog(ChildDialog):
    def __init__(self, parent, display_no_again):
        ChildDialog.__init__(self, parent)
        self.ui = ui.donations.Ui_Dialog()
        self.ui.setupUi(self)

        self.ui.checkBox.setVisible(display_no_again)
        self.ui.checkBox.clicked.connect(self.checkBoxClicked)

    def checkBoxClicked(self, state):
        RS.setHidden(RS.HD_Donations, state)


class ErrorDialog(ChildDialog):
    def __init__(self, parent, message):
        ChildDialog.__init__(self, parent)
        self.ui = ui.error_dialog.Ui_Dialog()
        self.ui.setupUi(self)

        self.ui.label.setText(message)
