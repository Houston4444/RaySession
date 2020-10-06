
from PyQt5.QtWidgets import QApplication

import ray
from daemon_manager import DaemonManager
from gui_client import Client, TrashedClient
from gui_signaler import Signaler
from gui_server_thread import GUIServerThread
from gui_tools import CommandLineArgs, RS
from main_window import MainWindow
from nsm_child import NSMChild, NSMChildOutside


class Session:
    def __init__(self):
        self.client_list = []
        self.trashed_clients = []
        self.favorite_list = []
        self.name = ''
        self.path = ''
        self.notes = ''
        self.is_running = False
        self.server_status = ray.ServerStatus.OFF

        self.is_renameable = True

        self._signaler = Signaler()

        server = GUIServerThread.instance()
        server.start()
        print('serverport', server.port)
        self._daemon_manager = DaemonManager(self)
        if CommandLineArgs.daemon_url:
            self._daemon_manager.setOscAddress(CommandLineArgs.daemon_url)
        elif CommandLineArgs.daemon_port:
            self._daemon_manager.setOscAddress(CommandLineArgs.daemon_port)
        elif not CommandLineArgs.out_daemon:
            self._daemon_manager.setNewOscAddress()

        # build nsm_child if NSM_URL in env
        self._nsm_child = None

        if CommandLineArgs.under_nsm:
            if CommandLineArgs.out_daemon:
                self._nsm_child = NSMChildOutside(self)
                self._daemon_manager.setExternal()
            else:
                self._nsm_child = NSMChild(self)

        # build and show Main UI
        self._main_win = MainWindow(self)

        self._daemon_manager.finishInit()
        server.finishInit(self)

        self._main_win.show()

        # display donations dialog under conditions
        if not RS.settings.value('hide_donations', False, type=bool):
            coreff_counter = RS.settings.value('coreff_counter', 0, type=int)
            coreff_counter += 1
            RS.settings.setValue('coreff_counter', coreff_counter)

            if coreff_counter % 44 == 29:
                self._main_win.donate(True)

        # The only way I found to not show Messages Dock by default.
        if not RS.settings.value('MainWindow/ShowMessages', False, type=bool):
            self._main_win.hideMessagesDock()

    def quit(self):
        self._main_win.hide()
        del self._main_win

    def setRunning(self, running: bool):
        self.is_running = running

    def isRunning(self):
        return bool(self.server_status != ray.ServerStatus.OFF)

    def updateServerStatus(self, server_status):
        self.server_status = server_status

    def setName(self, session_name):
        self.name = session_name

    def setPath(self, session_path):
        self.path = session_path

    def getShortPath(self):
        if self.path.startswith(CommandLineArgs.session_root):
            return self.path.replace(
                '%s/' % CommandLineArgs.session_root, '', 1)

        return self.path

    def getClient(self, client_id):
        for client in self.client_list:
            if client.client_id == client_id:
                return client

        raise NameError("gui_session does not contains client %s"
                        % client_id)

    def removeAllClients(self):
        self.client_list.clear()
        
    def addFavorite(self, template_name: str, icon_name: str, factory: bool):
        server = GUIServerThread.instance()
        if server:
            server.toDaemon('/ray/favorites/add', template_name,
                            icon_name, int(factory))
            
    def removeFavorite(self, template_name: str, factory: bool):
        for favorite in self.favorite_list:
            if favorite.name == template_name and favorite.factory == factory:
                break
        
        server = GUIServerThread.instance()
        if server:
            server.toDaemon('/ray/favorites/remove', template_name, int(factory))
    
    def isFavorite(self, template_name: str, factory: bool):
        for favorite in self.favorite_list:
            if favorite.name == template_name and favorite.factory == factory:
                return True
        return False

    def setDaemonOptions(self, options):
        self._main_win.setDaemonOptions(options)
        for client in self.client_list:
            client.widget.setDaemonOptions(options)

