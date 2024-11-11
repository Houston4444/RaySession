
import json
import os
from pathlib import Path
import subprocess
import time
from typing import TYPE_CHECKING
try:
    from liblo import Address
except ImportError:
    from pyliblo3 import Address
from PyQt5.QtCore import QCoreApplication, QProcess
from PyQt5.QtXml  import QDomDocument

import ray

from client import Client
from multi_daemon_file import MultiDaemonFile
from signaler import Signaler
from daemon_tools import (Terminal, RS, dirname,
                          is_pid_child_of, highlight_text)
from session import OperatingSession
import xdg
from patch_rewriter import rewrite_jack_patch_files

_translate = QCoreApplication.translate
signaler = Signaler.instance()


def session_operation(func):
    def wrapper(*args, **kwargs):
        if len(args) < 4:
            return

        sess, path, osc_args, src_addr, *rest = args
        
        if TYPE_CHECKING:
            assert isinstance(sess, SignaledSession)
            assert isinstance(path, str)

        if sess.steps_order:
            sess.send(src_addr, "/error", path, ray.Err.OPERATION_PENDING,
                      "An operation pending.")
            return

        if sess.file_copier.is_active():
            if path.startswith('/nsm/server/'):
                sess.send(src_addr, "/error", path, ray.Err.OPERATION_PENDING,
                      "An operation pending.")
            else:
                sess.send(src_addr, "/error", path, ray.Err.COPY_RUNNING,
                        "ray-daemon is copying files.\n"
                            + "Wait copy finish or abort copy,\n"
                            + "and restart operation !\n")
            return

        sess.remember_osc_args(path, osc_args, src_addr)

        response = func(*args, **kwargs)
        sess.next_function()

        return response
    return wrapper

def client_action(func):
    def wrapper(*args, **kwargs):
        if len(args) < 4:
            return

        sess, path, osc_args, src_addr, *rest = args
        
        if TYPE_CHECKING:
            assert isinstance(sess, SignaledSession)
            assert isinstance(osc_args, list)

        client_id: str = osc_args.pop(0)

        for client in sess.clients:
            if client.client_id == client_id:
                response = func(*args, client, **kwargs)
                break
        else:
            sess.send_error_no_client(src_addr, path, client_id)
            return

        return response
    return wrapper

