import time
import sys
from PyQt5.QtCore import QObject, pyqtSignal

import snapshots_dialog
import ray
from gui_server_thread import GUIServerThread
from client_properties_dialog import ClientPropertiesDialog

class Client(QObject, ray.ClientData):
    status_changed = pyqtSignal(int)
    
    def __init__(self, session, client_id, protocol, trashed=False):
        QObject.__init__(self)
        ray.ClientData.gui_init(self, client_id, protocol)
        
        self._session = session
        self._main_win = self._session._main_win
        
        self.ray_hack = ray.RayHack()

        self.status = ray.ClientStatus.STOPPED
        self.previous_status = ray.ClientStatus.STOPPED
        self.hasGui = False
        self.gui_visible = False
        self.has_dirty = False
        self.dirty_state = True
        self.no_save_level = 0
        self.last_save = time.time()

        self.widget = self._main_win.createClientWidget(self)
        self.properties_dialog = ClientPropertiesDialog.create(self._main_win,
                                                               self)

    def setStatus(self, status):
        self.previous_status = self.status
        self.status = status
        self.status_changed.emit(status)

        if (not self.has_dirty
            and self.status == ray.ClientStatus.READY
            and self.previous_status in (ray.ClientStatus.OPEN,
                                         ray.ClientStatus.SAVE)):
            self.last_save = time.time()

        self.widget.updateStatus(status)
        self.properties_dialog.updateStatus(status)

    def setGuiEnabled(self):
        self.hasGui = True
        self.widget.showGuiButton()

    def setGuiState(self, state):
        self.gui_state = state
        self.widget.setGuiState(state)

    def setDirtyState(self, bool_dirty):
        self.has_dirty = True
        self.dirty_state = bool_dirty
        self.widget.setDirtyState(bool_dirty)

    def setNoSaveLevel(self, no_save_level):
        self.no_save_level = no_save_level
        self.widget.setNoSaveLevel(no_save_level)
    
    def setProgress(self, progress):
        self.widget.setProgress(progress)

    def allowKill(self):
        self.widget.allowKill()

    def updateLabel(self, label):
        self.label = label
        self.sendPropertiesToDaemon()

    def updateClientProperties(self, *args):
        self.update(*args)
        print('okeorldl')
        print(args)
        print('eokkllxlx', self.client_id, self.label, self.icon)
        self.widget.updateClientData()

    def updateRayHack(self, *args):
        self.ray_hack.update(*args)
        self.widget.updateClientData()

    def prettierName(self):
        if self.label:
            return self.label

        if self.name:
            return self.name

        return self.executable_path

    def sendPropertiesToDaemon(self):
        server = GUIServerThread.instance()
        if not server:
            sys.stderr.write(
                'Server not found. Client %s can not send its properties\n'
                    % self.client_id)
            return
        
        server.toDaemon('/ray/client/update_properties',
                        *ray.ClientData.spreadClient(self))
        
        if self.protocol == ray.Protocol.RAY_HACK:
            self.sendRayHack()

    def sendRayHack(self):
        if not self.protocol == ray.Protocol.RAY_HACK:
            return
        
        server = GUIServerThread.instance()
        if not server:
            return
        
        server.toDaemon('/ray/client/update_ray_hack_properties',
                        self.client_id,
                        *self.ray_hack.spread())
        
    def showPropertiesDialog(self, second_tab=False):
        self.properties_dialog.updateContents()
        if second_tab:
            self.properties_dialog.setOnSecondTab()
        self.properties_dialog.show()
        self.properties_dialog.activateWindow()
    
    def reCreateWidget(self):
        del self.widget
        self.widget = self._main_win.createClientWidget(self)
        self.widget.updateClientData()

        if self.hasGui:
            self.setGuiEnabled()

    def hasBeenRecentlySaved(self):
        if (time.time() - self.last_save) >= 60:  
            # last save more than 60 seconds ago
            return False

        return True


class TrashedClient(object):
    def __init__(self, client_data, menu_action):
        self.data = client_data
        self.menu_action = menu_action
