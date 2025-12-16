# Imports from standard library
import logging
from typing import TYPE_CHECKING

# third party imports
from qtpy.QtCore import QCoreApplication

# Imports from src/shared
import osc_paths.ray.gui as rg
import ray

# Local imports
from client import Client
from patch_rewriter import rewrite_jack_patch_files

from .session_op import SessionOp

if TYPE_CHECKING:
    from session_operating import OperatingSession


_translate = QCoreApplication.translate
_logger = logging.getLogger(__name__)


class RenameFullClient(SessionOp):
    def __init__(self, session: 'OperatingSession', client: Client,
                 new_name: str, new_client_id: str):
        super().__init__(session)
        self.client = client
        self.new_name = new_name
        self.new_client_id = new_client_id
        self.routine = [self.save_client_and_patchers,
                        self.stop_client,
                        self.kill_client,
                        self.rename_full_client]

        self._was_running = False
        self._old_client_id = client.client_id

    def save_client_and_patchers(self):
        session = self.session
        for client in session.clients:
            if (client is self.client or 
                    (client.is_running and client.can_patcher)):
                session.expected_clients.append(client)
                client.save()
        
        self.next(ray.WaitFor.REPLY, timeout=10000)

    def stop_client(self):
        session = self.session
        session.expected_clients.clear()
        
        if self.client.is_running and not self.client.can_switch:
            self._was_running = True
            session.expected_clients.append(self.client)
            self.client.stop()

        self.next(ray.WaitFor.STOP_ONE, timeout=30000)

    def kill_client(self):
        if self.client in self.session.expected_clients:
            self.client.kill()
        
        self.next(ray.WaitFor.STOP_ONE, timeout=1000)

    def rename_full_client(self):
        session = self.session
        client = self.client
        if session.path is None:
            _logger.error('Impossible to rename full client, no path !!!')
            self.error(ray.Err.NO_SESSION_OPEN, 
                       'Impossible to rename full client, no path !!!')
            return
        
        tmp_client = Client(session)
        tmp_client.eat_attributes(client)
        tmp_client.client_id = self.new_client_id
        tmp_client.jack_naming = ray.JackNaming.LONG
        
        client.set_status(ray.ClientStatus.REMOVED)
        
        client._rename_files(
            session.path,
            session.name, session.name,
            client.prefix, tmp_client.prefix,
            client.client_id, tmp_client.client_id,
            client.links_dirname, tmp_client.links_dirname)

        ex_jack_name = client.jack_client_name
        ex_client_id = client.client_id
        new_jack_name = tmp_client.jack_client_name

        client.client_id = self.new_client_id
        client.jack_naming = ray.JackNaming.LONG
        client.label = self.new_name
        session._update_forbidden_ids_set()

        if new_jack_name != ex_jack_name:
            rewrite_jack_patch_files(
                session, ex_client_id, self.new_client_id,
                ex_jack_name, new_jack_name)
            session.canvas_saver.client_jack_name_changed(
                ex_jack_name, new_jack_name)

        client.sent_to_gui = False
        client.send_gui_client_properties()
        session.send_gui(rg.session.SORT_CLIENTS,
                      *[c.client_id for c in session.clients])

        # we need to save session file here
        # else, if session is aborted
        # client won't find its files at next restart
        session._save_session_file()

        session.send_monitor_event(
            'id_changed_to:' + self.new_client_id, ex_client_id)
        # session.next_function()
    
        if client.is_running:
            client.switch()
        elif self._was_running:
            client.start()
            
        session.message(
            f'client {self._old_client_id} renamed to {self.new_client_id}')
        self.reply('full client rename done.')