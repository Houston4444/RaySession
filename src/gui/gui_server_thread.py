import os
import sys
import liblo

import ray
from gui_tools import CommandLineArgs
from gui_signaler import Signaler

signaler = Signaler.instance()
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
    def errorFromServer(self, path, args, types, src_addr):
        self._signaler.error_message.emit(args)

    @ray_method('/reply', None)
    def receiveFromServer(self, path, args, types, src_addr):
        if len(args) < 2:
            return
        
        if not ray.areTheyAllString(args):
            return
        
        reply_path = args.pop(0)
        
        if reply_path == '/ray/server/list_sessions':
            self._signaler.add_sessions_to_list.emit(args)
        elif reply_path == '/ray/server/list_path':
            self._signaler.new_executable.emit(args)
        elif reply_path == '/ray/server/list_session_templates':
            self._signaler.session_template_found.emit(args)
        elif reply_path == '/ray/server/list_user_client_templates':
            self._signaler.user_client_template_found.emit(args)
        elif reply_path == '/ray/server/list_factory_client_templates':
            self._signaler.factory_client_template_found.emit(args)
        elif reply_path == '/ray/session/list_snapshots':
            self._signaler.snapshots_found.emit(args)

    @ray_method('/ray/gui/server/announce', 'siisi')
    def serverAnnounce(self, path, args, types, src_addr):
        if self._daemon_manager.isAnnounced():
            return

        version, server_status, options, session_root, is_net_free = args

        self._signaler.daemon_announce.emit(src_addr,
                                            version,
                                            server_status,
                                            options,
                                            session_root,
                                            is_net_free)

    @ray_method('/ray/gui/server/disannounce', '')
    def serverDisannounce(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/gui/server/nsm_locked', 'i')
    def daemonNsmLocked(self, path, args, types, src_addr):
        nsm_locked = bool(args[0])

        self._signaler.daemon_nsm_locked.emit(nsm_locked)
    
    @ray_method('/ray/gui/server/root', 's')
    def rayServerRootChanged(self, path, args, types, src_addr):
        session_root = args[0]
        
        CommandLineArgs.changeSessionRoot(session_root)
        self._signaler.root_changed.emit(session_root)
    
    @ray_method('/ray/gui/server/options', 'i')
    def rayGuiServerOptions(self, path, args, types, src_addr):
        options = args[0]
        self._signaler.daemon_options.emit(options)
    
    @ray_method('/ray/gui/server/status', 'i')
    def rayServerStatus(self, path, args, types, src_addr):
        server_status = args[0]
        self._signaler.server_status_changed.emit(server_status)
    
    @ray_method('/ray/gui/server/copying', 'i')
    def guiServerCopying(self, path, args, types, src_addr):
        copying = bool(int(args[0]))
        self._signaler.server_copying.emit(copying)
    
    @ray_method('/ray/gui/server/progress', 'f')
    def guiServerProgress(self, path, args, types, src_addr):
        progress = args[0]
        self._signaler.server_progress.emit(progress)
        
    @ray_method('/ray/gui/server/message', 's')
    def serverMessage(self, path, args, types, src_addr):
        message = args[0]
        self._signaler.new_message_sig.emit(message)

    @ray_method('/ray/gui/session/name', 'ss')
    def guiSessionName(self, path, args, types, src_addr):
        session_name, session_path = args
        self._signaler.session_name_sig.emit(session_name, session_path)
    
    @ray_method('/ray/gui/session/auto_snapshot', 'i')
    def replyAutoSnapshot(self, path, args, types, src_addr):
        self._signaler.reply_auto_snapshot.emit(bool(args[0]))
    
    @ray_method('/ray/gui/session/is_nsm', '')
    def rayOpeningNsmSession(self, path, args, types, src_addr):
        self._signaler.opening_session.emit()
    
    @ray_method('/ray/gui/session/renameable', 'i')
    def guiSessionRenameable(self, path, args, types, src_addr):
        renameable = bool(args[0])
        self._signaler.session_renameable.emit(renameable)
    
    @ray_method('/ray/gui/session/sort_clients', None)
    def rayGuiReorderClients(self, path, args, types, src_addr):
        for arg in args:
            if not isinstance(arg, str):
                return

        self._signaler.clients_reordered.emit(args)
    
    @ray_method('/ray/gui/client/new', 'ssssissssis')
    def newClientFromServer(self, path, args, types, src_addr):
        client_data = ray.ClientData(*args)
        self._signaler.new_client_added.emit(client_data)

    @ray_method('/ray/gui/client/update', 'ssssissssis')
    def updateClientProperties(self, path, args, types, src_addr):
        client_data = ray.ClientData(*args)
        self._signaler.client_updated.emit(client_data)

    @ray_method('/ray/gui/client/status', 'si')
    def guiClientStatus(self, path, args, types, src_addr):
        client_id, status = args

        if status == ray.ClientStatus.REMOVED:
            self._signaler.client_removed.emit(client_id)
            return

        self._signaler.client_status_changed.emit(client_id, status)

    @ray_method('/ray/gui/client/switch', 'ss')
    def guiClientSwitch(self, path, args, types, src_addr):
        old_client_id, new_client_id = args
        self._signaler.client_switched.emit(old_client_id, new_client_id)

    @ray_method('/ray/gui/client/progress', 'sf')
    def guiClientProgress(self, path, args, types, src_addr):
        client_id, progress = args
        self._signaler.client_progress.emit(client_id, progress)

    @ray_method('/ray/gui/client/dirty', 'si')
    def guiClientDirty(self, path, args, types, src_addr):
        client_id, dirty_num = args
        bool_dirty = bool(dirty_num)

        self._signaler.client_dirty_sig.emit(client_id, bool_dirty)

    @ray_method('/ray/gui/client/has_optional_gui', 's')
    def guiClientHasOptionalGui(self, path, args, types, src_addr):
        client_id = args[0]
        self._signaler.client_has_gui.emit(client_id)

    @ray_method('/ray/gui/client/gui_visible', 'si')
    def guiClientGuiVisible(self, path, args, types, src_addr):
        client_id, state = args
        self._signaler.client_gui_visible_sig.emit(client_id, bool(state))

    @ray_method('/ray/gui/client/still_running', 's')
    def guiClientStillRunning(self, path, args, types, src_addr):
        client_id = args[0]
        self._signaler.client_still_running.emit(client_id)
        
    @ray_method('/ray/gui/client/no_save_level', 'si')
    def rayClientWarningNoSave(self, path, args, types, src_addr):
        client_id, warning_no_save = args
        self._signaler.client_no_save_level.emit(client_id, warning_no_save)

    @ray_method('/ray/gui/trash/add', 'ssssissssis')
    def rayGuiTrashAdd(self, path, args, types, src_addr):
        client_data = ray.ClientData(*args)
        self._signaler.trash_add.emit(client_data)

    @ray_method('/ray/gui/trash/remove', 's')
    def rayGuiTrashRemove(self, path, args, types, src_addr):
        client_id = args[0]
        self._signaler.trash_remove.emit(client_id)

    @ray_method('/ray/gui/trash/clear', '')
    def rayGuiTrashClear(self, path, args, types, src_addr):
        self._signaler.trash_clear.emit()
        
    @ray_method('/ray/gui/favorites/added', 'ssi')
    def rayGuiFavoritesAdded(self, path, args, types, src_addr):
        name, icon, int_factory = args
        self._signaler.favorite_added.emit(name, icon, bool(int_factory))
        
    @ray_method('/ray/gui/favorites/removed', 'si')
    def rayGuiFavoritesRemoved(self, path, args, types, src_addr):
        name, int_factory = args
        self._signaler.favorite_removed.emit(name, bool(int_factory))
    
    def send(self, *args):
        if CommandLineArgs.debug:
            sys.stderr.write(
                '\033[95mOSC::gui sends\033[0m %s\n' % str(args[1:]) )
        
        liblo.ServerThread.send(self, *args)
    
    def toDaemon(self, *args):
        self.send(self._daemon_manager.address, *args)

    def announce(self):
        if CommandLineArgs.debug:
            sys.stderr.write('serverOSC::raysession_sends announce\n')

        nsm_mode = ray.NSMMode.NO_NSM

        if CommandLineArgs.under_nsm:
            if CommandLineArgs.out_daemon:
                nsm_mode = ray.NSMMode.NETWORK
            else:
                nsm_mode = ray.NSMMode.CHILD

        NSM_URL = os.getenv('NSM_URL')
        if not NSM_URL:
            NSM_URL = ""

        self.send(self._daemon_manager.address, '/ray/server/gui_announce',
                  ray.VERSION, int(CommandLineArgs.under_nsm),
                  NSM_URL, 0,
                  CommandLineArgs.net_daemon_id)

    def disannounce(self, src_addr):
        self.send(src_addr, '/ray/server/gui_disannounce')

    def openSession(self, session_name, session_template=''):
        if session_template:
            self.toDaemon(
                '/ray/server/open_session',
                session_name,
                session_template)
        else:
            self.toDaemon('/ray/server/open_session', session_name)

    def saveSession(self):
        self.toDaemon('/ray/session/save')

    def closeSession(self):
        self.toDaemon('/ray/session/close')

    def abortSession(self):
        self.toDaemon('/ray/session/abort')
