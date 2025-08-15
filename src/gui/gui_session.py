
# Imports from standard library
import logging
from typing import Callable, Optional

# third party imports
from qtpy.QtWidgets import QApplication
import osc_paths

# Imports from HoustonPatchbay
from patshared import GroupPos, Naming, TransportPosition, PortType

# Imports from src/shared
from osclib import OscMulTypes, OscPack
import ray
import osc_paths.ray as r
import osc_paths.ray.gui as rg
import osc_paths.ray.patchbay.monitor as rpm

# Local imports
from daemon_manager import DaemonManager
from gui_client import Client, TrashedClient
from gui_signaler import Signaler
from gui_server_thread import GuiServerThread
from gui_tools import CommandLineArgs, RS, error_text
from main_window import MainWindow
from nsm_child import NsmChild, NsmChildOutside
from ray_patchbay_manager import RayPatchbayManager


_logger = logging.getLogger(__name__)
_managed_paths = dict[str, Callable[[OscPack], None]]()

def manage(path: str, types: OscMulTypes):
    '''This decorator indicates that the decorated function manages
    the reception of the OSC path in the main thread.

    `types` are here only for convenience.
    
    The function is added to `_managed_paths` at startup,
    SessionSignaled._osc_receive execute it when a message is received.'''

    def decorated(func):
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        
        _managed_paths[path] = wrapper
        return wrapper
    return decorated


class Session:
    def __init__(self):
        self.client_list = list[Client]()
        self.trashed_clients = list[TrashedClient]()
        self.favorite_list = list[ray.Favorite]()
        self.recent_sessions = list[str]()
        self.name = ''
        self.path = ''
        self.notes = ''
        self.terminal_command = ''
        self.server_status = ray.ServerStatus.OFF

        self.is_renameable = True

        self.signaler = Signaler()
        self.patchbay_manager = RayPatchbayManager(self)

    def is_running(self) -> bool:
        return self.server_status is not ray.ServerStatus.OFF

    def update_server_status(self, server_status: ray.ServerStatus):
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

    def get_client(self, client_id: str) -> Optional[Client]:
        for client in self.client_list:
            if client.client_id == client_id:
                return client

        _logger.debug(f"gui_session does not contains client {client_id}")
        return None

    def add_favorite(self, template_name: str, icon_name: str,
                     factory: bool, display_name: str):
        server = GuiServerThread.instance()
        if server:
            server.to_daemon(r.favorites.ADD, template_name,
                             icon_name, int(factory), display_name)

    def remove_favorite(self, template_name: str, factory: bool):
        for favorite in self.favorite_list:
            if favorite.name == template_name and favorite.factory == factory:
                break

        server = GuiServerThread.instance()
        if server:
            server.to_daemon(r.favorites.REMOVE, template_name, int(factory))

    def is_favorite(self, template_name: str, factory: bool):
        for favorite in self.favorite_list:
            if favorite.name == template_name and favorite.factory == factory:
                return True
        return False


