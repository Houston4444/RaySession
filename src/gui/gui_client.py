import time
import sys
from typing import TYPE_CHECKING, Optional
from qtpy.QtCore import QObject, Signal
from qtpy.QtWidgets import QAction

import ray
from gui_server_thread import GuiServerThread
from client_properties_dialog import ClientPropertiesDialog

if TYPE_CHECKING:
    from gui_session import SignaledSession


class Client(QObject, ray.ClientData):
    status_changed = Signal(ray.ClientStatus)

    def __init__(self, session: 'SignaledSession',
                 client_id: str, protocol_int: int):
        QObject.__init__(self)

        self.session = session
        self.main_win = self.session.main_win

        # set ClientData attributes
        self.client_id = client_id
        self.protocol = ray.Protocol(protocol_int)
        self.ray_hack = ray.RayHack()
        self.ray_net = ray.RayNet()
        
        self._previous_status = ray.ClientStatus.STOPPED

        self.status = ray.ClientStatus.STOPPED
        self.has_gui = False
        self.gui_state = False
        self.has_dirty = False
        self.dirty_state = True
        self.no_save_level = 0
        self.last_save = time.time()
        self.widget = self.main_win.create_client_widget(self)
        self._properties_dialog: ClientPropertiesDialog = None

    def set_status(self, status: ray.ClientStatus):
        self._previous_status = self.status
        self.status = status
        self.status_changed.emit(status)

        if (not self.has_dirty
                and self.status is ray.ClientStatus.READY
                and self._previous_status in (
                    ray.ClientStatus.OPEN, ray.ClientStatus.SAVE)):
            self.last_save = time.time()

        self.widget.update_status(status)
        
        if self._properties_dialog is not None:
            self._properties_dialog.update_status(status)

    def set_gui_enabled(self):
        self.has_gui = True
        self.widget.show_gui_button()

    def set_gui_state(self, state: bool):
        self.set_gui_enabled()
        self.gui_state = state
        self.widget.set_gui_state(state)

    def set_dirty_state(self, dirty: bool):
        self.has_dirty = True
        self.dirty_state = dirty
        self.widget.set_dirty_state(dirty)

    def set_progress(self, progress: float):
        self.widget.set_progress(progress)

    def allow_kill(self):
        self.widget.allow_kill()

    def update_properties(self, *args):
        self.update(*args)
        if ':optional-gui:' in self.capabilities:
            self.has_gui = True
        
        self.widget.update_client_data()

    def update_ray_hack(self, *args):
        self.ray_hack.update(*args)
        self.widget.update_client_data()

    def update_ray_net(self, *args):
        self.ray_net.update(*args)
        self.widget.update_client_data()

    def send_properties_to_daemon(self):
        server = GuiServerThread.instance()
        if not server:
            sys.stderr.write(
                'Server not found. Client %s can not send its properties\n'
                % self.client_id)
            return

        server.to_daemon('/ray/client/update_properties',
                         *ray.ClientData.spread_client(self))

    def send_ray_hack(self):
        if self.protocol is not ray.Protocol.RAY_HACK:
            return

        server = GuiServerThread.instance()
        if not server:
            return

        server.to_daemon('/ray/client/update_ray_hack_properties',
                         self.client_id,
                         *self.ray_hack.spread())

    def send_ray_net(self):
        if self.protocol is not ray.Protocol.RAY_NET:
            return

        server = GuiServerThread.instance()
        if not server:
            return

        server.to_daemon('/ray/client/update_ray_net_properties',
                         self.client_id,
                         *self.ray_net.spread())

    def show_properties_dialog(self, second_tab=False):
        if self._properties_dialog is None:
            self._properties_dialog = ClientPropertiesDialog.create(
                self.main_win, self)

        self._properties_dialog.update_contents()

        if second_tab:
            if self.protocol is ray.Protocol.RAY_HACK:
                self._properties_dialog.enable_test_zone(True)
            self._properties_dialog.set_on_second_tab()

        self._properties_dialog.show()

        if ray.get_window_manager() is not ray.WindowManager.WAYLAND:
            self._properties_dialog.activateWindow()

    def close_properties_dialog(self):
        if self._properties_dialog is None:
            return
        
        self._properties_dialog.close()

    def re_create_widget(self):
        del self.widget
        self.widget = self.main_win.create_client_widget(self)
        self.widget.update_client_data()

        if self.has_gui:
            self.set_gui_enabled()

    # method not used yet
    def get_project_path(self) -> str:
        if not self.session.path:
            return ''

        prefix = self.session.name

        if self.prefix_mode is ray.PrefixMode.CLIENT_NAME:
            prefix = self.name
        elif self.prefix_mode is ray.PrefixMode.CUSTOM:
            prefix = self.custom_prefix

        return f'{self.session.path}/{prefix}.{self.client_id}'

    # method not used yet
    def get_icon_search_path(self) -> list[str]:
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
    def __init__(self, session: 'SignaledSession'):
        self.session = session
        self.menu_action: Optional[QAction] = None

    def set_menu_action(self, menu_action: QAction):
        self.menu_action = menu_action
