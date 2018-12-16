import os
import sys
from liblo import ServerThread, make_method, Address

import ray
from gui_tools import CommandLineArgs
from gui_signaler import Signaler

#signaler = Signaler.instance()
_instance = None


def ifDebug(string):
    if CommandLineArgs.debug:
        sys.stderr.write(string + '\n')


class GUIServerThread(ServerThread):
    def __init__(self):
        ServerThread.__init__(self)

        global _instance
        _instance = self

    def finishInit(self, session):
        self._session = session
        self._signaler = self._session._signaler
        self._daemon_manager = self._session._daemon_manager

    @staticmethod
    def instance():
        return _instance

    @make_method('/error', None)
    def errorFromServer(self, path, args):
        self.debugg(path, args)

        self._signaler.error_message.emit(args)

    @make_method('/reply', 'ss')
    def receiveFromServer(self, path, args):
        self.debugg(path, args)

        # if args[0] == '/ray/server/list_sessions':
        #session_name = args[1]
        # self._signaler.add_session_to_list.emit(session_name)

    @make_method('/reply_sessions_list', None)
    def replySessionsList(self, path, args):
        self.debugg(path, args)

        if not ray.areTheyAllString(args):
            return

        self._signaler.add_sessions_to_list.emit(args)

    @make_method('/reply_path', None)
    def replyPath(self, path, args):
        self.debugg(path, args)

        if not ray.areTheyAllString(args):
            return

        self._signaler.new_executable.emit(args)

    @make_method('/reply_session_templates', None)
    def replySessionTemplates(self, path, args):
        self.debugg(path, args)

        if not ray.areTheyAllString(args):
            return

        self._signaler.session_template_found.emit(args)

    @make_method('/reply_user_client_templates', None)
    def replyUserClientTemplates(self, path, args):
        self.debugg(path, args)

        if not ray.areTheyAllString(args):
            return

        self._signaler.user_client_template_found.emit(args)

    @make_method('/reply_factory_client_templates', None)
    def replyFactoryClientTemplates(self, path, args):
        self.debugg(path, args)

        if not ray.areTheyAllString(args):
            return

        self._signaler.factory_client_template_found.emit(args)

    @make_method('/ray/gui/daemon_announce', 'siisi')
    def serverAnnounce(self, path, args, types, src_addr):
        self.debugg(path, args)

        if self._daemon_manager.isAnnounced():
            return

        version, server_status, options, session_root, is_net_free = args

        self._signaler.daemon_announce.emit(src_addr,
                                            version,
                                            server_status,
                                            options,
                                            session_root,
                                            is_net_free)

    @make_method('/ray/gui/daemon_disannounce', '')
    def serverDisannounce(self, path, args, types, src_addr):
        self.debugg(path, args)
        pass

    @make_method('/ray/gui/daemon_nsm_locked', 'i')
    def daemonNsmLocked(self, path, args, types, src_addr):
        self.debugg(path, args)
        nsm_locked = bool(args[0])

        self._signaler.daemon_nsm_locked.emit(nsm_locked)

    @make_method('/ray/gui/server/message', 's')
    def serverMessage(self, path, args):
        self.debugg(path, args)

        message = args[0]
        self._signaler.new_message_sig.emit(message)

    @make_method('/ray/gui/server/copying', 'i')
    def guiServerCopying(self, path, args):
        copying = bool(int(args[0]))

        self._signaler.server_copying.emit(copying)

    @make_method('/ray/gui/session/name', 'ss')
    def guiSessionName(self, path, args):
        self.debugg(path, args)

        name1, name2 = args
        self._signaler.session_name_sig.emit(name1, name2)

    @make_method('/ray/gui/session/renameable', 'i')
    def guiSessionRenameable(self, path, args):
        self.debugg(path, args)

        renameable = bool(args[0])
        self._signaler.session_renameable.emit(renameable)

    @make_method('/ray/client/new', 'ssssissssi')
    def newClientFromServer(self, path, args):
        self.debugg(path, args)

        client_data = ray.ClientData(*args)
        self._signaler.new_client_added.emit(client_data)

    @make_method('/ray/client/update', 'ssssissssi')
    def updateClientProperties(self, path, args):
        self.debugg(path, args)

        client_data = ray.ClientData(*args)
        self._signaler.client_updated.emit(client_data)

    @make_method('/ray/client/status', 'si')
    def guiClientStatus(self, path, args):
        self.debugg(path, args)

        client_id, status = args

        if status == ray.ClientStatus.REMOVED:
            self._signaler.client_removed.emit(client_id)
            return

        self._signaler.client_status_changed.emit(client_id, status)

    @make_method('/ray/client/switch', 'ss')
    def guiClientSwitch(self, path, args):
        self.debugg(path, args)

        old_client_id, new_client_id = args

        self._signaler.client_switched.emit(old_client_id, new_client_id)

    @make_method('/ray/client/progress', 'sf')
    def guiClientProgress(self, path, args):
        self.debugg(path, args)

        client_id, progress = args

        self._signaler.client_progress.emit(client_id, progress)

    @make_method('/ray/client/dirty', 'si')
    def guiClientDirty(self, path, args):
        self.debugg(path, args)

        client_id, dirty_num = args
        bool_dirty = bool(dirty_num)

        self._signaler.client_dirty_sig.emit(client_id, bool_dirty)

    @make_method('/ray/client/has_optional_gui', 's')
    def guiClientHasOptionalGui(self, path, args):
        self.debugg(path, args)

        client_id = args[0]
        self._signaler.client_has_gui.emit(client_id)

    @make_method('/ray/client/gui_visible', 'si')
    def guiClientGuiVisible(self, path, args):
        self.debugg(path, args)

        client_id, state = args
        self._signaler.client_gui_visible_sig.emit(client_id, bool(state))

    @make_method('/ray/client/still_running', 's')
    def guiClientStillRunning(self, path, args):
        self.debugg(path, args)

        client_id = args[0]
        self._signaler.client_still_running.emit(client_id)

    @make_method('/ray/gui/server_progress', 'f')
    def guiServerProgress(self, path, args):
        self.debugg(path, args)

        progress = args[0]
        self._signaler.server_progress.emit(progress)

    @make_method('/ray/server_status', 'i')
    def rayServerStatus(self, path, args):
        server_status = args[0]
        self._signaler.server_status_changed.emit(server_status)

    @make_method('/ray/opening_nsm_session', None)
    def rayOpeningNsmSession(self, path, args):
        self._signaler.opening_session.emit()

    @make_method('/ray/gui/clients_reordered', None)
    def rayGuiReorderClients(self, path, args):
        for arg in args:
            if not isinstance(arg, str):
                return

        self._signaler.clients_reordered.emit(args)

    @make_method('/ray/trash/add', 'ssssissssi')
    def rayGuiTrashAdd(self, path, args):
        self.debugg(path, args)

        client_data = ray.ClientData(*args)
        self._signaler.trash_add.emit(client_data)

    @make_method('/ray/trash/remove', 's')
    def rayGuiTrashRemove(self, path, args):
        self.debugg(path, args)

        client_id = args[0]
        self._signaler.trash_remove.emit(client_id)

    @make_method('/ray/trash/clear', '')
    def rayGuiTrashClear(self, path, args):
        self.debugg(path, args)

        self._signaler.trash_clear.emit()

    def debugg(self, path, args):
        if CommandLineArgs.debug:
            sys.stderr.write(
                '\033[93mserverOSC::raysession_receives\033[0m %s, %s.\n' %
                (path, str(args)))

    def toDaemon(self, *args):
        print('shod send', self._daemon_manager.address, *args)
        print(*args)
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

        print('opooo')

        if with_net:
            self.toDaemon('/ray/server/list_sessions', 1)
        else:
            self.toDaemon('/ray/server/list_sessions', 0)

    def newSession(self, session_name):
        self.toDaemon('/ray/server/new_session', session_name)

    def newSessionFromTemplate(self, session_name, template_name):
        self.toDaemon(
            '/ray/server/new_from_template',
            session_name,
            template_name)

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