class SignaledSession(Session):
    def __init__(self):
        Session.__init__(self)
        self.signaler.osc_receive.connect(self._osc_receive)
        
        self.preview_notes = ''
        self.preview_client_list = list[ray.ClientData]()
        self.preview_started_clients = set()
        self.preview_snapshots = list[str]()
        self.preview_size = -1
        
        server = GuiServerThread.instance()
        if server is None:
            _logger.error('GuiServer not started at session init')
            return
        
        server.start()

        RS.set_signaler(self.signaler)

        self.daemon_manager = DaemonManager(self)
        if CommandLineArgs.daemon_url:
            self.daemon_manager.set_osc_address(CommandLineArgs.daemon_url)
        elif CommandLineArgs.daemon_port:
            self.daemon_manager.set_osc_address(CommandLineArgs.daemon_port)
        elif not CommandLineArgs.out_daemon:
            self.daemon_manager.set_new_osc_address()

        # build nsm_child if NSM_URL in env
        self.nsm_child = None

        if CommandLineArgs.under_nsm:
            if CommandLineArgs.out_daemon:
                self.nsm_child = NsmChildOutside(self)
                self.daemon_manager.set_external()
            else:
                self.nsm_child = NsmChild(self)

        # build and show Main UI
        self.daemon_manager.start()
        self.main_win = MainWindow(self)
        self.daemon_manager.finish_init()
        self.patchbay_manager.finish_init()
        self.main_win.show()

        # display donations dialog under breizh conditions
        if not RS.is_hidden(RS.HD_Donations):
            coreff_counter = RS.settings.value('coreff_counter', 0, type=int)
            coreff_counter += 1
            RS.settings.setValue('coreff_counter', coreff_counter)

            if coreff_counter % 44 == 29:
                self.main_win.donate(True)

        server.finish_init(self)

    def quit(self):
        self.patchbay_manager.clear_all()
        self.main_win.hide()
        del self.main_win

    def set_daemon_options(self, options: ray.Option):
        self.main_win.set_daemon_options(options)
        for client in self.client_list:
            client.widget.set_daemon_options(options)

    def _osc_receive(self, osp: OscPack):
        if osp.path in _managed_paths:
            _managed_paths[osp.path](self, osp) # type:ignore

    @manage(osc_paths.REPLY, 'ss*')
    def _reply(self, osp: OscPack):
        args: list[str] = osp.args # type:ignore
        if len(args) != 2:
            return

        if args[0] in (r.session.ADD_EXEC,
                        r.session.ADD_EXECUTABLE):
            client_id: str = args[1]

            for client in self.client_list:
                if (client.client_id == client_id
                        and client.protocol is ray.Protocol.RAY_HACK):
                    client.show_properties_dialog(second_tab=True)
                    break

    @manage(osc_paths.ERROR, 'sis')
    def _error(self, osp: OscPack):
        args: tuple[str, int, str] = osp.args # type:ignore
        err_path, err_code, err_message = args

        # don't shows a window error if error is OK
        # or related to an abort made by user
        if err_code in (ray.Err.OK, ray.Err.ABORT_ORDERED,
                        ray.Err.COPY_ABORTED):
            return

        message = error_text(err_code)
        if message:
            err_message = message

        self.main_win.error_message(err_message)

    @manage(osc_paths.MINOR_ERROR, 'sis')
    def _minor_error(self, osp: OscPack):
        args: tuple[str, int, str] = osp.args # type:ignore
        err_path, err_code, err_message = args

        # don't shows a window error if error is OK
        # or if it comes from just an unknown (and untreated) message
        if err_code in (ray.Err.OK, ray.Err.UNKNOWN_MESSAGE):
            return

        self.main_win.error_message(err_message)

    @manage(rg.server.DISANNOUNCE, '')
    def _server_disannounce(self, osp: OscPack):
        QApplication.quit()

    @manage(rg.server.NSM_LOCKED, 'i')
    def _server_nsm_locked(self, osp: OscPack):
        nsm_locked = bool(osp.args[0])
        self.main_win.set_nsm_locked(nsm_locked)

    @manage(rg.server.MESSAGE, 's')
    def _server_message(self, osp: OscPack):
        message: str = osp.args[0] # type:ignore
        self.main_win.print_message(message)

    @manage(rg.server.TERMINAL_COMMAND, 's')
    def _server_terminal_command(self, osp: OscPack):
        terminal_command: str = osp.args[0] # type:ignore
        self.terminal_command = terminal_command

        if self.main_win.preferences_dialog is not None:
            self.main_win.preferences_dialog.set_terminal_command(
                self.terminal_command)

    @manage(rg.server.OPTIONS, 'i')
    def _server_options(self, osp: OscPack):
        options_int = osp.args[0] # type:ignore
        self.set_daemon_options(ray.Option(options_int))

    @manage(rg.server.RECENT_SESSIONS, 's*')
    def _server_recent_sessions(self, osp: OscPack):
        recent_sessions: list[str] = osp.args # type:ignore
        self.recent_sessions = recent_sessions
        self.main_win.update_recent_sessions_menu()

    @manage(rg.server.AUTO_EXPORT_CUSTOM_NAMES, 'i')
    def _server_export_pretty_names(self, osp: OscPack):
        export = bool(osp.args[0]) # type:ignore
        if export:
            self.patchbay_manager.jack_export_naming = Naming.CUSTOM
        else:
            self.patchbay_manager.jack_export_naming = Naming.TRUE_NAME

        if self.patchbay_manager.options_dialog is not None:
            self.patchbay_manager.options_dialog.auto_export_pretty_names_changed(
                export)

    @manage(rg.session.NAME, 'ss')
    def _session_name(self, osp: OscPack):
        args: tuple[str, str] = osp.args # type:ignore
        sname, spath = args
        self._set_name(sname)
        self._set_path(spath)
        self.main_win.rename_session(sname, spath)

    @manage(rg.session.IS_NSM, '')
    def _session_is_nsm(self, osp: OscPack):
        self.main_win.opening_nsm_session()

    @manage(rg.session.RENAMEABLE, 'i')
    def _session_renameable(self, osp: OscPack):
        self.is_renameable = bool(osp.args[0])

        bool_set_edit = bool(
            self.is_renameable
            and self.server_status is ray.ServerStatus.READY
            and not CommandLineArgs.out_daemon)

        self.main_win.set_session_name_editable(bool_set_edit)

    @manage(rg.session.NOTES, 's')
    def _session_notes(self, osp: OscPack):
        notes: str = osp.args[0] # type:ignore
        self.notes = notes
        if self.main_win.notes_dialog is not None:
            self.main_win.notes_dialog.notes_updated()
        
    @manage(rg.session.NOTES_SHOWN, '')
    def _session_notes_shown(self, osp: OscPack):
        self.main_win.edit_notes()

    @manage(rg.session.NOTES_HIDDEN, '')
    def _session_notes_hidden(self, osp: OscPack):
        self.main_win.edit_notes(close=True)

    @manage(rg.session.SORT_CLIENTS, 's*')
    def _session_sort_clients(self, osp: OscPack):
        args: list[str] = osp.args # type:ignore
        new_client_list = list[Client]()

        for client_id in args:
            client = self.get_client(client_id)

            if not client:
                return

            new_client_list.append(client)

        if args == [c.client_id for c in self.client_list]:
            # no change between existing and new order
            return

        self.client_list.clear()
        self.main_win.re_create_list_widget()

        self.client_list = new_client_list
        for client in self.client_list:
            client.re_create_widget()
            client.widget.update_status(client.status)

    @manage(rg.client.NEW, ray.ClientData.ARG_TYPES)
    def _client_new(self, osp: OscPack):
        client = Client(self, *osp.args[:2]) # type:ignore
        client.update_properties(*osp.args)
        self.client_list.append(client)

    @manage(rg.client.UPDATE, ray.ClientData.ARG_TYPES)
    def _client_update(self, osp: OscPack):
        client_id: str = osp.args[0] # type:ignore
        client = self.get_client(client_id)
        if client:
            client.update_properties(*osp.args)

    @manage(rg.client.RAY_HACK_UPDATE, 's' + ray.RayHack.ARG_TYPES)
    def _client_ray_hack_update(self, osp: OscPack):
        client_id: str = osp.args.pop(0) # type:ignore
        client = self.get_client(client_id)
        if client and client.protocol is ray.Protocol.RAY_HACK:
            client.update_ray_hack(*osp.args)

    @manage(rg.client.RAY_NET_UPDATE, 'is' + ray.RayNet.ARG_TYPES)
    def _client_ray_net_update(self, osp: OscPack):
        client_id: str = osp.args[0] # type:ignore
        client = self.get_client(client_id)
        if client and client.is_ray_net:
            client.update_ray_net(*osp.args[1:])

    @manage(rg.client.SWITCH, 'ss')
    def _client_switch(self, osp: OscPack):
        args: tuple[str, str] = osp.args # type:ignore
        old_id, new_id = args
        for client in self.client_list:
            if client.client_id == old_id:
                client.client_id = new_id
                break

    @manage(rg.client.STATUS, 'si')
    def _client_status(self, osp: OscPack):
        args: tuple[str, int] = osp.args # type:ignore
        client_id: str = args[0]
        status = ray.ClientStatus(args[1])
        
        client = self.get_client(client_id)
        if client is None:
            return
        
        client.set_status(status)

        if client.status is ray.ClientStatus.REMOVED:
            self.main_win.remove_client(client_id)
            client.close_properties_dialog()
            self.client_list.remove(client)
            del client

        self.main_win.client_status_changed(client_id, status)

    @manage(rg.client.PROGRESS, 'sf')
    def _client_progress(self, osp: OscPack):
        args: tuple[str, float] = osp.args # type:ignore
        client_id, progress = args

        client = self.get_client(client_id)
        if client:
            client.set_progress(progress)

    @manage(rg.client.DIRTY, 'si')
    def _client_dirty(self, osp: OscPack):
        args: tuple[str, int] = osp.args # type:ignore
        client_id, int_dirty = args
        client = self.get_client(client_id)
        if client:
            client.set_dirty_state(bool(int_dirty))

    @manage(rg.client.GUI_VISIBLE, 'si')
    def _client_gui_visible(self, osp: OscPack):
        args: tuple[str, int] = osp.args # type:ignore
        client_id, int_state = args
        client = self.get_client(client_id)
        if client:
            client.set_gui_state(bool(int_state))
            
        self.patchbay_manager.optional_gui_state_changed(
            client_id, bool(int_state))

    @manage(rg.client.STILL_RUNNING, 's')
    def _client_still_running(self, osp: OscPack):
        args: tuple[str, int] = osp.args # type:ignore
        client_id = args[0]
        client = self.get_client(client_id)
        if client:
            client.allow_kill()

    @manage(rg.trash.ADD, ray.ClientData.ARG_TYPES)
    def _trash_add(self, osp: OscPack):
        trashed_client = TrashedClient(self)
        trashed_client.update(*osp.args) # type:ignore
        trash_action = self.main_win.trash_add(trashed_client)
        trashed_client.set_menu_action(trash_action)
        self.trashed_clients.append(trashed_client)

    @manage(rg.trash.RAY_HACK_UPDATE, 's' + ray.RayHack.ARG_TYPES)
    def _trash_ray_hack_update(self, osp: OscPack):
        client_id: str = osp.args[0] # type:ignore
        for trashed_client in self.trashed_clients:
            if trashed_client.client_id == client_id:
                trashed_client.ray_hack = ray.RayHack.new_from(*osp.args[1:])
                break

    @manage(rg.trash.RAY_NET_UPDATE, 's' + ray.RayNet.ARG_TYPES)
    def _trash_ray_net_update(self, osp: OscPack):
        client_id: str = osp.args[0] # type:ignore
        for trashed_client in self.trashed_clients:
            if trashed_client.client_id == client_id:
                trashed_client.ray_net = ray.RayNet.new_from(*osp.args[1:])
                break

    @manage(rg.trash.REMOVE, 's')
    def _trash_remove(self, osp: OscPack):
        client_id: str = osp.args[0] # type:ignore

        for trashed_client in self.trashed_clients:
            if trashed_client.client_id == client_id:
                break
        else:
            return

        self.trashed_clients.remove(trashed_client)
        self.main_win.trash_remove(trashed_client.menu_action) # type:ignore

    @manage(rg.trash.CLEAR, '')
    def _trash_clear(self, osp: OscPack):
        self.trashed_clients.clear()
        self.main_win.trash_clear()

    @manage(rg.favorites.ADDED, 'ssis')
    def _favorites_added(self, osp: OscPack):
        args: tuple[str, str, int, str] = osp.args # type:ignore
        template_name, icon_name, int_factory, display_name = args

        for favorite in self.favorite_list:
            if (favorite.name == template_name
                    and favorite.factory == bool(int_factory)):
                # favorite already exists, update its contents
                favorite.icon = icon_name
                favorite.display_name = display_name
                break
        else:
            self.favorite_list.append(ray.Favorite(
                template_name, icon_name, bool(int_factory), display_name))
            self.signaler.favorite_added.emit(
                template_name, icon_name, bool(int_factory), display_name)
        self.main_win.update_favorites_menu()

    @manage(rg.favorites.REMOVED, 'si')
    def _favorites_removed(self, osp: OscPack):
        args: tuple[str, int] = osp.args # type:ignore
        template_name, int_factory = args

        for favorite in self.favorite_list:
            if (favorite.name == template_name
                    and favorite.factory == bool(int_factory)):
                break
        else:
            return

        self.favorite_list.remove(favorite)
        self.signaler.favorite_removed.emit(template_name, bool(int_factory))
        self.main_win.update_favorites_menu()

    @manage(rg.preview.CLEAR, '')
    def _preview_clear(self, osp: OscPack):
        self.preview_notes = ''
        self.preview_client_list.clear()
        self.preview_started_clients.clear()
        self.preview_snapshots.clear()
        self.preview_size = -1

    @manage(rg.preview.NOTES, 's')
    def _preview_notes(self, osp: OscPack):
        preview_notes: str = osp.args[0] # type:ignore
        self.preview_notes = preview_notes
    
    @manage(rg.preview.client.UPDATE, ray.ClientData.ARG_TYPES)
    def _preview_client_update(self, osp: OscPack):
        client = ray.ClientData.new_from(*osp.args)
        for pv_client in self.preview_client_list:
            if pv_client.client_id == client.client_id:
                pv_client.update(*osp.args) # type:ignore
                break
        else:
            self.preview_client_list.append(client)

    @manage(rg.preview.client.RAY_HACK_UPDATE, 's' + ray.RayHack.ARG_TYPES)
    def _preview_client_ray_hack_update(self, osp: OscPack):
        client_id = osp.args[0] # type:ignore
        for pv_client in self.preview_client_list:
            if pv_client.client_id == client_id:
                pv_client.set_ray_hack(ray.RayHack.new_from(*osp.args[1:]))
                break
    
    @manage(rg.preview.client.RAY_NET_UPDATE, 's' + ray.RayNet.ARG_TYPES)
    def _preview_client_ray_net_update(self, osp: OscPack):
        client_id: str = osp.args[0] # type:ignore
        for pv_client in self.preview_client_list:
            if pv_client.client_id == client_id:
                pv_client.set_ray_net(ray.RayNet.new_from(*osp.args[1:]))
                break

    @manage(rg.preview.client.IS_STARTED, 'si')
    def _preview_client_is_started(self, osp: OscPack):
        args: tuple[str, int] = osp.args # type:ignore
        client_id, is_started = args

        for pv_client in self.preview_client_list:
            if pv_client.client_id == client_id:
                if is_started:
                    self.preview_started_clients.add(client_id)
                break

    @manage(rg.preview.SNAPSHOT, 's')
    def _preview_snapshot(self, osp: OscPack):
        pv_snapshot: str = osp.args[0] # type:ignore
        self.preview_snapshots.append(pv_snapshot)

    @manage(rg.preview.SESSION_SIZE, 'h')
    def _preview_session_size(self, osp: OscPack):
        pv_size: int = osp.args[0] # type:ignore
        self.preview_size = pv_size

    @manage(rg.SCRIPT_INFO, 's')
    def _script_info(self, osp: OscPack):
        text: str = osp.args[0] # type:ignore
        self.main_win.show_script_info(text)

    @manage(rg.HIDE_SCRIPT_INFO, '')
    def _hide_script_info(self, osp: OscPack):
        self.main_win.hide_script_info_dialog()

    @manage(rg.SCRIPT_USER_ACTION, 's')
    def _script_user_action(self, osp: OscPack):
        text: str = osp.args[0] # type:ignore
        self.main_win.show_script_user_action_dialog(text)

    @manage(rg.HIDE_SCRIPT_USER_ACTION, '')
    def _hide_script_user_action(self, osp: OscPack):
        self.main_win.hide_script_user_action_dialog()

    @manage(rpm.ANNOUNCE, 'iiiis')
    def _patchbay_announce(self, osp: OscPack):
        args: tuple[int, int, int, int, str] = osp.args # type:ignore
        self.patchbay_manager.patchbay_announce(*args)

    @manage(rpm.CLIENT_NAME_AND_UUID, 'sh')
    def _patchbay_client_name_and_uuid(self, osp: OscPack):
        args: tuple[str, int] = osp.args # type:ignore
        self.patchbay_manager.set_group_uuid_from_name(*args)

    @manage(rpm.PORT_ADDED, 'siih')
    def _patchbay_port_added(self, osp: OscPack):
        args: tuple[str, int, int, int] = osp.args # type:ignore
        name, port_type_int, port_flags, uuid = args
        port_type = PortType(port_type_int)
        self.patchbay_manager.add_port(
            name, port_type, port_flags, uuid)

    @manage(rpm.PORT_REMOVED, 's')
    def _patchbay_port_removed(self, osp: OscPack):
        port_name: str = osp.args[0] # type:ignore
        self.patchbay_manager.remove_port(port_name)

    @manage(rpm.PORT_RENAMED, 'ss|ssi')
    def _patchbay_port_renamed(self, osp: OscPack):
        self.patchbay_manager.rename_port(*osp.args) # type:ignore
        
    @manage(rpm.METADATA_UPDATED, 'hss')
    def _patchbay_metadata_updated(self, osp: OscPack):
        args: tuple[int, str, str] = osp.args # type:ignore
        self.patchbay_manager.metadata_update(*args)

    @manage(rpm.CONNECTION_ADDED, 'ss')
    def _patchbay_connection_added(self, osp: OscPack):
        args: tuple[str, str] = osp.args # type:ignore
        self.patchbay_manager.add_connection(*args)

    @manage(rpm.CONNECTION_REMOVED, 'ss')
    def _patchbay_connection_removed(self, osp: OscPack):
        args: tuple[str, str] = osp.args # type:ignore
        self.patchbay_manager.remove_connection(*args)

    @manage(rpm.UPDATE_GROUP_POSITION, 'i' + GroupPos.ARG_TYPES)
    def _patchbay_update_group_position(self, osp: OscPack):
        self.patchbay_manager.update_group_position(*osp.args)

    @manage(rpm.UPDATE_PORTGROUP, 'siiiss*')
    def _patchbay_update_portgroup(self, osp: OscPack):
        self.patchbay_manager.update_portgroup(*osp.args)

    @manage(rpm.VIEWS_CHANGED, 's')
    def _patchbay_views_changed(self, osp: OscPack):
        json_dict: str = osp.args[0] # type:ignore
        self.patchbay_manager.views_changed(json_dict)

    @manage(rpm.UPDATE_GROUP_CUSTOM_NAME, 'ss')
    def _patchbay_update_group_custom_name(self, osp: OscPack):
        args: tuple[str, str] = osp.args # type:ignore
        self.patchbay_manager.update_group_pretty_name(*args)

    @manage(rpm.UPDATE_PORT_CUSTOM_NAME, 'ss')
    def _patchbay_update_port_custom_name(self, osp: OscPack):
        args: tuple[str, str] = osp.args # type:ignore
        self.patchbay_manager.update_port_pretty_name(*args)

    @manage(rpm.SERVER_STARTED, '')
    def _patchbay_server_started(self, osp: OscPack):
        self.patchbay_manager.server_started()

    @manage(rpm.SERVER_STOPPED, '')
    def _patchbay_server_stopped(self, osp: OscPack):
        self.patchbay_manager.server_stopped()

    @manage(rpm.SERVER_LOSE, '')
    def _patchbay_server_lose(self, osp: OscPack):
        self.patchbay_manager.server_lose()

    @manage(rpm.DSP_LOAD, 'i')
    def _patchbay_dsp_load(self, osp: OscPack):
        dsp_load: int = osp.args[0] # type:ignore
        self.patchbay_manager.set_dsp_load(dsp_load)

    @manage(rpm.ADD_XRUN, '')
    def _patchbay_add_xrun(self, osp: OscPack):
        self.patchbay_manager.add_xrun()

    @manage(rpm.BUFFER_SIZE, 'i')
    def _patchbay_buffer_size(self, osp: OscPack):
        buffer_size: int = osp.args[0] # type:ignore
        self.patchbay_manager.buffer_size_changed(buffer_size)

    @manage(rpm.SAMPLE_RATE, 'i')
    def _patchbay_sample_rate(self, osp: OscPack):
        samplerate: int = osp.args[0] # type:ignore
        self.patchbay_manager.sample_rate_changed(samplerate)

    @manage(rpm.TRANSPORT_POSITION, 'iiiiiif')
    def _patchbay_transport_position(self, osp: OscPack):
        args: tuple[int, int, int, int, int, int, float] = \
            osp.args # type:ignore
        self.patchbay_manager.refresh_transport(TransportPosition(
            args[0], bool(args[1]), bool(args[2]), *args[3:]))

    @manage(rpm.BIG_PACKETS, 'i')
    def _patchbay_big_packets(self, osp: OscPack):
        state: int = osp.args[0] # type:ignore
        self.patchbay_manager.receive_big_packets(state)
        
    @manage(rpm.PRETTY_NAMES_LOCKED, 'i')
    def _patchbay_pretty_names_locked(self, osp: OscPack):
        self.patchbay_manager.pretty_names_locked(osp.args[0]) # type:ignore