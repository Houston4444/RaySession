from typing import TYPE_CHECKING

from osclib import OscPack
import ray

from .session_op import SessionOp

if TYPE_CHECKING:
    from session_operating import OperatingSession


class ClearClients(SessionOp):
    '''Stop and kill if necessary all client,
    usable only from the load script.'''
    def __init__(self, session: 'OperatingSession', osp: OscPack):
        super().__init__(session, osp=osp)
        self.routine = [self.stop_clients,
                        self.kill_clients,
                        self.final_reply]
        
        self.client_ids: list[str] = osp.args # type:ignore

    def stop_clients(self):
        session = self.session
        session.clients_to_quit.clear()
        session.expected_clients.clear()

        for client in session.clients:
            if client.client_id in self.client_ids or not self.client_ids:
                session.clients_to_quit.append(client)
                session.expected_clients.append(client)

        session.timer_quit.start()
        self.next(ray.WaitFor.QUIT, timeout=5000)

    def kill_clients(self):
        for client in self.session.expected_clients:
            client.kill()

        self.next(ray.WaitFor.QUIT, timeout=1000)

    def final_reply(self):
        self.reply('Clients cleared')
