
from typing import TYPE_CHECKING

import ray
from patchbay_manager import PatchbayManager
from gui_server_thread import GuiServerThread

if TYPE_CHECKING:
    from gui_session import Session

class PatchbayMainManager(PatchbayManager):
    def __init__(self, session: 'Session'):
        super().__init__(session)

    @staticmethod
    def send_to_patchbay_daemon(*args):
        server = GuiServerThread.instance()
        if not server:
            return

        if server.patchbay_addr is None:
            return

        server.send(server.patchbay_addr, *args)

    @staticmethod
    def send_to_daemon(*args):
        server = GuiServerThread.instance()
        if not server:
            return
        server.to_daemon(*args)
        
    def refresh(self):
        super().refresh()
        self.send_to_patchbay_daemon('/ray/patchbay/refresh')
    
    def disannounce(self):
        self.send_to_patchbay_daemon('/ray/patchbay/gui_disannounce')
        super().disannounce()
    
    def save_group_position(self, gpos: ray.GroupPosition):
        super().save_group_position(gpos)
        self.send_to_daemon(
            '/ray/server/patchbay/save_group_position', *gpos.spread())
        
    def change_buffersize(self, buffer_size: int):
        super().change_buffersize(buffer_size)
        self.send_to_patchbay_daemon('/ray/patchbay/set_buffer_size',
                                     buffer_size)
        
    def receive_big_packets(self, state: int):
        self.optimize_operation(not bool(state))
        if state:
            self.redraw_all_groups()