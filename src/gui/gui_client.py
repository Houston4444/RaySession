import time
import sys
import child_dialogs
import snapshots_dialog
import ray
from gui_server_thread import GUIServerThread


class Client(object):
    def __init__(self, session, client_data, trashed=False):
        self._session = session
        self._main_win = self._session._main_win

        self.client_id       = client_data.client_id
        self.executable_path = client_data.executable_path
        self.arguments       = client_data.arguments
        self.name            = client_data.name
        self.prefix_mode     = client_data.prefix_mode
        self.project_path    = client_data.project_path
        self.label           = client_data.label
        self.icon_name       = client_data.icon
        self.capabilities    = client_data.capabilities
        self.check_last_save = client_data.check_last_save
        self.ignored_extensions = client_data.ignored_extensions

        self.status = ray.ClientStatus.STOPPED
        self.previous_status = ray.ClientStatus.STOPPED
        self.hasGui = False
        self.gui_visible = False
        self.has_dirty = False
        self.dirty_state = True
        self.last_save = time.time()

        self.widget = self._main_win.createClientWidget(self)
        self.properties_dialog = child_dialogs.ClientPropertiesDialog(
            self._main_win, self)

    def setStatus(self, status):
        self.previous_status = self.status
        self.status = status

        if (not self.has_dirty
            and self.status == ray.ClientStatus.READY
            and self.previous_status in (ray.ClientStatus.OPEN,
                                         ray.ClientStatus.SAVE)):
            self.last_save = time.time()

        self.widget.updateStatus(status)

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

    def setProgress(self, progress):
        self.widget.setProgress(progress)

    def switch(self, new_client_id):
        self.client_id = new_client_id
        self.widget.updateClientData()

    def allowKill(self):
        self.widget.allowKill()

    def updateLabel(self, label):
        self.label = label
        self.sendPropertiesToDaemon()

    def updateClientProperties(self, client_data):
        self.executable_path = client_data.executable_path
        self.arguments       = client_data.arguments
        self.name            = client_data.name
        self.prefix_mode     = client_data.prefix_mode
        self.project_path    = client_data.project_path
        self.label           = client_data.label
        self.icon_name       = client_data.icon
        self.capabilities    = client_data.capabilities
        self.check_last_save = client_data.check_last_save
        
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
                        self.client_id,
                        self.executable_path,
                        self.arguments,
                        self.name,
                        self.prefix_mode,
                        self.project_path,
                        self.label,
                        self.icon_name,
                        self.capabilities,
                        int(self.check_last_save),
                        self.ignored_extensions)

    def showPropertiesDialog(self):
        self.properties_dialog.updateContents()
        self.properties_dialog.show()
        self.properties_dialog.activateWindow()
        
    def showSnapshotsDialog(self):
        dialog = snapshots_dialog.ClientSnapshotsDialog(self._main_win, self)
        dialog.show()
        dialog.activateWindow()

    def reCreateWidget(self):
        del self.widget
        self.widget = self._main_win.createClientWidget(self)
        self.widget.updateClientData()

        if self.hasGui:
            self.setGuiEnabled()

    def hasBeenRecentlySaved(self):
        if (time.time() - self.last_save) >= 60:  # last save more than 60 seconds ago
            return False

        return True


class TrashedClient(object):
    def __init__(self, client_data, menu_action):
        self.data = client_data
        self.menu_action = menu_action
