from PyQt5.QtWidgets import QMainWindow, QMenu
from PyQt5.QtCore import QObject
import os
import sys
import inspect

import ray
from daemon_manager import DaemonManager
from gui_client import Client, TrashedClient
from gui_signaler import Signaler
from gui_server_thread import GUIServerThread
from gui_tools import initGuiTools, CommandLineArgs, RS
from main_window import MainWindow
from nsm_child import NSMChild, NSMChildOutside

_instance = None

class Session(object):
    def __init__(self):
        self.client_list = []
        self.trashed_clients = []
        self.favorite_list = []
        self.name = ''
        self.path = ''
        self.is_running = False
        self.server_status = ray.ServerStatus.OFF

        self.is_renameable = True
        
        self._signaler = Signaler()
        
        server = GUIServerThread.instance()
        server.start()

        self._daemon_manager = DaemonManager(self)
        if CommandLineArgs.daemon_url:
            self._daemon_manager.setOscAddress(CommandLineArgs.daemon_url)
        elif not CommandLineArgs.out_daemon:
            self._daemon_manager.setNewOscAddress()

        if CommandLineArgs.under_nsm:
            if CommandLineArgs.out_daemon:
                self._nsm_child = NSMChildOutside(self)
                self._daemon_manager.setExternal()
            else:
                self._nsm_child = NSMChild(self)
        
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

        # The only way I found to not show Messages Dock by default.
        if not RS.settings.value('MainWindow/ShowMessages', False, type=bool):
            self._main_win.hideMessagesDock()

        self._daemon_manager.start()

    @staticmethod
    def instance():
        global _instance
        if not _instance:
            _instance = Session()
        return _instance

    def quit(self):
        self._main_win.hide()
        del self._main_win

    def setRunning(self, bool):
        self.is_running = bool

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
        else:
            raise NameError("gui_session does not contains client %s"
                                % client_id)

    #def addClient(self, client_data):
        #client = Client(self, client_data)
        #self.client_list.append(client)

    def removeClient(self, client_id):
        client = self.getClient(client_id)
        if client:
            client.properties_dialog.close()
            self.client_list.remove(client)
            del client

    #def updateClientStatus(self, client_id, status):
        #client = self.getClient(client_id)
        #if client:
            #client.setStatus(status)

    def removeAllClients(self):
        self.client_list.clear()
            
    def addFavorite(self, name, icon_name, factory, from_server=False):
        for favorite in self.favorite_list:
            if favorite.name == name and favorite.factory == factory:
                favorite.icon = icon_name
                return 
        
        fav = ray.Favorite(name, icon_name, factory)
        self.favorite_list.append(fav)
        
        self._main_win.updateFavoritesMenu()
        
        if not from_server:
            server = GUIServerThread.instance()
            if server:
                print('fkeorfav')
                server.toDaemon('/ray/favorites/add', name,
                                icon_name, int(factory))
        
    def removeFavorite(self, name, factory, from_server=False):
        for favorite in self.favorite_list:
            if favorite.name == name and favorite.factory == factory:
                self.favorite_list.remove(favorite)
                break
        
        self._main_win.updateFavoritesMenu()
        
        if not from_server:
            server = GUIServerThread.instance()
            if server:
                server.toDaemon('/ray/favorites/remove', name, int(factory))

    def setDaemonOptions(self, options):
        self._main_win.setDaemonOptions(options)
        for client in self.client_list:
            client.widget.setDaemonOptions(options)

class SignaledSession(Session):
    def __init__(self):
        Session.__init__(self)
        self._signaler.osc_receive.connect(self.oscReceive)
        
    def oscReceive(self, path, args, types, src_addr):
        func_path = path
        func_name = func_path.replace('/', '', 1).replace('/', '_')
        
        if func_name in self.__dir__():
            function = self.__getattribute__(func_name)
            function(path, args)
    
    def ray_gui_server_nsm_locked(self, path, args):
        nsm_locked = bool(args[0])
        self._main_win.setNsmLocked(nsm_locked)
    
    def ray_gui_server_message(self, path, args):
        message = args[0]
        self._main_win.printMessage(message)
    
    def ray_gui_server_options(self, path, args):
        options = args[0]
        self.setDaemonOptions(options)
    
    def ray_gui_session_name(self, path, args):
        sname, spath = args
        self.setName(sname)
        self.setPath(spath)
        self._main_win.renameSession(sname, spath)
        
    def ray_gui_session_is_nsm(self, path, args):
        self._main_win.openingNsmSession()
    
    def ray_gui_session_renameable(self, path, args):
        self.is_renameable = bool(args[0])
        
        bool_set_edit = bool(self.is_renameable
                             and self.server_status == ray.ServerStatus.READY
                             and not CommandLineArgs.out_daemon)
        
        self._main_win.setSessionNameEditable(bool_set_edit)
    
    def ray_gui_session_sort_clients(self, path, args):
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
    
    def ray_gui_client_new(self, path, args):
        client = Client(self, ray.ClientData(*args))
        self.client_list.append(client)
    
    def ray_gui_client_update(self, path, args):
        client_data = ray.ClientData(*args)
        client = self.getClient(client_data.client_id)
        if client:
            client.updateClientProperties(client_data)
    
    def ray_gui_client_status(self, path, args):
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
    
    def ray_gui_client_switch(self, path, args):
        old_client_id, new_client_id = args
        
        client = self.getClient(old_client_id)
        if client:
            client.switch(new_client_id)
    
    def ray_gui_client_progress(self, path, args):
        client_id, progress = args
        
        client = self.getClient(client_id)
        if client:
            client.setProgress(progress)
    
    def ray_gui_client_dirty(self, path, args):
        client_id, int_dirty = args
        client = self.getClient(client_id)
        if client:
            client.setDirtyState(bool(int_dirty))
    
    def ray_gui_client_has_optional_gui(self, path, args):
        client_id = args[0]
        client = self.getClient(client_id)
        if client:
            client.setGuiEnabled()
    
    def ray_gui_client_gui_visible(self, path, args):
        client_id, int_state = args
        client = self.getClient(client_id)
        if client:
            client.setGuiState(bool(int_state))
    
    def ray_gui_client_still_running(self, path, args):
        client_id = args[0]
        client = self.getClient(client_id)
        if client:
            client.allowKill()
    
    def ray_gui_client_no_save_level(self, path, args):
        client_id, no_save_level = args
        
        client = self.getClient(client_id)
        if client:
            client.setNoSaveLevel(no_save_level)
    
    def ray_gui_trash_add(self, path, args):
        client_data = ray.ClientData(*args)
        trash_action = self._main_win.trashAdd(client_data)
        trashed_client = TrashedClient(client_data, trash_action)
        self.trashed_clients.append(trashed_client)
    
    def ray_gui_trash_remove(self, path, args):
        client_id = args[0]
        
        for trashed_client in self.trashed_clients:
            if trashed_client.data.client_id == client_id:
                break
        else:
            return
        
        self.trashed_clients.remove(trashed_client)
        self._main_win.trashRemove(trashed_client.menu_action)
        
    def ray_gui_trash_clear(self, path, args):
        self.trashed_clients.clear()
        self._main_win.trashClear()
        
    def ray_gui_favorites_added(self, path, args):
        name, icon_name, int_factory = args
        self.addFavorite(name, icon_name, bool(int_factory), True)
        
    def ray_gui_favorites_remove(self, path, args):
        name, int_factory = args
        self.removeFavorite(name, bool(int_factory), True)
        
