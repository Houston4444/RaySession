
# Imports from standard library
import logging
from typing import TYPE_CHECKING, Optional
from osclib import Address, Message

# Imports from src/shared
import ray

# Local imports
from osc_server_thread import OscServerThread, Gui
from tcp_server_thread import TcpServerThread
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

    def send_tcp(self, *args):
        if self.is_dummy:
            return
        
        self.send_tcp_even_dummy(*args)

    def send_tcp_even_dummy(self, *args):
        tcp_server = TcpServerThread.instance()
        if not tcp_server:
            return
        
        try:
            tcp_server.send(*args)
        except BaseException as e:
            url: str = args[0]
            if isinstance(url, Address):
                url = url.url
            
            _logger.error(f'Failed to send TCP to {url}, {args[1:]}')
            _logger.error(str(e))

    def send_patchbay_daemon(self, *args):
        tcp_server = TcpServerThread.instance()
        if not tcp_server:
            return
        
        tcp_server.send_patchbay_daemon(*args)

    def mega_send(self, addr, messages: list[Message]):
        server = OscServerThread.get_instance()
        if not server:
            return
        
        server.mega_send(addr, messages)

    def mega_send_patchbay(self, messages: list[Message]):
        server = OscServerThread.get_instance()
        if not server:
            return
        
        server.mega_send_patchbay(messages)

    def mega_send_gui(self, messages: list[Message]):
        server = OscServerThread.get_instance()
        if not server:
            return
        
        server.mega_send_gui(messages)

    def send_gui(self, *args):
        if self.is_dummy:
            return

        server = OscServerThread.get_instance()
        if not server:
            return

        server.send_gui(*args)

    def send_tcp_gui(self, *args):
        if self.is_dummy:
            return
        
        server = OscServerThread.get_instance()
        tcp_server = TcpServerThread.instance()
        
        if server is None or tcp_server is None:
            return
        
        rm_tcps = list[Gui]()
        
        for gui in server.gui_list:
            if gui.tcp_addr is None:
                continue

            try:
                tcp_server.send(gui.tcp_addr, *args)
            except OSError:
                _logger.warning(
                    f'Failed to send TCP message to GUI at {gui.tcp_addr.url}')
                rm_tcps.append(gui.tcp_addr)
            except BaseException as e:
                _logger.warning(
                    f'Failed to send TCP message to GUI at {gui.tcp_addr.url}')
                _logger.error(str(e))
                
        for gui in rm_tcps:
            for gui_ in server.gui_list:
                if gui_ is gui:
                    gui_.tcp_addr = None
                    break

    def send_gui_message(self, message:str):
        self.send_gui('/ray/gui/server/message', message)

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
            self.send(src_addr, '/reply', src_path, message)
        else:
            self.send(src_addr, '/error', src_path, err, message)

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
