import os
import sys

import ray
from daemon_manager import DaemonManager
from gui_client import Client
from gui_signaler import Signaler
from gui_server_thread import GUIServerThread
from gui_tools import initGuiTools, CommandLineArgs, settings
from main_window import MainWindow

_instance = None

from PyQt5.QtWidgets import QMainWindow

class Session(object):
    def __init__(self):
        self.client_list     = []
        self.trashed_clients = []
        self.name            = None
        self.is_running      = False
        self.server_status   = ray.ServerStatus.OFF
        
        self.is_renameable = True
        
        #global _instance
        #_instance = self
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
        
        #build and show Main UI
        self._main_win = MainWindow(self)
        
        ##build and start liblo server
        
        
        self._daemon_manager.finishInit()
        server.finishInit(self)
        #self._nsm_child.finishInit()
        #self._main_win.finishInit()
        
        self._main_win.show()
        
        #The only way I found to not show Messages Dock by default.
        if not settings.value('MainWindow/ShowMessages', False, type=bool):
            self._main_win.hideMessagesDock()
        
        self._daemon_manager.start()
        
        
    
    @staticmethod
    def instance():
        global _instance
        if not _instance:
            _instance = Session()
        return _instance
    
    def quit(self):
        print('kkk')
        self._main_win.hide()
        
        #del self._main_win._server
        print('kkkkk')
        del self._main_win
        print('jjoo')
    
    def setRunning(self, bool):
        self.is_running = bool
        
    def isRunning(self):
        return bool(self.server_status != ray.ServerStatus.OFF)
    
    def updateServerStatus(self, server_status):
        self.server_status = server_status
    
    def setName(self, session_name):
        self.name = session_name
        
    def getClient(self, client_id):
        for client in self.client_list:
            if client.client_id == client_id:
                return client
        else:
            sys.stderr.write(
                "session::getClient client '%s' not in client_list !!!\n"
                    % client_id)
            
            print(self.client_list)
            print(self.name)
    
    def addClient(self, client_data):
        client = Client(self, client_data)
        self.client_list.append(client)
        print('addClient ok', client.client_id)
    
    def removeClient(self, client_id):
        client = self.getClient(client_id)
        if client:
            client.properties_dialog.close()
            self.client_list.remove(client)
            del client
            
        print('removeClient warum')
    
    def updateClientProperties(self, client_data):
        client = self.getClient(client_data.client_id)
        if client:
            client.updateClientProperties(client_data)
    
    def updateClientStatus(self, client_id, status):
        client = self.getClient(client_id)
        if client:
            client.setStatus(status)
            
    def setClientHasGui(self, client_id):
        client = self.getClient(client_id)
        if client:
            client.setGuiEnabled()
        
    def setClientGuiState(self, client_id, state):
        client = self.getClient(client_id)
        if client:
            client.setGuiState(state)
        
    def setClientDirtyState(self, client_id, bool_dirty):
        client = self.getClient(client_id)
        if client:
            client.setDirtyState(bool_dirty)
    
    def switchClient(self, old_client_id, new_client_id):
        client = self.getClient(old_client_id)
        if client:
            client.switch(new_client_id)
    
    def clientIsStillRunning(self, client_id):
        client = self.getClient(client_id)
        if client:
            client.allowKill()
    
    def removeAllClients(self):
        self.client_list.clear()
        
    def reOrderClients(self, client_id_list):
        new_client_list = []
        for client_id in client_id_list:
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
