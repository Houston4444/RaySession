import os
import sys
import liblo

import ray
from gui_tools import CommandLineArgs

_instance = None

def ray_method(path, types):
    def decorated(func):
        @liblo.make_method(path, types)
        def wrapper(*args, **kwargs):
            t_thread, t_path, t_args, t_types, src_addr, rest = args

            if CommandLineArgs.debug:
                sys.stderr.write(
                    '\033[93mOSC::gui_receives\033[0m %s, %s, %s, %s\n'
                    % (t_path, t_types, t_args, src_addr.url))

            response = func(*args[:-1], **kwargs)

            if not response is False:
                t_thread._signaler.osc_receive.emit(t_path, t_args)

            return response
        return wrapper
    return decorated


class GUIServerThread(liblo.ServerThread):
    def __init__(self):
        liblo.ServerThread.__init__(self)

        global _instance
        _instance = self

    def finishInit(self, session):
        self._session = session
        self._signaler = self._session._signaler
        self._daemon_manager = self._session._daemon_manager

    @staticmethod
    def instance():
        return _instance

    @ray_method('/error', 'sis')
    def _error(self, path, args, types, src_addr):
        pass

    @ray_method('/minor_error', 'sis')
    def error(self, path, args, types, src_addr):
        pass

    @ray_method('/reply', None)
    def _reply(self, path, args, types, src_addr):
        if len(args) == 0:
            return False

        if not ray.areTheyAllString(args):
            return False

        new_args = args.copy()
        reply_path = new_args.pop(0)

        if reply_path == '/ray/server/list_sessions':
            self._signaler.add_sessions_to_list.emit(new_args)
        elif reply_path == '/ray/server/list_path':
            self._signaler.new_executable.emit(new_args)
        elif reply_path == '/ray/server/list_session_templates':
            self._signaler.session_template_found.emit(new_args)
        elif reply_path == '/ray/server/list_user_client_templates':
            self._signaler.user_client_template_found.emit(new_args)
        elif reply_path == '/ray/server/list_factory_client_templates':
            self._signaler.factory_client_template_found.emit(new_args)
        elif reply_path in ('/ray/session/list_snapshots',
                            '/ray/client/list_snapshots'):
            self._signaler.snapshots_found.emit(new_args)

    @ray_method('/ray/gui/server/announce', 'siisi')
    def _server_announce(self, path, args, types, src_addr):
        if self._daemon_manager.isAnnounced():
            return

        version, server_status, options, session_root, is_net_free = args

        self._signaler.daemon_announce.emit(
            src_addr, version, server_status,
            options, session_root, is_net_free)

    @ray_method('/ray/gui/server/disannounce', '')
    def _server_disannounce(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/gui/server/nsm_locked', 'i')
    def _server_nsm_locked(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/gui/server/root', 's')
    def _server_root(self, path, args, types, src_addr):
        session_root = args[0]
        CommandLineArgs.changeSessionRoot(session_root)
        self._signaler.root_changed.emit(session_root)

    @ray_method('/ray/gui/server/options', 'i')
    def _server_options(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/gui/server/status', 'i')
    def _server_status(self, path, args, types, src_addr):
        server_status = args[0]
        self._signaler.server_status_changed.emit(server_status)

    @ray_method('/ray/gui/server/copying', 'i')
    def _server_copying(self, path, args, types, src_addr):
        copying = bool(int(args[0]))
        self._signaler.server_copying.emit(copying)

    @ray_method('/ray/gui/server/progress', 'f')
    def _server_progress(self, path, args, types, src_addr):
        progress = args[0]
        self._signaler.server_progress.emit(progress)

    @ray_method('/ray/gui/server/message', 's')
    def _server_message(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/gui/session/name', 'ss')
    def _session_name(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/gui/session/notes', 's')
    def _session_notes(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/gui/session/auto_snapshot', 'i')
    def _session_auto_snapshot(self, path, args, types, src_addr):
        self._signaler.reply_auto_snapshot.emit(bool(args[0]))

    @ray_method('/ray/gui/session/is_nsm', '')
    def _session_is_nsm(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/gui/session/renameable', 'i')
    def _session_renameable(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/gui/session/sort_clients', None)
    def _session_sort_clients(self, path, args, types, src_addr):
        if not ray.areTheyAllString(args):
            return False

    @ray_method('/ray/gui/client_template_update', 'is' + ray.ClientData.sisi())
    def _client_template_update(self, path, args, types, src_addr):
        self._signaler.client_template_update.emit(args)

    @ray_method('/ray/gui/client_template_ray_hack_update', 'is' + ray.RayHack.sisi())
    def _client_template_ray_hack_update(self, path, args, types, src_addr):
        self._signaler.client_template_ray_hack_update.emit(args)
    
    @ray_method('/ray/gui/client/new', ray.ClientData.sisi())
    def _client_new(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/gui/client/update', ray.ClientData.sisi())
    def _client_update(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/gui/client/ray_hack_update', 'ssiiiisi')
    def _client_ray_hack_update(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/gui/client/switch', 'ss')
    def _client_switch(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/gui/client/status', 'si')
    def _client_status(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/gui/client/progress', 'sf')
    def _client_progress(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/gui/client/dirty', 'si')
    def _client_dirty(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/gui/client/has_optional_gui', 's')
    def _client_has_optional_gui(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/gui/client/gui_visible', 'si')
    def _client_gui_visible(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/gui/client/still_running', 's')
    def _client_still_running(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/gui/client/no_save_level', 'si')
    def _client_no_save_level(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/gui/trash/add', ray.ClientData.sisi())
    def _trash_add(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/gui/trash/ray_hack_update', 's' + ray.RayHack.sisi())
    def _trash_update_ray_hack(self, path, args, types, src_addr):
        pass
    
    @ray_method('/ray/gui/trash/remove', 's')
    def _trash_remove(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/gui/trash/clear', '')
    def _trash_clear(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/gui/favorites/added', 'ssi')
    def _favorites_added(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/gui/favorites/removed', 'si')
    def _favorites_removed(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/gui/script_info', 's')
    def _script_info(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/gui/hide_script_info', '')
    def _hide_script_info(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/gui/script_user_action', 's')
    def _script_user_action(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/gui/hide_script_user_action', '')
    def _hide_script_user_action(self, path, args, types, src_addr):
        pass

    def send(self, *args):
        if CommandLineArgs.debug:
            sys.stderr.write(
                '\033[95mOSC::gui sends\033[0m %s\n' % str(args[1:]))

        liblo.ServerThread.send(self, *args)

    def toDaemon(self, *args):
        self.send(self._daemon_manager.address, *args)

    def announce(self):
        if CommandLineArgs.debug:
            sys.stderr.write('serverOSC::raysession_sends announce\n')

        NSM_URL = os.getenv('NSM_URL')
        if not NSM_URL:
            NSM_URL = ""

        self.send(self._daemon_manager.address, '/ray/server/gui_announce',
                  ray.VERSION, int(CommandLineArgs.under_nsm),
                  NSM_URL, 0,
                  CommandLineArgs.net_daemon_id)

    def disannounce(self, src_addr):
        self.send(src_addr, '/ray/server/gui_disannounce')

    def openSession(self, session_name, save_previous=1, session_template=''):
        self.toDaemon('/ray/server/open_session', session_name,
                      save_previous, session_template)

    def saveSession(self):
        self.toDaemon('/ray/session/save')

    def closeSession(self):
        self.toDaemon('/ray/session/close')

    def abortSession(self):
        self.toDaemon('/ray/session/abort')
