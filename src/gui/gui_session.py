
import sys

from PyQt5.QtWidgets import QApplication

import ray

from patchcanvas import patchcanvas
from daemon_manager import DaemonManager
from gui_client import Client, TrashedClient
from gui_signaler import Signaler
from gui_server_thread import GuiServerThread
from gui_tools import CommandLineArgs, RS
from main_window import MainWindow
from nsm_child import NSMChild, NSMChildOutside
from patchbay_manager import PatchbayManager


class Session:
    def __init__(self):
        self.client_list = []
        self.trashed_clients = []
        self.favorite_list = []
        self.name = ''
        self.path = ''
        self.notes = ''
        self.server_status = ray.ServerStatus.OFF

        self.is_renameable = True

        self.signaler = Signaler()
        self.patchbay_manager = PatchbayManager(self)

        server = GuiServerThread.instance()
        server.start()

        self.daemon_manager = DaemonManager(self)
        if CommandLineArgs.daemon_url:
            self.daemon_manager.set_osc_address(CommandLineArgs.daemon_url)
        elif CommandLineArgs.daemon_port:
            self.daemon_manager.set_osc_address(CommandLineArgs.daemon_port)
        elif not CommandLineArgs.out_daemon:
            self.daemon_manager.set_new_osc_address()

        # build nsm_child if NSM_URL in env
        self._nsm_child = None

        if CommandLineArgs.under_nsm:
            if CommandLineArgs.out_daemon:
                self._nsm_child = NSMChildOutside(self)
                self.daemon_manager.set_external()
            else:
                self._nsm_child = NSMChild(self)

        # build and show Main UI
        self.main_win = MainWindow(self)
        self.daemon_manager.finish_init()
        self.patchbay_manager.finish_init()
        server.finish_init(self)

        self.main_win.show()

        # display donations dialog under conditions
        if not RS.is_hidden(RS.HD_Donations):
            coreff_counter = RS.settings.value('coreff_counter', 0, type=int)
            coreff_counter += 1
            RS.settings.setValue('coreff_counter', coreff_counter)

            if coreff_counter % 44 == 29:
                self.main_win.donate(True)

    def quit(self):
        self.patchbay_manager.clear_all()
        self.main_win.hide()
        del self.main_win

    def is_running(self)->bool:
        return bool(self.server_status != ray.ServerStatus.OFF)

    def update_server_status(self, server_status: int):
        self.server_status = server_status

    def _set_name(self, session_name: str):
        self.name = session_name

    def _set_path(self, session_path: str):
        self.path = session_path

    def get_short_path(self):
        if self.path.startswith(CommandLineArgs.session_root):
            return self.path.replace(
                '%s/' % CommandLineArgs.session_root, '', 1)

        return self.path

    def get_client(self, client_id: str)->Client:
        for client in self.client_list:
            if client.client_id == client_id:
                return client

        if CommandLineArgs.debug:
            sys.stderr.write("gui_session does not contains client %s\n"
                             % client_id)
        return None

    def add_favorite(self, template_name: str, icon_name: str, factory: bool):
        server = GuiServerThread.instance()
        if server:
            server.to_daemon('/ray/favorites/add', template_name,
                            icon_name, int(factory))

    def remove_favorite(self, template_name: str, factory: bool):
        for favorite in self.favorite_list:
            if favorite.name == template_name and favorite.factory == factory:
                break

        server = GuiServerThread.instance()
        if server:
            server.to_daemon('/ray/favorites/remove', template_name, int(factory))

    def is_favorite(self, template_name: str, factory: bool):
        for favorite in self.favorite_list:
            if favorite.name == template_name and favorite.factory == factory:
                return True
        return False

    def set_daemon_options(self, options):
        self.main_win.setDaemonOptions(options)
        for client in self.client_list:
            client.widget.setDaemonOptions(options)

