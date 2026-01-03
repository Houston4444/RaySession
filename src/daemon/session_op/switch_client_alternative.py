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
        self.client_id = client_id
        'the client_id to switch to'
        self.save_client = save_client
        self._was_running = False
        self._tmp_dir: Path | None = None
        self._new_client: Client | None = None
        self.routine = [
            self.save_the_client,
            self.stop_client,
            self.kill_client,
            self.copy_client,
            self.rename_files]

    def save_the_client(self):
        client = self.client
        if self.save_client and client.is_running and not client.is_dumb:
            client.save()
            
        self.next(ray.WaitFor.REPLY, timeout=5000)

    def stop_client(self):
        session = self.session
        client = self.client
        session.expected_clients.clear()
        
        for trashed_client in session.trashed_clients:
            if trashed_client.client_id == self.client_id:
                self._new_client = trashed_client
                break

        if (client.is_running
                and not (client.can_switch
                         and (self._new_client is None
                              or client.can_switch_with(self._new_client)))):
            self._was_running = True
            session.expected_clients.append(self.client)
            self.client.stop()

        self.next(ray.WaitFor.STOP_ONE, timeout=30000)

    def kill_client(self):
        if self.client in self.session.expected_clients:
            self.client.kill()
        
        self.next(ray.WaitFor.STOP_ONE, timeout=1000)

    def copy_client(self):
        session = self.session
        client = self.client

        if session.path is None:
            raise NoSessionPath
        
        if self._new_client is None:
            self._new_client = Client(session)
            self._new_client.eat_attributes(client)
            self._new_client.client_id = self.client_id
            pretty_id = self.client_id.replace('_', ' ')
            ex_pretty_id = client.client_id.replace('_', ' ')
            if pretty_id not in self._new_client.label:
                if self._new_client.label.endswith(f' ({ex_pretty_id})'):
                    self._new_client.label = \
                        self._new_client.label.rpartition(' (')[0]
                self._new_client.label += f' ({pretty_id})'
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
            client._rename_files(
                self._tmp_dir, session.name, session.name,
                client.prefix, self._new_client.prefix,
                client.client_id, self.client_id,
                client.links_dirname, self._new_client.links_dirname)

            for file_path in self._tmp_dir.iterdir():
                try:
                    file_path.rename(file_path.parents[1] / file_path.name)
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
        
        has_id_1, has_id_2, together = False, False, False
        for alter_group in session.alternative_groups:
            if client.client_id in alter_group:
                has_id_1 = True
                if self.client_id in alter_group:
                    has_id_1, has_id_2, together = True, True, True
                    break
            elif self.client_id in alter_group:
                has_id_2 = True
                
        if together:
            pass
        elif has_id_1 and has_id_2:
            for alter_group in session.alternative_groups:
                alter_group.discard(client.client_id)
                alter_group.discard(self.client_id)
        
            for alter_group in session.alternative_groups.copy():
                if len(alter_group) < 2:
                    session.alternative_groups.remove(alter_group)
        
            session.alternative_groups.append(
                {client.client_id, self.client_id})
            
        elif has_id_1:
            for alter_group in session.alternative_groups:
                if client.client_id in alter_group:
                    alter_group.add(self.client_id)
                    break
        
        elif has_id_2:
            for alter_group in session.alternative_groups:
                if self.client_id in alter_group:
                    alter_group.add(client.client_id)
                    break
        else:
            session.alternative_groups.append(
                {client.client_id, self.client_id})
        
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
            client.switch()
        elif self._was_running:
            client.start()
        
        self.reply(f'client {tmp_client.client_id} switched to '
                   f'alternative {self.client_id}')