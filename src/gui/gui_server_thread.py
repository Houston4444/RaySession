
# Imports from standard library
import os
from typing import TYPE_CHECKING, Optional, Callable
import logging

from patshared import GroupPos

# Imports from src/shared
from osclib import BunServerThread, OscMulTypes, OscPack, Address
import ray
import osc_paths
import osc_paths.ray as r
import osc_paths.ray.gui as rg

# Local imports
from gui_tools import CommandLineArgs

if TYPE_CHECKING:
    from gui_session import SignaledSession


_logger = logging.getLogger(__name__)
_instance = None

_validators = dict[str, Callable]()
_validators_types = dict[str, OscMulTypes]()

METHODS_DICT = {
    osc_paths.ERROR: 'sis',
    osc_paths.MINOR_ERROR: 'sis',
    rg.server.DISANNOUNCE: '',
    rg.server.NSM_LOCKED: 'i',
    rg.server.OPTIONS: 'i',
    rg.server.MESSAGE: 's',
    rg.server.TERMINAL_COMMAND: 's',
    rg.server.RECENT_SESSIONS: 's*',
    rg.session.NAME: 'ss',
    rg.session.NOTES: 's',
    rg.session.NOTES_SHOWN: '',
    rg.session.NOTES_HIDDEN: '',
    rg.session.IS_NSM: '',
    rg.session.RENAMEABLE: 'i',
    rg.session.SORT_CLIENTS: 's*',
    rg.client.NEW: ray.ClientData.ARG_TYPES,
    rg.client.UPDATE: ray.ClientData.ARG_TYPES,
    rg.client.RAY_HACK_UPDATE: 's' + ray.RayHack.ARG_TYPES,
    rg.client.SWITCH: 'ss',
    rg.client.STATUS: 'si',
    rg.client.DIRTY: 'si',
    rg.client.HAS_OPTIONAL_GUI: 's',
    rg.client.GUI_VISIBLE: 'si',
    rg.client.STILL_RUNNING: 's',
    rg.trash.ADD: ray.ClientData.ARG_TYPES,
    rg.trash.RAY_HACK_UPDATE: 's' + ray.RayHack.ARG_TYPES,
    rg.trash.RAY_NET_UPDATE: 's' + ray.RayNet.ARG_TYPES,
    rg.trash.REMOVE: 's',
    rg.trash.CLEAR: '',
    rg.favorites.ADDED: 'ssis',
    rg.favorites.REMOVED: 'si',
    rg.SCRIPT_INFO: 's',
    rg.HIDE_SCRIPT_INFO: '',
    rg.SCRIPT_USER_ACTION: 's',
    rg.HIDE_SCRIPT_USER_ACTION: '',
    rg.patchbay.PORT_ADDED: 'siih',
    rg.patchbay.PORT_RENAMED: 'ss|ssi',
    rg.patchbay.PORT_REMOVED: 's',
    rg.patchbay.CONNECTION_ADDED: 'ss',
    rg.patchbay.CONNECTION_REMOVED: 'ss',
    rg.patchbay.SERVER_STOPPED: '',
    rg.patchbay.METADATA_UPDATED: 'hss',
    rg.patchbay.DSP_LOAD: 'i',
    rg.patchbay.ADD_XRUN: '',
    rg.patchbay.BUFFER_SIZE: 'i',
    rg.patchbay.SAMPLE_RATE: 'i',
    rg.patchbay.SERVER_STARTED: '',
    rg.patchbay.BIG_PACKETS: 'i',
    rg.patchbay.SERVER_LOSE: '',
    rg.patchbay.FAST_TEMP_FILE_MEMORY: 's',
    rg.patchbay.CLIENT_NAME_AND_UUID: 'sh',
    rg.patchbay.TRANSPORT_POSITION: 'iiiiiif',
    rg.patchbay.UPDATE_GROUP_POSITION: 'i' + GroupPos.ARG_TYPES,
    rg.patchbay.VIEWS_CHANGED: 's',
    rg.patchbay.UPDATE_PORTGROUP: 'siiiss*',
    rg.patchbay.UPDATE_GROUP_PRETTY_NAME: 'ss',
    rg.patchbay.UPDATE_PORT_PRETTY_NAME: 'ss',
    rg.preview.CLEAR: '',
    rg.preview.NOTES: 's',
    rg.preview.client.UPDATE: ray.ClientData.ARG_TYPES,
    rg.preview.client.RAY_HACK_UPDATE: 's' + ray.RayHack.ARG_TYPES,
    rg.preview.client.RAY_NET_UPDATE: 's' + ray.RayNet.ARG_TYPES,
    rg.preview.client.IS_STARTED: 'si',
    rg.preview.SNAPSHOT: 's',
    rg.preview.SESSION_SIZE: 'h',
}
'''all theses OSC messages are directly treated by
SignaledSession in `gui_session`module'''