class SignaledSession(Session):
    def __init__(self):
        Session.__init__(self)
        self.signaler.osc_receive.connect(self._osc_receive)
        self.daemon_manager.start()

        self.canvas_groups = []
        self.canvas_ports = []
        self.next_canvas_port_id = -1

    def _osc_receive(self, path, args):
        func_path = path
        func_name = func_path.replace('/', '_')

        if func_name in self.__dir__():
            function = self.__getattribute__(func_name)
            function(path, args)

    def _reply(self, path, args):
        if len(args) == 2:
            if args[0] == '/ray/session/add_executable':
                client_id = args[1]

                for client in self.client_list:
                    if (client.client_id == client_id
                            and client.protocol == ray.Protocol.RAY_HACK):
                        client.show_properties_dialog(second_tab=True)
                        break


    def _error(self, path, args):
        err_path, err_code, err_message = args

        # don't shows a window error if error is OK
        # or related to an abort made by user
        if err_code in (ray.Err.OK, ray.Err.ABORT_ORDERED,
                        ray.Err.COPY_ABORTED):
            return

        self.main_win.errorMessage(err_message)

    def _minor_error(self, path, args):
        err_path, err_code, err_message = args

        # don't shows a window error if error is OK
        # or if it comes from just an unknown (and untreated) message
        if err_code in (ray.Err.OK, ray.Err.UNKNOWN_MESSAGE):
            return

        self.main_win.errorMessage(err_message)


    def _ray_gui_server_disannounce(self, path, args):
        QApplication.quit()

    def _ray_gui_server_nsm_locked(self, path, args):
        nsm_locked = bool(args[0])
        self.main_win.setNsmLocked(nsm_locked)

    def _ray_gui_server_message(self, path, args):
        message = args[0]
        self.main_win.printMessage(message)

    def _ray_gui_server_options(self, path, args):
        options = args[0]
        self.set_daemon_options(options)

    def _ray_gui_session_name(self, path, args):
        sname, spath = args
        self._set_name(sname)
        self._set_path(spath)
        self.main_win.renameSession(sname, spath)

    def _ray_gui_session_is_nsm(self, path, args):
        self.main_win.openingNsmSession()

    def _ray_gui_session_renameable(self, path, args):
        self.is_renameable = bool(args[0])

        bool_set_edit = bool(self.is_renameable
                             and self.server_status == ray.ServerStatus.READY
                             and not CommandLineArgs.out_daemon)

        self.main_win.setSessionNameEditable(bool_set_edit)

    def _ray_gui_session_notes(self, path, args):
        self.notes = args[0]
        if self.main_win.notes_dialog is not None:
            self.main_win.notes_dialog.notesUpdated()

    def _ray_gui_session_notes_shown(self, path, args):
        self.main_win.editNotes()

    def _ray_gui_session_notes_hidden(self, path, args):
        self.main_win.editNotes(close=True)

    def _ray_gui_session_sort_clients(self, path, args):
        new_client_list = []
        for client_id in args:
            client = self.get_client(client_id)

            if not client:
                return

            new_client_list.append(client)

        if args == [c.client_id for c in self.client_list]:
            # no change between existing and new order
            return

        self.client_list.clear()
        self.main_win.reCreateListWidget()

        self.client_list = new_client_list
        for client in self.client_list:
            client.re_create_widget()
            client.widget.updateStatus(client.status)

    def _ray_gui_client_new(self, path, args):
        client = Client(self, *args[:2])
        client.update_properties(*args)
        self.client_list.append(client)

    def _ray_gui_client_update(self, path, args):
        client_id = args[0]
        client = self.get_client(client_id)
        if client:
            client.update_properties(*args)

    def _ray_gui_client_ray_hack_update(self, path, args):
        client_id = args.pop(0)
        client = self.get_client(client_id)
        if client and client.protocol == ray.Protocol.RAY_HACK:
            client.update_ray_hack(*args)

    def _ray_gui_client_ray_net_update(self, path, args):
        client_id = args.pop(0)
        client = self.get_client(client_id)
        if client and client.protocol == ray.Protocol.RAY_NET:
            client.update_ray_net(*args)

    def  _ray_gui_client_switch(self, path, args):
        old_id, new_id = args
        for client in self.client_list:
            if client.client_id == old_id:
                client.client_id = new_id
                break

    def _ray_gui_client_status(self, path, args):
        client_id, status = args
        client = self.get_client(client_id)
        if client:
            client.set_status(status)

            if status == ray.ClientStatus.REMOVED:
                self.main_win.removeClient(client_id)
                client.properties_dialog.close()
                self.client_list.remove(client)
                del client

        self.main_win.clientStatusChanged(client_id, status)

    def _ray_gui_client_progress(self, path, args):
        client_id, progress = args

        client = self.get_client(client_id)
        if client:
            client.set_progress(progress)

    def _ray_gui_client_dirty(self, path, args):
        client_id, int_dirty = args
        client = self.get_client(client_id)
        if client:
            client.set_dirty_state(bool(int_dirty))

    def _ray_gui_client_has_optional_gui(self, path, args):
        client_id = args[0]
        client = self.get_client(client_id)

        if client:
            client.set_gui_enabled()

    def _ray_gui_client_gui_visible(self, path, args):
        client_id, int_state = args
        client = self.get_client(client_id)
        if client:
            client.set_gui_state(bool(int_state))

    def _ray_gui_client_still_running(self, path, args):
        client_id = args[0]
        client = self.get_client(client_id)
        if client:
            client.allow_kill()

    def _ray_gui_client_no_save_level(self, path, args):
        client_id, no_save_level = args

        client = self.get_client(client_id)
        if client:
            client.set_no_save_level(no_save_level)

    def _ray_gui_trash_add(self, path, args):
        trashed_client = TrashedClient()
        trashed_client.update(*args)
        trash_action = self.main_win.trashAdd(trashed_client)
        trashed_client.set_menu_action(trash_action)
        self.trashed_clients.append(trashed_client)

    def _ray_gui_trash_ray_hack_update(self, path, args):
        client_id = args.pop(0)
        for trashed_client in self.trashed_clients:
            if trashed_client.client_id == client_id:
                trashed_client.ray_hack = ray.RayHack.newFrom(*args)
                break

    def _ray_gui_trash_ray_net_update(self, path, args):
        client_id = args.pop(0)
        for trashed_client in self.trashed_clients:
            if trashed_client.client_id == client_id:
                trashed_client.ray_net = ray.RayNet.newFrom(*args)
                break

    def _ray_gui_trash_remove(self, path, args):
        client_id = args[0]

        for trashed_client in self.trashed_clients:
            if trashed_client.client_id == client_id:
                break
        else:
            return

        self.trashed_clients.remove(trashed_client)
        self.main_win.trashRemove(trashed_client.menu_action)

    def _ray_gui_trash_clear(self, path, args):
        self.trashed_clients.clear()
        self.main_win.trashClear()

    def _ray_gui_favorites_added(self, path, args):
        template_name, icon_name, int_factory = args

        for favorite in self.favorite_list:
            if (favorite.name == template_name
                    and favorite.factory == bool(int_factory)):
                # favorite already exists, update the icon
                favorite.icon = icon_name
                break
        else:
            fav = ray.Favorite(template_name, icon_name, bool(int_factory))
            self.favorite_list.append(fav)
            self.signaler.favorite_added.emit(
                template_name, icon_name, bool(int_factory))
        self.main_win.updateFavoritesMenu()

    def _ray_gui_favorites_removed(self, path, args):
        template_name, int_factory = args

        for favorite in self.favorite_list:
            if (favorite.name == template_name
                    and favorite.factory == bool(int_factory)):
                break
        else:
            return

        self.favorite_list.remove(favorite)
        self.signaler.favorite_removed.emit(template_name, bool(int_factory))
        self.main_win.updateFavoritesMenu()

    def _ray_gui_script_info(self, path, args):
        text = args[0]
        self.main_win.showScriptInfo(text)

    def _ray_gui_hide_script_info(self, path, args):
        self.main_win.hideScriptInfoDialog()

    def _ray_gui_script_user_action(self, path, args):
        text = args[0]
        self.main_win.showScriptUserActionDialog(text)

    def _ray_gui_hide_script_user_action(self, path, args):
        self.main_win.hideScriptUserActionDialog()

    def _ray_gui_patchbay_announce(self, path, args):
        self.patchbay_manager.patchbay_announce(*args)

    def _ray_gui_patchbay_client_name_and_uuid(self, path, args):
        self.patchbay_manager.client_name_and_uuid(*args)

    def _ray_gui_patchbay_port_added(self, path, args):
        self.patchbay_manager.add_port(*args)

    def _ray_gui_patchbay_port_removed(self, path, args):
        self.patchbay_manager.remove_port(*args)

    def _ray_gui_patchbay_port_renamed(self, path, args):
        self.patchbay_manager.rename_port(*args)

    def _ray_gui_patchbay_metadata_updated(self, path, args):
        self.patchbay_manager.metadata_update(*args)

    def _ray_gui_patchbay_connection_added(self, path, args):
        self.patchbay_manager.add_connection(*args)

    def _ray_gui_patchbay_connection_removed(self, path, args):
        self.patchbay_manager.remove_connection(*args)

    def _ray_gui_patchbay_update_group_position(self, path, args):
        self.patchbay_manager.update_group_position(*args)

    def _ray_gui_patchbay_update_portgroup(self, path, args):
        self.patchbay_manager.update_portgroup(*args)

    def _ray_gui_patchbay_server_started(self, path, args):
        self.patchbay_manager.server_started(*args)

    def _ray_gui_patchbay_server_stopped(self, path, args):
        self.patchbay_manager.server_stopped(*args)

    def _ray_gui_patchbay_server_lose(self, path, args):
        self.patchbay_manager.server_lose(*args)

    def _ray_gui_patchbay_dsp_load(self, path, args):
        self.patchbay_manager.set_dsp_load(*args)

    def _ray_gui_patchbay_add_xrun(self, path, args):
        self.patchbay_manager.add_xrun(*args)

    def _ray_gui_patchbay_buffer_size(self, path, args):
        self.patchbay_manager.buffer_size_changed(*args)

    def _ray_gui_patchbay_sample_rate(self, path, args):
        self.patchbay_manager.sample_rate_changed(*args)

    def _ray_gui_patchbay_big_packets(self, path, args):
        self.patchbay_manager.receive_big_packets(*args)

    def _ray_gui_patchbay_fast_temp_file_memory(self, path, args):
        self.patchbay_manager.fast_temp_file_memory(*args)

    def _ray_gui_patchbay_fast_temp_file_running(self, path, args):
        self.patchbay_manager.fast_temp_file_running(*args)
