import os
import sys
import liblo

import ray
from gui_tools import CommandLineArgs
from gui_signaler import Signaler

signaler = Signaler.instance()
_instance = None


def ifDebug(string):
    if CommandLineArgs.debug:
        sys.stderr.write(string + '\n')

def ray_method(path, types):
    def decorated(func):
        @liblo.make_method(path, types)
        def wrapper(*args, **kwargs):
            if CommandLineArgs.debug:
                sys.stderr.write(
                    '\033[93mOSC::gui_receives\033[0m %s, %s.\n'
                        % (path, str(args)))
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

    @ray_method('/error', None)
    def errorFromServer(self, path, args, types, src_addr):
        self._signaler.error_message.emit(args)

    @ray_method('/reply', 'ss')
    def receiveFromServer(self, path, args, types, src_addr):
        pass

    @ray_method('/reply_sessions_list', None)
    def replySessionsList(self, path, args, types, src_addr):
        if not ray.areTheyAllString(args):
            return

        self._signaler.add_sessions_to_list.emit(args)

    @ray_method('/reply_path', None)
    def replyPath(self, path, args, types, src_addr):
        if not ray.areTheyAllString(args):
            return

        self._signaler.new_executable.emit(args)

    @ray_method('/reply_session_templates', None)
    def replySessionTemplates(self, path, args, types, src_addr):
        if not ray.areTheyAllString(args):
            return

        self._signaler.session_template_found.emit(args)

    @ray_method('/reply_user_client_templates', None)
    def replyUserClientTemplates(self, path, args, types, src_addr):
        if not ray.areTheyAllString(args):
            return

        self._signaler.user_client_template_found.emit(args)

    @ray_method('/reply_factory_client_templates', None)
    def replyFactoryClientTemplates(self, path, args, types, src_addr):
        if not ray.areTheyAllString(args):
            return

        self._signaler.factory_client_template_found.emit(args)
        
    @ray_method('/reply_snapshots_list', None)
    def replySnapshotsList(self, path, args, types, src_addr):
        if not ray.areTheyAllString(args):
            return 
        
        self._signaler.snapshots_found.emit(args)
        
    @ray_method('/reply_auto_snapshot', 'i')
    def replyAutoSnapshot(self, path, args, types, src_addr):
        self._signaler.reply_auto_snapshot.emit(bool(args[0]))

    @ray_method('/ray/gui/daemon_announce', 'siisi')
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

    @ray_method('/ray/gui/daemon_disannounce', '')
    def serverDisannounce(self, path, args, types, src_addr):
        pass

    @ray_method('/ray/gui/daemon_nsm_locked', 'i')
    def daemonNsmLocked(self, path, args, types, src_addr):
        nsm_locked = bool(args[0])

        self._signaler.daemon_nsm_locked.emit(nsm_locked)

    @ray_method('/ray/gui/server/message', 's')
    def serverMessage(self, path, args, types, src_addr):
        message = args[0]
        self._signaler.new_message_sig.emit(message)

    @ray_method('/ray/gui/server/copying', 'i')
    def guiServerCopying(self, path, args, types, src_addr):
        copying = bool(int(args[0]))
        self._signaler.server_copying.emit(copying)

    @ray_method('/ray/gui/session/name', 'ss')
    def guiSessionName(self, path, args, types, src_addr):
        name1, name2 = args
        self._signaler.session_name_sig.emit(name1, name2)

    @ray_method('/ray/gui/session/renameable', 'i')
    def guiSessionRenameable(self, path, args, types, src_addr):
        renameable = bool(args[0])
        self._signaler.session_renameable.emit(renameable)

    @ray_method('/ray/client/new', 'ssssissssis')
    def newClientFromServer(self, path, args, types, src_addr):
        client_data = ray.ClientData(*args)
        self._signaler.new_client_added.emit(client_data)

    @ray_method('/ray/client/update', 'ssssissssis')
    def updateClientProperties(self, path, args, types, src_addr):
        client_data = ray.ClientData(*args)
        self._signaler.client_updated.emit(client_data)

    @ray_method('/ray/client/status', 'si')
    def guiClientStatus(self, path, args, types, src_addr):
        client_id, status = args

        if status == ray.ClientStatus.REMOVED:
            self._signaler.client_removed.emit(client_id)
            return

        self._signaler.client_status_changed.emit(client_id, status)

    @ray_method('/ray/client/switch', 'ss')
    def guiClientSwitch(self, path, args, types, src_addr):
        old_client_id, new_client_id = args
        self._signaler.client_switched.emit(old_client_id, new_client_id)

    @ray_method('/ray/client/progress', 'sf')
    def guiClientProgress(self, path, args, types, src_addr):
        client_id, progress = args
        self._signaler.client_progress.emit(client_id, progress)

    @ray_method('/ray/client/dirty', 'si')
    def guiClientDirty(self, path, args, types, src_addr):
        client_id, dirty_num = args
        bool_dirty = bool(dirty_num)

        self._signaler.client_dirty_sig.emit(client_id, bool_dirty)

    @ray_method('/ray/client/has_optional_gui', 's')
    def guiClientHasOptionalGui(self, path, args, types, src_addr):
        client_id = args[0]
        self._signaler.client_has_gui.emit(client_id)

    @ray_method('/ray/client/gui_visible', 'si')
    def guiClientGuiVisible(self, path, args, types, src_addr):
        client_id, state = args
        self._signaler.client_gui_visible_sig.emit(client_id, bool(state))

    @ray_method('/ray/client/still_running', 's')
    def guiClientStillRunning(self, path, args, types, src_addr):
        client_id = args[0]
        self._signaler.client_still_running.emit(client_id)

    @ray_method('/ray/gui/server_progress', 'f')
    def guiServerProgress(self, path, args, types, src_addr):
        progress = args[0]
        self._signaler.server_progress.emit(progress)

    @ray_method('/ray/server_status', 'i')
    def rayServerStatus(self, path, args, types, src_addr):
        server_status = args[0]
        self._signaler.server_status_changed.emit(server_status)
        
    @ray_method('/ray/server/root_changed', 's')
    def rayServerRootChanged(self, path, args, types, src_addr):
        session_root = args[0]
        
        CommandLineArgs.changeSessionRoot(session_root)
        self._signaler.root_changed.emit(session_root)

    @ray_method('/ray/opening_nsm_session', None)
    def rayOpeningNsmSession(self, path, args, types, src_addr):
        self._signaler.opening_session.emit()

    @ray_method('/ray/gui/clients_reordered', None)
    def rayGuiReorderClients(self, path, args, types, src_addr):
        for arg in args:
            if not isinstance(arg, str):
                return

        self._signaler.clients_reordered.emit(args)

    @ray_method('/ray/trash/add', 'ssssissssis')
    def rayGuiTrashAdd(self, path, args, types, src_addr):
        client_data = ray.ClientData(*args)
        self._signaler.trash_add.emit(client_data)

    @ray_method('/ray/trash/remove', 's')
    def rayGuiTrashRemove(self, path, args, types, src_addr):
        client_id = args[0]
        self._signaler.trash_remove.emit(client_id)

    @ray_method('/ray/trash/clear', '')
    def rayGuiTrashClear(self, path, args, types, src_addr):
        self._signaler.trash_clear.emit()
        
    @ray_method('/ray/gui/favorite', 'ssi')
    def rayGuiFavorite(self, path, args, types, src_addr):
        name, icon, int_factory = args
        self._signaler.get_favorite.emit(name, icon, bool(int_factory))

    def toDaemon(self, *args):
        if CommandLineArgs.debug:
            sys.stderr.write(
                '\033[94mOSC::gui_sends\033[0m %s.\n' %
                (str(args)))
        self.send(self._daemon_manager.address, *args)

    def announce(self):
        if CommandLineArgs.debug:
            sys.stderr.write('serverOSC::raysession_sends announce')

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
        ifDebug('serverOSC::raysession_sends disannounce')
        self.send(src_addr, '/ray/server/gui_disannounce')

    def startListSession(self, with_net=False):
        ifDebug('serverOSC::raysession_sends list sessions')
        self.toDaemon('/ray/server/list_sessions', int(with_net))

    def newSession(self, session_name):
        self.toDaemon('/ray/server/new_session', session_name)

    def newSessionFromTemplate(self, session_name, template_name):
        self.toDaemon('/ray/server/new_session', session_name, template_name)

    def openSession(self, session_name, session_template=''):
        if session_template:
            self.toDaemon(
                '/ray/server/open_session',
                session_name,
                session_template)
        else:
            self.toDaemon('/ray/server/open_session', session_name)

    def saveSession(self):
        ifDebug('serverOSC::raysession_sends save session')
        self.toDaemon('/ray/session/save')

    def closeSession(self):
        ifDebug('serverOSC::raysession_sends close session')
        self.toDaemon('/ray/session/close')

    def abortSession(self):
        ifDebug('serverOSC::raysession_sends abort session')
        self.toDaemon('/ray/session/abort')

    def duplicateSession(self, session_name):
        ifDebug('serverOSC::raysession_sends duplication session')
        self.toDaemon('/ray/session/duplicate', session_name)

    def saveTemplateSession(self, session_template_name):
        ifDebug('serverOSC::raysession_sends save template session')
        self.toDaemon('/ray/session/save_as_template', session_template_name)

    def startClient(self, client_id):
        ifDebug('serverOSC::raysession_sends start client %s' % client_id)
        self.toDaemon('/ray/client/resume', client_id)

    def stopClient(self, client_id):
        ifDebug('serverOSC::raysession_sends stop client %s' % client_id)
        self.toDaemon('/ray/client/stop', client_id)

    def killClient(self, client_id):
        ifDebug('serverOSC::raysession_sends stop client %s' % client_id)
        self.toDaemon('/ray/client/kill', client_id)

    def saveClient(self, client_id):
        ifDebug('serverOSC::raysession_sends save client %s' % client_id)
        self.toDaemon('/ray/client/save', client_id)

    def removeClient(self, client_id):
        ifDebug('serverOSC::raysession_sends remove client %s' % client_id)
        self.toDaemon('/ray/client/remove', client_id)

    def showClientOptionalGui(self, client_id):
        ifDebug('serverOSC::raysession_sends show optional GUI %s' % client_id)
        self.toDaemon('/ray/client/show_optional_gui', client_id)

    def hideClientOptionalGui(self, client_id):
        ifDebug('serverOSC::raysession_sends hide optional GUI %s' % client_id)
        self.toDaemon('/ray/client/hide_optional_gui', client_id)

    def saveClientTemplate(self, client_id, template_name):
        self.toDaemon('/ray/client/save_as_template', client_id, template_name)

    def addClient(self, program_name):
        ifDebug('serverOSC::raysession_sends add Client %s' % program_name)
        self.toDaemon('/ray/session/add_executable', program_name)

    def changeClientOrder(self, client_ids_list):
        self.toDaemon('/ray/session/reorder_clients', *client_ids_list)

    def abortCopy(self):
        self.toDaemon('/ray/server/abort_copy')