def validator(path: str, multypes: OscMulTypes, directos=False):
    '''With this decorator, the OSC path method will continue
    its work in the main thread (in gui_session module),
    except if the function returns False.
    
    `path`: OSC str path

    `multypes`: str containing all accepted arg types (see OscMulTypes)
    '''
    def decorated(func: Callable):
        def wrapper(*args, **kwargs):
            response = func(*args, **kwargs)
            if directos or response is False:
                return False
            return True
    
        _validators[path] = wrapper
        _validators_types[path] = multypes

        return wrapper
    return decorated

def directos(path: str, full_types: str, no_sess=''):
    '''This OSC path method decorated with this 
    does all its job directly in the thread of the server.
    No work will have to be done in the main thread.
    see `validator` doc.'''
    return validator(path, full_types, no_sess=no_sess, directos=True)


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

        

        self.add_nice_methods(METHODS_DICT, self._generic_callback)
        self.add_nice_methods(_validators_types, self._generic_callback)
        self.set_fallback_nice_method(self._fallback_callback)

    @staticmethod
    def instance():
        return _instance

    def _generic_callback(self, osp: OscPack):
        if self.stopping:
            return

        _logger.debug(
            '\033[93mOSC::gui_receives\033[0m '
            f'({osp.path}, {osp.args}, {osp.types})')        
        
        if osp.path in _validators:
            if not _validators[osp.path](self, osp):
                return
        
        self.signaler.osc_receive.emit(osp)

    def _fallback_callback(self, osp: OscPack):
        if osp.path == '/ping':
            return

        if (osp.path, osp.types) == (rg.patchbay.UPDATE_PORTGROUP, 'siii'):
            # FIXME
            # this message should not be send at start
            # from canvas_saver (daemon)
            return

        _logger.warning(
            f'unknown message received from {osp.src_addr.url} '
            f'{osp.path}, {osp.types}')

    @validator(osc_paths.REPLY, 'ss*')
    def _reply(self, osp: OscPack):
        new_args: list[str] = osp.args.copy()
        reply_path = new_args.pop(0)

        match reply_path:
            case r.server.LIST_SESSIONS:
                self.signaler.add_sessions_to_list.emit(new_args)
            case r.server.LIST_PATH:
                self.signaler.new_executable.emit(new_args)
            case r.server.LIST_SESSION_TEMPLATES:
                self.signaler.session_template_found.emit(new_args)
            case r.server.LIST_USER_CLIENT_TEMPLATES:
                self.signaler.user_client_template_found.emit(new_args)
            case r.server.LIST_FACTORY_CLIENT_TEMPLATES:
                self.signaler.factory_client_template_found.emit(new_args)
            case r.session.LIST_SNAPSHOTS|r.client.LIST_SNAPSHOTS:
                self.signaler.snapshots_found.emit(new_args)
            case r.server.RENAME_SESSION:
                self.signaler.other_session_renamed.emit()
            case r.session.DUPLICATE_ONLY:
                self.signaler.other_session_duplicated.emit()
            case r.server.SAVE_SESSION_TEMPLATE:
                self.signaler.other_session_templated.emit()
            case r.server.ABORT_PARRALLEL_COPY:
                self.signaler.parrallel_copy_aborted.emit()

    @validator(rg.server.ANNOUNCE, 'siisis')
    def _server_announce(self, osp: OscPack):
        if self.daemon_manager.is_announced():
            return

        args: tuple[str, int, int, str, int, str] = osp.args

        (version, server_status_int, options,
         session_root, is_net_free, tcp_url) = args

        if (self.session is not None
                and self.session.main_win is not None
                and self.session.main_win.waiting_for_patchbay):
            self.send(osp.src_addr, r.server.ASK_FOR_PATCHBAY, '')
            self.session.main_win.waiting_for_patchbay = False

        self.signaler.daemon_announce.emit(
            osp.src_addr, version, ray.ServerStatus(server_status_int),
            ray.Option(options), session_root, is_net_free)

    @validator(rg.server.ROOT, 's')
    def _server_root(self, osp: OscPack):
        session_root: str = osp.args[0]
        CommandLineArgs.change_session_root(session_root)
        self.signaler.root_changed.emit(session_root)

    @validator(rg.server.STATUS, 'i')
    def _server_status(self, osp: OscPack):
        status_int: int = osp.args[0]
        self.signaler.server_status_changed.emit(
            ray.ServerStatus(status_int))

    @validator(rg.server.COPYING, 'i')
    def _server_copying(self, osp: OscPack):
        copying: int = osp.args[0]
        self.signaler.server_copying.emit(bool(copying))

    @validator(rg.server.PARRALLEL_COPY_STATE, 'ii')
    def _server_parrallel_copy_state(self, osp: OscPack):
        args: tuple[int, int] = osp.args
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

    @validator(rg.server.PARRALLEL_COPY_PROGRESS, 'if')
    def _server_copy_progress(self, osp: OscPack):
        args: tuple[int, float] = osp.args
        session_id, progress = args

        if not self._parrallel_copy_id_queue:
            return
        
        if session_id == self._parrallel_copy_id_queue[0]:
            self.signaler.parrallel_copy_progress.emit(*args)

    @validator(rg.server.PROGRESS, 'f')
    def _server_progress(self, osp: OscPack):
        progress: float = osp.args[0]
        self.signaler.server_progress.emit(progress)

    @validator(rg.session.AUTO_SNAPSHOT, 'i')
    def _session_auto_snapshot(self, osp: OscPack):
        auto_snapshot: int = osp.args[0]
        self.signaler.reply_auto_snapshot.emit(bool(auto_snapshot))

    @validator(rg.listed_session.DETAILS, 'sihi')
    def _listed_session_details(self, osp: OscPack):
        args: tuple[str, int, int, int] = osp.args
        self.signaler.session_details.emit(*args)

    @validator(rg.listed_session.SCRIPTED_DIR, 'si')
    def _listed_session_scripted_dir(self, osp: OscPack):
        args: tuple[str, int] = osp.args
        self.signaler.scripted_dir.emit(*args)

    @validator(rg.client_template.UPDATE, 'iss' + ray.ClientData.ARG_TYPES)
    def _client_template_update(self, osp: OscPack):
        self.signaler.client_template_update.emit(osp.args)

    @validator(rg.client_template.RAY_HACK_UPDATE, 'is' + ray.RayHack.ARG_TYPES)
    def _client_template_ray_hack_update(self, osp: OscPack):
        self.signaler.client_template_ray_hack_update.emit(osp.args)

    @validator(rg.client_template.RAY_NET_UPDATE, 'is' + ray.RayNet.ARG_TYPES)
    def _client_template_ray_net_update(self, osp: OscPack):
        self.signaler.client_template_ray_net_update.emit(osp.args)

    @validator(rg.client.PROGRESS, 'sf')
    def _client_progress(self, osp: OscPack):
        args: tuple[str, float] = osp.args
        self.signaler.client_progress.emit(*args)

    @validator(rg.patchbay.ANNOUNCE, 'iiis')
    def _ray_gui_patchbay_announce(self, osp: OscPack):
        args: tuple[int, int, int, str] = osp.args
        self.patchbay_addr = Address(args[3])
    
    @validator(rg.preview.STATE, 'i')
    def _ray_gui_preview_state(self, osp: OscPack):
        pv_state: int = osp.args[0]
        self.signaler.session_preview_update.emit(pv_state)

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
        self.send(self.daemon_manager.address, r.server.GUI_ANNOUNCE,
                  ray.VERSION, int(CommandLineArgs.under_nsm),
                  os.getenv('NSM_URL', ''), os.getpid(),
                  CommandLineArgs.net_daemon_id, '')

    def disannounce(self, src_addr: Address):
        self.send(src_addr, r.server.GUI_DISANNOUNCE)
        if self.patchbay_addr is not None:
            self.send(self.patchbay_addr, r.patchbay.GUI_DISANNOUNCE, '')

    def open_session(
            self, session_name: str, save_previous=1, session_template=''):
        self.to_daemon(r.server.OPEN_SESSION, session_name,
                       save_previous, session_template)

    def save_session(self):
        self.to_daemon(r.session.SAVE)

    def close_session(self):
        self.to_daemon(r.session.CLOSE)

    def abort_session(self):
        self.to_daemon(r.session.ABORT)

    def duplicate_a_session(self, session_name:str, new_session_name:str):
        self._parrallel_new_session_name = new_session_name
        self.to_daemon(rg.session.DUPLICATE_ONLY,
                       session_name, new_session_name,
                       CommandLineArgs.session_root)

    def get_parrallel_copy_id(self) -> int:
        '''Used by open session dialog to know
        if a parrallel copy is running'''
        if not self._parrallel_copy_id_queue:
            return 0

        return self._parrallel_copy_id_queue[0]

    def get_parrallel_new_session_name(self) -> str:
        return self._parrallel_new_session_name