# There is only one possible instance of SignaledSession
# This is not the case for Session and OperatingSession.
# This session receives signals from OSC server.
class SignaledSession(OperatingSession):
    def __init__(self, root: str):
        OperatingSession.__init__(self, root)

        signaler.osc_recv.connect(self.osc_receive)
        signaler.dummy_load_and_template.connect(self.dummy_load_and_template)

        # dict where:
        # key is a sessions root folder
        # value is a list of recent sessions
        self.recent_sessions: dict[str, list[str]] = RS.settings.value(
            'daemon/recent_sessions', {}, type=dict)
        self.check_recent_sessions_existing()

        self.preview_dummy_session = None
        self.dummy_sessions = list[DummySession]()
        self._next_session_id = 1
        
        self._folder_sizes_and_dates = []
        
        self._cache_folder_sizes_path = xdg.xdg_cache_home().joinpath(
            'RaySession', 'folder_sizes.json')

        if os.path.isfile(self._cache_folder_sizes_path):
            try:
                self._folder_sizes_and_dates = json.load(
                    self._cache_folder_sizes_path)
            except:
                # cache file load failed and this is really not strong
                pass
    
    def _get_new_dummy_session_id(self)->int:
        to_return = self._next_session_id
        self._next_session_id += 1
        return to_return

    def _new_dummy_session(self, root:str):
        new_dummy = DummySession(root, self._get_new_dummy_session_id())
        self.dummy_sessions.append(new_dummy)
        return new_dummy

    def save_folder_sizes_cache_file(self):
        cache_dir = dirname(self._cache_folder_sizes_path)
        if not os.path.exists(cache_dir):
            try:
                os.makedirs(cache_dir)
            except:
                # can't save cache file, this is really not strong
                return
        
        try:
            file = open(self._cache_folder_sizes_path, 'w')
            json.dump(self._folder_sizes_and_dates, file)
            file.close()
        except:
            # cache file save failed, not strong
            pass

    def osc_receive(self, path, args, types, src_addr):
        nsm_equivs = {"/nsm/server/add" : "/ray/session/add_executable",
                      "/nsm/server/save": "/ray/session/save",
                      "/nsm/server/open": "/ray/server/open_session",
                      "/nsm/server/new" : "/ray/server/new_session",
                      "/nsm/server/duplicate": "/ray/session/duplicate",
                      "/nsm/server/close": "/ray/session/close",
                      "/nsm/server/abort": "/ray/session/abort",
                      "/nsm/server/quit" : "/ray/server/quit"}
                      # /nsm/server/list is not used here because it doesn't
                      # works as /ray/server/list_sessions
        nsm_path = nsm_equivs.get(path)
        func_path = nsm_path if nsm_path else path

        func_name = func_path.replace('/', '_')

        if func_name in self.__dir__():
            function = self.__getattribute__(func_name)
            function(path, args, src_addr)

    def send_error_no_client(self, src_addr, path, client_id):
        self.send(src_addr, "/error", path, ray.Err.CREATE_FAILED,
                  _translate('GUIMSG', "No client with this client_id:%s")
                    % client_id)

    def send_error_copy_running(self, src_addr, path):
        self.send(src_addr, "/error", path, ray.Err.COPY_RUNNING,
                  _translate('GUIMSG', "Impossible, copy running !"))

    ############## FUNCTIONS CONNECTED TO SIGNALS FROM OSC ###################

    def _nsm_server_announce(self, path: str, args, src_addr):
        client_name, capabilities, executable_path, major, minor, pid = args

        if self.wait_for == ray.WaitFor.QUIT:
            if path.startswith('/nsm/server/'):
                # Error is wrong but compatible with NSM API
                self.send(src_addr, "/error", path, ray.Err.NO_SESSION_OPEN,
                          "Sorry, but there's no session open "
                          + "for this application to join.")
            return

        # we can't be absolutely sure that the announcer is the good one
        # but if client announce a known PID,
        # we can be sure of which client is announcing

        for client in self.clients:
            if client.pid == pid and not client.nsm_active and client.is_running():
                client.server_announce(path, args, src_addr, False)
                break
        else:
            for client in self.clients:
                if (not client.nsm_active and client.is_running()
                        and is_pid_child_of(pid, client.pid)):
                    client.server_announce(path, args, src_addr, False)
                    break
            else:
                for client in self.clients:
                    if (client.launched_in_terminal
                            and client.process_drowned
                            and client.executable_path == executable_path):
                        # when launched in terminal
                        # the client process can be stopped
                        # because the terminal process is 'linked' to an existing instance
                        # then, we may can say this stopped client is the good one,
                        # and we declare it as external because we won't check its process
                        # state with QProcess.state().
                        client.server_announce(path, args, src_addr, True)
                        break
                else:
                    # Client launched externally from daemon
                    # by command : $:NSM_URL=url executable
                    client = self._new_client(executable_path)
                    self.externals_timer.start()
                    self.send_monitor_event('joined', client.client_id)
                    client.server_announce(path, args, src_addr, True)

        if self.wait_for == ray.WaitFor.ANNOUNCE:
            self.end_timer_if_last_expected(client)

    def _reply(self, path, args, src_addr):
        if self.wait_for == ray.WaitFor.QUIT:
            return

        message = args[1]
        client = self.get_client_by_address(src_addr)
        if client:
            client.set_reply(ray.Err.OK, message)

            server = self.get_server()
            if (server is not None
                    and server.server_status == ray.ServerStatus.READY
                    and server.options & ray.Option.DESKTOPS_MEMORY):
                self.desktops_memory.replace()
        else:
            self.message("Reply from unknown client")

    def _error(self, path, args, src_addr):
        path, errcode, message = args

        client = self.get_client_by_address(src_addr)
        if client:
            client.set_reply(errcode, message)

            if self.wait_for == ray.WaitFor.REPLY:
                self.end_timer_if_last_expected(client)
        else:
            self.message("error from unknown client")

    def _nsm_client_label(self, path, args, src_addr):
        client = self.get_client_by_address(src_addr)
        if client:
            client.set_label(args[0])

    def _nsm_client_network_properties(self, path, args, src_addr):
        client = self.get_client_by_address(src_addr)
        if client:
            net_daemon_url, net_session_root = args
            client.set_network_properties(net_daemon_url, net_session_root)

    def _nsm_client_no_save_level(self, path, args, src_addr):
        client = self.get_client_by_address(src_addr)
        if client and client.is_capable_of(':warning-no-save:'):
            client.no_save_level = args[0]

            self.send_gui('/ray/gui/client/no_save_level',
                           client.client_id, client.no_save_level)

    def _ray_server_ask_for_patchbay(self, path, args, src_addr):
        # if we are here, this means we need a patchbay to osc to run
        server = self.get_server()
        if server is None:
            return
        QProcess.startDetached('ray-jackpatch_to_osc',
                               [str(server.port), src_addr.url])

    def _ray_server_abort_copy(self, path, args, src_addr):
        self.file_copier.abort()

    def _ray_server_abort_parrallel_copy(self, path, args, src_addr):
        session_id = args[0]
        
        for dummy_session in self.dummy_sessions:
            if dummy_session.session_id == session_id:
                dummy_session.file_copier.abort()
                break
        self.send(src_addr, '/reply', path, 'Parrallel copy aborted')

    def _ray_server_abort_snapshot(self, path, args, src_addr):
        self.snapshoter.abort()

    def _ray_server_change_root(self, path, args, src_addr):
        session_root = args[0]
        if self.path:
            self.send(src_addr, '/error', path, ray.Err.SESSION_LOCKED,
                      "impossible to change root. session %s is loaded"
                      % self.path)
            return

        if not os.path.exists(session_root):
            try:
                os.makedirs(session_root)
            except:
                self.send(src_addr, '/error', path, ray.Err.CREATE_FAILED,
                          "invalid session root !")
                return

        if not os.access(session_root, os.W_OK):
            self.send(src_addr, '/error', path, ray.Err.CREATE_FAILED,
                      "unwriteable session root !")
            return

        self.root = session_root

        multi_daemon_file = MultiDaemonFile.get_instance()
        if multi_daemon_file:
            multi_daemon_file.update()

        self.send(src_addr, '/reply', path,
                  "root folder changed to %s" % self.root)
        self.send_gui('/ray/gui/server/root', self.root)

        if self.root not in self.recent_sessions.keys():
            self.recent_sessions[self.root] = []
        self.send_gui('/ray/gui/server/recent_sessions',
                       *self.recent_sessions[self.root])

    def _ray_server_list_client_templates(self, path, args, src_addr):
        # def send_gui_template_update(template_dict: dict):
        #     template_name = template_dict['template_name']
        #     template_client = template_dict['template_client']
        #     display_name = template_dict['display_name']
            
        #     self.send_gui(
        #         '/ray/gui/client_template_update',
        #         int(factory), template_name, display_name,
        #         *template_client.spread())
        #     if template_client.protocol == ray.Protocol.RAY_HACK:
        #         self.send_gui(
        #             '/ray/gui/client_template_ray_hack_update',
        #             int(factory), template_name,
        #             *template_client.ray_hack.spread())
        #     elif template_client.protocol == ray.Protocol.RAY_NET:
        #         self.send_gui(
        #             '/ray/gui/client_template_ray_net_update',
        #             int(factory), template_name,
        #             *template_client.ray_net.spread())
        
        # if src_addr is an announced ray GUI
        # server will send it all templates properties
        # else, server replies only templates names
        src_addr_is_gui = False
        server = self.get_server()
        if server is not None:
            src_addr_is_gui = server.is_gui_address(src_addr)

        template_names = set()
        filters = args

        factory = bool('factory' in path)
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

        self.send(src_addr, '/reply', path, *template_names)
        
        if src_addr_is_gui:
            for app_template in templates_database:
                template_name = app_template.template_name
                template_client = app_template.template_client
                display_name = app_template.display_name
                
                self.send_gui(
                    '/ray/gui/client_template_update',
                    int(factory), template_name, display_name,
                    *template_client.spread())

                if template_client.protocol == ray.Protocol.RAY_HACK:
                    self.send_gui(
                        '/ray/gui/client_template_ray_hack_update',
                        int(factory), template_name,
                        *template_client.ray_hack.spread())
                elif template_client.protocol == ray.Protocol.RAY_NET:
                    self.send_gui(
                        '/ray/gui/client_template_ray_net_update',
                        int(factory), template_name,
                        *template_client.ray_net.spread())

        self.send(src_addr, '/reply', path)

    def _ray_server_list_factory_client_templates(self, path, args, src_addr):
        self._ray_server_list_client_templates(path, args, src_addr)

    def _ray_server_list_user_client_templates(self, path, args, src_addr):
        self._ray_server_list_client_templates(path, args, src_addr)

    def _ray_server_list_sessions(self, path, args, src_addr):
        with_net = False
        last_sent_time = time.time()

        if args:
            with_net = args[0]

        if with_net:
            for client in self.clients:
                if (client.protocol == ray.Protocol.RAY_NET
                        and client.ray_net.daemon_url):
                    self.send(Address(client.ray_net.daemon_url),
                              '/ray/server/list_sessions', 1)

        if not self.root:
            self.send(src_addr, '/error', path, ray.Err.GENERAL_ERROR,
                      "no session root, so no sessions to list")
            return

        session_list = []
        sessions_set = set()
        n = 0

        for root, dirs, files in os.walk(self.root):
            #exclude hidden files and dirs
            files = [f for f in files if not f.startswith('.')]
            dirs[:] = [d for d in dirs  if not d.startswith('.')]

            if root == self.root:
                continue

            for file in files:
                if file in ('raysession.xml', 'session.nsm'):
                    # prevent search in sub directories
                    dirs.clear()

                    basefolder = root.replace(self.root + '/', '', 1)
                    session_list.append(basefolder)
                    sessions_set.add(basefolder)
                    n += len(basefolder)

                    if n >= 10000 or time.time() - last_sent_time > 0.300:
                        last_sent_time = time.time()
                        self.send(src_addr, "/reply", path, *session_list)

                        session_list.clear()
                        n = 0
                    break

        if session_list:
            self.send(src_addr, "/reply", path, *session_list)

        self.send(src_addr, "/reply", path)
        
        search_scripts_dir = self.root
        has_general_scripts = False
        
        while search_scripts_dir and not search_scripts_dir != '/':
            if os.path.isdir(search_scripts_dir + '/' + ray.SCRIPTS_DIR):
                has_general_scripts = True
                break
            search_scripts_dir = dirname(search_scripts_dir)

        locked_sessions = []
        multi_daemon_file = MultiDaemonFile.get_instance()
        if multi_daemon_file is not None:
            locked_sessions = multi_daemon_file.get_all_session_paths()

        for root, dirs, files in os.walk(self.root):
            #exclude hidden files and dirs
            files = [f for f in files if not f.startswith('.')]
            dirs[:] = [d for d in dirs  if not d.startswith('.')]

            if root == self.root:
                if has_general_scripts:
                    self.send(src_addr, '/ray/gui/listed_session/scripted_dir',
                              '', ray.ScriptFile.PARENT)
                continue
            
            basefolder = root.replace(self.root + '/', '', 1)
            
            if ray.SCRIPTS_DIR in dirs:
                script_files = ray.ScriptFile.PREVENT
                
                for action in ('load', 'save', 'close'):
                    if os.access(
                            "%s/%s/%s.sh" % (root, ray.SCRIPTS_DIR, action),
                            os.X_OK):
                        script_files += ray.ScriptFile.by_string(action)

                self.send(src_addr, '/ray/gui/listed_session/scripted_dir',
                          basefolder, script_files)
            
            if basefolder not in sessions_set:
                continue

            has_notes = bool(ray.NOTES_PATH in files)
            last_modified = int(os.path.getmtime(root))
            locked = bool(root in locked_sessions)

            self.send(src_addr, '/ray/gui/listed_session/details',
                      basefolder, int(has_notes), last_modified, int(locked))

            # prevent search in sub directories
            dirs.clear()        

    def _nsm_server_list(self, path, args, src_addr):
        if self.root:
            for root, dirs, files in os.walk(self.root):
                #exclude hidden files and dirs
                files = [f for f in files if not f.startswith('.')]
                dirs[:] = [d for d in dirs  if not d.startswith('.')]

                if root == self.root:
                    continue

                for file in files:
                    if file in ('raysession.xml', 'session.nsm'):
                        basefolder = root.replace(self.root + '/', '', 1)
                        self.send(src_addr, '/reply', path, basefolder)

        self.send(src_addr, '/reply', path, "")

    @session_operation
    def _ray_server_new_session(self, path, args, src_addr):
        if len(args) == 2 and args[1]:
            session_name, template_name = args

            spath = ''
            if session_name.startswith('/'):
                spath = session_name
            else:
                spath = "%s/%s" % (self.root, session_name)

            if not os.path.exists(spath):
                self.steps_order = [self.save,
                                    self.close_no_save_clients,
                                    self.snapshot,
                                    (self.prepare_template, *args, False),
                                    (self.preload, session_name),
                                    self.close,
                                    self.take_place,
                                    self.load,
                                    self.new_done]
                return

        self.steps_order = [self.save,
                            self.close_no_save_clients,
                            self.snapshot,
                            self.close,
                            (self.new, args[0]),
                            self.save,
                            self.new_done]

    @session_operation
    def _ray_server_open_session(self, path, args, src_addr, open_off=False):
        session_name: str = args[0]
        save_previous = True
        template_name = ''

        if len(args) >= 2:
            save_previous = bool(args[1])
        if len(args) >= 3:
            template_name = args[2]

        if (not session_name
                or '//' in session_name
                or session_name.startswith(('../', '.ray-', 'ray-'))):
            self._send_error(ray.Err.CREATE_FAILED, 'invalid session name.')
            return

        if template_name:
            if '/' in template_name:
                self._send_error(ray.Err.CREATE_FAILED, 'invalid template name')
                return

        spath = ''
        if session_name.startswith('/'):
            spath = session_name
        else:
            spath = "%s/%s" % (self.root, session_name)

        if spath == self.path:
            self._send_error(ray.Err.SESSION_LOCKED,
                _translate('GUIMSG', 'session %s is already opened !')
                    % highlight_text(session_name))
            return

        multi_daemon_file = MultiDaemonFile.get_instance()
        if (multi_daemon_file
                and not multi_daemon_file.is_free_for_session(spath)):
            Terminal.warning("Session %s is used by another daemon"
                              % highlight_text(spath))

            self._send_error(ray.Err.SESSION_LOCKED,
                _translate('GUIMSG',
                    'session %s is already used by another daemon !')
                        % highlight_text(session_name))
            return

        # don't use template if session folder already exists
        if os.path.exists(spath):
            template_name = ''

        self.steps_order = []

        if save_previous:
            self.steps_order += [(self.save, True)]

        self.steps_order += [self.close_no_save_clients]

        if save_previous:
            self.steps_order += [(self.snapshot, '', '', False, True)]

        if template_name:
            self.steps_order += [(self.prepare_template, session_name,
                                 template_name, True)]

        self.steps_order += [(self.preload, session_name),
                             # if open_off, clear all clients at close
                             (self.close, open_off),
                             self.take_place,
                             (self.load, open_off),
                             self.load_done]

    def _ray_server_open_session_off(self, path, args, src_addr):
        self._ray_server_open_session(path, args, src_addr, open_off=True)

    def _ray_server_rename_session(self, path, args, src_addr):
        old_session_name, new_session_name = args
        spath = self.get_full_path(old_session_name)

        for f in 'raysession.xml', 'session.nsm':
            if os.path.isfile("%s/%s" % (spath, f)):
                break
        else:
            self.send(src_addr, '/error', path, ray.Err.BAD_PROJECT,
                      "%s is not an existing session, can't rename !"
                      % old_session_name)

        if '/' in new_session_name:
            self.send(src_addr, '/error', path, ray.Err.BAD_PROJECT,
                      "'/' is not allowed in new_session_name")
            return False

        tmp_session = self._new_dummy_session(self.root)
        tmp_session.ray_server_rename_session(path, args, src_addr)

    def _ray_server_save_session_template(self, path, args, src_addr):
        if len(args) == 2:
            session_name, template_name = args
            sess_root = self.root
            net = False
        else:
            session_name, template_name, sess_root = args
            net = True

        if (sess_root != self.root
                or session_name != self.get_short_path()):
            tmp_session = self._new_dummy_session(sess_root)
            tmp_session.ray_server_save_session_template(
                path, [session_name, template_name, net], src_addr)
            return

        self._ray_session_save_as_template(
            path, [template_name, net], src_addr)

    def _ray_server_get_session_preview(self, path, args, src_addr):
        session_name = args[0]
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
            path, args, src_addr, self._folder_sizes_and_dates)

    def _ray_server_set_option(self, path, args, src_addr):
        option = args[0]

        if abs(option) == ray.Option.BOOKMARK_SESSION:
            if self.path:
                if option > 0:
                    self.bookmarker.make_all(self.path)
                else:
                    self.bookmarker.remove_all(self.path)

    def _ray_server_patchbay_save_group_position(self, path, args, src_addr):
        self.canvas_saver.save_group_position(*args)

    def _ray_server_patchbay_save_portgroup(self, path, args, src_addr):
        self.canvas_saver.save_portgroup(*args)

    @session_operation
    def _ray_session_save(self, path, args, src_addr):        
        self.steps_order = [self.save, self.snapshot, self.save_done]

    @session_operation
    def _ray_session_save_as_template(self, path, args, src_addr):
        template_name = args[0]
        net = False if len(args) < 2 else args[1]

        for client in self.clients:
            if client.protocol == ray.Protocol.RAY_NET:
                client.ray_net.session_template = template_name

        self.steps_order = [self.save, self.snapshot,
                            (self.save_session_template,
                             template_name, net)]

    @session_operation
    def _ray_session_take_snapshot(self, path, args, src_addr):
        if not self.path:
            self.send(src_addr, '/error', path, ray.Err.NO_SESSION_OPEN,
                      'No session is loaded, impossible to take snapshot')
            return
        
        snapshot_name = ''
        with_save = 0
        
        if len(args) == 2:
            snapshot_name, with_save = args
        else:
            snapshot_name = args[0]

        self.steps_order.clear()

        if with_save:
            self.steps_order.append(self.save)
        self.steps_order += [(self.snapshot, snapshot_name, '', True),
                             self.snapshot_done]

    @session_operation
    def _ray_session_close(self, path, args, src_addr):
        self.steps_order = [(self.save, True),
                            self.close_no_save_clients,
                            self.snapshot,
                            (self.close, True),
                            self.close_done]

    def _ray_session_abort(self, path, args, src_addr):
        if not self.path:
            self.file_copier.abort()
            self.send(src_addr, "/error", path, ray.Err.NO_SESSION_OPEN,
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
            if self.osc_path.startswith('/nsm/server/'):
                short_path = self.osc_path.rpartition('/')[2]

                if short_path == 'save':
                    self.save_error(ray.Err.CREATE_FAILED)
                elif short_path == 'open':
                    self.load_error(ray.Err.SESSION_LOCKED)
                elif short_path == 'new':
                    self._send_error(ray.Err.CREATE_FAILED,
                                "Could not create the session directory")
                elif short_path == 'duplicate':
                    self.duplicate_aborted(self.osc_args[0])
                elif short_path in ('close', 'abort', 'quit'):
                    # let the current close works here
                    self.send(src_addr, "/error", path,
                              ray.Err.OPERATION_PENDING,
                              "An operation pending.")
                    return
            else:
                self._send_error(ray.Err.ABORT_ORDERED,
                               _translate('GUIMSG',
                                    'abort ordered from elsewhere, sorry !'))

        self.remember_osc_args(path, args, src_addr)
        self.steps_order = [(self.close, True), self.abort_done]

        if self.file_copier.is_active():
            self.file_copier.abort(self.next_function, [])
        else:
            self.next_function()

    def _ray_server_quit(self, path, args, src_addr):
        self.remember_osc_args(path, args, src_addr)
        self.steps_order = [self.terminate_step_scripter,
                            self.close, self.exit_now]

        if self.file_copier.is_active():
            self.file_copier.abort(self.next_function, [])
        else:
            self.next_function()

    def _ray_session_cancel_close(self, path, args, src_addr):
        if not self.steps_order:
            return

        self.timer.stop()
        self.timer_waituser_progress.stop()
        self.steps_order.clear()
        self._clean_expected()
        self.set_server_status(ray.ServerStatus.READY)

    def _ray_session_skip_wait_user(self, path, args, src_addr):
        if not self.steps_order:
            return

        self.timer.stop()
        self.timer_waituser_progress.stop()
        self._clean_expected()
        self.next_function()

    @session_operation
    def _ray_session_duplicate(self, path, args, src_addr):
        new_session_full_name: str = args[0]

        spath = ''
        if new_session_full_name.startswith('/'):
            spath = new_session_full_name
        else:
            spath = "%s/%s" % (self.root, new_session_full_name)

        if os.path.exists(spath):
            self._send_error(ray.Err.CREATE_FAILED,
                _translate('GUIMSG', "%s already exists !")
                    % highlight_text(spath))
            return

        multi_daemon_file = MultiDaemonFile.get_instance()
        if (multi_daemon_file
                and not multi_daemon_file.is_free_for_session(spath)):
            Terminal.warning("Session %s is used by another daemon"
                             % highlight_text(new_session_full_name))
            self._send_error(ray.Err.SESSION_LOCKED,
                _translate('GUIMSG',
                    'session %s is already used by this or another daemon !')
                        % highlight_text(new_session_full_name))
            return

        self.steps_order = [self.save,
                            self.close_no_save_clients,
                            self.snapshot,
                            (self.duplicate, new_session_full_name),
                            (self.preload, new_session_full_name),
                            self.close,
                            self.take_place,
                            self.load,
                            self.duplicate_done]

    def _ray_session_duplicate_only(self, path, args: list[str], src_addr):
        session_to_load, new_session, sess_root = args

        spath = ''
        if new_session.startswith('/'):
            spath = new_session
        else:
            spath = "%s/%s" % (sess_root, new_session)

        if os.path.exists(spath):
            self.send(src_addr, '/ray/net_daemon/duplicate_state', 1)
            self.send(src_addr, '/error', path, ray.Err.CREATE_FAILED,
                      _translate('GUIMSG', "%s already exists !")
                        % highlight_text(spath))
            return

        if sess_root == self.root and session_to_load == self.get_short_path():
            if (self.steps_order
                    or self.file_copier.is_active()):
                self.send(src_addr, '/ray/net_daemon/duplicate_state', 1)
                return

            self.remember_osc_args(path, args, src_addr)

            self.steps_order = [self.save,
                                self.snapshot,
                                (self.duplicate, new_session),
                                self.duplicate_only_done]

            self.next_function()

        else:
            tmp_session = self._new_dummy_session(sess_root)
            tmp_session.osc_src_addr = src_addr
            tmp_session.dummy_duplicate(path, args, src_addr)

    @session_operation
    def _ray_session_open_snapshot(self, path, args, src_addr):
        if not self.path:
            return

        snapshot = args[0]

        self.steps_order = [self.save,
                              self.close_no_save_clients,
                              (self.snapshot, '', snapshot, True),
                              (self.close, True),
                              (self.init_snapshot, self.path, snapshot),
                              (self.preload, self.path),
                              self.take_place,
                              self.load,
                              self.load_done]

    def _ray_session_rename(self, path, args, src_addr):
        new_session_name = args[0]

        if self.steps_order:
            return

        if not self.path:
            return

        if self.file_copier.is_active():
            return

        if new_session_name == self.name:
            return

        if not self.is_nsm_locked():
            for filename in os.listdir(dirname(self.path)):
                if filename == new_session_name:
                    # another directory exists with new session name
                    return

        for client in self.clients:
            if client.is_running():
                self.send_gui_message(
                    _translate('GUIMSG',
                               'Stop all clients before rename session !'))
                return

        for client in self.clients + self.trashed_clients:
            client.adjust_files_after_copy(new_session_name, ray.Template.RENAME)

        if not self.is_nsm_locked():
            try:
                spath = "%s/%s" % (dirname(self.path), new_session_name)
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
        self.send_gui('/ray/gui/session/name', self.name, self.path)

    def _ray_session_set_notes(self, path, args, src_addr):
        self.notes = args[0]
        self.send(src_addr, '/reply', path, 'Notes has been set')

    def _ray_session_get_notes(self, path, args, src_addr):
        self.send(src_addr, '/reply', path, self.notes)
        self.send(src_addr, '/reply', path)

    def _ray_session_add_executable(self, path: str, args, src_addr):
        protocol = ray.Protocol.NSM
        executable = args[0]
        via_proxy = 0
        prefix_mode = ray.PrefixMode.SESSION_NAME
        custom_prefix = ''
        client_id = ""
        start_it = 1
        jack_naming = 0

        if len(args) == 1:
            pass

        elif ray.are_they_all_strings(args):
            if TYPE_CHECKING:
                assert isinstance(args, list[str])
            
            via_proxy = int(bool('via_proxy' in args[1:]))
            start_it = int(bool('not_start' not in args[1:]))
            if 'ray_hack' in args[1:]:
                protocol = ray.Protocol.RAY_HACK

            for arg in args[1:]:
                if arg == 'prefix_mode:client_name':
                    prefix_mode = ray.PrefixMode.CLIENT_NAME

                elif arg == 'prefix_mode:session_name':
                    prefix_mode = ray.PrefixMode.SESSION_NAME

                elif arg.startswith('prefix:'):
                    custom_prefix = arg.partition(':')[2]
                    if not custom_prefix or '/' in custom_prefix:
                        self.send(src_addr, '/error', path,
                                  ray.Err.CREATE_FAILED,
                                  "wrong custom prefix !")
                        return

                    prefix_mode = ray.PrefixMode.CUSTOM

                elif arg.startswith('client_id:'):
                    client_id = arg.partition(':')[2]
                    if not client_id.replace('_', '').isalnum():
                        self.send(src_addr, '/error', path,
                                  ray.Err.CREATE_FAILED,
                                  f"client_id {client_id} is not alphanumeric")
                        return

                    # Check if client_id already exists
                    for client in self.clients + self.trashed_clients:
                        if client.client_id == client_id:
                            self.send(src_addr, '/error', path,
                                ray.Err.CREATE_FAILED,
                                "client_id %s is already used" % client_id)
                            return

                elif arg.startswith('jack_naming:'):
                    str_jack_naming = arg.partition(':')[2]
                    if str_jack_naming.lower() in ('1', 'long'):
                        jack_naming = 1

        else:
            executable, start_it, protocol, \
                prefix_mode, custom_prefix, client_id, jack_naming = args

            if prefix_mode == ray.PrefixMode.CUSTOM and not custom_prefix:
                prefix_mode = ray.PrefixMode.SESSION_NAME

            client_id: str

            if client_id:
                if not client_id.replace('_', '').isalnum():
                    self.send(src_addr, '/error', path, ray.Err.CREATE_FAILED,
                      _translate("error", "client_id %s is not alphanumeric")
                        % client_id)
                    return

                # Check if client_id already exists
                for client in self.clients + self.trashed_clients:
                    if client.client_id == client_id:
                        self.send(src_addr, '/error', path,
                          ray.Err.CREATE_FAILED,
                          _translate("error", "client_id %s is already used")
                            % client_id)
                        return

        if not client_id:
            client_id = self.generate_client_id(executable)

        client = Client(self)

        client.protocol = protocol
        if client.protocol == ray.Protocol.NSM and via_proxy:
            client.executable_path = 'ray-proxy'
        else:
            client.executable_path = executable
        client.name = os.path.basename(executable)
        client.client_id = client_id
        client.prefix_mode = prefix_mode
        client.custom_prefix = custom_prefix
        client.set_default_git_ignored(executable)
        client.jack_naming = jack_naming

        if self._add_client(client):
            if start_it:
                client.start()

            reply_str = client.client_id
            if path.startswith('/nsm/server/'):
                reply_str = "Launched."

            self.send(src_addr, '/reply', path, reply_str)
        else:
            self.send(src_addr, '/error', path, ray.Err.NOT_NOW,
                      "Impossible to add client now")

    def _ray_session_add_client_template(self, path, args, src_addr):
        if not self.path:
            self.send(src_addr, "/error", path, ray.Err.NO_SESSION_OPEN,
                      "Cannot add to session because no session is loaded.")
            return

        factory = bool(args[0])
        template_name: str = args[1]
        auto_start = bool(len(args) <= 2 or args[2] != 'not_start')
        unique_id: str = args[3] if len(args) > 3 else ''

        if unique_id:
            if not unique_id.replace('_', '').isalnum():
                self.send(src_addr, '/error', path,
                            ray.Err.CREATE_FAILED,
                            f"client_id {unique_id} is not alphanumeric")
                return

            # Check if client_id already exists
            for client in self.clients + self.trashed_clients:
                if client.client_id == unique_id:
                    self.send(src_addr, '/error', path,
                        ray.Err.CREATE_FAILED,
                        f"client_id {unique_id} is already used")
                    return

        self.add_client_template(
            src_addr, path, template_name, factory, auto_start, unique_id)

    def _ray_session_add_factory_client_template(self, path, args, src_addr):
        self._ray_session_add_client_template(path, [1] + args, src_addr)

    def _ray_session_add_user_client_template(self, path, args, src_addr):
        self._ray_session_add_client_template(path, [0] + args, src_addr)

    @session_operation
    def _ray_session_add_other_session_client(self, path, args, src_addr):
        other_session, client_id = args    

        # @session_operation remember them but this is not needed here
        self._forget_osc_args()

        dummy_session = DummySession(self.root)
        dummy_session.dummy_load(other_session)
        
        # hopefully for a dummy session,
        # there is nothing to wait to have a loaded session
        # This is quite dirty but so easier

        if not dummy_session.path:
            self.send(src_addr, '/error', path, ray.Err.NOT_NOW,
                      "falied to load other session %s" % other_session)
            return
        
        for client in dummy_session.clients:
            if client.client_id == client_id:
                new_client = Client(self)
                new_client.client_id = self.generate_client_id(
                    Client.short_client_id(client_id))

                ok = self._add_client(new_client)
                if not ok:
                    self.send(src_addr, '/error', path, ray.Err.NOT_NOW,
                              'session is busy')
                    return

                new_client.eat_other_session_client(src_addr, path, client)
                break
        else:
            self.send(src_addr, '/error', path, ray.Err.NO_SUCH_FILE,
                      'no client %s found in session %s' % (client_id, other_session))

    def _ray_session_reorder_clients(self, path, args, src_addr):
        client_ids_list = args

        if not self.path:
            self.send(src_addr, '/error', path, ray.Err.NO_SESSION_OPEN,
                      "no session to reorder clients")

        if len(self.clients) < 2:
            self.send(src_addr, '/reply', path, "clients reordered")
            return

        self._re_order_clients(client_ids_list, src_addr, path)

    def _ray_session_clear_clients(self, path, args, src_addr):
        if not self.load_locked:
            self.send(src_addr, '/error', path, ray.Err.NOT_NOW,
                "clear_clients has to be used only during the load script !")
            return

        self.clear_clients(src_addr, path, *args)

    def _ray_session_list_snapshots(self, path, args, src_addr, client_id=""):
        if not self.path:
            self.send(src_addr, '/error', path, ray.Err.NO_SESSION_OPEN,
                      "no session to list snapshots")
            return

        auto_snapshot = not self.snapshoter.is_auto_snapshot_prevented()
        self.send_gui('/ray/gui/session/auto_snapshot', int(auto_snapshot))

        snapshots = self.snapshoter.list(client_id)

        i = 0
        snap_send = []

        for snapshot in snapshots:
            if i == 20:
                self.send(src_addr, '/reply', path, *snap_send)

                snap_send.clear()
                i = 0
            else:
                snap_send.append(snapshot)
                i += 1

        if snap_send:
            self.send(src_addr, '/reply', path, *snap_send)
        self.send(src_addr, '/reply', path)

    def _ray_session_set_auto_snapshot(self, path, args, src_addr):
        self.snapshoter.set_auto_snapshot(bool(args[0]))

    def _ray_session_list_clients(self, path, args: list[str], src_addr):
        if not self.path:
            self.send(src_addr, '/error', path, ray.Err.NO_SESSION_OPEN,
                      _translate('GUIMSG', 'No session to list clients !'))
            return

        f_started = -1
        f_active = -1
        f_auto_start = -1
        f_no_save_level = -1

        search_properties = list[tuple[int, str]]()

        for arg in args:
            cape = 1
            if arg.startswith('not_'):
                cape = 0
                arg = arg.replace('not_', '', 1)

            if ':' in arg:
                search_properties.append((cape, arg))

            elif arg == 'started':
                f_started = cape
            elif arg == 'active':
                f_active = cape
            elif arg == 'auto_start':
                f_auto_start = cape
            elif arg == 'no_save_level':
                f_no_save_level = cape

        client_id_list = list[str]()

        for client in self.clients:
            if ((f_started < 0 or f_started == client.is_running())
                and (f_active < 0 or f_active == client.nsm_active)
                and (f_auto_start < 0 or f_auto_start == client.auto_start)
                and (f_no_save_level < 0
                     or f_no_save_level == int(bool(client.noSaveLevel())))):
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
            self.send(src_addr, '/reply', path, *client_id_list)
        self.send(src_addr, '/reply', path)

    def _ray_session_list_trashed_clients(self, path, args, src_addr):
        client_id_list = list[str]()

        for trashed_client in self.trashed_clients:
            client_id_list.append(trashed_client.client_id)

        if client_id_list:
            self.send(src_addr, '/reply', path, *client_id_list)
        self.send(src_addr, '/reply', path)

    def _ray_session_run_step(self, path, args, src_addr):
        if not self.step_scripter.is_running():
            self.send(src_addr, '/error', path, ray.Err.GENERAL_ERROR,
              'No stepper script running, run run_step from session scripts')
            return

        if self.step_scripter.stepper_has_called():
            self.send(src_addr, '/error', path, ray.Err.GENERAL_ERROR,
             'step already done. Run run_step only one time in the script')
            return

        if not self.steps_order:
            self.send(src_addr, '/error', path, ray.Err.GENERAL_ERROR,
                      'No operation pending !')
            return

        self.run_step_addr = src_addr
        self.next_function(True, args)

    @client_action
    def _ray_client_stop(self, path, args, src_addr, client:Client):
        client.stop(src_addr, path)

    @client_action
    def _ray_client_kill(self, path, args, src_addr, client:Client):
        client.kill()
        self.send(src_addr, "/reply", path, "Client killed.")

    @client_action
    def _ray_client_trash(self, path, args, src_addr, client:Client):
        if client.is_running():
            self.send(src_addr, '/error', path, ray.Err.OPERATION_PENDING,
                        "Stop client before to trash it !")
            return

        if self.file_copier.is_active(client.client_id):
            self.file_copier.abort()
            self.send(src_addr, '/error', path, ray.Err.COPY_RUNNING,
                        "Files were copying for this client.")
            return

        self._trash_client(client)

        self.send(src_addr, "/reply", path, "Client removed.")

    def _ray_client_start(self, path, args, src_addr):
        self._ray_client_resume(path, args, src_addr)

    @client_action
    def _ray_client_resume(self, path, args, src_addr, client:Client):
        if client.is_running():
            self.send_gui_message(
                _translate('GUIMSG', 'client %s is already running.')
                    % client.gui_msg_style())

            # make ray_control exit code 0 in this case
            self.send(src_addr, '/reply', path, 'client running')
            return

        if self.file_copier.is_active(client.client_id):
            self.send_error_copy_running(src_addr, path)
            return

        client.start(src_addr, path)

    @client_action
    def _ray_client_open(self, path, args, src_addr, client:Client):
        if self.file_copier.is_active(client.client_id):
            self.send_error_copy_running(src_addr, path)
            return

        if client.nsm_active:
            self.send_gui_message(
                _translate('GUIMSG', 'client %s is already active.')
                    % client.gui_msg_style())

            # make ray_control exit code 0 in this case
            self.send(src_addr, '/reply', path, 'client active')
        else:
            client.load(src_addr, path)

    @client_action
    def _ray_client_save(self, path, args, src_addr, client:Client):
        if client.can_save_now():
            if self.file_copier.is_active(client.client_id):
                self.send_error_copy_running(src_addr, path)
                return
            client.save(src_addr, path)
        else:
            self.send_gui_message(_translate('GUIMSG', "%s is not saveable.")
                                    % client.gui_msg_style())
            self.send(src_addr, '/reply', path, 'client saved')

    @client_action
    def _ray_client_save_as_template(self, path, args, src_addr, client:Client):
        template_name = args[0]

        if self.file_copier.is_active():
            self.send_error_copy_running(src_addr, path)
            return

        client.save_as_template(template_name, src_addr, path)

    @client_action
    def _ray_client_show_optional_gui(self, path, args, src_addr, client:Client):
        client.send_to_self_address("/nsm/client/show_optional_gui")
        client.show_gui_ordered = True
        self.send(src_addr, '/reply', path, 'show optional GUI asked')

    @client_action
    def _ray_client_hide_optional_gui(self, path, args, src_addr, client:Client):
        client.send_to_self_address("/nsm/client/hide_optional_gui")
        self.send(src_addr, '/reply', path, 'hide optional GUI asked')

    @client_action
    def _ray_client_update_properties(self, path, args, src_addr, client:Client):
        client.update_secure(client.client_id, *args)
        client.send_gui_client_properties()
        self.send(src_addr, '/reply', path, 'client properties updated')

    @client_action
    def _ray_client_update_ray_hack_properties(self, path, args,
                                               src_addr, client:Client):
        ex_no_save_level = client.noSaveLevel()

        if client.is_ray_hack():
            client.ray_hack.update(*args)

        no_save_level = client.noSaveLevel()

        if no_save_level != ex_no_save_level:
            self.send_gui('/ray/gui/client/no_save_level',
                           client.client_id, no_save_level)

        self.send(src_addr, '/reply', path, 'ray_hack updated')

    @client_action
    def _ray_client_update_ray_net_properties(self, path, args,
                                              src_addr, client:Client):
        if client.protocol == ray.Protocol.RAY_NET:
            client.ray_net.update(*args)
        self.send(src_addr, '/reply', path, 'ray_net updated')

    @client_action
    def _ray_client_set_properties(self, path, args, src_addr, client:Client):
        message = ''
        for arg in args:
            message += "%s\n" % arg

        client.set_properties_from_message(message)
        self.send(src_addr, '/reply', path,
                    'client properties updated')

    @client_action
    def _ray_client_get_properties(self, path, args, src_addr, client:Client):
        message = client.get_properties_message()
        self.send(src_addr, '/reply', path, message)
        self.send(src_addr, '/reply', path)

    @client_action
    def _ray_client_get_proxy_properties(self, path, args, src_addr,
                                         client:Client):
        proxy_file = '%s/ray-proxy.xml' % client.get_project_path()

        if not os.path.isfile(proxy_file):
            self.send(src_addr, '/error', path, ray.Err.GENERAL_ERROR,
                _translate('GUIMSG', '%s seems to not be a proxy client !')
                    % client.gui_msg_style())
            return

        try:
            file = open(proxy_file, 'r')
            xml = QDomDocument()
            xml.setContent(file.read())
            content = xml.documentElement()
            file.close()
        except:
            self.send(src_addr, '/error', path, ray.Err.BAD_PROJECT,
                _translate('GUIMSG', "impossible to read %s correctly !")
                    % proxy_file)
            return

        if content.tagName() != "RAY-PROXY":
            self.send(src_addr, '/error', path, ray.Err.BAD_PROJECT,
                _translate('GUIMSG', "impossible to read %s correctly !")
                    % proxy_file)
            return

        cte = content.toElement()
        message = ""
        for prop in ('executable', 'arguments', 'config_file',
                     'save_signal', 'stop_signal',
                     'no_save_level', 'wait_window',
                     'VERSION'):
            message += "%s:%s\n" % (prop, cte.attribute(prop))

        # remove last empty line
        message = message.rpartition('\n')[0]

        self.send(src_addr, '/reply', path, message)
        self.send(src_addr, '/reply', path)

    @client_action
    def _ray_client_set_proxy_properties(self, path, args, src_addr,
                                         client:Client):
        message = ''
        for arg in args:
            message += "%s\n" % arg

        if client.is_running():
            self.send(src_addr, '/error', path, ray.Err.GENERAL_ERROR,
              _translate('GUIMSG',
               'Impossible to set proxy properties while client is running.'))
            return

        proxy_file = '%s/ray-proxy.xml' % client.get_project_path()

        if (not os.path.isfile(proxy_file)
                and client.executable_path != 'ray-proxy'):
            self.send(src_addr, '/error', path, ray.Err.GENERAL_ERROR,
                _translate('GUIMSG', '%s seems to not be a proxy client !')
                    % client.gui_msg_style())
            return

        if os.path.isfile(proxy_file):
            try:
                file = open(proxy_file, 'r')
                xml = QDomDocument()
                xml.setContent(file.read())
                content = xml.documentElement()
                file.close()
            except:
                self.send(src_addr, '/error', path, ray.Err.BAD_PROJECT,
                    _translate('GUIMSG', "impossible to read %s correctly !")
                        % proxy_file)
                return
        else:
            xml = QDomDocument()
            p = xml.createElement('RAY-PROXY')
            p.setAttribute('VERSION', ray.VERSION)
            xml.appendChild(p)
            content = xml.documentElement()

            if not os.path.isdir(client.get_project_path()):
                try:
                    os.makedirs(client.get_project_path())
                except:
                    self.send(src_addr, '/error', path, ray.Err.CREATE_FAILED,
                              "Impossible to create proxy directory")
                    return

        if content.tagName() != "RAY-PROXY":
            self.send(src_addr, '/error', path, ray.Err.BAD_PROJECT,
                _translate('GUIMSG', "impossible to read %s correctly !")
                    % proxy_file)
            return

        cte = content.toElement()

        for line in message.split('\n'):
            prop, colon, value = line.partition(':')
            if prop in (
                    'executable', 'arguments',
                    'config_file', 'save_signal', 'stop_signal',
                    'no_save_level', 'wait_window', 'VERSION'):
                cte.setAttribute(prop, value)

        try:
            file = open(proxy_file, 'w')
            file.write(xml.toString())
            file.close()
        except:
            self.send(src_addr, '/error', path, ray.Err.BAD_PROJECT,
                _translate('GUIMSG', "%s is not writeable")
                    % proxy_file)
            return

        self.send(src_addr, '/reply', path, message)
        self.send(src_addr, '/reply', path)

    @client_action
    def _ray_client_get_description(self, path, args, src_addr, client:Client):
        self.send(src_addr, '/reply', path, client.description)
        self.send(src_addr, '/reply', path)

    @client_action
    def _ray_client_set_description(self, path, args, src_addr, client:Client):
        client.description = args[0]
        self.send(src_addr, '/reply', path, 'Description updated')

    @client_action
    def _ray_client_list_files(self, path, args, src_addr, client:Client):
        client_files = client.get_project_files()
        self.send(src_addr, '/reply', path, *client_files)
        self.send(src_addr, '/reply', path)

    @client_action
    def _ray_client_get_pid(self, path, args, src_addr, client:Client):
        if client.is_running():
            self.send(src_addr, '/reply', path, str(client.pid))
            self.send(src_addr, '/reply', path)
        else:
            self.send(src_addr, '/error', path, ray.Err.NOT_NOW,
                "client is not running, impossible to get its pid")

    def _ray_client_list_snapshots(self, path, args, src_addr):
        self._ray_session_list_snapshots(path, [], src_addr, args[0])

    @session_operation
    def _ray_client_open_snapshot(self, path, args, src_addr):
        client_id, snapshot = args

        for client in self.clients:
            if client.client_id == client_id:
                if client.is_running():
                    self.steps_order = [
                        self.save,
                        (self.snapshot, '', snapshot, True),
                        self.before_close_client_for_snapshot,
                        (self.close_client, client),
                        (self.load_client_snapshot, client_id, snapshot),
                        (self.start_client, client),
                        self.load_client_snapshot_done]
                else:
                    self.steps_order = [
                        self.save,
                        (self.snapshot, '', snapshot, True),
                        (self.load_client_snapshot, client_id, snapshot),
                        self.load_client_snapshot_done]
                break
        else:
            self.send_error_no_client(src_addr, path, client_id)

    @client_action
    def _ray_client_is_started(self, path, args, src_addr, client:Client):
        if client.is_running():
            self.send(src_addr, '/reply', path, 'client running')
        else:
            self.send(src_addr, '/error', path, ray.Err.GENERAL_ERROR,
                        _translate('GUIMSG', '%s is not running.')
                        % client.gui_msg_style())

    @client_action
    def _ray_client_send_signal(self, path, args, src_addr, client:Client):
        sig = args[0]
        client.send_signal(sig, src_addr, path)

    @client_action
    def _ray_client_set_custom_data(self, path, args, src_addr, client:Client):
        data, value = args
        client.custom_data[data] = value
        self.send(src_addr, '/reply', path, 'custom data set')

    @client_action
    def _ray_client_get_custom_data(self, path, args, src_addr, client:Client):
        data = args[0]

        if data not in client.custom_data:
            self.send(src_addr, '/error', path, ray.Err.NO_SUCH_FILE,
                        "client %s has no custom_data key '%s'"
                        % (client.client_id, data))
            return

        self.send(src_addr, '/reply', path, client.custom_data[data])
        self.send(src_addr, '/reply', path)

    @client_action
    def _ray_client_set_tmp_data(self, path, args, src_addr, client:Client):
        data, value = args
        client.custom_tmp_data[data] = value
        self.send(src_addr, '/reply', path, 'custom tmp data set')

    @client_action
    def _ray_client_get_tmp_data(self, path, args, src_addr, client:Client):
        data = args[0]

        if data not in client.custom_tmp_data:
            self.send(src_addr, '/error', path, ray.Err.NO_SUCH_FILE,
                      "client %s has no tmp_custom_data key '%s'"
                        % (client.client_id, data))
            return

        self.send(src_addr, '/reply', path, client.custom_tmp_data[data])
        self.send(src_addr, '/reply', path)

    @client_action
    def _ray_client_change_prefix(self, path, args, src_addr, client:Client):
        if client.is_running():
            self.send(src_addr, '/error', path, ray.Err.NOT_NOW,
                      "impossible to change prefix while client is running")
            return

        prefix_mode = args[0]
        custom_prefix = ''

        if prefix_mode in (ray.PrefixMode.SESSION_NAME, 'session_name'):
            prefix_mode = ray.PrefixMode.SESSION_NAME
        elif prefix_mode in (ray.PrefixMode.CLIENT_NAME, 'client_name'):
            prefix_mode = ray.PrefixMode.CLIENT_NAME
        else:
            prefix_mode = ray.PrefixMode.CUSTOM

        if prefix_mode == ray.PrefixMode.CUSTOM:
            custom_prefix = args[1]
            if not custom_prefix:
                self.send(
                    src_addr, '/error', path, ray.Err.GENERAL_ERROR,
                    "You need to specify a custom prefix as 2nd argument")
                return

        client.change_prefix(prefix_mode, custom_prefix)
        
        # we need to save session file here
        # else, if session is aborted
        # client won't find its files at next restart
        self._save_session_file()

        self.send(src_addr, '/reply', path, 'prefix changed')

    @client_action
    def _ray_client_change_advanced_properties(self, path, args, src_addr, client: Client):
        if client.is_running():
            self.send(src_addr, '/error', path, ray.Err.NOT_NOW,
                      "impossible to change id while client is running")
            return

        new_client_id: str
        prefix_mode: int
        custom_prefix: str
        jack_naming: int

        new_client_id, prefix_mode, custom_prefix, jack_naming = args

        if new_client_id != client.client_id:
            if new_client_id in [c.client_id for c in
                                 self.clients + self.trashed_clients]:
                self.send(src_addr, '/error', path, ray.Err.BLACKLISTED,
                        f"client id '{new_client_id}' already exists in the session")
                return

        if prefix_mode == ray.PrefixMode.CUSTOM and not custom_prefix:
            self.send(src_addr, '/error', path, ray.Err.BAD_PROJECT,
                      "Custom prefix missing is missing !")
            return

        tmp_client = Client(self)
        tmp_client.eat_attributes(client)
        tmp_client.client_id = new_client_id
        tmp_client.prefix_mode = prefix_mode
        tmp_client.custom_prefix = custom_prefix
        tmp_client.jack_naming = jack_naming
        
        client.set_status(ray.ClientStatus.REMOVED)
        
        client._rename_files(
            Path(self.path),
            self.name, self.name,
            client.get_prefix_string(), tmp_client.get_prefix_string(),
            client.client_id, tmp_client.client_id,
            client.get_links_dir(), tmp_client.get_links_dir())

        ex_jack_name = client.get_jack_client_name()
        ex_client_id = client.client_id
        new_jack_name = tmp_client.get_jack_client_name()

        client.client_id = new_client_id
        client.prefix_mode = prefix_mode
        client.custom_prefix = custom_prefix
        client.jack_naming = jack_naming
        self._update_forbidden_ids_set()

        if new_jack_name != ex_jack_name:
            rewrite_jack_patch_files(
                self, ex_client_id, new_client_id,
                ex_jack_name, new_jack_name)
            self.canvas_saver.client_jack_name_changed(
                ex_jack_name, new_jack_name)

        client.sent_to_gui = False
        client.send_gui_client_properties()
        self.send_gui('/ray/gui/session/sort_clients',
                      *[c.client_id for c in self.clients])

        # we need to save session file here
        # else, if session is aborted
        # client won't find its files at next restart
        self._save_session_file()

        self.send_monitor_event('id_changed_to:' + new_client_id, ex_client_id)
        self.send(src_addr, '/reply', path, 'client id changed')

    @client_action
    def _ray_client_full_rename(self, path, args, src_addr, client: Client):
        if self.steps_order:
            self.send(src_addr, '/error', path, ray.Err.NOT_NOW,
                      "Session is not ready for full client rename")
            return
        
        new_client_name: str = args[0]
        new_client_id = new_client_name.replace(' ', '_')

        if not new_client_id or not new_client_id.replace('_', '').isalnum():
            self.send(src_addr, '/error', path, ray.Err.BAD_PROJECT,
                      f'client_id {new_client_id} is not alphanumeric')
            return

        if new_client_id in self.forbidden_ids_set:
            self.send(src_addr, '/error', path, ray.Err.BAD_PROJECT,
                      f'client_id {new_client_id} is forbidden in this session')
            return

        if client.is_running():
            if not client.status == ray.ClientStatus.READY:
                self.send(src_addr, '/error', path, ray.Err.NOT_NOW,
                          f'client_id {new_client_id} is not ready')
                return

            elif client.is_capable_of(':switch:'):
                self.steps_order = [
                    (self.save_client_and_patchers, client),
                    (self.rename_full_client, client, new_client_name, new_client_id),
                    (self.switch_client, client),
                    (self.rename_full_client_done, client)]
            else:
                self.steps_order = [
                    (self.save_client_and_patchers, client),
                    (self.close_client, client),
                    (self.rename_full_client, client, new_client_name, new_client_id),
                    (self.restart_client, client),
                    (self.rename_full_client_done, client)
                ]
        else:
            self.steps_order = [
                (self.rename_full_client, client, new_client_name, new_client_id),
                (self.rename_full_client_done, client)
            ]

        self.next_function()

    @client_action
    def _ray_client_change_id(self, path, args, src_addr, client: Client):
        if client.is_running():
            self.send(src_addr, '/error', path, ray.Err.NOT_NOW,
                      "impossible to change id while client is running")
            return

        new_client_id: str = args[0]
        
        if new_client_id in [c.client_id for c in
                             self.clients + self.trashed_clients]:
            self.send(src_addr, '/error', path, ray.Err.BLACKLISTED,
                      f"client id '{new_client_id}' already exists in the session")
            return
        
        if not new_client_id.replace('_', '').isalnum():
            self.send(src_addr, '/error', path, ray.Err.BAD_PROJECT,
                      f"client id {new_client_id} contains forbidden characters")
            return
        
        ex_client_id = client.client_id
        ex_jack_name = client.get_jack_client_name()
        client.set_status(ray.ClientStatus.REMOVED)

        prefix = client.get_prefix_string()
        links_dir = client.get_links_dir()

        client._rename_files(
            Path(self.path),
            self.name, self.name,
            prefix, prefix,
            ex_client_id, new_client_id,
            links_dir, links_dir)

        client.client_id = new_client_id
        self._update_forbidden_ids_set()
        new_jack_name = client.get_jack_client_name()

        if new_jack_name != ex_jack_name:
            rewrite_jack_patch_files(
                self, ex_client_id, new_client_id,
                ex_jack_name, new_jack_name)
            self.canvas_saver.client_jack_name_changed(
                ex_jack_name, new_jack_name)

        client.sent_to_gui = False
        client.send_gui_client_properties()
        self.send_gui('/ray/gui/session/sort_clients',
                      *[c.client_id for c in self.clients])

        # we need to save session file here
        # else, if session is aborted
        # client won't find its files at next restart
        self._save_session_file()

        self.send_monitor_event('id_changed_to:' + new_client_id, ex_client_id)
        self.send(src_addr, '/reply', path, 'client id changed')
    
    def _ray_trashed_client_restore(self, path, args, src_addr):
        if not self.path:
            self.send(src_addr, "/error", path, ray.Err.NO_SESSION_OPEN,
                      "Nothing in trash because no session is loaded.")
            return

        for client in self.trashed_clients:
            if client.client_id == args[0]:
                if self._restore_client(client):
                    self.send(src_addr, '/reply', path, "client restored")
                else:
                    self.send(src_addr, '/error', path, ray.Err.NOT_NOW,
                              "Session is in a loading locked state")
                break
        else:
            self.send(src_addr, "/error", path, -10, "No such client.")

    def _ray_trashed_client_remove_definitely(self, path, args, src_addr):
        if not self.path:
            self.send(src_addr, "/error", path, ray.Err.NO_SESSION_OPEN,
                      "Nothing in trash because no session is loaded.")
            return

        client_id = args[0]

        for client in self.trashed_clients:
            if client.client_id == client_id:
                break
        else:
            self.send(src_addr, "/error", path, -10, "No such client.")
            return

        self.send_gui('/ray/gui/trash/remove', client.client_id)

        for file in client.get_project_files():
            try:
                subprocess.run(['rm', '-R', file])
            except:
                self.send(src_addr, '/minor_error', path, -10,
                          "Error while removing client file %s" % file)
                continue

        self.trashed_clients.remove(client)
        self._save_session_file()

        self.send(src_addr, '/reply', path, "client definitely removed")
        self.send_monitor_event('removed', client_id)

    def _ray_trashed_client_remove_keep_files(self, path, args, src_addr):
        if not self.path:
            self.send(src_addr, "/error", path, ray.Err.NO_SESSION_OPEN,
                      "Nothing in trash because no session is loaded.")
            return

        client_id = args[0]

        for client in self.trashed_clients:
            if client.client_id == client_id:
                break
        else:
            self.send(src_addr, "/error", path, -10, "No such client.")
            return

        self.send_gui('/ray/gui/trash/remove', client.client_id)

        self.trashed_clients.remove(client)

        self.send(src_addr, '/reply', path, "client removed")
        self.send_monitor_event('removed', client_id)

    def _ray_net_daemon_duplicate_state(self, path, args, src_addr):
        state = args[0]
        for client in self.clients:
            if (client.protocol == ray.Protocol.RAY_NET
                    and client.ray_net.daemon_url
                    and ray.are_same_osc_port(client.ray_net.daemon_url,
                                              src_addr.url)):
                client.ray_net.duplicate_state = state
                client.net_daemon_copy_timer.stop()
                break
        else:
            return

        if state == 1:
            if self.wait_for == ray.WaitFor.DUPLICATE_FINISH:
                self.end_timer_if_last_expected(client)
            return

        if (self.wait_for == ray.WaitFor.DUPLICATE_START and state == 0):
            self.end_timer_if_last_expected(client)

        client.net_daemon_copy_timer.start()

    def check_recent_sessions_existing(self):
        # check here if recent sessions still exist
        if self.root in self.recent_sessions.keys():
            to_remove_list = list[str]()
            for sess in self.recent_sessions[self.root]:
                if not os.path.exists(
                        "%s/%s/raysession.xml" % (self.root, sess)):
                    to_remove_list.append(sess)
            for sess in to_remove_list:
                self.recent_sessions[self.root].remove(sess)

    def server_open_session_at_start(self, session_name):
        self.steps_order = [(self.preload, session_name),
                            self.take_place,
                            self.load,
                            self.load_done]
        self.next_function()

    def dummy_load_and_template(self, session_name, template_name, sess_root):
        tmp_session = self._new_dummy_session(sess_root)
        tmp_session.dummy_load_and_template(session_name, template_name)

    def terminate(self):
        if self.terminated_yet:
            return

        if self.file_copier.is_active():
            self.file_copier.abort()

        self.terminated_yet = True
        self.steps_order = [self.terminate_step_scripter,
                            self.close, self.exit_now]
        self.next_function()


class DummySession(OperatingSession):
    ''' A dummy session allows to make such operations on not current session
        It is used for session preview, or duplicate a session for example.
        When a session is dummy, it has no server options
        (bookmarks, snapshots, session scripts...).
        All clients are dummy and can't be started.
        Their file copier is not dummy, it can send OSC messages to gui,
        That is why we need a session_id to find it '''

    def __init__(self, root, session_id=0):
        OperatingSession.__init__(self, root, session_id)
        self.is_dummy = True
        self.canvas_saver.is_dummy = True

    def dummy_load_and_template(self, session_full_name, template_name):
        self.steps_order = [(self.preload, session_full_name),
                            self.take_place,
                            self.load,
                            (self.save_session_template, template_name, True)]
        self.next_function()

    def dummy_duplicate(self, path, args, src_addr):
        self.remember_osc_args(path, args, src_addr)
        session_to_load, new_session_full_name, sess_root = args
        self.steps_order = [(self.preload, session_to_load),
                            self.take_place,
                            self.load,
                            (self.duplicate, new_session_full_name),
                            self.duplicate_only_done]
        self.next_function()

    def ray_server_save_session_template(self, path, args, src_addr):
        self.remember_osc_args(path, args, src_addr)
        session_name, template_name, net = args
        self.steps_order = [(self.preload, session_name),
                            self.take_place,
                            self.load,
                            (self.save_session_template, template_name, net)]
        self.next_function()

    def ray_server_rename_session(self, path, args, src_addr):
        self.remember_osc_args(path, args, src_addr)
        full_session_name, new_session_name = args

        self.steps_order = [(self.preload, full_session_name),
                            self.take_place,
                            self.load,
                            (self.rename, new_session_name),
                            self.save,
                            (self.rename_done, new_session_name)]
        self.next_function()
    
    def ray_server_get_session_preview(self, path, args, src_addr,
                                       folder_sizes:list):
        session_name = args[0]
        self.steps_order = [(self.preload, session_name, False),
                            self.take_place,
                            self.load,
                            (self.send_preview, src_addr, folder_sizes)]
        self.next_function()
    
    def dummy_load(self, session_name):
        self.steps_order = [(self.preload, session_name, False),
                            self.take_place,
                            self.load]
        self.next_function()
