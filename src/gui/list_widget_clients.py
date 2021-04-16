from PyQt5.QtWidgets import QListWidget, QListWidgetItem, QFrame, QMenu, QBoxLayout
from PyQt5.QtGui import QIcon, QPixmap, QFont, QFontDatabase, QFontMetrics
from PyQt5.QtCore import pyqtSlot, QSize

import ray
from gui_server_thread import GUIServerThread
from gui_tools import clientStatusString, _translate, isDarkTheme, RayIcon
import child_dialogs
import snapshots_dialog

import ui.client_slot
import ui.client_slot_2



class ClientSlot(QFrame):
    @staticmethod
    def split_in_two(string: str)->tuple:
        middle = int(len(string)/2)
        sep_indexes = []
        last_was_digit = False
        
        for sep in (' ', '-', '_', 'capital'):
            for i in range(len(string)):
                c = string[i]
                if sep == 'capital':
                    if c.upper() == c:
                        if not c.isdigit() or not last_was_digit:
                            sep_indexes.append(i)
                        last_was_digit = c.isdigit()
                        
                elif c == sep:
                    sep_indexes.append(i)
                    
            if sep_indexes:
                break
        
        if not sep_indexes or sep_indexes == [0]:
            return (string, '')
        
        best_index = 0
        best_dif = middle
        
        for s in sep_indexes:
            dif = abs(middle - s)
            if dif < best_dif:
                best_index = s
                best_dif = dif
        
        if sep == ' ':
            return (string[:best_index], string[best_index+1:])
        return (string[:best_index], string[best_index:])
    
    @classmethod
    def toDaemon(cls, *args):
        server = GUIServerThread.instance()
        if server:
            server.toDaemon(*args)

    def __init__(self, list_widget, list_widget_item, client):
        QFrame.__init__(self)
        self.ui = ui.client_slot_2.Ui_ClientSlotWidget()
        self.ui.setupUi(self)

        # needed variables
        self.list_widget = list_widget
        self.list_widget_item = list_widget_item
        self.client = client
        self._main_win = self.client._session._main_win
        self.gui_state = False
        self._stop_is_kill = False

        self.ui.toolButtonGUI.setVisible(False)
        if client.protocol != ray.Protocol.RAY_HACK:
            self.ui.toolButtonHack.setVisible(False)

        # connect buttons to functions
        self.ui.toolButtonHack.orderHackVisibility.connect(
            self.orderHackVisibility)
        self.ui.toolButtonGUI.clicked.connect(self.changeGuiState)
        self.ui.startButton.clicked.connect(self.startClient)
        self.ui.stopButton.clicked.connect(self.stopClient)
        self.ui.saveButton.clicked.connect(self.saveClient)
        self.ui.closeButton.clicked.connect(self.trashClient)
        self.ui.lineEditClientStatus.statusPressed.connect(self.abortCopy)

        self.icon_on = QIcon()
        self.icon_off = QIcon()

        self.ui.actionSaveAsApplicationTemplate.triggered.connect(
            self.saveAsApplicationTemplate)
        self.ui.actionRename.triggered.connect(self.renameDialog)
        self.ui.actionReturnToAPreviousState.triggered.connect(
            self.openSnapshotsDialog)
        self.ui.actionProperties.triggered.connect(
            self.client.showPropertiesDialog)

        self.menu = QMenu(self)

        self.menu.addAction(self.ui.actionSaveAsApplicationTemplate)
        self.menu.addAction(self.ui.actionRename)
        self.menu.addAction(self.ui.actionReturnToAPreviousState)
        self.menu.addAction(self.ui.actionProperties)

        self.ui.actionReturnToAPreviousState.setVisible(
            self._main_win.has_git)

        self.ui.iconButton.setMenu(self.menu)

        dark = isDarkTheme(self)

        self.saveIcon = RayIcon('document-save', dark)
        self.savedIcon = RayIcon('document-saved', dark)
        self.unsavedIcon = RayIcon('document-unsaved', dark)
        self.noSaveIcon = RayIcon('document-nosave', dark)
        self.icon_visible = RayIcon('visibility', dark)
        self.icon_invisible = RayIcon('hint', dark)
        self.stop_icon = RayIcon('media-playback-stop', dark)
        self.kill_icon = RayIcon('media-playback-stop_red', dark)
        self.ui.startButton.setIcon(RayIcon('media-playback-start', dark))
        self.ui.closeButton.setIcon(RayIcon('window-close', dark))
        self.ui.saveButton.setIcon(self.saveIcon)
        self.ui.stopButton.setIcon(self.stop_icon)

        self.ubuntu_font = QFont(
            QFontDatabase.applicationFontFamilies(0)[0], 8)
        self.ubuntu_font_cond = QFont(
            QFontDatabase.applicationFontFamilies(1)[0], 8)
        self.ubuntu_font.setBold(True)
        self.ubuntu_font_cond.setBold(True)

        if ':optional-gui:' in self.client.capabilities:
            self.setGuiState(self.client.gui_state)
            self.ui.toolButtonGUI.setVisible(True)

        if self.client.has_dirty:
            self.setDirtyState(self.client.dirty_state)

        self.updateClientData()

    def clientId(self):
        return self.client.client_id

    def startClient(self):
        self.toDaemon('/ray/client/resume', self.clientId())

    def stopClient(self):
        if self._stop_is_kill:
            self.toDaemon('/ray/client/kill', self.clientId())
            return
        
        # we need to prevent accidental stop with a window confirmation
        # under conditions
        self._main_win.stopClient(self.clientId())

    def saveClient(self):
        self.toDaemon('/ray/client/save', self.clientId())

    def trashClient(self):
        self.toDaemon('/ray/client/trash', self.clientId())

    def abortCopy(self):
        self._main_win.abortCopyClient(self.clientId())

    def saveAsApplicationTemplate(self):
        dialog = child_dialogs.SaveTemplateClientDialog(
            self._main_win, self.client)
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

    def renameDialog(self):
        dialog = child_dialogs.ClientRenameDialog(self._main_win,
                                                  self.client)
        dialog.exec()
        if dialog.result():
            self.client.label = dialog.getNewLabel()
            self.client.sendPropertiesToDaemon()

    def updateLabel(self, label):
        self._main_win.updateClientLabel(self.clientId(), label)

    def set_fat(self, yesno: bool, very_fat=False):
        if yesno:
            self.ui.mainLayout.setDirection(QBoxLayout.TopToBottom)
            self.ui.spacerLeftOfDown.setVisible(True)
            self.list_widget_item.setSizeHint(
                QSize(100, 80 if very_fat else 70))
        else:
            self.ui.spacerLeftOfDown.setVisible(False)
            self.ui.mainLayout.setDirection(QBoxLayout.LeftToRight)
            self.list_widget_item.setSizeHint(QSize(100, 45))
    
    def set_display_name(self):
        default_font_size = 13
        font = self.ui.ClientName.font()
        main_size = QFontMetrics(font).width(self.client.prettier_name())
        
        layout_width = self.list_widget.width()
        
        if layout_width < 233:
            self.ui.startButton.setVisible(self.ui.startButton.isEnabled())
            self.ui.stopButton.setVisible(self.ui.stopButton.isEnabled())
            self.ui.toolButtonHack.setVisible(False)
        else:
            self.ui.startButton.setVisible(True)
            self.ui.stopButton.setVisible(True)
            self.ui.toolButtonHack.setVisible(
                self.client.protocol == ray.Protocol.RAY_HACK)
        
        scroll_bar = self.list_widget.verticalScrollBar()
        if scroll_bar.isVisible():
            layout_width -= scroll_bar.width()
        
        max_label_width = layout_width - 231
        
        if self.ui.toolButtonGUI.isVisible():
            max_label_width -= self.ui.toolButtonGUI.width()
        if self.ui.toolButtonHack.isVisible():
            max_label_width -= self.ui.toolButtonHack.width()
        
        if main_size <= max_label_width:
            self.ui.ClientName.setText(self.client.prettier_name())
            self.set_fat(False)
            return
        
        # split title in two lines
        top, bottom = self.split_in_two(self.client.prettier_name())
            
        max_size = 0
        
        for text in (top, bottom):
            if not text:
                continue
            
            size = QFontMetrics(font).width(text)
            max_size = max(max_size, size)
        
        if max_size <= max_label_width:
            self.ui.ClientName.setText('\n'.join((top, bottom)))
            self.set_fat(False)
            return
        
        # responsive design, put label at top of the controls
        # if there is not enought space for label
            
        max_label_width = layout_width - 50
        
        if main_size <= max_label_width:
            self.set_fat(True)
            self.ui.ClientName.setText(self.client.prettier_name())
            return

        self.set_fat(True, very_fat=True)
        
        top, bottom = self.split_in_two(self.client.prettier_name())
        self.ui.ClientName.setText('\n'.join((top, bottom)))

    def updateClientData(self):
        # set main label and main disposition
        self.set_display_name()

        # set tool tip
        tool_tip = "<html><head/><body>"
        tool_tip += "<p><span style=\" font-weight:600;\">%s<br></span>" \
            % self.client.name
        tool_tip += "<span style=\" font-style:italic;\">%s</span></p>" \
            % self.client.description
        tool_tip += "<p></p>"
        tool_tip += "<p>%s : %s<br>" \
            % (_translate('client_slot', 'Protocol'),
               ray.protocolToStr(self.client.protocol))
        tool_tip += "%s : %s<br>" \
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

        self.ui.toolButtonGUI.setVisible(
            bool(':optional-gui:' in self.client.capabilities))

        if self.client.executable_path in ('ray-proxy', 'nsm-proxy'):
            if isDarkTheme(self):
                self.icon_visible = QIcon()
                self.icon_visible.addPixmap(
                    QPixmap(':scalable/breeze-dark/emblem-symbolic-link'),
                    QIcon.Normal, QIcon.Off)
                self.icon_invisible = QIcon()
                self.icon_invisible.addPixmap(
                    QPixmap(':scalable/breeze-dark/link'),
                    QIcon.Normal, QIcon.Off)
                self.icon_invisible.addPixmap(
                    QPixmap(':scalable/breeze-dark/disabled/link'),
                    QIcon.Disabled, QIcon.Off)
            else:
                self.icon_visible = QIcon()
                self.icon_visible.addPixmap(
                    QPixmap(':scalable/breeze/emblem-symbolic-link'),
                    QIcon.Normal, QIcon.Off)
                self.icon_invisible = QIcon()
                self.icon_invisible.addPixmap(
                    QPixmap(':scalable/breeze/link'), QIcon.Normal, QIcon.Off)
                self.icon_invisible.addPixmap(
                    QPixmap(':scalable/breeze/disabled/link'),
                    QIcon.Disabled, QIcon.Off)

    def grayIcon(self, gray):
        if gray:
            self.ui.iconButton.setIcon(self.icon_off)
        else:
            self.ui.iconButton.setIcon(self.icon_on)

    def updateStatus(self, status):
        self.ui.lineEditClientStatus.setText(clientStatusString(status))

        ray_hack = bool(self.client.protocol == ray.Protocol.RAY_HACK)

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

            self.ui.saveButton.setIcon(self.saveIcon)
            self.ui.stopButton.setIcon(self.stop_icon)
            self._stop_is_kill = False

            if not ray_hack:
                self.setGuiState(False)

        elif status == ray.ClientStatus.PRECOPY:
            self.ui.startButton.setEnabled(False)
            self.ui.stopButton.setEnabled(False)
            self.ui.saveButton.setEnabled(False)
            self.ui.closeButton.setEnabled(True)
            self.ui.ClientName.setStyleSheet('QLabel {font-weight : normal}')
            self.ui.ClientName.setEnabled(False)
            self.ui.toolButtonGUI.setEnabled(False)
            self.grayIcon(True)

            self.ui.saveButton.setIcon(self.saveIcon)
            self.ui.stopButton.setIcon(self.stop_icon)
            self._stop_is_kill = False

        elif status == ray.ClientStatus.COPY:
            self.ui.saveButton.setEnabled(False)

    def setMaxLabelWidth(self):
        self.set_display_name()

    def allowKill(self):
        self._stop_is_kill = True
        self.ui.stopButton.setIcon(self.kill_icon)

    def flashIfOpen(self, boolflash):
        if boolflash:
            self.ui.lineEditClientStatus.setText(
                clientStatusString(ray.ClientStatus.OPEN))
        else:
            self.ui.lineEditClientStatus.setText('')

    def setHackButtonState(self, state: bool):
        self.ui.toolButtonHack.setChecked(state)

    def showGuiButton(self):
        self.ui.toolButtonGUI.setIcon(self.icon_invisible)
        self.ui.toolButtonGUI.setVisible(True)

    def setGuiState(self, state: bool):
        if state:
            self.ui.toolButtonGUI.setIcon(self.icon_visible)
        else:
            self.ui.toolButtonGUI.setIcon(self.icon_invisible)

        self.gui_state = state

    def changeGuiState(self):
        if self.gui_state:
            self.toDaemon('/ray/client/hide_optional_gui', self.clientId())
        else:
            self.toDaemon('/ray/client/show_optional_gui', self.clientId())

    def orderHackVisibility(self, state):
        if self.client.protocol != ray.Protocol.RAY_HACK:
            return

        if state:
            self.client.showPropertiesDialog(second_tab=True)
        else:
            self.client.properties_dialog.hide()

    def setDirtyState(self, bool_dirty):
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

    def resizeEvent(self, event):
        QFrame.resizeEvent(self, event)
        
        print('sle', self.client.prettier_name(), self.width(), self.minimumSizeHint().width())

    def contextMenuEvent(self, event):
        act_selected = self.menu.exec(self.mapToGlobal(event.pos()))
        event.accept()


