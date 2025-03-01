
# Imports from standard library
import os
from typing import TYPE_CHECKING, Optional
import logging

from patshared import GroupPos

# Imports from src/shared
from osclib import BunServerThread, make_method, Address
import ray
import osc_paths as p
import osc_paths.ray as R
import osc_paths.ray.gui as RG
import osc_paths.ray.gui.patchbay as RGP

# Local imports
from gui_tools import CommandLineArgs

if TYPE_CHECKING:
    from gui_session import SignaledSession


_logger = logging.getLogger(__name__)
_instance = None


def ray_method(path, types):
    def decorated(func):
        @make_method(path, types)
        def wrapper(*args, **kwargs):
            t_thread, t_path, t_args, t_types, src_addr, rest = args
            if TYPE_CHECKING:
                assert isinstance(t_thread, GuiServerThread)

            _logger.debug(
                '\033[93mOSC::gui_receives\033[0m '
                f'{t_path}, {t_types}, {t_args}, {src_addr.url}')

            if t_thread.stopping:
                return

            response = func(*args[:-1], **kwargs)

            if not response is False:
                t_thread.signaler.osc_receive.emit(t_path, t_args)

            return response
        return wrapper
    return decorated


class GuiServerThread(BunServerThread):
    def __init__(self):
        BunServerThread.__init__(self)

        global _instance
        _instance = self

        # Try to prevent impossibility to stop server
        # while receiving messages
        self.stopping = False
        
        self._parrallel_copy_id_queue = []
        self._parrallel_new_session_name = ''

    def stop(self):
        self.stopping = True
        super().stop()

    def finish_init(self, session: 'SignaledSession'):
        self.session = session
        self.signaler = self.session.signaler
        self.daemon_manager = self.session.daemon_manager
        self.patchbay_addr: Optional[Address] = None

        # all theses OSC messages are directly treated by
        # SignaledSession in gui_session.py
        # in the function with the the name of the message
        # with '/' replaced with '_'
        # for example /ray/gui/session/name goes to
        # _ray_gui_session_name

        for path_types in (
            (p.ERROR, 'sis'),
            (p.MINOR_ERROR, 'sis'),
            (RG.server.DISANNOUNCE, ''),
            (RG.server.NSM_LOCKED, 'i'),
            (RG.server.OPTIONS, 'i'),
            (RG.server.MESSAGE, 's'),
            (RG.server.TERMINAL_COMMAND, 's'),
            (RG.session.NAME, 'ss'),
            (RG.session.NOTES, 's'),
            (RG.session.NOTES_SHOWN, ''),
            (RG.session.NOTES_HIDDEN, ''),
            (RG.session.IS_NSM, ''),
            (RG.session.RENAMEABLE, 'i'),
            (RG.client.NEW, ray.ClientData.sisi()),
            (RG.client.UPDATE, ray.ClientData.sisi()),
            (RG.client.RAY_HACK_UPDATE, 's' + ray.RayHack.sisi()),
            (RG.client.SWITCH, 'ss'),
            (RG.client.STATUS, 'si'),
            (RG.client.DIRTY, 'si'),
            (RG.client.HAS_OPTIONAL_GUI, 's'),
            (RG.client.GUI_VISIBLE, 'si'),
            (RG.client.STILL_RUNNING, 's'),
            (RG.trash.ADD, ray.ClientData.sisi()),
            (RG.trash.RAY_HACK_UPDATE, 's' + ray.RayHack.sisi()),
            (RG.trash.RAY_NET_UPDATE, 's' + ray.RayNet.sisi()),
            (RG.trash.REMOVE, 's'),
            (RG.trash.CLEAR, ''),
            (RG.favorites.ADDED, 'ssis'),
            (RG.favorites.REMOVED, 'si'),
            (RG.SCRIPT_INFO, 's'),
            (RG.HIDE_SCRIPT_INFO, ''),
            (RG.SCRIPT_USER_ACTION, 's'),
            (RG.HIDE_SCRIPT_USER_ACTION, ''),
            
            # patchbay related paths
            (RGP.PORT_ADDED, 'siih'),
            (RGP.PORT_RENAMED, 'ss'),
            (RGP.PORT_RENAMED, 'ssi'),
            (RGP.PORT_REMOVED, 's'),
            (RGP.CONNECTION_ADDED, 'ss'),
            (RGP.CONNECTION_REMOVED, 'ss'),
            (RGP.SERVER_STOPPED, ''),
            (RGP.METADATA_UPDATED, 'hss'),
            (RGP.DSP_LOAD, 'i'),
            (RGP.ADD_XRUN, ''),
            (RGP.BUFFER_SIZE, 'i'),
            (RGP.SAMPLE_RATE, 'i'),
            (RGP.SERVER_STARTED, ''),
            (RGP.BIG_PACKETS, 'i'),
            (RGP.SERVER_LOSE, ''),
            (RGP.FAST_TEMP_FILE_MEMORY, 's'),
            (RGP.CLIENT_NAME_AND_UUID, 'sh'),
            (RGP.TRANSPORT_POSITION, 'iiiiiif'),
            (RGP.UPDATE_GROUP_POSITION, 'i' + GroupPos.args_types()),
            (RGP.VIEWS_CHANGED, 's'),
            (RGP.UPDATE_GROUP_PRETTY_NAME, 'ss'),
            (RGP.UPDATE_PORT_PRETTY_NAME, 'ss'),
            
            # previews
            (RG.preview.CLEAR, ''),
            (RG.preview.NOTES, 's'),
            (RG.preview.client.UPDATE, ray.ClientData.sisi()),
            (RG.preview.client.RAY_HACK_UPDATE, 's' + ray.RayHack.sisi()),
            (RG.preview.client.RAY_NET_UPDATE, 's' + ray.RayNet.sisi()),
            (RG.preview.client.IS_STARTED, 'si'),
            (RG.preview.SNAPSHOT, 's'),
            (RG.preview.SESSION_SIZE, 'h')):
                self.add_method(path_types[0], path_types[1],
                                self._generic_callback)

    @staticmethod
    def instance():
        return _instance

    def _generic_callback(self, path, args, types, src_addr):
        if self.stopping:
            return

        _logger.debug(
            '\033[93mOSC::gui_receives\033[0m '
            f'({path}, {args}, {types})')

        self.signaler.osc_receive.emit(path, args)

    @ray_method(p.REPLY, None)
    def _reply(self, path, args: list, types: str, src_addr):
        if not (types and ray.types_are_all_strings(types)):
            return False

        new_args = args.copy()
        reply_path = new_args.pop(0)

        if reply_path == R.server.LIST_SESSIONS:
            self.signaler.add_sessions_to_list.emit(new_args)
        elif reply_path == R.server.LIST_PATH:
            self.signaler.new_executable.emit(new_args)
        elif reply_path == R.server.LIST_SESSION_TEMPLATES:
            self.signaler.session_template_found.emit(new_args)
        elif reply_path == R.server.LIST_USER_CLIENT_TEMPLATES:
            self.signaler.user_client_template_found.emit(new_args)
        elif reply_path == R.server.LIST_FACTORY_CLIENT_TEMPLATES:
            self.signaler.factory_client_template_found.emit(new_args)
        elif reply_path in (R.session.LIST_SNAPSHOTS,
                            R.client.LIST_SNAPSHOTS):
            self.signaler.snapshots_found.emit(new_args)
        elif reply_path == R.server.RENAME_SESSION:
            self.signaler.other_session_renamed.emit()
        elif reply_path == R.session.DUPLICATE_ONLY:
            self.signaler.other_session_duplicated.emit()
        elif reply_path == R.server.SAVE_SESSION_TEMPLATE:
            self.signaler.other_session_templated.emit()
        elif reply_path == R.server.ABORT_PARRALLEL_COPY:
            self.signaler.parrallel_copy_aborted.emit()

    @ray_method(RG.server.ANNOUNCE, 'siisis')
    def _server_announce(self, path, args, types, src_addr):
        if self.daemon_manager.is_announced():
            return

        (version, server_status_int, options,
         session_root, is_net_free, tcp_url) = args

        if (self.session is not None
                and self.session.main_win is not None
                and self.session.main_win.waiting_for_patchbay):
            self.send(src_addr, R.server.ASK_FOR_PATCHBAY, '')
            self.session.main_win.waiting_for_patchbay = False

        self.signaler.daemon_announce.emit(
            src_addr, version, ray.ServerStatus(server_status_int),
            ray.Option(options), session_root, is_net_free)

    @ray_method(RG.server.ROOT, 's')
    def _server_root(self, path, args, types, src_addr):
        session_root = args[0]
        CommandLineArgs.change_session_root(session_root)
        self.signaler.root_changed.emit(session_root)

    @ray_method(RG.server.STATUS, 'i')
    def _server_status(self, path, args, types, src_addr):
        self.signaler.server_status_changed.emit(ray.ServerStatus(args[0]))

    @ray_method(RG.server.COPYING, 'i')
    def _server_copying(self, path, args, types, src_addr):
        copying = args[0]
        self.signaler.server_copying.emit(bool(copying))

    @ray_method(RG.server.PARRALLEL_COPY_STATE, 'ii')
    def _server_parrallel_copy_state(self, path, args, types, src_addr):
        session_id, state = args

        if state:
            # copy is starting
            if self._parrallel_copy_id_queue:
                if session_id not in self._parrallel_copy_id_queue:
                    self._parrallel_copy_id_queue.append(session_id)
            else:
                self._parrallel_copy_id_queue.append(session_id)
                self.signaler.parrallel_copy_state.emit(*args)
        else:
            # copy is finished
            if session_id in self._parrallel_copy_id_queue:
                self._parrallel_copy_id_queue.remove(session_id)
                self.signaler.parrallel_copy_state.emit(*args)

    @ray_method(RG.server.PARRALLEL_COPY_PROGRESS, 'if')
    def _server_copy_progress(self, path, args, types, src_addr):
        session_id, progress = args

        if not self._parrallel_copy_id_queue:
            return
        
        if session_id == self._parrallel_copy_id_queue[0]:
            self.signaler.parrallel_copy_progress.emit(*args)

    @ray_method(RG.server.PROGRESS, 'f')
    def _server_progress(self, path, args, types, src_addr):
        progress = args[0]
        self.signaler.server_progress.emit(progress)

    @ray_method(RG.server.RECENT_SESSIONS, None)
    def _server_recent_sessions(self, path, args, types, src_addr):
        for t in types:
            if t != 's':
                return False

    @ray_method(RG.session.AUTO_SNAPSHOT, 'i')
    def _session_auto_snapshot(self, path, args, types, src_addr):
        self.signaler.reply_auto_snapshot.emit(bool(args[0]))

    @ray_method(RG.session.SORT_CLIENTS, None)
    def _session_sort_clients(self, path, args, types, src_addr):
        if not ray.types_are_all_strings(types):
            return False

    @ray_method(RG.listed_session.DETAILS, 'sihi')
    def _listed_session_details(self, path, args, types, src_addr):
        self.signaler.session_details.emit(*args)

    @ray_method(RG.listed_session.SCRIPTED_DIR, 'si')
    def _listed_session_scripted_dir(self, path, args, types, src_addr):
        self.signaler.scripted_dir.emit(*args)

    @ray_method(RG.CLIENT_TEMPLATE_UPDATE, 'iss' + ray.ClientData.sisi())
    def _client_template_update(self, path, args, types, src_addr):
        self.signaler.client_template_update.emit(args)

    @ray_method(RG.CLIENT_TEMPLATE_RAY_HACK_UPDATE, 'is' + ray.RayHack.sisi())
    def _client_template_ray_hack_update(self, path, args, types, src_addr):
        self.signaler.client_template_ray_hack_update.emit(args)

    @ray_method(RG.CLIENT_TEMPLATE_RAY_NET_UPDATE, 'is' + ray.RayNet.sisi())
    def _client_template_ray_net_update(self, path, args, types, src_addr):
        self.signaler.client_template_ray_net_update.emit(args)

    @ray_method(RG.client.PROGRESS, 'sf')
    def _client_progress(self, path, args, types, src_addr):
        self.signaler.client_progress.emit(*args)
        return True

    @ray_method(RGP.ANNOUNCE, 'iiis')
    def _ray_gui_patchbay_announce(self, path, args, types, src_addr):
        self.patchbay_addr = Address(args[3])
    
    @ray_method(RGP.UPDATE_PORTGROUP, None)
    def _ray_gui_patchbay_update_portgroup(
            self, path, args, types: str, src_addr: Address):
        if not types.startswith('siiis'):
            return False

        types_end = types.replace('siiis', '', 1)
        for c in types_end:
            if c != 's':
                return False
    
    @ray_method(RG.preview.STATE, 'i')
    def _ray_gui_preview_state(self, path, args, types, src_addr):
        self.signaler.session_preview_update.emit(args[0])

    def send(self, *args):
        _logger.debug(f'\033[95mOSC::gui sends\033[0m {args[1:]}')
        super().send(*args)

    def to_daemon(self, *args):
        self.send(self.daemon_manager.address, *args)

    def send_patchbay_daemon(self, *args):
        if self.patchbay_addr is None:
            return
        
        self.send(self.patchbay_addr, *args)
        
        # try:
        #     self.send(self.patchbay_addr, *args)
        # except OSError:
        #     _logger.warning(
        #         'Failed to send message to patchbay daemon '
        #         f'{self.patchbay_addr.url}')
        #     self.patchbay_addr = None
        # except BaseException as e:
        #     _logger.error(str(e))

    def announce(self):
        _logger.debug('raysession_sends announce')
        self.send(self.daemon_manager.address, R.server.GUI_ANNOUNCE,
                  ray.VERSION, int(CommandLineArgs.under_nsm),
                  os.getenv('NSM_URL', ''), os.getpid(),
                  CommandLineArgs.net_daemon_id, '')

    def disannounce(self, src_addr):
        self.send(src_addr, R.server.GUI_DISANNOUNCE)

    def open_session(self, session_name, save_previous=1, session_template=''):
        self.to_daemon(R.server.OPEN_SESSION, session_name,
                      save_previous, session_template)

    def save_session(self):
        self.to_daemon(R.session.SAVE)

    def close_session(self):
        self.to_daemon(R.session.CLOSE)

    def abort_session(self):
        self.to_daemon(R.session.ABORT)

    def duplicate_a_session(self, session_name:str, new_session_name:str):
        self._parrallel_new_session_name = new_session_name
        self.to_daemon(RG.session.DUPLICATE_ONLY,
                       session_name, new_session_name,
                       CommandLineArgs.session_root)

    def get_parrallel_copy_id(self) -> int:
        ''' used by open session dialog to know
        if a parrallel copy is running '''
        if not self._parrallel_copy_id_queue:
            return 0

        return self._parrallel_copy_id_queue[0]

    def get_parrallel_new_session_name(self)->str:
        return self._parrallel_new_session_name