class SignaledSession(Session):
    def __init__(self):
        Session.__init__(self)
        self._signaler.osc_receive.connect(self.oscReceive)

        self._daemon_manager.start()

    def oscReceive(self, path, args):
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
                        client.showPropertiesDialog(second_tab=True)
                        break


    def _error(self, path, args):
        err_path, err_code, err_message = args

        # don't shows a window error if error is OK
        # or related to an abort made by user
        if err_code in (ray.Err.OK, ray.Err.ABORT_ORDERED,
                        ray.Err.COPY_ABORTED):
            return

        self._main_win.errorMessage(err_message)

    def _minor_error(self, path, args):
        err_path, err_code, err_message = args

        # don't shows a window error if error is OK
        # or if it comes from just an unknown (and untreated) message
        if err_code in (ray.Err.OK, ray.Err.UNKNOWN_MESSAGE):
            return

        self._main_win.errorMessage(err_message)


    def _ray_gui_server_disannounce(self, path, args):
        QApplication.quit()

    def _ray_gui_server_nsm_locked(self, path, args):
        nsm_locked = bool(args[0])
        self._main_win.setNsmLocked(nsm_locked)

    def _ray_gui_server_message(self, path, args):
        message = args[0]
        self._main_win.printMessage(message)

    def _ray_gui_server_options(self, path, args):
        options = args[0]
        self.setDaemonOptions(options)

    def _ray_gui_session_name(self, path, args):
        sname, spath = args
        self.setName(sname)
        self.setPath(spath)
        self._main_win.renameSession(sname, spath)

    def _ray_gui_session_is_nsm(self, path, args):
        self._main_win.openingNsmSession()

    def _ray_gui_session_renameable(self, path, args):
        self.is_renameable = bool(args[0])

        bool_set_edit = bool(self.is_renameable
                             and self.server_status == ray.ServerStatus.READY
                             and not CommandLineArgs.out_daemon)

        self._main_win.setSessionNameEditable(bool_set_edit)

    def _ray_gui_session_notes(self, path, args):
        self.notes = args[0]
        # TODO write the notes GUI

    def _ray_gui_session_sort_clients(self, path, args):
        new_client_list = []
        for client_id in args:
            client = self.getClient(client_id)

            if not client:
                return

            new_client_list.append(client)

        self.client_list.clear()
        self._main_win.reCreateListWidget()

        self.client_list = new_client_list
        for client in self.client_list:
            client.reCreateWidget()
            client.widget.updateStatus(client.status)

    def _ray_gui_client_new(self, path, args):
        client = Client(self, *args[:2])
        client.updateClientProperties(*args)
        self.client_list.append(client)

        #client = Client(self, ray.ClientData.newFrom(*args))
        #self.client_list.append(client)

    def _ray_gui_client_update(self, path, args):
        client_id = args[0]
        client = self.getClient(client_id)
        if client:
            client.updateClientProperties(*args)

    def _ray_gui_client_ray_hack_update(self, path, args):
        client_id = args.pop(0)
        client = self.getClient(client_id)
        if client and client.protocol == ray.Protocol.RAY_HACK:
            client.updateRayHack(*args)

    def  _ray_gui_client_switch(self, path, args):
        old_id, new_id = args
        for client in self.client_list:
            if client.client_id == old_id:
                client.client_id = new_id
                break

    def _ray_gui_client_status(self, path, args):
        client_id, status = args
        client = self.getClient(client_id)
        if client:
            client.setStatus(status)

            if status == ray.ClientStatus.REMOVED:
                self._main_win.removeClient(client_id)
                client.properties_dialog.close()
                self.client_list.remove(client)
                del client

        self._main_win.clientStatusChanged(client_id, status)

    def _ray_gui_client_progress(self, path, args):
        client_id, progress = args

        client = self.getClient(client_id)
        if client:
            client.setProgress(progress)

    def _ray_gui_client_dirty(self, path, args):
        client_id, int_dirty = args
        client = self.getClient(client_id)
        if client:
            client.setDirtyState(bool(int_dirty))

    def _ray_gui_client_has_optional_gui(self, path, args):
        client_id = args[0]
        client = self.getClient(client_id)
        if client:
            client.setGuiEnabled()

    def _ray_gui_client_gui_visible(self, path, args):
        client_id, int_state = args
        client = self.getClient(client_id)
        if client:
            client.setGuiState(bool(int_state))

    def _ray_gui_client_still_running(self, path, args):
        client_id = args[0]
        client = self.getClient(client_id)
        if client:
            client.allowKill()

    def _ray_gui_client_no_save_level(self, path, args):
        client_id, no_save_level = args

        client = self.getClient(client_id)
        if client:
            client.setNoSaveLevel(no_save_level)

    def _ray_gui_trash_add(self, path, args):
        trashed_client = TrashedClient()
        trashed_client.update(*args)
        trash_action = self._main_win.trashAdd(trashed_client)
        trashed_client.setMenuAction(trash_action)
        self.trashed_clients.append(trashed_client)

    def _ray_gui_trash_ray_hack_update(self, path, args):
        client_id = args.pop(0)
        for trashed_client in self.trashed_clients:
            if trashed_client.client_id == client_id:
                trashed_client.ray_hack = ray.RayHack.newFrom(*args)
                break

    def _ray_gui_trash_remove(self, path, args):
        client_id = args[0]

        for trashed_client in self.trashed_clients:
            if trashed_client.client_id == client_id:
                break
        else:
            return

        self.trashed_clients.remove(trashed_client)
        self._main_win.trashRemove(trashed_client.menu_action)

    def _ray_gui_trash_clear(self, path, args):
        self.trashed_clients.clear()
        self._main_win.trashClear()

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
            self._signaler.favorite_added.emit(
                template_name, icon_name, bool(int_factory))
        self._main_win.updateFavoritesMenu()

    def _ray_gui_favorites_removed(self, path, args):
        template_name, int_factory = args
        
        for favorite in self.favorite_list:
            if (favorite.name == template_name
                    and favorite.factory == bool(int_factory)):
                break
        else:
            return

        self.favorite_list.remove(favorite)
        self._signaler.favorite_removed.emit(template_name, bool(int_factory))
        self._main_win.updateFavoritesMenu()

    def _ray_gui_script_info(self, path, args):
        text = args[0]
        self._main_win.showScriptInfo(text)

    def _ray_gui_hide_script_info(self, path, args):
        self._main_win.hideScriptInfoDialog()

    def _ray_gui_script_user_action(self, path, args):
        text = args[0]
        self._main_win.showScriptUserActionDialog(text)

    def _ray_gui_hide_script_user_action(self, path, args):
        self._main_win.hideScriptUserActionDialog()
