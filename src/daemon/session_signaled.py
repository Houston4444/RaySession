
# Imports from standard library
import json
import os
from pathlib import Path
import subprocess
import time
from typing import TYPE_CHECKING, Callable, Optional, Any
import logging

# third party imports
from qtpy.QtCore import QCoreApplication

# Imports from src/shared
from patshared import GroupPos
from osclib import Address, OscPack, are_same_osc_port
import ray
import xdg
import osc_paths
import osc_paths.ray as r
import osc_paths.ray.gui as rg
import osc_paths.nsm as nsm

# Local imports
from client import Client
import multi_daemon_file
from signaler import Signaler
from daemon_tools import (
    NoSessionPath, Terminal, RS, is_pid_child_of, highlight_text)
from session_operating import OperatingSession
import session_op as sop
from patch_rewriter import rewrite_jack_patch_files
import patchbay_dmn_mng
from session_dummy import DummySession

_logger = logging.getLogger(__name__)
_translate = QCoreApplication.translate
signaler = Signaler.instance()

_managed_funcs = dict[str, Callable]()


def manage(path: str | tuple[str, ...], types: str):
    '''This decorator indicates that the decorated function manages
    the OSC path(s) received. `types` are indicated only for convenience.
    '''

    def decorated(func):
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        
        if isinstance(path, str):
            _managed_funcs[path] = wrapper
        elif isinstance(path, tuple):
            for p in path:
                _managed_funcs[p] = wrapper
        return wrapper
    return decorated


def session_operation(path: str | tuple[str, ...], types: str):
    '''This decorator indicates that the decorated function manages
    the OSC path(s) received, and that this function needs some checks
    (operation pending, copy running).'''

    def decorated(func: Callable):
        def wrapper(*args, **kwargs):
            if len(args) < 2:
                return

            sess, osp, *rest = args
            
            if TYPE_CHECKING:
                sess: SignaledSession
                osp: OscPack

            if sess.steps_order:
                sess.send(*osp.error(), ray.Err.OPERATION_PENDING,
                          "An operation pending.")
                return

            if sess.file_copier.is_active():
                if osp.path.startswith('/nsm/server/'):
                    sess.send(
                        *osp.error(), ray.Err.OPERATION_PENDING,
                        "An operation pending.")
                else:
                    sess.send(
                        *osp.error(), ray.Err.COPY_RUNNING,
                        "ray-daemon is copying files.\n"
                        "Wait copy finish or abort copy,\n"
                        "and restart operation !\n")
                return

            sess.steps_osp = osp

            response = func(*args, **kwargs)
            
            if not sess.steps_order:
                sess.steps_osp = None

            sess.next_function()

            return response
        
        if isinstance(path, str):
            _managed_funcs[path] = wrapper
        elif isinstance(path, tuple):
            for p in path:
                _managed_funcs[p] = wrapper

        return wrapper
    return decorated


def client_action(path: str, types: str):
    '''This decorator indicates that the decorated function manages
    the OSC path(s) received, and gives directly the client as argument
    if it exists. Otherwise, it replies an error to the sender.'''

    def decorated(func: Callable):
        def wrapper(*args, **kwargs):
            if len(args) < 2:
                return

            sess, osp, *rest = args
            
            if TYPE_CHECKING:
                sess: SignaledSession
                osp: OscPack

            client_id: str = osp.args[0] # type:ignore
            client: Client

            for client in sess.clients:
                if client.client_id == client_id:
                    response = func(*args, client, **kwargs)
                    break
            else:
                sess.send_error_no_client(osp, client_id)
                return

            return response
        
        _managed_funcs[path] = wrapper
        
        return wrapper
    return decorated


