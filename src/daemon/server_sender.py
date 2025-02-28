
# Imports from standard library
import logging
from typing import TYPE_CHECKING, Optional

# Imports from src/shared
import ray
from osclib import MegaSend
import osc_paths as p
import osc_paths.ray.gui as RG

# Local imports
from osc_server_thread import OscServerThread, Gui
from daemon_tools import AppTemplate

if TYPE_CHECKING:
    from osc_server_thread import OscServerThread


_logger = logging.getLogger(__name__)


class ServerSender:
    '''Abstract class giving some quick access to OSC server'''
    
    def __init__(self):
        self.is_dummy = False

    def has_server(self) -> bool:
        if not OscServerThread.get_instance():
            return False

        return not self.is_dummy

    def send(self, *args):
        if self.is_dummy:
            return

        server = OscServerThread.get_instance()
        if not server:
            return

        server.send(*args)

    def send_even_dummy(self, *args):
        server = OscServerThread.get_instance()
        if not server:
            return

        server.send(*args)

    def send_patchbay_daemon(self, *args):
        server = OscServerThread.get_instance()
        if not server:
            return
        
        server.send_patchbay_dmn(*args)

    def mega_send(self, addr, mega_send: MegaSend):
        server = OscServerThread.get_instance()
        if not server:
            return
        
        server.mega_send(addr, mega_send)

    def mega_send_patchbay(self, mega_send: MegaSend):
        server = OscServerThread.get_instance()
        if not server:
            return
        
        server.mega_send_patchbay(mega_send)

    def mega_send_gui(self, mega_send: MegaSend):
        server = OscServerThread.get_instance()
        if not server:
            return
        
        server.mega_send_gui(mega_send)

    def send_gui(self, *args):
        if self.is_dummy:
            return

        server = OscServerThread.get_instance()
        if not server:
            return

        server.send_gui(*args)

    def send_gui_message(self, message:str):
        self.send_gui(RG.server.MESSAGE, message)

        server = OscServerThread.get_instance()
        if server:
            server.send_controller_message(message)

    def set_server_status(self, server_status:ray.ServerStatus):
        if self.is_dummy:
            return

        server = OscServerThread.get_instance()
        if not server:
            return

        server.set_server_status(server_status)

    def get_server_status(self) -> ray.ServerStatus:
        if self.is_dummy:
            return ray.ServerStatus.OFF

        server = OscServerThread.get_instance()
        if not server:
            return ray.ServerStatus.OFF

        return server.server_status

    def is_nsm_locked(self):
        if self.is_dummy:
            return False

        server = OscServerThread.get_instance()
        if not server:
            return False

        return server.is_nsm_locked

    def get_server(self) -> 'Optional[OscServerThread]':
        if self.is_dummy:
            return None
        
        return OscServerThread.get_instance()

    def get_server_even_dummy(self):
        return OscServerThread.get_instance()

    def get_server_url(self):
        server = OscServerThread.get_instance()
        if server:
            return server.url

        return ''

    def get_server_port(self):
        server = OscServerThread.get_instance()
        if server:
            return server.port

        return 0

    def answer(self, src_addr, src_path, message, err=ray.Err.OK):
        if err == ray.Err.OK:
            self.send(src_addr, p.REPLY, src_path, message)
        else:
            self.send(src_addr, p.ERROR, src_path, err, message)

    def has_server_option(self, option: ray.Option) -> bool:
        server = self.get_server()
        if not server:
            return False

        return bool(option in server.options)

    def get_client_templates_database(self, base: str) -> list[AppTemplate]:
        server = OscServerThread.get_instance()
        if server:
            return server.client_templates_database[base]
        return []
