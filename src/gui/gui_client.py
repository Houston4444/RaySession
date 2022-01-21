import time
import sys
from PyQt5.QtCore import QObject, pyqtSignal

import ray
from gui_server_thread import GuiServerThread
from client_properties_dialog import ClientPropertiesDialog

class Client(QObject, ray.ClientData):
    status_changed = pyqtSignal(int)

    def __init__(self, session, client_id: str, protocol: int):
        QObject.__init__(self)
        ray.ClientData.gui_init(self, client_id, protocol)

        self.session = session
        self.main_win = self.session.main_win

        self._previous_status = ray.ClientStatus.STOPPED

        self.ray_hack = ray.RayHack()
        self.ray_net = ray.RayNet()
        self.status = ray.ClientStatus.STOPPED
        self.has_gui = False
        self.gui_state = False
        self.has_dirty = False
        self.dirty_state = True
        self.no_save_level = 0
        self.last_save = time.time()
        self.check_last_save = True
        print('ziejdjk', time.time())
        self.widget = self.main_win.create_client_widget(self)
        print('zoubiaa', time.time())
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

        self.widget.update_status(status)
        self.properties_dialog.update_status(status)

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

    def set_no_save_level(self, no_save_level: int):
        self.no_save_level = no_save_level
        self.widget.set_no_save_level(no_save_level)

    def set_progress(self, progress: float):
        self.widget.set_progress(progress)

    def allow_kill(self):
        self.widget.allow_kill()

    def update_properties(self, *args):
        self.update(*args)
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
        if self.protocol != ray.Protocol.RAY_HACK:
            return

        server = GuiServerThread.instance()
        if not server:
            return

        server.to_daemon('/ray/client/update_ray_hack_properties',
                        self.client_id,
                        *self.ray_hack.spread())

    def send_ray_net(self):
        if self.protocol != ray.Protocol.RAY_NET:
            return

        server = GuiServerThread.instance()
        if not server:
            return

        server.to_daemon('/ray/client/update_ray_net_properties',
                        self.client_id,
                        *self.ray_net.spread())

    def show_properties_dialog(self, second_tab=False):
        self.properties_dialog.update_contents()
        if second_tab:
            if self.protocol == ray.Protocol.RAY_HACK:
                self.properties_dialog.enable_test_zone(True)
            self.properties_dialog.set_on_second_tab()
        self.properties_dialog.show()
        if ray.get_window_manager() != ray.WindowManager.WAYLAND:
            self.properties_dialog.activateWindow()

    def re_create_widget(self):
        del self.widget
        self.widget = self.main_win.create_client_widget(self)
        self.widget.update_client_data()

        if self.has_gui:
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
    
    def can_be_own_jack_client(self, jack_client_name:str)->bool:
        if self.status in (ray.ClientStatus.STOPPED, ray.ClientStatus.PRECOPY):
            return False
        
        if jack_client_name == self.jack_client_name:
            return True

        if jack_client_name.startswith(self.jack_client_name + '/'):
            return True

        if (jack_client_name.startswith(self.jack_client_name + ' (')
                and ')' in jack_client_name):
            return True

        # Carla often puts a .0 at end of client name if it doesn't find
        # any '.' in jack_client_name
        jack_client_name = jack_client_name.partition('/')[0]

        if (not self.jack_client_name.endswith('.' + self.client_id)
                and jack_client_name == self.jack_client_name + '.0'):
            return True

        return False


class TrashedClient(ray.ClientData):
    def __init__(self):
        self.menu_action = None

    def set_menu_action(self, menu_action):
        self.menu_action = menu_action