class ClientItem(QListWidgetItem):
    def __init__(self, parent, client_data):
        QListWidgetItem.__init__(self, parent, QListWidgetItem.UserType + 1)
        self.f_widget = ClientSlot(parent, self, client_data)
        parent.setItemWidget(self, self.f_widget)
        self.setSizeHint(QSize(100, 45))
        
        #self.setSizeHint(QSize(100, 70))
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
    
    def reCreateWidget(self, parent, big_label=False):
        client_data = self.f_widget.client
        del self.f_widget
        #self.close()
        self.f_widget = ClientSlot(parent, self, client_data)
        self.setSizeHint(QSize(100, 70 if big_label else 45))
        parent.setItemWidget(self, self.f_widget)
        


class ListWidgetClients(QListWidget):
    @classmethod
    def toDaemon(self, *args):
        server = GUIServerThread.instance()
        if server:
            server.toDaemon(*args)

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

        n = 0

        for client_id in client_id_list:
            for i in range(self.count()):
                if self.item(i).getClientId() == client_id:
                    self.item(i).setSortNumber(n)
                    break
            n += 1

        self.sortItems()

    def clientPropertiesStateChanged(self, client_id, bool_visible):
        for i in range(self.count()):
            item = self.item(i)
            if item.getClientId() == client_id:
                widget = item.f_widget
                widget.setHackButtonState(bool_visible)
                break

    def setSession(self, session):
        self._session = session

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

            if (self._session is not None
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

    def resizeEvent(self, event):
        QListWidget.resizeEvent(self, event)
        for i in range(self.count()):
            item = self.item(i)
            widget = self.itemWidget(item)
            widget.set_display_name()
        
