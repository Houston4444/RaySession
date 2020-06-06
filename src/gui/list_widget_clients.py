import time
from PyQt5.QtWidgets import (QListWidget, QListWidgetItem, QFrame, QMenu, 
                             QLineEdit, QAction)
from PyQt5.QtGui import QIcon, QPalette, QPixmap, QFontMetrics, QFont, QFontDatabase
from PyQt5.QtCore import Qt, pyqtSignal, pyqtSlot, QSize, QFile

import ray
from gui_server_thread import GUIServerThread
from gui_tools import clientStatusString, _translate, isDarkTheme
import child_dialogs
import snapshots_dialog

import ui_client_slot



class ClientSlot(QFrame):
    def __init__(self, list_widget, client):
        QFrame.__init__(self)
        self.ui = ui_client_slot.Ui_ClientSlotWidget()
        self.ui.setupUi(self)

        # needed variables
        self.list_widget = list_widget
        self.client = client
        self._main_win = self.client._session._main_win

        self.is_dirty_able = False
        self.gui_visible = True
        self.ui.toolButtonGUI.setVisible(False)

        # connect buttons to functions
        self.ui.toolButtonGUI.toggleGui.connect(self.toggleGui)
        self.ui.startButton.clicked.connect(self.startClient)
        self.ui.stopButton.clicked.connect(self.stopClient)
        self.ui.killButton.clicked.connect(self.killClient)
        self.ui.saveButton.clicked.connect(self.saveClient)
        self.ui.closeButton.clicked.connect(self.trashClient)
        self.ui.lineEditClientStatus.statusPressed.connect(self.abortCopy)
        # self.ui.ClientName.name_changed.connect(self.updateLabel)
        
        # prevent "stopped" status displayed at client switch
        #self.ui.lineEditClientStatus,.setTextNow(
                          #clientStatusString(self.client.status))

        self.icon_on = QIcon()
        self.icon_off = QIcon()

        self.updateClientData()

        self.ui.actionSaveAsApplicationTemplate.triggered.connect(
            self.saveAsApplicationTemplate)
        self.ui.actionProperties.triggered.connect(
            self.client.showPropertiesDialog)
        self.ui.actionReturnToAPreviousState.triggered.connect(
            self.openSnapshotsDialog)

        self.menu = QMenu(self)

        self.menu.addAction(self.ui.actionSaveAsApplicationTemplate)
        self.menu.addAction(self.ui.actionReturnToAPreviousState)
        self.menu.addAction(self.ui.actionProperties)
        
        self.ui.actionReturnToAPreviousState.setVisible(
            self._main_win.has_git)

        self.ui.iconButton.setMenu(self.menu)

        self.saveIcon = QIcon()
        self.saveIcon.addPixmap(
            QPixmap(':scalable/breeze/document-save'),
            QIcon.Normal,
            QIcon.Off)
        self.saveIcon.addPixmap(
            QPixmap(':scalable/breeze/disabled/document-save'),
            QIcon.Disabled,
            QIcon.Off)
        self.ui.saveButton.setIcon(self.saveIcon)

        self.savedIcon = QIcon()
        self.savedIcon.addPixmap(
            QPixmap(':scalable/breeze/document-saved'),
            QIcon.Normal,
            QIcon.Off)

        self.unsavedIcon = QIcon()
        self.unsavedIcon.addPixmap(
            QPixmap(':scalable/breeze/document-unsaved'),
            QIcon.Normal,
            QIcon.Off)
        
        self.noSaveIcon = QIcon()
        self.noSaveIcon.addPixmap(
            QPixmap(':scalable/breeze/document-nosave'),
            QIcon.Normal,
            QIcon.Off)

        # choose button colors
        if isDarkTheme(self):
            startIcon = QIcon()
            startIcon.addPixmap(
                QPixmap(':scalable/breeze-dark/media-playback-start'),
                QIcon.Normal,
                QIcon.Off)
            startIcon.addPixmap(
                QPixmap(':scalable/breeze-dark/disabled/media-playback-start'),
                QIcon.Disabled,
                QIcon.Off)
            self.ui.startButton.setIcon(startIcon)

            stopIcon = QIcon()
            stopIcon.addPixmap(
                QPixmap(':scalable/breeze-dark/media-playback-stop'),
                QIcon.Normal,
                QIcon.Off)
            stopIcon.addPixmap(
                QPixmap(':scalable/breeze-dark/disabled/media-playback-stop'),
                QIcon.Disabled,
                QIcon.Off)
            self.ui.stopButton.setIcon(stopIcon)

            self.saveIcon = QIcon()
            self.saveIcon.addPixmap(
                QPixmap(':scalable/breeze-dark/document-save'),
                QIcon.Normal,
                QIcon.Off)
            self.saveIcon.addPixmap(
                QPixmap(':scalable/breeze-dark/disabled/document-save'),
                QIcon.Disabled,
                QIcon.Off)
            self.ui.saveButton.setIcon(self.saveIcon)

            self.savedIcon = QIcon()
            self.savedIcon.addPixmap(
                QPixmap(':scalable/breeze-dark/document-saved'),
                QIcon.Normal,
                QIcon.Off)

            self.unsavedIcon = QIcon()
            self.unsavedIcon.addPixmap(
                QPixmap(':scalable/breeze-dark/document-unsaved'),
                QIcon.Normal,
                QIcon.Off)
            
            self.noSaveIcon = QIcon()
            self.noSaveIcon.addPixmap(
                QPixmap(':scalable/breeze-dark/document-nosave'),
                QIcon.Normal,
                QIcon.Off)

            closeIcon = QIcon()
            closeIcon.addPixmap(
                QPixmap(':scalable/breeze-dark/window-close'),
                QIcon.Normal,
                QIcon.Off)
            closeIcon.addPixmap(
                QPixmap(':scalable/breeze-dark/disabled/window-close'),
                QIcon.Disabled,
                QIcon.Off)
            self.ui.closeButton.setIcon(closeIcon)

        self.ubuntu_font = QFont(
            QFontDatabase.applicationFontFamilies(0)[0], 8)
        self.ubuntu_font_cond = QFont(
            QFontDatabase.applicationFontFamilies(1)[0], 8)
        self.ubuntu_font.setBold(True)
        self.ubuntu_font_cond.setBold(True)

        self.ui.killButton.setVisible(False)

    def clientId(self):
        return self.client.client_id

    def toDaemon(self, *args):
        server = GUIServerThread.instance()
        if server:
            server.toDaemon(*args)

    def startClient(self):
        self.toDaemon('/ray/client/resume', self.clientId())

    def stopClient(self):
        # we need to prevent accidental stop with a window confirmation
        # under conditions
        self._main_win.stopClient(self.clientId())

    def killClient(self):
        self.toDaemon('/ray/client/kill', self.clientId())

    def saveClient(self):
        self.toDaemon('/ray/client/save', self.clientId())

    def trashClient(self):
        self.toDaemon('/ray/client/trash', self.clientId())

    def abortCopy(self):
        self._main_win.abortCopyClient(self.clientId())

    def saveAsApplicationTemplate(self):
        dialog = child_dialogs.SaveTemplateClientDialog(self._main_win)
        dialog.exec()
        if not dialog.result():
            return

        template_name = dialog.getTemplateName()
        self.toDaemon('/ray/client/save_as_template', self.clientId(),
                      template_name)
        
    def openSnapshotsDialog(self):
        dialog = snapshots_dialog.ClientSnapshotsDialog(self._main_win,
                                                        self.client)
        dialog.exec()
        if dialog.result():
            snapshot = dialog.getSelectedSnapshot()
            self.toDaemon('/ray/client/open_snapshot',
                          self.clientId(), snapshot)

    def updateLabel(self, label):
        self._main_win.updateClientLabel(self.clientId(), label)

    def updateClientData(self):
        # set main label
        label = self.client.label if self.client.label else self.client.name
        self.ui.ClientName.setText(label)

        # set tool tip
        tool_tip = "<html><head/><body>"
        tool_tip += "<p><span style=\" font-weight:600;\">%s<br></span>" \
            % self.client.name
        tool_tip += "<span style=\" font-style:italic;\">%s</span></p>" \
            % self.client.description
        tool_tip += "<p></p>"
        tool_tip += "<p>%s : %s<br>" \
            % (_translate('client_slot', 'Executable'),
               self.client.executable_path)
        tool_tip += "%s : %s</p>" \
            % (_translate('client_slot', 'client id'), self.client.client_id)
        tool_tip += "</body></html>"
        
        self.ui.ClientName.setToolTip(tool_tip)

        # set icon
        self.icon_on = ray.getAppIcon(self.client.icon, self)
        self.icon_off = QIcon(self.icon_on.pixmap(32, 32, QIcon.Disabled))

        self.grayIcon(
            bool(
                self.client.status in (
                    ray.ClientStatus.STOPPED,
                    ray.ClientStatus.PRECOPY)))

    def grayIcon(self, gray):
        if gray:
            self.ui.iconButton.setIcon(self.icon_off)
        else:
            self.ui.iconButton.setIcon(self.icon_on)

    def updateStatus(self, status):
        self.ui.lineEditClientStatus.setText(clientStatusString(status))
        
        if status in (
                ray.ClientStatus.LAUNCH,
                ray.ClientStatus.OPEN,
                ray.ClientStatus.SWITCH,
                ray.ClientStatus.NOOP):
            self.ui.startButton.setEnabled(False)
            self.ui.stopButton.setEnabled(True)
            self.ui.saveButton.setEnabled(False)
            self.ui.closeButton.setEnabled(False)
            self.ui.ClientName.setStyleSheet('QLabel {font-weight : bold}')
            self.ui.ClientName.setEnabled(True)
            self.ui.toolButtonGUI.setEnabled(True)
            self.grayIcon(False)

        elif status == ray.ClientStatus.READY:
            self.ui.startButton.setEnabled(False)
            self.ui.stopButton.setEnabled(True)
            self.ui.closeButton.setEnabled(False)
            self.ui.ClientName.setStyleSheet('QLabel {font-weight : bold}')
            self.ui.ClientName.setEnabled(True)
            self.ui.toolButtonGUI.setEnabled(True)
            self.ui.saveButton.setEnabled(True)
            self.grayIcon(False)

        elif status == ray.ClientStatus.STOPPED:
            self.ui.startButton.setEnabled(True)
            self.ui.stopButton.setEnabled(False)
            self.ui.saveButton.setEnabled(False)
            self.ui.closeButton.setEnabled(True)
            self.ui.ClientName.setStyleSheet('QLabel {font-weight : normal}')
            self.ui.ClientName.setEnabled(False)
            self.ui.toolButtonGUI.setEnabled(False)
            self.grayIcon(True)

            self.ui.stopButton.setVisible(True)
            self.ui.killButton.setVisible(False)

            self.ui.saveButton.setIcon(self.saveIcon)

        elif status == ray.ClientStatus.PRECOPY:
            self.ui.startButton.setEnabled(False)
            self.ui.stopButton.setEnabled(False)
            self.ui.saveButton.setEnabled(False)
            self.ui.closeButton.setEnabled(True)
            self.ui.ClientName.setStyleSheet('QLabel {font-weight : normal}')
            self.ui.ClientName.setEnabled(False)
            self.ui.toolButtonGUI.setEnabled(False)
            self.grayIcon(True)

            self.ui.stopButton.setVisible(True)
            self.ui.killButton.setVisible(False)

            self.ui.saveButton.setIcon(self.saveIcon)

        elif status == ray.ClientStatus.COPY:
            self.ui.saveButton.setEnabled(False)

    def allowKill(self):
        self.ui.stopButton.setVisible(False)
        self.ui.killButton.setVisible(True)

    def flashIfOpen(self, boolflash):
        if boolflash:
            self.ui.lineEditClientStatus.setText(
                clientStatusString(ray.ClientStatus.OPEN))
        else:
            self.ui.lineEditClientStatus.setText('')

    def showGuiButton(self):
        self.ui.toolButtonGUI.setVisible(True)
        if self.client.executable_path in ('nsm-proxy', 'ray-proxy'):
            self.ui.toolButtonGUI.setText(_translate('client_slot', 'proxy'))
            self.ui.toolButtonGUI.setToolTip(
                _translate('client_slot', 'Display proxy window'))

    def setGuiState(self, state):
        self.gui_visible = state
        self.ui.toolButtonGUI.setChecked(state)

    def toggleGui(self):
        if not self.gui_visible:
            self.toDaemon('/ray/client/show_optional_gui', self.clientId())
        else:
            self.toDaemon('/ray/client/hide_optional_gui', self.clientId())

    def setDirtyState(self, bool_dirty):
        self.is_dirty_able = True

        if bool_dirty:
            self.ui.saveButton.setIcon(self.unsavedIcon)
        else:
            self.ui.saveButton.setIcon(self.savedIcon)

    def setNoSaveLevel(self, no_save_level):
        if no_save_level:
            self.ui.saveButton.setIcon(self.noSaveIcon)
        else:
            self.ui.saveButton.setIcon(self.saveIcon)
    
    def setProgress(self, progress):
        self.ui.lineEditClientStatus.setProgress(progress)
        
    def setDaemonOptions(self, options):
        has_git = bool(options & ray.Option.HAS_GIT)
        self.ui.actionReturnToAPreviousState.setVisible(has_git)

    def contextMenuEvent(self, event):
        act_selected = self.menu.exec(self.mapToGlobal(event.pos()))
        event.accept()


