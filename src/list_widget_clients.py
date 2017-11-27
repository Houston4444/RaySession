from PyQt5.QtWidgets import QListWidget, QListWidgetItem, QFrame
from PyQt5.QtGui     import QIcon, QPalette, QPixmap
from PyQt5.QtCore    import Qt, pyqtSignal, QSize
 
import ui_client_slot


class ClientSlot(QFrame):
    def __init__(self, list_widget, client):
        QFrame.__init__(self)
        self.ui = ui_client_slot.Ui_ClientSlotWidget()
        self.ui.setupUi(self)
        
        #needed variables
        self.list_widget     = list_widget
        self.client          = client
        
        
        #self.client_id       = client.client_id
        #self.client_name     = client.name
        #self.executable_path = client.executable_path
        #self.label           = client.label
        #self.icon_name       = client.icon
        
        
        self.is_dirty_able   = False
        self.gui_visible     = True
        
        #set label and tooltip on label
        #self.ui.ClientName.setText(self.executable_path)
        self.updateClientLabel()
        self.updateToolTip()
        
        #set icon
        self.icon = QIcon.fromTheme(self.client.icon)
        self.ui.iconButton.setIcon(self.icon)
        self.updateClientLabel()
        #self.updateIcon(self.executable_path)
        
        self.ui.toolButtonGUI.setVisible(False)
        
        #connect buttons to functions
        self.ui.toolButtonGUI.clicked.connect(self.toggleGui)
        self.ui.startButton.clicked.connect(self.startClient)
        self.ui.stopButton.clicked.connect(self.stopClient)
        self.ui.saveButton.clicked.connect(self.saveClient)
        self.ui.closeButton.clicked.connect(self.removeClient)
        
        if self.palette().brush(2, QPalette.WindowText).color().lightness() > 128:
            startIcon = QIcon()
            startIcon.addPixmap(QPixmap(':scalable/breeze-dark/media-playback-start'), QIcon.Normal, QIcon.Off)
            startIcon.addPixmap(QPixmap(':scalable/breeze-dark/disabled/media-playback-start'), QIcon.Disabled, QIcon.Off)
            self.ui.startButton.setIcon(startIcon)
            
            stopIcon = QIcon()
            stopIcon.addPixmap(QPixmap(':scalable/breeze-dark/media-playback-stop'), QIcon.Normal, QIcon.Off)
            stopIcon.addPixmap(QPixmap(':scalable/breeze-dark/disabled/media-playback-stop'), QIcon.Disabled, QIcon.Off)
            self.ui.stopButton.setIcon(stopIcon)
            
            saveIcon = QIcon()
            saveIcon.addPixmap(QPixmap(':scalable/breeze-dark/document-save'), QIcon.Normal, QIcon.Off)
            saveIcon.addPixmap(QPixmap(':scalable/breeze-dark/disabled/document-save'), QIcon.Disabled, QIcon.Off)
            self.ui.saveButton.setIcon(saveIcon)
            
            closeIcon = QIcon()
            closeIcon.addPixmap(QPixmap(':scalable/breeze-dark/window-close'), QIcon.Normal, QIcon.Off)
            closeIcon.addPixmap(QPixmap(':scalable/breeze-dark/disabled/window-close'), QIcon.Disabled, QIcon.Off)
            self.ui.closeButton.setIcon(closeIcon)
            
    
    def clientId(self):
        return self.client.client_id
    
    def startClient(self):
        self.list_widget.clientStartRequest.emit(self.clientId())
        
    def stopClient(self):
        self.list_widget.clientStopRequest.emit(self.clientId())
        
    def saveClient(self):
        self.list_widget.clientSaveRequest.emit(self.clientId())
    
    def removeClient(self):
        self.list_widget.clientRemoveRequest.emit(self.clientId())
    
    def switch(self, new_client_id):
        #self.client_id = new_client_id
        self.updateToolTip()
    
    def updateIcon(self, client_name):
        if not self.icon.isNull():
            return
        
        icon_name = client_name.lower().replace('_', '-')
        
        if icon_name == 'hydrogen':
            icon_name = 'h2-icon'
        elif icon_name == 'guitarix':
            icon_name = 'gx_head'
        elif icon_name == 'jackpatch':
            icon_name = 'curve-connector'
        
        self.icon = QIcon.fromTheme(icon_name)
        self.ui.iconButton.setIcon(self.icon)
    
    def updateClientIcon(self, icon_name):
        self.icon = QIcon.fromTheme(icon_name)
        self.ui.iconButton.setIcon(self.icon)
    
    def updateClientLabel(self):
        label = self.client.label
        if not label:
            label = self.client.name
        print(label, self.client.label, self.client.name)
        self.ui.ClientName.setText(label)
        
    def updateClientName(self, client_name):
        if self.client.label:
            return
        self.ui.ClientName.setText(client_name)
        self.updateIcon(client_name)
    
    def updateToolTip(self):
        self.ui.ClientName.setToolTip('Executable : ' + self.client.executable_path + '\n' + 'NSM id : ' + self.clientId())
    
    def updateClientData(self):
        self.updateClientLabel()
        self.updateClientIcon(self.client.icon)
    
    #def updateClientData(self, client_data):
        #self.client_id       = client_data.client_id
        #self.client_name     = client_data.name
        #self.executable_path = client_data.executable_path
        #self.label           = client_data.label
        #self.icon_name       = client_data.icon
        
        ##self.updateClientName(self.client_name)
        #self.updateClientLabel()
        #self.updateClientIcon(self.icon_name)
        
    def updateStatus(self, status):
        self.ui.lineEditClientStatus.setText(status)
        
        if status in ('launch', 'open'):
            self.ui.startButton.setEnabled(False)
            self.ui.stopButton.setEnabled(True)
            self.ui.saveButton.setEnabled(False)
            self.ui.closeButton.setEnabled(False)
            self.ui.iconButton.setEnabled(True)
            self.ui.ClientName.setStyleSheet('QLabel {font-weight : bold}')
            self.ui.ClientName.setEnabled(True)
            self.ui.toolButtonGUI.setEnabled(True)
                
        elif status == 'ready':
            self.ui.startButton.setEnabled(False)
            self.ui.stopButton.setEnabled(True)
            self.ui.closeButton.setEnabled(False)
            self.ui.iconButton.setEnabled(True)
            self.ui.ClientName.setStyleSheet('QLabel {font-weight : bold}')
            self.ui.ClientName.setEnabled(True)
            self.ui.toolButtonGUI.setEnabled(True)
            if not self.is_dirty_able:
                self.ui.saveButton.setEnabled(True)
            
        elif status == 'stopped':
            self.ui.startButton.setEnabled(True)
            self.ui.stopButton.setEnabled(False)
            self.ui.saveButton.setEnabled(False)
            self.ui.closeButton.setEnabled(True)
            self.ui.iconButton.setEnabled(False)
            self.ui.ClientName.setStyleSheet('QLabel {font-weight : normal}')
            self.ui.ClientName.setEnabled(False)
            self.ui.toolButtonGUI.setEnabled(False)
            
    def flashIfOpen(self, boolflash):
        if boolflash:
            self.ui.lineEditClientStatus.setText('open')
        else:
            self.ui.lineEditClientStatus.setText('')
    
    def showGuiButton(self):
        basecolor   = self.palette().base().color().name()
        textcolor   = self.palette().buttonText().color().name()
        textdbcolor = self.palette().brush(QPalette.Disabled, QPalette.WindowText).color().name()
        
        style = "QToolButton{border-radius: 2px ;border-left: 1px solid " + \
                "qlineargradient(spread:pad, x1:0, y1:0, x2:0, y2:1, stop:0 " + textcolor + \
                ", stop:0.35 " + basecolor + ", stop:0.75 " + basecolor + ", stop:1 " + textcolor + ")" + \
                ";border-right: 1px solid " + "qlineargradient(spread:pad, x1:0, y1:0, x2:0, y2:1, stop:0 " + textcolor + \
                ", stop:0.25 " + basecolor + ", stop:0.75 " + basecolor + ", stop:1 " + textcolor + ")" + \
                ";border-top: 1px solid " + textcolor + ";border-bottom : 1px solid " + textcolor +  \
                "; background-color: " + basecolor + "; font-size: 11px" + "}" + \
                "QToolButton::checked{background-color: " + \
                "qlineargradient(spread:pad, x1:0, y1:0, x2:0, y2:1, stop:0 " + textcolor + \
                ", stop:0.25 " + basecolor + ", stop:0.85 " + basecolor + ", stop:1 " + textcolor + ")" + \
                "; margin-top: 0px; margin-left: 0px " + "}" + \
                "QToolButton::disabled{;border-left: 1px solid " + \
                "qlineargradient(spread:pad, x1:0, y1:0, x2:0, y2:1, stop:0 " + textdbcolor + \
                ", stop:0.25 " + basecolor + ", stop:0.75 " + basecolor + ", stop:1 " + textdbcolor + ")" + \
                ";border-right: 1px solid " + \
                "qlineargradient(spread:pad, x1:0, y1:0, x2:0, y2:1, stop:0 " + textdbcolor + \
                ", stop:0.25 " + basecolor + ", stop:0.75 " + basecolor + ", stop:1 " + textdbcolor + ")" + \
                ";border-top: 1px solid " + textdbcolor + ";border-bottom : 1px solid " + textdbcolor + \
                "; background-color: " + basecolor + "}"
        
        self.ui.toolButtonGUI.setStyleSheet(style)
        self.ui.toolButtonGUI.setVisible(True)
        if self.client.executable_path in ('nsm-proxy', 'ray-proxy'):
            self.ui.toolButtonGUI.setText('proxy')
            self.ui.toolButtonGUI.setToolTip('show proxy window')
     
    def setGuiState(self, state):
        self.gui_visible = state
        self.ui.toolButtonGUI.setChecked(state)
        
    def toggleGui(self):
        if not self.gui_visible:
            self.list_widget.clientShowGuiRequest.emit(self.clientId())
        else:
            self.list_widget.clientHideGuiRequest.emit(self.clientId())
    
    def setDirtyState(self, bool_dirty):
        self.is_dirty_able = True
        self.ui.saveButton.setEnabled(bool_dirty)
        
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
    orderChanged = pyqtSignal(list)
    clientStartRequest   = pyqtSignal(str)
    clientStopRequest    = pyqtSignal(str)
    clientSaveRequest    = pyqtSignal(str)
    clientRemoveRequest  = pyqtSignal(str)
    clientHideGuiRequest = pyqtSignal(str)
    clientShowGuiRequest = pyqtSignal(str)
    
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
        #when re_order comes from ray-deamon (loading session)
        if len(client_id_list) != self.count():
            return
        
        for client_id in client_id_list:
            for i in range(self.count()):
                if self.item(i).getClientId() == client_id:
                    break
            else:
                return
            
        next_item_list = []
        
        #return
        
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
            widget = self.itemWidget(item)
            client_id = widget.getClientId()
            client_ids_list.append(client_id)
        
        self.orderChanged.emit(client_ids_list)
        
    def mousePressEvent(self, event):
        if not self.itemAt(event.pos()):
            self.setCurrentRow(-1)
            return
        
        QListWidget.mousePressEvent(self, event)
        

        
