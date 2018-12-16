import time
from PyQt5.QtWidgets import QListWidget, QListWidgetItem, QFrame, QMenu, QApplication
from PyQt5.QtGui     import QIcon, QPalette, QPixmap, QFontMetrics, QFont, QFontDatabase
from PyQt5.QtCore    import Qt, pyqtSignal, QSize, QFile
 
import ray
from gui_server_thread import GUIServerThread 
from gui_tools import clientStatusString, _translate

import ui_client_slot
    
class ClientSlot(QFrame):
    def __init__(self, list_widget, client):
        QFrame.__init__(self)
        self.ui = ui_client_slot.Ui_ClientSlotWidget()
        self.ui.setupUi(self)
        
        #needed variables
        self.list_widget = list_widget
        self.client      = client
        self._main_win = self.client._session._main_win
        
        self.is_dirty_able   = False
        self.gui_visible     = True
        self.ui.toolButtonGUI.setVisible(False)
        
        #connect buttons to functions
        self.ui.toolButtonGUI.toggleGui.connect(self.toggleGui)
        self.ui.startButton.clicked.connect(self.startClient)
        self.ui.stopButton.clicked.connect(self.stopClient)
        self.ui.killButton.clicked.connect(self.killClient)
        self.ui.saveButton.clicked.connect(self.saveClient)
        self.ui.closeButton.clicked.connect(self.removeClient)
        self.ui.lineEditClientStatus.copyAborted.connect(self.abortCopy)
        #self.ui.ClientName.name_changed.connect(self.updateLabel)
        
        self.icon_on  = QIcon()
        self.icon_off = QIcon()
        
        self.updateClientData()
        
        self.ui.actionSaveAsApplicationTemplate.triggered.connect(self.saveAsApplicationTemplate)
        self.ui.actionProperties.triggered.connect(self.openPropertiesDialog)
        
        self.menu = QMenu(self)
        
        self.menu.addAction(self.ui.actionSaveAsApplicationTemplate)
        self.menu.addAction(self.ui.actionProperties)
        
        self.ui.iconButton.setMenu(self.menu)
        
        self.saveIcon = QIcon()
        self.saveIcon.addPixmap(QPixmap(':scalable/breeze/document-save'), QIcon.Normal, QIcon.Off)
        self.saveIcon.addPixmap(QPixmap(':scalable/breeze/disabled/document-save'), QIcon.Disabled, QIcon.Off)
        self.ui.saveButton.setIcon(self.saveIcon)
        
        self.savedIcon = QIcon()
        self.savedIcon.addPixmap(QPixmap(':scalable/breeze/document-saved'), QIcon.Normal, QIcon.Off)
        
        self.unsavedIcon = QIcon()
        self.unsavedIcon.addPixmap(QPixmap(':scalable/breeze/document-unsaved'), QIcon.Normal, QIcon.Off)
        
        #choose button colors
        if self.palette().brush(2, QPalette.WindowText).color().lightness() > 128:
            startIcon = QIcon()
            startIcon.addPixmap(QPixmap(':scalable/breeze-dark/media-playback-start'), QIcon.Normal, QIcon.Off)
            startIcon.addPixmap(QPixmap(':scalable/breeze-dark/disabled/media-playback-start'), QIcon.Disabled, QIcon.Off)
            self.ui.startButton.setIcon(startIcon)
            
            stopIcon = QIcon()
            stopIcon.addPixmap(QPixmap(':scalable/breeze-dark/media-playback-stop'), QIcon.Normal, QIcon.Off)
            stopIcon.addPixmap(QPixmap(':scalable/breeze-dark/disabled/media-playback-stop'), QIcon.Disabled, QIcon.Off)
            self.ui.stopButton.setIcon(stopIcon)
            
            self.saveIcon = QIcon()
            self.saveIcon.addPixmap(QPixmap(':scalable/breeze-dark/document-save'), QIcon.Normal, QIcon.Off)
            self.saveIcon.addPixmap(QPixmap(':scalable/breeze-dark/disabled/document-save'), QIcon.Disabled, QIcon.Off)
            self.ui.saveButton.setIcon(self.saveIcon)
            
            self.savedIcon = QIcon()
            self.savedIcon.addPixmap(QPixmap(':scalable/breeze-dark/document-saved'), QIcon.Normal, QIcon.Off)
            
            self.unsavedIcon = QIcon()
            self.unsavedIcon.addPixmap(QPixmap(':scalable/breeze-dark/document-unsaved'), QIcon.Normal, QIcon.Off)
            
            closeIcon = QIcon()
            closeIcon.addPixmap(QPixmap(':scalable/breeze-dark/window-close'), QIcon.Normal, QIcon.Off)
            closeIcon.addPixmap(QPixmap(':scalable/breeze-dark/disabled/window-close'), QIcon.Disabled, QIcon.Off)
            self.ui.closeButton.setIcon(closeIcon)
            
        self.ubuntu_font      = QFont(QFontDatabase.applicationFontFamilies(0)[0], 8)
        self.ubuntu_font_cond = QFont(QFontDatabase.applicationFontFamilies(1)[0], 8)
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
        #self.list_widget.clientStartRequest.emit(self.clientId())
        
    def stopClient(self):
        #we need to prevent accidental stop with a window confirmation
        #under conditions
        #self.list_widget.clientStopRequest.emit(self.clientId())
        self._main_win.stopClient(self.clientId())
    
    def killClient(self):
        self.toDaemon('/ray/client/kill', self.clientId())
        #self.list_widget.clientKillRequest.emit(self.clientId())
    
    def saveClient(self):
        self.toDaemon('/ray/client/save', self.clientId())
        #self.list_widget.clientSaveRequest.emit(self.clientId())
    
    def removeClient(self):
        self.toDaemon('/ray/client/remove', self.clientId())
        #self.list_widget.clientRemoveRequest.emit(self.clientId())
    
    def abortCopy(self):
        #server = self.getServer()
        #if server:
            #server.abortCopyClient(self.clientId())
        #self.list_widget.clientAbortCopyRequest.emit(self.clientId())
        self._main_win.abortCopyClient(self.clientId())
    
    def saveAsApplicationTemplate(self):
        #self.list_widget.clientSaveTemplateRequest.emit(self.clientId())
        self._main_win.newClientTemplate(self.clientId())
    
    def openPropertiesDialog(self):
        #self.list_widget.clientPropertiesRequest.emit(self.clientId())
        self._main_win.openClientProperties(self.clientId())
    
    def updateLabel(self, label):
        self._main_win.updateClientLabel(self.clientId(), label)
        #self.list_widget.updateLabelRequest.emit(self.clientId(), label)
        
    
    def updateClientData(self):
        #set main label
        label = self.client.label if self.client.label else self.client.name
        self.ui.ClientName.setText(label)
        
        #set tool tip
        self.ui.ClientName.setToolTip('Executable : ' + self.client.executable_path + '\n' + 'NSM id : ' + self.clientId())
        
        #set icon
        self.icon_on  = ray.getAppIcon(self.client.icon_name, self)
        self.icon_off = QIcon(self.icon_on.pixmap(32, 32, QIcon.Disabled))
        
        self.grayIcon(bool(self.client.status in (ray.ClientStatus.STOPPED, ray.ClientStatus.PRECOPY)))
        
    def grayIcon(self, gray):
        if gray:
            self.ui.iconButton.setIcon(self.icon_off)
        else:
            self.ui.iconButton.setIcon(self.icon_on)
        
    def updateStatus(self, status):
        self.ui.lineEditClientStatus.setText(clientStatusString(status))
        
        if status in (ray.ClientStatus.LAUNCH, ray.ClientStatus.OPEN, ray.ClientStatus.SWITCH):
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
            self.ui.lineEditClientStatus.setText(clientStatusString(ray.ClientStatus.OPEN))
        else:
            self.ui.lineEditClientStatus.setText('')
    
    def showGuiButton(self):
        self.ui.toolButtonGUI.setVisible(True)
        if self.client.executable_path in ('nsm-proxy', 'ray-proxy'):
            self.ui.toolButtonGUI.setText(_translate('client_slot', 'proxy'))
            self.ui.toolButtonGUI.setToolTip(_translate('client_slot', 'Display proxy window'))
     
    def setGuiState(self, state):
        self.gui_visible = state
        self.ui.toolButtonGUI.setChecked(state)
        
    def toggleGui(self):
        if not self.gui_visible:
            self.toDaemon('/ray/client/show_optional_gui', self.clientId())
            #self.list_widget.clientShowGuiRequest.emit(self.clientId())
        else:
            self.toDaemon('/ray/client/hide_optional_gui', self.clientId())
            self.list_widget.clientHideGuiRequest.emit(self.clientId())
            
        #self.gui_visible = not self.gui_visible
    
    def setDirtyState(self, bool_dirty):
        self.is_dirty_able = True
        
        if bool_dirty:
            self.ui.saveButton.setIcon(self.unsavedIcon)
        else:
            self.ui.saveButton.setIcon(self.savedIcon)
    
    def setProgress(self, progress):
        self.ui.lineEditClientStatus.setProgress(progress)
    
    def contextMenuEvent(self, event):
        act_selected = self.menu.exec(self.mapToGlobal(event.pos()))
        event.accept()
        
class ClientItem(QListWidgetItem):
    def __init__(self, parent, client_data):
        QListWidgetItem.__init__(self, parent, QListWidgetItem.UserType +1)
        self.f_widget    = ClientSlot(parent, client_data)
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
        #when re_order comes from ray-daemon (loading session)
        if len(client_id_list) != self.count():
            return
        
        for client_id in client_id_list:
            for i in range(self.count()):
                if self.item(i).getClientId() == client_id:
                    break
            else:
                return
            
        next_item_list = []
        
        
        n=0
        
        for client_id in client_id_list:
            for i in range(self.count()):
                if self.item(i).getClientId() == client_id:
                    self.item(i).setSortNumber(n)
                    break
            n+=1
                
        self.sortItems()
        
    
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
            server.orderChanged(client_ids_list)
        
    def mousePressEvent(self, event):
        if not self.itemAt(event.pos()):
            self.setCurrentRow(-1)
            return
        
        QListWidget.mousePressEvent(self, event)
        