class ClientItem(QListWidgetItem):
    def __init__(self, parent, client_data):
        QListWidgetItem.__init__(self, parent, QListWidgetItem.UserType + 1)
        self.f_widget = ClientSlot(parent, client_data)
        parent.setItemWidget(self, self.f_widget)
        self.setSizeHint(QSize(100, 45))
        self.sort_number = 0

    def __lt__(self, other):
        result = bool(self.sort_number < other.sort_number)
        return result

    def __gt__(self, other):
        return self.sort_number > other.sort_number

    def setSortNumber(self, sort_number):
        self.sort_number = sort_number

    def getClientId(self):
        return self.f_widget.clientId()


class ListWidgetClients(QListWidget):
    def __init__(self, parent):
        QListWidget.__init__(self, parent)
        self.last_n = 0
        self._session = None
        
    def createClientWidget(self, client_data):
        item = ClientItem(self, client_data)
        item.setSortNumber(self.last_n)
        self.last_n += 1
        return item.f_widget

    def removeClientWidget(self, client_id):
        for i in range(self.count()):
            item = self.item(i)
            if item.getClientId() == client_id:
                widget = item.f_widget
                self.takeItem(i)
                del item
                break

    def reOrderClients(self, client_id_list):
        # when re_order comes from ray-daemon (loading session)
        if len(client_id_list) != self.count():
            return

        for client_id in client_id_list:
            for i in range(self.count()):
                if self.item(i).getClientId() == client_id:
                    break
            else:
                return

        next_item_list = []

        n = 0

        for client_id in client_id_list:
            for i in range(self.count()):
                if self.item(i).getClientId() == client_id:
                    self.item(i).setSortNumber(n)
                    break
            n += 1

        self.sortItems()
    
    def setSession(self, session):
        self._session = session
    
    def toDaemon(self, *args):
        server = GUIServerThread.instance()
        if server:
            server.toDaemon(*args)
    
    @pyqtSlot()
    def launchFavorite(self):
        template_name, factory = self.sender().data()
        self.toDaemon('/ray/session/add_client_template',
                      int(factory),
                      template_name)

    def dropEvent(self, event):
        QListWidget.dropEvent(self, event)

        client_ids_list = []

        for i in range(self.count()):
            item = self.item(i)
            #widget = self.itemWidget(item)
            client_id = item.getClientId()
            client_ids_list.append(client_id)

        server = GUIServerThread.instance()
        if server:
            server.toDaemon('/ray/session/reorder_clients', *client_ids_list)

    def mousePressEvent(self, event):
        if not self.itemAt(event.pos()):
            self.setCurrentRow(-1)
            
        QListWidget.mousePressEvent(self, event)
    
    def contextMenuEvent(self, event):
        if not self.itemAt(event.pos()):
            self.setCurrentRow(-1)
            
            if (self._session
                    and not self._session.server_status in (
                        ray.ServerStatus.OFF,
                        ray.ServerStatus.CLOSE,
                        ray.ServerStatus.OUT_SAVE,
                        ray.ServerStatus.WAIT_USER,
                        ray.ServerStatus.OUT_SNAPSHOT)):
                menu = QMenu()
                fav_menu = QMenu(_translate('menu', 'Favorites'), menu)
                fav_menu.setIcon(QIcon(':scalable/breeze/star-yellow'))
                
                for favorite in self._session.favorite_list:
                    act_app = fav_menu.addAction(
                        ray.getAppIcon(favorite.icon, self), favorite.name)
                    act_app.setData([favorite.name, favorite.factory])
                    act_app.triggered.connect(self.launchFavorite)
            
                menu.addMenu(fav_menu)
                
                menu.addAction(
                    self._session._main_win.ui.actionAddApplication)
                menu.addAction(self._session._main_win.ui.actionAddExecutable)
            
                act_selected = menu.exec(self.mapToGlobal(event.pos()))
            event.accept()
            return
        
        
