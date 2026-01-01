# Imports from standard library
from pathlib import Path
from typing import TYPE_CHECKING

# third party imports
from qtpy.QtCore import QCoreApplication

# Imports from src/shared
import ray
import osc_paths.ray.gui as rg

# Local imports
from client import Client
from daemon_tools import NoSessionPath

from .session_op import SessionOp

if TYPE_CHECKING:
    from session import Session


_translate = QCoreApplication.translate


class SwitchClientAlternative(SessionOp):
    def __init__(self, session: 'Session',
                 client: Client, client_id: str, save_client=False):
        super().__init__(session)
        self.client = client
        print('on init ', self.client.client_id)
        self.client_id = client_id
        'the client_id to switch to'
        self.save_client = save_client
        self._tmp_dir: Path | None = None
        self._client_running = False
        self._new_client: Client | None = None
        self.routine = [
            self.save_the_client, self.copy_client, self.rename_files]
        
    def save_the_client(self):
        client = self.client
        if (self.save_client and client.is_running
                and not client.is_dumb_client()):
            client.save()
            
        self.next(ray.WaitFor.REPLY, timeout=5000)
        
    def copy_client(self):
        session = self.session
        client = self.client

        if session.path is None:
            raise NoSessionPath
        
        for client in session.trashed_clients:
            if client.client_id == self.client_id:
                self._new_client = client
                break
        else:
            self._new_client = Client(session)
            self._new_client.eat_attributes(client)
            self._new_client.client_id = self.client_id
            session.trashed_clients.append(self._new_client)

            self._tmp_dir = session.path / f'.client_copy.{self.client_id}'
            
            try:
                self._tmp_dir.mkdir()
            except:
                self.error(
                    ray.Err.CREATE_FAILED, 
                    f'failed to create {self._tmp_dir} '
                    'needed for client copy')
                return
            
            session.file_copier.start_client_copy(
                client.client_id, client.project_files, self._tmp_dir)
        
        self.next(ray.WaitFor.FILE_COPY)
        
    def rename_files(self):
        session = self.session
        client = self.client
        
        if session.file_copier.aborted:
            self.error(ray.Err.COPY_ABORTED, 
                       'Failed to switch client to alternative, copy aborted')
            return        
        
        if session.path is None or self._new_client is None:
            raise NoSessionPath
        
        if self._tmp_dir is not None:
            for file_path in self._tmp_dir.iterdir():
                try:
                    if file_path.name == client.project_path.name:
                        file_path.rename(
                            session.path / self._new_client.project_path.name)
                    else:
                        file_path.rename(
                            session.path
                            / file_path.name.replace(
                                client.project_path.name + '.',
                                self._new_client.project_path.name + '.'))
                except:
                    self.error(ray.Err.CREATE_FAILED,
                            f'Failed to copy {file_path.name}')
                    return
            
            try:
                self._tmp_dir.unlink()
            except:
                self.minor_error(
                    ray.Err.CREATE_FAILED,
                    f'failed to remove {self._tmp_dir}, not so strong')
        switch = client.can_switch_with(self._new_client)
        
        client.set_status(ray.ClientStatus.REMOVED)
        tmp_client = Client(session)
        tmp_client.eat_attributes(client)
        tmp_client.client_id = client.client_id
        client.eat_attributes(self._new_client)
        client.client_id = self.client_id
        
        self._new_client.eat_attributes(tmp_client)
        self._new_client.client_id = tmp_client.client_id

        new_client_index = session.trashed_clients.index(self._new_client)
        session.trashed_clients.remove(self._new_client)
        session.trashed_clients.insert(new_client_index, self._new_client)
        client.sent_to_gui = False
        client.send_gui_client_properties()
        session.send_gui(
            rg.session.SORT_CLIENTS,
            *[c.client_id for c in session.clients])
        
        if client.is_running:
            if switch:
                client.switch()
            else:
                client.stop()
        
        self.reply(f'client {tmp_client.client_id} switched to '
                   f'alternative {self.client_id}')