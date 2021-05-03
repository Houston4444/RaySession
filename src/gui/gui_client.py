import time
import sys
from PyQt5.QtCore import QObject, pyqtSignal

import ray
from gui_server_thread import GUIServerThread
from client_properties_dialog import ClientPropertiesDialog

class Client(QObject, ray.ClientData):
    status_changed = pyqtSignal(int)

    def __init__(self, session, client_id: str, protocol: int):
        QObject.__init__(self)
        ray.ClientData.gui_init(self, client_id, protocol)

        self.session = session
        self.main_win = self.session.main_win
        
        self._previous_status = ray.ClientStatus.STOPPED
        self._has_gui = False

        self.ray_hack = ray.RayHack()
        self.ray_net = ray.RayNet()
        self.status = ray.ClientStatus.STOPPED
        self.gui_state = False
        self.has_dirty = False
        self.dirty_state = True
        self.no_save_level = 0
        self.last_save = time.time()
        self.check_last_save = True

        self.widget = self.main_win.createClientWidget(self)
        self.properties_dialog = ClientPropertiesDialog.create(self.main_win, self)

    def set_status(self, status: int):
        self._previous_status = self.status
        self.status = status
        self.status_changed.emit(status)

        if (not self.has_dirty
                and self.status == ray.ClientStatus.READY
                and self._previous_status in (
                    ray.ClientStatus.OPEN, ray.ClientStatus.SAVE)):
            self.last_save = time.time()

        self.widget.updateStatus(status)
        self.properties_dialog.updateStatus(status)

    def set_gui_enabled(self):
        self._has_gui = True
        self.widget.showGuiButton()

    def set_gui_state(self, state: bool):
        self.gui_state = state
        self.widget.setGuiState(state)

    def set_dirty_state(self, dirty: bool):
        self.has_dirty = True
        self.dirty_state = dirty
        self.widget.setDirtyState(dirty)

    def set_no_save_level(self, no_save_level: int):
        self.no_save_level = no_save_level
        self.widget.setNoSaveLevel(no_save_level)

    def set_progress(self, progress: float):
        self.widget.setProgress(progress)

    def allow_kill(self):
        self.widget.allowKill()

    def update_properties(self, *args):
        self.update(*args)
        self.widget.updateClientData()

    def update_ray_hack(self, *args):
        self.ray_hack.update(*args)
        self.widget.updateClientData()

    def update_ray_net(self, *args):
        self.ray_net.update(*args)
        self.widget.updateClientData()

    def prettier_name(self):
        if self.label:
            return self.label

        if self.name:
            return self.name

        return self.executable_path

    def send_properties_to_daemon(self):
        server = GUIServerThread.instance()
        if not server:
            sys.stderr.write(
                'Server not found. Client %s can not send its properties\n'
                % self.client_id)
            return

        server.toDaemon('/ray/client/update_properties',
                        *ray.ClientData.spreadClient(self))

    def send_ray_hack(self):
        if self.protocol != ray.Protocol.RAY_HACK:
            return

        server = GUIServerThread.instance()
        if not server:
            return

        server.toDaemon('/ray/client/update_ray_hack_properties',
                        self.client_id,
                        *self.ray_hack.spread())

    def send_ray_net(self):
        if self.protocol != ray.Protocol.RAY_NET:
            return

        server = GUIServerThread.instance()
        if not server:
            return

        server.toDaemon('/ray/client/update_ray_net_properties',
                        self.client_id,
                        *self.ray_net.spread())

    def show_properties_dialog(self, second_tab=False):
        self.properties_dialog.updateContents()
        if second_tab:
            if self.protocol == ray.Protocol.RAY_HACK:
                self.properties_dialog.enableTestZone(True)
            self.properties_dialog.setOnSecondTab()
        self.properties_dialog.show()
        self.properties_dialog.activateWindow()

    def re_create_widget(self):
        del self.widget
        self.widget = self.main_win.createClientWidget(self)
        self.widget.updateClientData()

        if self._has_gui:
            self.set_gui_enabled()

    # method not used yet
    def get_project_path(self)->str:
        if not self.session.path:
            return ''

        prefix = self.session.name

        if self.prefix_mode == ray.PrefixMode.CLIENT_NAME:
            prefix = self.name
        elif self.prefix_mode == ray.PrefixMode.CUSTOM:
            prefix = self.custom_prefix

        return "%s/%s.%s" % (self.session.path, prefix, self.client_id)

    # method not used yet
    def get_icon_search_path(self)->list:
        if not self.session.daemon_manager.is_local:
            return []

        project_path = self.get_project_path()
        if not project_path:
            return []

        search_list = []
        main_icon_path = '.local/share/icons'
        search_list.append("%s/%s" % (search_list, main_icon_path))

        for path in ('16x16', '24x24', '32x32', '64x64', 'scalable'):
            search_list.append("%s/%s/%s" % (project_path,
                                             main_icon_path, path))
        return search_list


class TrashedClient(ray.ClientData):
    def __init__(self):
        self.menu_action = None

    def set_menu_action(self, menu_action):
        self.menu_action = menu_action