class SignaledSession(OperatingSession):
    '''There is only one possible instance of SignaledSession
    This is not the case for Session and OperatingSession.
    This session receives signals from OSC server.'''
    steps_order: list[sop.SessionOp | Callable | tuple[Callable | Any, ...]]
    
    def __init__(self, root: Path):
        OperatingSession.__init__(self, root)

        signaler.osc_recv.connect(self.osc_receive)
        signaler.dummy_load_and_template.connect(self.dummy_load_and_template)
        signaler.patchbay_finished.connect(self.patchbay_process_finished)

        # fill recent sessions
        recent_sessions: dict[str, list[str]] = RS.settings.value(
            'daemon/recent_sessions', {}, type=dict)

        for root_path, session_list in recent_sessions.items():
            self.recent_sessions[Path(root_path)] = session_list

        self.check_recent_sessions_existing()

        self.preview_dummy_session = None
        self.dummy_sessions = list[DummySession]()
        self._next_dummy_id = 1
        
        self._folder_sizes_and_dates = []
        
        self._cache_folder_sizes_path = (
            xdg.xdg_cache_home() / ray.APP_TITLE / 'folder_sizes.json')

        if self._cache_folder_sizes_path.is_file():
            try:
                self._folder_sizes_and_dates = json.load(
                    self._cache_folder_sizes_path) # type:ignore : Path works here !
            except:
                # cache file load failed and this is really not strong
                pass
    
    def _get_new_dummy_session_id(self) -> int:
        to_return = self._next_dummy_id
        self._next_dummy_id += 1
        return to_return

    def _new_dummy_session(self, root: Path) -> DummySession:
        new_dummy = DummySession(root, self._get_new_dummy_session_id())
        self.dummy_sessions.append(new_dummy)
        return new_dummy

    def save_folder_sizes_cache_file(self):
        cache_dir = self._cache_folder_sizes_path.parent
        if not cache_dir.exists():
            try:
                cache_dir.mkdir(parents=True)
            except:
                # can't save cache file, this is really not strong
                return
        
        try:
            with open(self._cache_folder_sizes_path, 'w') as file:
                json.dump(self._folder_sizes_and_dates, file)
        except:
            # cache file save failed, not strong
            pass

    def osc_receive(self, osp: OscPack):
        if osp.path in _managed_funcs:
            _managed_funcs[osp.path](self, osp)

    def send_error_no_client(self, osp: OscPack, client_id: str):
        self.send(*osp.error(), ray.Err.CREATE_FAILED,
                  _translate('GUIMSG', "No client with this client_id:%s")
                    % client_id)

    def send_error_copy_running(self, osp: OscPack):
        self.send(*osp.error(), ray.Err.COPY_RUNNING,
                  _translate('GUIMSG', "Impossible, copy running !"))

    ############## FUNCTIONS CONNECTED TO SIGNALS FROM OSC ###################

    @manage(nsm.server.ANNOUNCE, 'sssiii')
    def _nsm_server_announce(self, osp: OscPack):
        client_name, capabilities, executable_path, major, minor, pid = \
            osp.args # type:ignore
        executable_path: str
        pid: int

        if self.wait_for is ray.WaitFor.QUIT:
            if osp.path.startswith('/nsm/server/'):
                # Error is wrong but compatible with NSM API
                self.send(*osp.error(), ray.Err.NO_SESSION_OPEN,
                          "Sorry, but there's no session open "
                          + "for this application to join.")
            return

        def find_the_client() -> Optional[Client]:
            # we can't be absolutely sure that the announcer is the good one
            # but if client announce a known PID,
            # we can be sure of which client is announcing
            if pid == os.getpid():
                # this client is internal for sure
                for client in self.clients:
                    if (client.protocol is ray.Protocol.INTERNAL
                            and client.executable == executable_path
                            and client._internal is not None
                            and client._internal.running
                            and not client.nsm_active):
                        return client
            
            for client in self.clients:
                if (client.pid == pid
                        and not client.nsm_active
                        and client.is_running):
                    return client
                
            for client in self.clients:
                if (not client.nsm_active and client.is_running
                        and is_pid_child_of(pid, client.pid)):
                    return client

        client = find_the_client()
        if client is not None:
            client.server_announce(osp, False)
        else:
            for client in self.clients:
                if (client.launched_in_terminal
                        and client.process_drowned
                        and client.executable == executable_path):
                    # when launched in terminal
                    # the client process can be stopped
                    # because the terminal process is 'linked' to an existing instance
                    # then, we may can say this stopped client is the good one,
                    # and we declare it as external because we won't check its process
                    # state with QProcess.state().
                    client.server_announce(osp, True)
                    break
            else:
                # Client launched externally from daemon
                # by command : $:NSM_URL=url executable
                client = self._new_client(executable_path)
                self.externals_timer.start()
                self.send_monitor_event('joined', client.client_id)
                client.server_announce(osp, True)

        if self.wait_for is ray.WaitFor.ANNOUNCE:
            self.end_timer_if_last_expected(client)

    @manage(osc_paths.REPLY, 'ss*')
    def _reply(self, osp: OscPack):
        if self.wait_for is ray.WaitFor.QUIT:
            return

        message: str = osp.args[1] # type:ignore
        client = self.get_client_by_address(osp.src_addr)
        if client:
            client.set_reply(ray.Err.OK, message)

            server = self.get_server()
            if (server is not None
                    and server.server_status is ray.ServerStatus.READY
                    and ray.Option.DESKTOPS_MEMORY in server.options):
                self.desktops_memory.replace()
        else:
            self.message("Reply from unknown client")

    @manage(osc_paths.ERROR, 'sis')
    def _error(self, osp: OscPack):
        path, errcode, message = osp.args # type:ignore
        errcode: int
        message: str

        client = self.get_client_by_address(osp.src_addr)
        if client:
            client.set_reply(errcode, message)

            if self.wait_for is ray.WaitFor.REPLY:
                self.end_timer_if_last_expected(client)
        else:
            self.message("error from unknown client")

    @manage(nsm.client.LABEL, 's')
    def _nsm_client_label(self, osp: OscPack):
        client = self.get_client_by_address(osp.src_addr)
        if client:
            client.set_label(osp.args[0]) # type:ignore

    @manage(nsm.client.NETWORK_PROPERTIES, 'ss')
    def _nsm_client_network_properties(self, osp: OscPack):
        osp_args: tuple[str, str] = osp.args # type:ignore
        client = self.get_client_by_address(osp.src_addr)
        if client:
            net_daemon_url, net_session_root = osp_args
            client.set_network_properties(net_daemon_url, net_session_root)

    @manage(r.server.GUI_ANNOUNCE, 'sisiis')
    def _ray_server_gui_announce(self, osp: OscPack):
        args: tuple[str, int, str, int, int, str] = osp.args # type:ignore
        (version, int_nsm_locked, net_master_daemon_url,
         gui_pid, net_daemon_id, tcp_url) = args
        
        server = self.get_server()
        if server is None:
            return
        
        nsm_locked = bool(int_nsm_locked)
        is_net_free = True
        
        if nsm_locked:
            is_net_free = multi_daemon_file.is_free_for_root(
                server.net_daemon_id, self.root)
        
        server.announce_gui(
            osp.src_addr.url, nsm_locked, is_net_free, gui_pid, None)

    @manage(r.server.ASK_FOR_PATCHBAY, 's')
    def _ray_server_ask_for_patchbay(self, osp: OscPack):        
        # if we are here, it means that we need a patchbay daemon to run
        patchbay_dmn_mng.start(osp.src_addr.url)

    @manage(r.server.ABORT_COPY, '')
    def _ray_server_abort_copy(self, osp: OscPack):
        self.file_copier.abort()

    @manage(r.server.ABORT_PARRALLEL_COPY, 'i')
    def _ray_server_abort_parrallel_copy(self, osp: OscPack):
        session_id = osp.args[0]
        
        for dummy_session in self.dummy_sessions:
            if dummy_session.session_id == session_id:
                dummy_session.file_copier.abort()
                break
        self.send(*osp.reply(), 'Parrallel copy aborted')

    @manage(r.server.ABORT_SNAPSHOT, '')
    def _ray_server_abort_snapshot(self, osp: OscPack):
        self.snapshoter.abort()

    @manage(r.server.CHANGE_ROOT, 's')
    def _ray_server_change_root(self, osp: OscPack):
        new_root_str: str = osp.args[0] # type:ignore
        if self.path:
            self.send(*osp.error(), ray.Err.SESSION_LOCKED,
                      "impossible to change root. session %s is loaded"
                      % self.path)
            return

        new_root = Path(new_root_str)

        if not new_root.exists():
            try:
                new_root.mkdir(parents=True)
            except:
                self.send(*osp.error(), ray.Err.CREATE_FAILED,
                          "invalid session root !")
                return

        if not os.access(new_root_str, os.W_OK):
            self.send(*osp.error(), ray.Err.CREATE_FAILED,
                      "unwriteable session root !")
            return

        self.root = new_root

        multi_daemon_file.update()

        self.send(*osp.reply(),
                  "root folder changed to %s" % self.root)
        self.send_gui(rg.server.ROOT, str(self.root))

        if self.root not in self.recent_sessions.keys():
            self.recent_sessions[self.root] = []
        self.send_gui(rg.server.RECENT_SESSIONS,
                       *self.recent_sessions[self.root])

    def _ray_server_list_client_templates(self, osp: OscPack):
        # if osp.src_addr is an announced ray GUI
        # server will send it all templates properties
        # else, server replies only templates names
        src_addr_is_gui = False
        server = self.get_server()
        if server is not None:
            src_addr_is_gui = server.is_gui_address(osp.src_addr)

        template_names = set()
        filters: list[str] = osp.args # type:ignore

        factory = bool(osp.path == r.server.LIST_FACTORY_CLIENT_TEMPLATES)
        base = 'factory' if factory else 'user'

        templates_database = self.get_client_templates_database(base)
        if not templates_database:
            self._rebuild_templates_database(base)
            templates_database = self.get_client_templates_database(base)

        for t in templates_database:
            if filters:
                skipped_by_filter = False
                message = t.template_client.get_properties_message()

                for filt in filters:
                    for line in message.splitlines():
                        if line == filt:
                            break
                    else:
                        skipped_by_filter = True
                        break

                if skipped_by_filter:
                    continue
                
            template_names.add(t.template_name)

        self.send(*osp.reply(), *template_names)
        
        if src_addr_is_gui:
            for app_template in templates_database:
                template_name = app_template.template_name
                template_client = app_template.template_client
                display_name = app_template.display_name
                
                self.send_gui(
                    rg.client_template.UPDATE,
                    int(factory), template_name, display_name,
                    *template_client.spread())

                if template_client.is_ray_hack:
                    self.send_gui(
                        rg.client_template.RAY_HACK_UPDATE,
                        int(factory), template_name,
                        *template_client.ray_hack.spread())
                elif template_client.is_ray_net:
                    self.send_gui(
                        rg.client_template.RAY_NET_UPDATE,
                        int(factory), template_name,
                        *template_client.ray_net.spread())

        self.send(*osp.reply())

    @manage(r.server.LIST_FACTORY_CLIENT_TEMPLATES, 's*')
    def _ray_server_list_factory_client_templates(self, osp: OscPack):
        self._ray_server_list_client_templates(osp)

    @manage(r.server.LIST_USER_CLIENT_TEMPLATES, 's*')
    def _ray_server_list_user_client_templates(self, osp: OscPack):
        self._ray_server_list_client_templates(osp)

    @manage(r.server.LIST_SESSIONS, '|i')
    def _ray_server_list_sessions(self, osp: OscPack):
        with_net = False
        last_sent_time = time.time()

        if osp.args:
            with_net = bool(osp.args[0])

        if with_net:
            for client in self.clients:
                if (client.is_ray_net
                        and client.ray_net.daemon_url):
                    self.send(Address(client.ray_net.daemon_url),
                              r.server.LIST_SESSIONS, 1)

        if not self.root.is_absolute():
            self.send(*osp.error(), ray.Err.GENERAL_ERROR,
                      "no session root, so no sessions to list")
            return

        session_list = list[str]()
        sessions_set = set()
        n = 0

        for root, dirs, files in os.walk(self.root):
            #exclude hidden files and dirs
            files = [f for f in files if not f.startswith('.')]
            dirs[:] = [d for d in dirs  if not d.startswith('.')]

            if root == str(self.root):
                continue

            for file in files:
                if file in ('raysession.xml', 'session.nsm'):
                    # prevent search in sub directories
                    dirs.clear()

                    basefolder = str(Path(root).relative_to(self.root))
                    session_list.append(basefolder)
                    sessions_set.add(basefolder)
                    n += len(basefolder)

                    if n >= 10000 or time.time() - last_sent_time > 0.300:
                        last_sent_time = time.time()
                        self.send(*osp.reply(), *session_list)

                        session_list.clear()
                        n = 0
                    break

        if session_list:
            self.send(*osp.reply(), *session_list)

        self.send(*osp.reply())
        
        search_scripts_dir = self.root
        has_general_scripts = False
        
        while str(search_scripts_dir) != search_scripts_dir.root:
            if Path(search_scripts_dir / ray.SCRIPTS_DIR).is_dir():
                has_general_scripts = True
                break
            search_scripts_dir = search_scripts_dir.parent

        locked_sessions = set(multi_daemon_file.get_all_session_paths())

        for root, dirs, files in os.walk(self.root):
            #exclude hidden files and dirs
            files = [f for f in files if not f.startswith('.')]
            dirs[:] = [d for d in dirs  if not d.startswith('.')]

            if root == str(self.root):
                if has_general_scripts:
                    self.send(
                        osp.src_addr, rg.listed_session.SCRIPTED_DIR,
                        '', ray.ScriptFile.PARENT.value)
                continue
            
            basefolder = str(Path(root).relative_to(self.root))
            
            if ray.SCRIPTS_DIR in dirs:
                script_files = ray.ScriptFile.PREVENT
                
                for action in ('load', 'save', 'close'):
                    if os.access(
                            Path(root) / ray.SCRIPTS_DIR / f'{action}.sh',
                            os.X_OK):
                        script_files |= ray.ScriptFile[action.upper()]

                self.send(osp.src_addr, rg.listed_session.SCRIPTED_DIR,
                          basefolder, script_files.value)
            
            if basefolder not in sessions_set:
                continue

            has_notes = bool(ray.NOTES_PATH in files)
            last_modified = int(os.path.getmtime(root))
            locked = bool(root in locked_sessions)

            self.send(osp.src_addr, rg.listed_session.DETAILS,
                      basefolder, int(has_notes), last_modified, int(locked))

            # prevent search in sub directories
            dirs.clear()        

    @manage(nsm.server.LIST, '')
    def _nsm_server_list(self, osp: OscPack):
        if self.root.is_absolute():
            for root, dirs, files in os.walk(self.root):
                #exclude hidden files and dirs
                files = [f for f in files if not f.startswith('.')]
                dirs[:] = [d for d in dirs  if not d.startswith('.')]

                if root == str(self.root):
                    continue

                for file in files:
                    if file in ('raysession.xml', 'session.nsm'):
                        basefolder = str(Path(root).relative_to(self.root))
                        self.send(*osp.reply(), basefolder)

        self.send(*osp.reply(), '')

    @session_operation((r.server.NEW_SESSION, nsm.server.NEW), 's|ss')
    def _ray_server_new_session(self, osp: OscPack):
        if len(osp.args) == 2 and osp.args[1]:
            osp_args: tuple[str, str] = osp.args # type:ignore
            session_name, template_name = osp_args

            spath = self.root / session_name

            if not spath.exists():
                self.steps_order = [
                    sop.Save(self),
                    sop.CloseNoSaveClients(self),
                    sop.SaveSnapshot(self),
                    sop.PrepareTemplate(self, session_name, template_name),
                    (self.preload, session_name),
                    sop.Close(self),
                    self.take_place,
                    sop.Load(self),
                    self.new_done]
                return

        self.steps_order = [sop.Save(self),
                            sop.CloseNoSaveClients(self),
                            sop.SaveSnapshot(self),
                            sop.Close(self),
                            (self.new, osp.args[0]),
                            sop.Save(self),
                            self.new_done]

    @session_operation((r.server.OPEN_SESSION, nsm.server.OPEN), 's|si|sis')
    def _ray_server_open_session(self, osp: OscPack, open_off=False):
        session_name: str = osp.args[0] # type:ignore
        save_previous = True
        template_name = ''

        if len(osp.args) >= 2:
            save_previous = bool(osp.args[1])
        if len(osp.args) >= 3:
            template_name: str = osp.args[2] # type:ignore

        if (not session_name
                or '//' in session_name
                or session_name.startswith(('../', '.ray-', 'ray-'))):
            self._send_error(ray.Err.CREATE_FAILED, 'invalid session name.')
            return

        if template_name:
            if '/' in template_name:
                self._send_error(ray.Err.CREATE_FAILED, 'invalid template name')
                return

        spath = self.root / session_name

        if spath == self.path:
            self._send_error(ray.Err.SESSION_LOCKED,
                _translate('GUIMSG', 'session %s is already opened !')
                    % highlight_text(session_name))
            return

        if not multi_daemon_file.is_free_for_session(spath):
            Terminal.warning("Session %s is used by another daemon"
                              % highlight_text(str(spath)))

            self._send_error(ray.Err.SESSION_LOCKED,
                _translate('GUIMSG',
                    'session %s is already used by another daemon !')
                        % highlight_text(session_name))
            return

        # don't use template if session folder already exists
        if spath.exists():
            template_name = ''

        self.steps_order = []

        if save_previous:
            self.steps_order += [sop.Save(self, outing=True)]

        self.steps_order += [sop.CloseNoSaveClients(self)]

        if save_previous:
            self.steps_order += [sop.SaveSnapshot(self, outing=True)]

        if template_name:
            self.steps_order += [sop.PrepareTemplate(self, session_name, template_name, net=True)]

        self.steps_order += [
            (self.preload, session_name),
            sop.Close(self, clear_all_clients=open_off),
            self.take_place,
            sop.Load(self, open_off=open_off),
            self.load_done]

    @manage(r.server.OPEN_SESSION_OFF, 's|si')
    def _ray_server_open_session_off(self, osp: OscPack):
        self._ray_server_open_session(osp, open_off=True)

    @manage(r.server.RENAME_SESSION, 'ss')
    def _ray_server_rename_session(self, osp: OscPack):
        osp_args : tuple[str, str] = osp.args  # type:ignore
        old_session_name, new_session_name = osp_args
        spath = self.root / old_session_name

        for f in 'raysession.xml', 'session.nsm':
            if Path(spath / f).is_file():
                break
        else:
            self.send(*osp.error(), ray.Err.BAD_PROJECT,
                      f"{old_session_name} is not an existing session, "
                      "can't rename !")

        if '/' in new_session_name:
            self.send(*osp.error(), ray.Err.BAD_PROJECT,
                      "'/' is not allowed in new_session_name")
            return

        tmp_session = self._new_dummy_session(self.root)
        tmp_session.ray_server_rename_session(osp)

    @manage(r.server.SAVE_SESSION_TEMPLATE, 'ss|sss')
    def _ray_server_save_session_template(self, osp: OscPack):
        net = bool(osp.types == 'sss')
        session_name: str = osp.args[0] # type:ignore
        template_name: str = osp.args[1] # type:ignore

        if net:
            sess_root: str = osp.args[2] # type:ignore

            if (sess_root != str(self.root)
                    or session_name != self.short_path_name):
                tmp_session = self._new_dummy_session(Path(sess_root))
                tmp_session.ray_server_save_session_template(
                    osp, session_name, template_name, net)
                return

        if self.steps_order:
            self.send(*osp.error(), ray.Err.OPERATION_PENDING,
                      "An operation pending.")
            return

        if self.file_copier.is_active():
            if osp.path.startswith('/nsm/server/'):
                self.send(*osp.error(), ray.Err.OPERATION_PENDING,
                          "An operation pending.")
            else:
                self.send(
                    *osp.error(), ray.Err.COPY_RUNNING,
                    "ray-daemon is copying files.\n"
                    "Wait copy finish or abort copy,\n"
                    "and restart operation !\n")
            return

        self.steps_osp = osp

        # response = func(*args, **kwargs)
        # sess.next_function()

        for client in self.clients:
            if client.is_ray_net:
                client.ray_net.session_template = template_name

        self.steps_order = [
            sop.Save(self),
            sop.SaveSnapshot(self),
            sop.SaveSessionTemplate(self, template_name)]

    @manage(r.server.GET_SESSION_PREVIEW, 's')
    def _ray_server_get_session_preview(self, osp: OscPack):
        session_name = osp.args[0]
        server = self.get_server()
        if server is None:
            return
        
        if server.session_to_preview != session_name:
            # prevent to open a dummy session
            # in case user change preview so fastly
            # that this thread is late and user already
            # changed the session to preview
            return

        del self.preview_dummy_session
        self.preview_dummy_session = DummySession(self.root)
        self.preview_dummy_session.ray_server_get_session_preview(
            osp, self._folder_sizes_and_dates)

    @manage(r.server.SET_OPTION, 'i')
    def _ray_server_set_option(self, osp: OscPack):
        opt_int: int = osp.args[0] # type:ignore
        option = ray.Option(abs(opt_int)) 
        
        if option is ray.Option.BOOKMARK_SESSION:
            if self.path:
                if opt_int > 0:
                    self.bookmarker.make_all(self.path)
                else:
                    self.bookmarker.remove_all(self.path)

    @manage(r.server.AUTO_EXPORT_CUSTOM_NAMES, 's')
    def _ray_server_auto_export_pretty_names(self, osp: OscPack):
        patchbay_dmn_mng.start()

    @manage((r.server.EXPORT_CUSTOM_NAMES,
             r.server.IMPORT_PRETTY_NAMES,
             r.server.CLEAR_PRETTY_NAMES), '')
    def _ray_server_export_pretty_names(self, osp: OscPack):
        match osp.path:
            case r.server.EXPORT_CUSTOM_NAMES:
                patchbay_dmn_mng.start(
                    one_shot_act=r.patchbay.EXPORT_ALL_CUSTOM_NAMES)
            case r.server.IMPORT_PRETTY_NAMES:
                patchbay_dmn_mng.start(
                    one_shot_act=r.patchbay.IMPORT_ALL_PRETTY_NAMES)
            case r.server.CLEAR_PRETTY_NAMES:
                patchbay_dmn_mng.start(
                    one_shot_act=r.patchbay.CLEAR_ALL_PRETTY_NAMES)

    @manage(r.server.patchbay.SAVE_GROUP_POSITION,
            'i' + GroupPos.ARG_TYPES)
    def _ray_server_patchbay_save_group_position(self, osp: OscPack):
        self.canvas_saver.save_group_position(*osp.args)

    @manage(r.server.patchbay.SAVE_PORTGROUP, 'siiiss*')
    def _ray_server_patchbay_save_portgroup(self, osp: OscPack):
        self.canvas_saver.save_portgroup(*osp.args)

    @manage(r.server.patchbay.VIEWS_CHANGED, 's')
    def _ray_server_patchbay_views_changed(self, osp: OscPack):
        self.canvas_saver.views_changed(*osp.args)

    @manage(r.server.patchbay.CLEAR_ABSENTS_IN_VIEW, 's')
    def _ray_server_patchbay_clear_absents_in_view(self, osp: OscPack):
        self.canvas_saver.clear_absents_in_view(*osp.args)
        
    @manage(r.server.patchbay.VIEW_NUMBER_CHANGED, 'ii')
    def _ray_server_patchbay_view_number_changed(self, osp: OscPack):
        osp_args: tuple[int, int] = osp.args # type:ignore
        self.canvas_saver.change_view_number(*osp_args)
        
    @manage(r.server.patchbay.VIEW_PTV_CHANGED, 'ii')
    def _ray_server_patchbay_view_ptv_changed(self, osp: OscPack):
        osp_args: tuple[int, int] = osp.args # type:ignore
        self.canvas_saver.view_ptv_changed(*osp_args)

    @manage(r.server.patchbay.SAVE_GROUP_CUSTOM_NAME, 'sssi')
    def _ray_server_patchbay_save_group_custom_name(self, osp: OscPack):
        osp_args : tuple[str, str, str, int] = osp.args # type:ignore
        group_name, pretty_name, over_pretty, save_in_jack = osp_args
        self.canvas_saver.save_group_custom_name(
            group_name, pretty_name, over_pretty)
        self.send_patchbay_daemon(
            r.patchbay.SAVE_GROUP_CUSTOM_NAME,
            group_name, pretty_name, save_in_jack)
        
    @manage(r.server.patchbay.SAVE_PORT_CUSTOM_NAME, 'sssi')
    def _ray_server_patchbay_save_port_custom_name(self, osp: OscPack):
        osp_args : tuple[str, str, str, int] = osp.args # type:ignore
        port_name, pretty_name, over_pretty, save_in_jack = osp_args
        self.canvas_saver.save_port_custom_name(
            port_name, pretty_name, over_pretty)
        self.send_patchbay_daemon(
            r.patchbay.SAVE_PORT_CUSTOM_NAME,
            port_name, pretty_name, save_in_jack)

    @manage(r.server.PATCHBAY_DAEMON_READY, '')
    def _ray_server_patchbay_daemon_ready(self, osp: OscPack):
        self.canvas_saver.send_custom_names_to_patchbay_daemon(osp)
        patchbay_dmn_mng.set_ready()

    @session_operation((r.session.SAVE, nsm.server.SAVE), '')
    def _ray_session_save(self, osp: OscPack):        
        # self.steps_order = [self.save, self.snapshot, self.save_done]
        self.steps_order = [
            sop.Save(self), sop.SaveSnapshot(self), self.save_done]

    @session_operation(r.session.SAVE_AS_TEMPLATE, 's')
    def _ray_session_save_as_template(self, osp: OscPack):
        template_name: str = osp.args[0] #type:ignore

        for client in self.clients:
            if client.is_ray_net:
                client.ray_net.session_template = template_name

        self.steps_order = [
            sop.Save(self),
            sop.SaveSnapshot(self),
            sop.SaveSessionTemplate(self, template_name)]

    @session_operation(r.session.TAKE_SNAPSHOT, 's|si')
    def _ray_session_take_snapshot(self, osp: OscPack):
        if self.path is None:
            self.send(*osp.error(), ray.Err.NO_SESSION_OPEN,
                      'No session is loaded, impossible to take snapshot')
            return
        
        snapshot_name: str = osp.args[0] #type:ignore
        with_save = 0
        if len(osp.args) >= 2:
            with_save: int = osp.args[1] #type:ignore

        self.steps_order.clear()

        if with_save:
            self.steps_order.append(sop.Save(self))
            
        self.steps_order += [
            sop.SaveSnapshot(
                self, snapshot_name=snapshot_name,
                force=True, error_is_minor=False),
            self.snapshot_done]

    @session_operation((r.session.CLOSE, nsm.server.CLOSE), '')
    def _ray_session_close(self, osp: OscPack):
        self.steps_order = [sop.Save(self, outing=True),
                            sop.CloseNoSaveClients(self),
                            sop.SaveSnapshot(self),
                            sop.Close(self, clear_all_clients=True),
                            self.close_done]

    @manage((r.session.ABORT, nsm.server.ABORT), '')
    def _ray_session_abort(self, osp: OscPack):
        if self.path is None:
            self.file_copier.abort()
            self.send(*osp.error(), ray.Err.NO_SESSION_OPEN,
                      "No session to abort.")
            return

        self.wait_for = ray.WaitFor.NONE
        self.timer.stop()

        # Non Session Manager can't abort if an operation pending
        # RS can and it would be a big regression to remove this feature
        # So before to abort we need to send an error reply
        # to the last server control message
        # if an operation pending.

        if self.steps_order:
            if (self.steps_osp is not None
                    and self.steps_osp.path.startswith('/nsm/server/')):
                ns = nsm.server

                match self.steps_osp.path:
                    case ns.SAVE:
                        self.save_error(ray.Err.CREATE_FAILED)
                    case ns.OPEN:
                        self.load_error(ray.Err.SESSION_LOCKED)
                    case ns.NEW:
                        self._send_error(
                            ray.Err.CREATE_FAILED,
                            "Could not create the session directory")
                    case ns.DUPLICATE:
                        new_session_full_name: str = \
                            self.steps_osp.args[0] #type:ignore
                        self.duplicate_aborted(new_session_full_name)
                    case ns.CLOSE|ns.ABORT|ns.QUIT:
                        # let the current close works here
                        self.send(*osp.error(),
                                ray.Err.OPERATION_PENDING,
                                "An operation pending.")
                        return
            else:
                self._send_error(
                    ray.Err.ABORT_ORDERED,
                    _translate('GUIMSG',
                               'abort ordered from elsewhere, sorry !'))

        self.steps_osp = osp
        self.steps_order = [sop.Close(self, clear_all_clients=True),
                            self.abort_done]

        if self.file_copier.is_active():
            self.file_copier.abort(self.next_function, [])
        else:
            self.next_function()

    @manage((r.server.QUIT, nsm.server.QUIT), '')
    def _ray_server_quit(self, osp: OscPack):
        patchbay_dmn_mng.daemon_exit()
        self.steps_osp = osp
        self.steps_order = [self.terminate_step_scripter,
                            sop.Close(self), self.exit_now]

        if self.file_copier.is_active():
            self.file_copier.abort(self.next_function, [])
        else:
            self.next_function()

    @manage(r.session.CANCEL_CLOSE, '')
    def _ray_session_cancel_close(self, osp: OscPack):
        if not self.steps_order:
            return

        self.timer.stop()
        self.timer_waituser_progress.stop()
        self.steps_order.clear()
        self._clean_expected()
        self.set_server_status(ray.ServerStatus.READY)

    @manage(r.session.SKIP_WAIT_USER, '')
    def _ray_session_skip_wait_user(self, osp: OscPack):
        if not self.steps_order:
            return

        self.timer.stop()
        self.timer_waituser_progress.stop()
        self._clean_expected()
        self.next_function()

    @session_operation((r.session.DUPLICATE, nsm.server.DUPLICATE), 's')
    def _ray_session_duplicate(self, osp: OscPack):
        new_session_full_name: str = osp.args[0] #type:ignore
        spath = self.root / new_session_full_name

        if spath.exists():
            self._send_error(ray.Err.CREATE_FAILED,
                _translate('GUIMSG', "%s already exists !")
                    % highlight_text(spath))
            return

        if not multi_daemon_file.is_free_for_session(spath):
            Terminal.warning("Session %s is used by another daemon"
                             % highlight_text(new_session_full_name))
            self._send_error(ray.Err.SESSION_LOCKED,
                _translate('GUIMSG',
                    'session %s is already used by this or another daemon !')
                        % highlight_text(new_session_full_name))
            return

        self.steps_order = [sop.Save(self),
                            sop.CloseNoSaveClients(self),
                            sop.SaveSnapshot(self),
                            sop.Duplicate(self, new_session_full_name),
                            (self.preload, new_session_full_name),
                            sop.Close(self),
                            self.take_place,
                            sop.Load(self),
                            self.duplicate_done]

    @manage(r.session.DUPLICATE_ONLY, 'sss')
    def _ray_session_duplicate_only(self, osp: OscPack):
        osp_args: tuple[str, str, str] = osp.args #type:ignore
        session_to_load, new_session, sess_root = osp_args
        spath = Path(sess_root) / new_session

        if spath.exists():
            self.send(osp.src_addr, r.net_daemon.DUPLICATE_STATE, 1)
            self.send(*osp.error(), ray.Err.CREATE_FAILED,
                      _translate('GUIMSG', "%s already exists !")
                        % highlight_text(str(spath)))
            return

        if (sess_root == str(self.root)
                and session_to_load == self.short_path_name):
            if (self.steps_order
                    or self.file_copier.is_active()):
                self.send(osp.src_addr, r.net_daemon.DUPLICATE_STATE, 1)
                return

            self.steps_osp = osp

            self.steps_order = [sop.Save(self),
                                sop.SaveSnapshot(self),
                                sop.Duplicate(self, new_session),
                                self.duplicate_only_done]

            self.next_function()

        else:
            tmp_session = self._new_dummy_session(Path(sess_root))
            tmp_session.steps_osp = osp
            tmp_session.dummy_duplicate(osp)

    @session_operation(r.session.OPEN_SNAPSHOT, 's')
    def _ray_session_open_snapshot(self, osp: OscPack):
        if self.path is None:
            return

        snapshot: str = osp.args[0] # type:ignore

        self.steps_order = [
            sop.Save(self),
            sop.CloseNoSaveClients(self),
            sop.SaveSnapshot(self, rewind_snapshot=snapshot, force=True),
            sop.Close(self, clear_all_clients=True),
            sop.LoadSnapshot(self, snapshot),
            (self.preload, str(self.path)),
            self.take_place,
            sop.Load(self),
            self.load_done]

    @manage(r.session.RENAME, 's')
    def _ray_session_rename(self, osp: OscPack):
        new_session_name: str = osp.args[0] #type:ignore

        if self.steps_order:
            return

        if self.path is None:
            return

        if self.file_copier.is_active():
            return

        if new_session_name == self.name:
            return

        if not self.is_nsm_locked():
            for filename in self.path.parent.iterdir():
                if filename.name == new_session_name:
                    # another directory exists with new session name
                    return

        for client in self.clients:
            if client.is_running:
                self.send_gui_message(
                    _translate('GUIMSG',
                               'Stop all clients before rename session !'))
                return

        for client in self.clients + self.trashed_clients:
            client.adjust_files_after_copy(new_session_name, ray.Template.RENAME)

        if not self.is_nsm_locked():
            try:
                spath = self.path.parent / new_session_name
                subprocess.run(['mv', self.path, spath])
                self._set_path(spath)

                self.send_gui_message(
                    _translate('GUIMSG', 'Session directory is now: %s')
                    % self.path)
            except:
                pass

        # we need to save the session file here
        # because session just has been renamed
        # and clients dependant of the session name
        # would not find there files if session is aborted just after
        self._save_session_file()

        self.send_gui_message(
            _translate('GUIMSG', 'Session %s has been renamed to %s .')
            % (self.name, new_session_name))
        self.send_gui(rg.session.NAME, self.name, str(self.path))

    @manage(r.session.SET_NOTES, 's')
    def _ray_session_set_notes(self, osp: OscPack):
        self.notes = osp.args[0]
        self.send(*osp.reply(), 'Notes has been set')

    @manage(r.session.GET_NOTES, '')
    def _ray_session_get_notes(self, osp: OscPack):
        self.send(*osp.reply(), self.notes)
        self.send(*osp.reply())

    @manage((r.session.ADD_EXEC, nsm.server.ADD), 'siiissi|ss*')
    def _ray_session_add_exec(self, osp: OscPack):
        self._ray_session_add_executable(osp, old_defaults=False)

    @manage(r.session.ADD_EXECUTABLE, 'siiissi|ss*')
    def _ray_session_add_executable(self, osp: OscPack, old_defaults=True):
        executable: str = osp.args[0] #type:ignore
        protocol = ray.Protocol.NSM

        if old_defaults:
            prefix_mode = ray.PrefixMode.SESSION_NAME
            jack_naming = 0
        else:
            prefix_mode = ray.PrefixMode.CLIENT_NAME
            jack_naming = 1

        custom_prefix = ''
        client_id = ""
        start_it = 1

        if len(osp.args) == 1:
            pass

        elif osp.strings_only:
            start_it = int(bool('not_start' not in osp.args[1:]))

            if 'ray_hack' in osp.args[1:]:
                protocol = ray.Protocol.RAY_HACK

            args: tuple[str, ...] = osp.args  #type:ignore
            for arg in args:
                if arg == 'prefix_mode:client_name':
                    prefix_mode = ray.PrefixMode.CLIENT_NAME

                elif arg == 'prefix_mode:session_name':
                    prefix_mode = ray.PrefixMode.SESSION_NAME

                elif arg.startswith('prefix:'):
                    custom_prefix = arg.partition(':')[2]
                    if not custom_prefix or '/' in custom_prefix:
                        self.send(*osp.error(),
                                  ray.Err.CREATE_FAILED,
                                  "wrong custom prefix !")
                        return

                    prefix_mode = ray.PrefixMode.CUSTOM

                elif arg.startswith('client_id:'):
                    client_id = arg.partition(':')[2]
                    if not client_id.replace('_', '').isalnum():
                        self.send(*osp.error(),
                                  ray.Err.CREATE_FAILED,
                                  f"client_id {client_id} is not alphanumeric")
                        return

                    # Check if client_id already exists
                    for client in self.clients + self.trashed_clients:
                        if client.client_id == client_id:
                            self.send(*osp.error(),
                                ray.Err.CREATE_FAILED,
                                "client_id %s is already used" % client_id)
                            return

                elif arg.startswith('jack_naming:'):
                    str_jack_naming = arg.partition(':')[2]
                    if str_jack_naming.lower() in ('1', 'long'):
                        jack_naming = 1

        else:
            osp_args: tuple[str, int, int, int, str, str, int] = \
                osp.args  #type:ignore
            executable, start_it, protocol_int, \
                prefix_mode_int, custom_prefix, client_id, jack_naming = osp_args

            protocol = ray.Protocol(protocol_int)
            prefix_mode = ray.PrefixMode(prefix_mode_int)

            if prefix_mode is ray.PrefixMode.CUSTOM and not custom_prefix:
                if old_defaults:
                    prefix_mode = ray.PrefixMode.SESSION_NAME
                else:
                    prefix_mode = ray.PrefixMode.CLIENT_NAME

            client_id: str

            if client_id:
                if not client_id.replace('_', '').isalnum():
                    self.send(*osp.error(), ray.Err.CREATE_FAILED,
                      _translate("error", "client_id %s is not alphanumeric")
                        % client_id)
                    return

                # Check if client_id already exists
                for client in self.clients + self.trashed_clients:
                    if client.client_id == client_id:
                        self.send(*osp.error(),
                          ray.Err.CREATE_FAILED,
                          _translate("error", "client_id %s is already used")
                            % client_id)
                        return

        if not client_id:
            client_id = self.generate_client_id(executable)

        client = Client(self)

        client.protocol = protocol
        client.executable = executable
        client.name = os.path.basename(executable)
        client.client_id = client_id
        client.prefix_mode = prefix_mode
        client.custom_prefix = custom_prefix
        client.set_default_git_ignored(executable)
        client.jack_naming = ray.JackNaming(jack_naming)

        if self._add_client(client):
            if start_it:
                client.start()

            reply_str = client.client_id
            if osp.path.startswith('/nsm/server/'):
                reply_str = "Launched."

            self.send(*osp.reply(), reply_str)
        else:
            self.send(*osp.error(), ray.Err.NOT_NOW,
                      "Impossible to add client now")

    @manage(r.session.ADD_CLIENT_TEMPLATE, 'iss*')
    def _ray_session_add_client_template(self, osp: OscPack):
        if self.path is None:
            self.send(*osp.error(), ray.Err.NO_SESSION_OPEN,
                      "Cannot add to session because no session is loaded.")
            return

        if self.steps_order or self.file_copier.active:
            self.send(*osp.error(), ray.Err.NOT_NOW, "Session is busy")
            return

        osp_args: tuple[int, str] = osp.args # type:ignore
        rest: list[str]
        factory, template_name, *rest = osp_args
        factory = bool(factory)
        auto_start, unique_id = False, ''
        if len(rest) >= 1:
            auto_start = bool(rest[0] != 'not_start')
        if len(rest) >= 2:
            unique_id = rest[1]

        if unique_id:
            if not unique_id.replace('_', '').isalnum():
                self.send(*osp.error(),
                          ray.Err.CREATE_FAILED,
                          f"client_id {unique_id} is not alphanumeric")
                return

            # Check if client_id already exists
            for client in self.clients + self.trashed_clients:
                if client.client_id == unique_id:
                    self.send(
                        *osp.error(),
                        ray.Err.CREATE_FAILED,
                        f"client_id {unique_id} is already used")
                    return

        self.steps_order = [
            sop.AddClientTemplate(
                self, template_name, factory,
                auto_start=auto_start, unique_id=unique_id, osp=osp)]

        self.next_function()

    @manage(r.session.ADD_FACTORY_CLIENT_TEMPLATE, 'ss*')
    def _ray_session_add_factory_client_template(self, osp: OscPack):
        osp.args = [1] + osp.args #type:ignore
        self._ray_session_add_client_template(osp)

    @manage(r.session.ADD_USER_CLIENT_TEMPLATE, 'ss*')
    def _ray_session_add_user_client_template(self, osp: OscPack):
        osp.args = [0] + osp.args #type:ignore
        self._ray_session_add_client_template(osp)

    @session_operation(r.session.ADD_OTHER_SESSION_CLIENT, 'ss')
    def _ray_session_add_other_session_client(self, osp: OscPack):
        osp_args: tuple[str, str] = osp.args #type:ignore
        other_session, client_id = osp_args    

        dummy_session = DummySession(self.root)
        dummy_session.dummy_load(other_session)
        
        # hopefully for a dummy session,
        # there is nothing to wait to have a loaded session
        # This is quite dirty but so easier

        if dummy_session.path is None:
            self.send(
                *osp.error(), ray.Err.NOT_NOW,
                f'failed to load temporary other session {other_session}')
            return
        
        for client in dummy_session.clients:
            if client.client_id == client_id:
                break
        else:
            self.send(
                *osp.error(), ray.Err.NO_SUCH_FILE,
                f'no client {client_id} found in session {other_session}')
            return

        self.steps_order = [sop.AddOtherSessionClient(self, client, osp=osp)]

    @manage(r.session.REORDER_CLIENTS, 'ss*')
    def _ray_session_reorder_clients(self, osp: OscPack):
        client_ids_list: list[str, ...] = osp.args  #type:ignore

        if self.path is None:
            self.send(*osp.error(), ray.Err.NO_SESSION_OPEN,
                      "no session to reorder clients")

        if len(self.clients) < 2:
            self.send(*osp.reply(), "clients reordered")
            return

        self._re_order_clients(client_ids_list, osp)

    @manage(r.session.CLEAR_CLIENTS, 's*')
    def _ray_session_clear_clients(self, osp: OscPack):
        if not self.load_locked:
            self.send(*osp.error(), ray.Err.NOT_NOW,
                "clear_clients has to be used only during the load script !")
            return

        self.clear_clients(osp)

    @manage(r.session.LIST_SNAPSHOTS, '')
    def _ray_session_list_snapshots(self, osp: OscPack, client_id=""):
        if self.path is None:
            self.send(*osp.error(), ray.Err.NO_SESSION_OPEN,
                      "no session to list snapshots")
            return

        auto_snapshot = not self.snapshoter.is_auto_snapshot_prevented()
        self.send_gui(rg.session.AUTO_SNAPSHOT, int(auto_snapshot))

        snapshots = self.snapshoter.list(client_id)

        i = 0
        snap_send = list[str]()

        for snapshot in snapshots:
            if i == 20:
                self.send(*osp.reply(), *snap_send)

                snap_send.clear()
                i = 0
            else:
                snap_send.append(snapshot)
                i += 1

        if snap_send:
            self.send(*osp.reply(), *snap_send)
        self.send(*osp.reply())

    @manage(r.session.SET_AUTO_SNAPSHOT, 'i')
    def _ray_session_set_auto_snapshot(self, osp: OscPack):
        self.snapshoter.set_auto_snapshot(bool(osp.args[0]))

    @manage(r.session.LIST_CLIENTS, 's*')
    def _ray_session_list_clients(self, osp: OscPack):
        if self.path is None:
            self.send(*osp.error(), ray.Err.NO_SESSION_OPEN,
                      _translate('GUIMSG', 'No session to list clients !'))
            return

        f_started = -1
        f_active = -1
        f_auto_start = -1
        f_no_save_level = -1

        search_properties = list[tuple[int, str]]()

        osp_args: tuple[str, ...] = osp.args #type:ignore
        for arg in osp_args:
            cape = 1
            if arg.startswith('not_'):
                cape = 0
                arg = arg.replace('not_', '', 1)

            match arg:
                case s if ':' in s:
                    search_properties.append((cape, arg))
                case 'started':
                    f_started = cape
                case 'active':
                    f_active = cape
                case 'auto_start':
                    f_auto_start = cape
                case 'no_save_level':
                    f_no_save_level = cape

        client_id_list = list[str]()

        for client in self.clients:
            if ((f_started < 0 or f_started == client.is_running)
                and (f_active < 0 or f_active == client.nsm_active)
                and (f_auto_start < 0 or f_auto_start == client.auto_start)
                and (f_no_save_level < 0
                     or f_no_save_level == int(bool(
                         client.relevant_no_save_level())))):
                if search_properties:
                    message = client.get_properties_message()

                    for cape, search_prop in search_properties:
                        line_found = False

                        for line in message.split('\n'):
                            if line == search_prop:
                                line_found = True
                                break

                        if cape != line_found:
                            break
                    else:
                        client_id_list.append(client.client_id)
                else:
                    client_id_list.append(client.client_id)

        if client_id_list:
            self.send(*osp.reply(), *client_id_list)
        self.send(*osp.reply())

    @manage(r.session.LIST_TRASHED_CLIENTS, '')
    def _ray_session_list_trashed_clients(self, osp: OscPack):
        client_id_list = [tc.client_id for tc in self.trashed_clients]
        if client_id_list:
            self.send(*osp.reply(), *client_id_list)
        self.send(*osp.reply())

    @manage(r.session.RUN_STEP, 's*')
    def _ray_session_run_step(self, osp: OscPack):
        if not self.step_scripter.is_running():
            self.send(*osp.error(), ray.Err.GENERAL_ERROR,
              'No stepper script running, run run_step from session scripts')
            return

        if self.step_scripter.stepper_has_called():
            self.send(*osp.error(), ray.Err.GENERAL_ERROR,
             'step already done. Run run_step only one time in the script')
            return

        if not self.steps_order:
            self.send(*osp.error(), ray.Err.GENERAL_ERROR,
                      'No operation pending !')
            return

        self.run_step_addr = osp.src_addr
        self.next_function(True, osp.args)

    @client_action(r.client.STOP, 's')
    def _ray_client_stop(self, osp: OscPack, client:Client):
        client.stop(osp)

    @client_action(r.client.KILL, 's')
    def _ray_client_kill(self, osp: OscPack, client:Client):
        client.kill()
        self.send(*osp.reply(), "Client killed.")

    @client_action(r.client.TRASH, 's')
    def _ray_client_trash(self, osp: OscPack, client:Client):
        if client.is_running:
            self.send(*osp.error(), ray.Err.OPERATION_PENDING,
                        "Stop client before to trash it !")
            return

        if self.file_copier.is_active(client.client_id):
            self.file_copier.abort()
            self.send(*osp.error(), ray.Err.COPY_RUNNING,
                        "Files were copying for this client.")
            return

        self._trash_client(client)

        self.send(*osp.reply(), "Client removed.")

    @manage(r.client.START, 's')
    def _ray_client_start(self, osp: OscPack):
        self._ray_client_resume(osp) #type:ignore

    @client_action(r.client.RESUME, 's')
    def _ray_client_resume(self, osp: OscPack, client:Client):
        if client.is_running:
            self.send_gui_message(
                _translate('GUIMSG', 'client %s is already running.')
                    % client.gui_msg_style)

            # make ray_control exit code 0 in this case
            self.send(*osp.reply(), 'client running')
            return

        if self.file_copier.is_active(client.client_id):
            self.send_error_copy_running(osp)
            return

        client.start(osp)

    @client_action(r.client.OPEN, 's')
    def _ray_client_open(self, osp: OscPack, client:Client):
        if self.file_copier.is_active(client.client_id):
            self.send_error_copy_running(osp)
            return

        if client.nsm_active:
            self.send_gui_message(
                _translate('GUIMSG', 'client %s is already active.')
                    % client.gui_msg_style)

            # make ray_control exit code 0 in this case
            self.send(*osp.reply(), 'client active')
        else:
            client.load(osp)

    @client_action(r.client.SAVE, 's')
    def _ray_client_save(self, osp: OscPack, client:Client):
        if client.can_save_now():
            if self.file_copier.is_active(client.client_id):
                self.send_error_copy_running(osp)
                return
            client.save(osp)
        else:
            self.send_gui_message(_translate('GUIMSG', "%s is not saveable.")
                                    % client.gui_msg_style)
            self.send(*osp.reply(), 'client saved')

    @client_action(r.client.SAVE_AS_TEMPLATE, 'ss')
    def _ray_client_save_as_template(self, osp: OscPack, client: Client):
        template_name: str = osp.args[1] #type:ignore

        if self.file_copier.is_active():
            self.send_error_copy_running(osp)
            return

        self.steps_osp = osp
        self.steps_order = [
            sop.SaveClientAsTemplate(self, client, template_name, osp=osp)]
        
        self.next_function()

    @client_action(r.client.SHOW_OPTIONAL_GUI, 's')
    def _ray_client_show_optional_gui(self, osp: OscPack, client:Client):
        client.send_to_self_address(nsm.client.SHOW_OPTIONAL_GUI)
        self.send(*osp.reply(), 'show optional GUI asked')

    @client_action(r.client.HIDE_OPTIONAL_GUI, 's')
    def _ray_client_hide_optional_gui(self, osp: OscPack, client:Client):
        client.send_to_self_address(nsm.client.HIDE_OPTIONAL_GUI)
        self.send(*osp.reply(), 'hide optional GUI asked')

    @client_action(r.client.UPDATE_PROPERTIES, ray.ClientData.ARG_TYPES)
    def _ray_client_update_properties(self, osp: OscPack, client:Client):
        client.update_secure(*osp.args)
        client.send_gui_client_properties()
        self.send(*osp.reply(), 'client properties updated')

    @client_action(r.client.UPDATE_RAY_HACK_PROPERTIES, 's' + ray.RayHack.ARG_TYPES)
    def _ray_client_update_ray_hack_properties(self, osp: OscPack, client:Client):
        if client.is_ray_hack:
            client.ray_hack.update(*osp.args[1:])

        self.send(*osp.reply(), 'ray_hack updated')

    @client_action(r.client.UPDATE_RAY_NET_PROPERTIES, 's' + ray.RayNet.ARG_TYPES)
    def _ray_client_update_ray_net_properties(self, osp: OscPack, client:Client):
        if client.is_ray_net:
            client.ray_net.update(*osp.args[1:])
        self.send(*osp.reply(), 'ray_net updated')

    @client_action(r.client.SET_PROPERTIES, 'sss*')
    def _ray_client_set_properties(self, osp: OscPack, client:Client):
        message = ''
        for arg in osp.args[1:]:
            message += "%s\n" % arg

        client.set_properties_from_message(message)
        self.send(*osp.reply(),
                    'client properties updated')

    @client_action(r.client.GET_PROPERTIES, 's')
    def _ray_client_get_properties(self, osp: OscPack, client:Client):
        message = client.get_properties_message()
        self.send(*osp.reply(), message)
        self.send(*osp.reply())

    @client_action(r.client.GET_DESCRIPTION, 's')
    def _ray_client_get_description(self, osp: OscPack, client:Client):
        self.send(*osp.reply(), client.description)
        self.send(*osp.reply())

    @client_action(r.client.SET_DESCRIPTION, 'ss')
    def _ray_client_set_description(self, osp: OscPack, client:Client):
        description: str = osp.args[1] #type:ignore
        client.description = description
        self.send(*osp.reply(), 'Description updated')

    @client_action(r.client.LIST_FILES, 's')
    def _ray_client_list_files(self, osp: OscPack, client:Client):
        self.send(*osp.reply(),
                  *[str(c) for c in client.project_files])
        self.send(*osp.reply())

    @client_action(r.client.GET_PID, 's')
    def _ray_client_get_pid(self, osp: OscPack, client:Client):
        if client.is_running:
            self.send(*osp.reply(), str(client.pid))
            self.send(*osp.reply())
        else:
            self.send(*osp.error(), ray.Err.NOT_NOW,
                "client is not running, impossible to get its pid")

    @manage(r.client.LIST_SNAPSHOTS, 's')
    def _ray_client_list_snapshots(self, osp: OscPack):
        client_id: str = osp.args[0] #type:ignore
        self._ray_session_list_snapshots(osp, client_id)

    @session_operation(r.client.OPEN_SNAPSHOT, 'ss')
    def _ray_client_open_snapshot(self, osp: OscPack):
        osp_args: tuple[str, str] = osp.args #type:ignore
        client_id, snapshot = osp_args

        for client in self.clients:
            if client.client_id == client_id:
                if client.is_running:
                    self.steps_order = [
                        sop.Save(self),
                        sop.SaveSnapshot(self, rewind_snapshot=snapshot, force=True),
                        self.before_close_client_for_snapshot,
                        (self.close_client, client),
                        sop.LoadSnapshot(self, snapshot, client_id=client_id),
                        (self.start_client, client),
                        self.load_client_snapshot_done]
                else:
                    self.steps_order = [
                        sop.Save(self),
                        sop.SaveSnapshot(self, rewind_snapshot=snapshot, force=True),
                        sop.LoadSnapshot(self, snapshot, client_id=client_id),
                        self.load_client_snapshot_done]
                break
        else:
            self.send_error_no_client(osp, client_id)

    @client_action(r.client.IS_STARTED, 's')
    def _ray_client_is_started(self, osp: OscPack, client:Client):
        if client.is_running:
            self.send(*osp.reply(), 'client running')
        else:
            self.send(*osp.error(), ray.Err.GENERAL_ERROR,
                      _translate('GUIMSG', '%s is not running.')
                        % client.gui_msg_style)

    @client_action(r.client.SEND_SIGNAL, 'si')
    def _ray_client_send_signal(self, osp: OscPack, client:Client):
        sig: int = osp.args[1] #type:ignore
        client.send_signal(sig, osp.src_addr, osp.path)

    @client_action(r.client.SET_CUSTOM_DATA, 'sss')
    def _ray_client_set_custom_data(self, osp: OscPack, client:Client):
        osp_args: tuple[str, str, str] = osp.args #type:ignore
        client_id, data, value = osp_args
        client.custom_data[data] = value
        self.send(*osp.reply(), 'custom data set')

    @client_action(r.client.GET_CUSTOM_DATA, 'ss')
    def _ray_client_get_custom_data(self, osp: OscPack, client:Client):
        data: str = osp.args[1] #type:ignore

        if data not in client.custom_data:
            self.send(*osp.error(), ray.Err.NO_SUCH_FILE,
                        "client %s has no custom_data key '%s'"
                        % (client.client_id, data))
            return

        self.send(*osp.reply(), client.custom_data[data])
        self.send(*osp.reply())

    @client_action(r.client.SET_TMP_DATA, 'sss')
    def _ray_client_set_tmp_data(self, osp: OscPack, client:Client):
        osp_args: tuple[str, ...] = osp.args # type:ignore
        client_id, data, value = osp_args
        client.custom_tmp_data[data] = value
        self.send(*osp.reply(), 'custom tmp data set')

    @client_action(r.client.GET_TMP_DATA, 'ss')
    def _ray_client_get_tmp_data(self, osp: OscPack, client:Client):
        data: str = osp.args[1] # type:ignore

        if data not in client.custom_tmp_data:
            self.send(*osp.error(), ray.Err.NO_SUCH_FILE,
                      "client %s has no tmp_custom_data key '%s'"
                        % (client.client_id, data))
            return

        self.send(*osp.reply(), client.custom_tmp_data[data])
        self.send(*osp.reply())

    @client_action(r.client.CHANGE_PREFIX, 'si|ss|sis|sss')
    def _ray_client_change_prefix(self, osp: OscPack, client:Client):
        if client.is_running:
            self.send(*osp.error(), ray.Err.NOT_NOW,
                      "impossible to change prefix while client is running")
            return

        prefix_mode = ray.PrefixMode(osp.args[1])
        custom_prefix = ''

        if prefix_mode is ray.PrefixMode.CUSTOM:
            custom_prefix: str = osp.args[2] #type:ignore
            if not custom_prefix:
                self.send(
                    *osp.error(), ray.Err.GENERAL_ERROR,
                    "You need to specify a custom prefix as 2nd argument")
                return

        client.change_prefix(prefix_mode, custom_prefix)
        
        # we need to save session file here
        # else, if session is aborted
        # client won't find its files at next restart
        self._save_session_file()

        self.send(*osp.reply(), 'prefix changed')

    @client_action(r.client.CHANGE_ADVANCED_PROPERTIES, 'ssisi')
    def _ray_client_change_advanced_properties(
            self, osp: OscPack, client: Client):
        if client.is_running:
            self.send(*osp.error(), ray.Err.NOT_NOW,
                      "impossible to change id while client is running")
            return

        osp_args: tuple[str, str, int, str, int] = osp.args #type:ignore
        client_id, new_client_id, prefix_mode_int, \
            custom_prefix, jack_naming =  osp_args

        if new_client_id != client.client_id:
            if new_client_id in [c.client_id for c in
                                 self.clients + self.trashed_clients]:
                self.send(*osp.error(), ray.Err.BLACKLISTED,
                        f"client id '{new_client_id}' already exists in the session")
                return

        prefix_mode = ray.PrefixMode(prefix_mode_int)

        if prefix_mode is ray.PrefixMode.CUSTOM and not custom_prefix:
            self.send(*osp.error(), ray.Err.BAD_PROJECT,
                      "Custom prefix is missing !")
            return

        tmp_client = Client(self)
        tmp_client.eat_attributes(client)
        tmp_client.client_id = new_client_id
        tmp_client.prefix_mode = prefix_mode
        tmp_client.custom_prefix = custom_prefix
        tmp_client.jack_naming = ray.JackNaming(jack_naming)
        
        client.set_status(ray.ClientStatus.REMOVED)
        
        if self.path is None:
            raise NoSessionPath
        
        client._rename_files(
            self.path,
            self.name, self.name,
            client.prefix, tmp_client.prefix,
            client.client_id, tmp_client.client_id,
            client.links_dirname, tmp_client.links_dirname)

        ex_jack_name = client.jack_client_name
        ex_client_id = client.client_id
        new_jack_name = tmp_client.jack_client_name

        client.client_id = new_client_id
        client.prefix_mode = prefix_mode
        client.custom_prefix = custom_prefix
        client.jack_naming = ray.JackNaming(jack_naming)
        self._update_forbidden_ids_set()

        if new_jack_name != ex_jack_name:
            rewrite_jack_patch_files(
                self, ex_client_id, new_client_id,
                ex_jack_name, new_jack_name)
            self.canvas_saver.client_jack_name_changed(
                ex_jack_name, new_jack_name)

        client.sent_to_gui = False
        client.send_gui_client_properties()
        self.send_gui(rg.session.SORT_CLIENTS,
                      *[c.client_id for c in self.clients])

        # we need to save session file here
        # else, if session is aborted
        # client won't find its files at next restart
        self._save_session_file()

        self.send_monitor_event('id_changed_to:' + new_client_id, ex_client_id)
        self.send(*osp.reply(), 'client id changed')

    @client_action(r.client.FULL_RENAME, 'ss')
    def _ray_client_full_rename(self, osp: OscPack, client: Client):
        if self.steps_order:
            self.send(*osp.error(), ray.Err.NOT_NOW,
                      "Session is not ready for full client rename")
            return
        
        new_client_name: str = osp.args[1] # type:ignore
        new_client_id = new_client_name.replace(' ', '_')

        if not new_client_id or not new_client_id.replace('_', '').isalnum():
            self.send(*osp.error(), ray.Err.BAD_PROJECT,
                      f'client_id {new_client_id} is not alphanumeric')
            return

        if new_client_id in self.forbidden_ids_set:
            self.send(*osp.error(), ray.Err.BAD_PROJECT,
                      f'client_id {new_client_id} is forbidden in this session')
            return

        if client.is_running:
            if client.status is not ray.ClientStatus.READY:
                self.send(*osp.error(), ray.Err.NOT_NOW,
                          f'client_id {new_client_id} is not ready')
                return

            elif client.can_switch:
                self.steps_order = [
                    (self.save_client_and_patchers, client),
                    (self.rename_full_client, client,
                     new_client_name, new_client_id),
                    (self.switch_client, client),
                    (self.rename_full_client_done, client)]
            else:
                self.steps_order = [
                    (self.save_client_and_patchers, client),
                    (self.close_client, client),
                    (self.rename_full_client, client,
                     new_client_name, new_client_id),
                    (self.restart_client, client),
                    (self.rename_full_client_done, client)
                ]
        else:
            self.steps_order = [
                (self.rename_full_client, client, new_client_name, new_client_id),
                (self.rename_full_client_done, client)
            ]

        self.next_function()

    @client_action(r.client.CHANGE_ID, 'ss')
    def _ray_client_change_id(self, osp: OscPack, client: Client):
        if client.is_running:
            self.send(*osp.error(), ray.Err.NOT_NOW,
                      "impossible to change id while client is running")
            return

        new_client_id: str = osp.args[1] #type:ignore
        
        if new_client_id in [c.client_id for c in
                             self.clients + self.trashed_clients]:
            self.send(*osp.error(), ray.Err.BLACKLISTED,
                      f"client id '{new_client_id}' already exists in the session")
            return
        
        if not new_client_id.replace('_', '').isalnum():
            self.send(*osp.error(), ray.Err.BAD_PROJECT,
                      f"client id {new_client_id} contains forbidden characters")
            return
        
        ex_client_id = client.client_id
        ex_jack_name = client.jack_client_name
        client.set_status(ray.ClientStatus.REMOVED)

        prefix = client.prefix
        links_dir = client.links_dirname

        if self.path is None:
            raise NoSessionPath

        client._rename_files(
            self.path,
            self.name, self.name,
            prefix, prefix,
            ex_client_id, new_client_id,
            links_dir, links_dir)

        client.client_id = new_client_id
        self._update_forbidden_ids_set()
        new_jack_name = client.jack_client_name

        if new_jack_name != ex_jack_name:
            rewrite_jack_patch_files(
                self, ex_client_id, new_client_id,
                ex_jack_name, new_jack_name)
            self.canvas_saver.client_jack_name_changed(
                ex_jack_name, new_jack_name)

        client.sent_to_gui = False
        client.send_gui_client_properties()
        self.send_gui(rg.session.SORT_CLIENTS,
                      *[c.client_id for c in self.clients])

        # we need to save session file here
        # else, if session is aborted
        # client won't find its files at next restart
        self._save_session_file()

        self.send_monitor_event('id_changed_to:' + new_client_id, ex_client_id)
        self.send(*osp.reply(), 'client id changed')
    
    @manage(r.trashed_client.RESTORE, 's')
    def _ray_trashed_client_restore(self, osp: OscPack):
        if self.path is None:
            self.send(*osp.error(), ray.Err.NO_SESSION_OPEN,
                      "Nothing in trash because no session is loaded.")
            return

        for client in self.trashed_clients:
            if client.client_id == osp.args[0]:
                if self._restore_client(client):
                    self.send(*osp.reply(), "client restored")
                else:
                    self.send(*osp.error(), ray.Err.NOT_NOW,
                              "Session is in a loading locked state")
                break
        else:
            self.send(*osp.error(), -10, "No such client.")

    @manage(r.trashed_client.REMOVE_DEFINITELY, 's')
    def _ray_trashed_client_remove_definitely(self, osp: OscPack):
        if self.path is None:
            self.send(*osp.error(), ray.Err.NO_SESSION_OPEN,
                      "Nothing in trash because no session is loaded.")
            return

        client_id: str = osp.args[0] #type:ignore

        for client in self.trashed_clients:
            if client.client_id == client_id:
                break
        else:
            self.send(*osp.error(), -10, "No such client.")
            return

        self.send_gui(rg.trash.REMOVE, client.client_id)

        for file_path in client.project_files:
            try:
                subprocess.run(['rm', '-R', file_path])
            except:
                self.send(osp.src_addr, osc_paths.MINOR_ERROR, osp.path, -10,
                          f"Error while removing client file {file_path}")
                continue

        self.trashed_clients.remove(client)
        self._save_session_file()

        self.send(*osp.reply(), "client definitely removed")
        self.send_monitor_event('removed', client_id)

    @manage(r.trashed_client.REMOVE_KEEP_FILES, 's')
    def _ray_trashed_client_remove_keep_files(self, osp: OscPack):
        if self.path is None:
            self.send(*osp.error(), ray.Err.NO_SESSION_OPEN,
                      "Nothing in trash because no session is loaded.")
            return

        client_id: str = osp.args[0] #type:ignore

        for client in self.trashed_clients:
            if client.client_id == client_id:
                break
        else:
            self.send(*osp.error(), -10, "No such client.")
            return

        self.send_gui(rg.trash.REMOVE, client.client_id)

        self.trashed_clients.remove(client)

        self.send(*osp.reply(), "client removed")
        self.send_monitor_event('removed', client_id)

    @manage(r.net_daemon.DUPLICATE_STATE, 'f')
    def _ray_net_daemon_duplicate_state(self, osp: OscPack):
        state: int = osp.args[0] #type:ignore
        for client in self.clients:
            if (client.is_ray_net
                    and client.ray_net.daemon_url
                    and are_same_osc_port(client.ray_net.daemon_url,
                                          osp.src_addr.url)):
                client.ray_net.duplicate_state = state
                client.net_daemon_copy_timer.stop()
                break
        else:
            return

        if state == 1:
            if self.wait_for is ray.WaitFor.DUPLICATE_FINISH:
                self.end_timer_if_last_expected(client)
            return

        if (self.wait_for is ray.WaitFor.DUPLICATE_START and state == 0):
            self.end_timer_if_last_expected(client)

        client.net_daemon_copy_timer.start()

    def check_recent_sessions_existing(self):
        '''remove from self.recent_sessions sessions not existing anymore'''
        recent_sessions = self.recent_sessions.get(self.root)
        if recent_sessions is None:
            return
        
        for sess in recent_sessions.copy():
            if not Path(self.root / sess / 'raysession.xml').exists():
                recent_sessions.remove(sess)

    def server_open_session_at_start(self, session_name):
        self.steps_order = [(self.preload, session_name),
                            self.take_place,
                            sop.Load(self),
                            self.load_done]
        self.next_function()

    def dummy_load_and_template(
            self, session_name: str, template_name: str, sess_root: str):
        tmp_session = self._new_dummy_session(Path(sess_root))
        tmp_session.dummy_load_and_template(session_name, template_name)

    def terminate(self):
        if self.terminated_yet:
            return

        patchbay_dmn_mng.daemon_exit()

        if self.file_copier.is_active():
            self.file_copier.abort()

        self.terminated_yet = True
        self.steps_order = [self.terminate_step_scripter,
                            sop.Close(self), self.exit_now]

        self.next_function()