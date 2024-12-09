import logging
from typing import TYPE_CHECKING, Optional

from patchbay.patchcanvas.patshared import GroupPos

from osclib import ServerThread, get_free_osc_port, TCP, get_net_url, make_method, Address

if TYPE_CHECKING:
    from gui_session import SignaledSession


_logger = logging.getLogger(__name__)
_instance: 'Optional[GuiTcpThread]' = None


def ray_method(path, types):
    def decorated(func):
        @make_method(path, types)
        def wrapper(*args, **kwargs):
            t_thread, t_path, t_args, t_types, src_addr, rest = args
            if TYPE_CHECKING:
                assert isinstance(t_thread, GuiTcpThread)

            # if CommandLineArgs.debug:
            #     sys.stderr.write(
            #         '\033[93mOSC::gui_receives\033[0m %s, %s, %s, %s\n'
            #         % (t_path, t_types, t_args, src_addr.url))

            if t_thread.stopping:
                return

            response = func(*args[:-1], **kwargs)

            if not response is False:
                t_thread.signaler.osc_receive.emit(t_path, t_args)

            return response
        return wrapper
    return decorated


class GuiTcpThread(ServerThread):
    def __init__(self):
        port = get_free_osc_port(5644, TCP)
        ServerThread.__init__(self, port, TCP)

        global _instance
        _instance = self
        
        self.stopping = False
        self.patchbay_addr: Optional[Address] = None
        self.daemon_addr: Optional[Address] = None
    
    @staticmethod
    def instance() -> 'GuiTcpThread':
        return _instance
    
    def finish_init(self, session: 'SignaledSession'):
        self.session = session
        self.signaler = self.session.signaler
        self.daemon_manager = self.session.daemon_manager

        # all theses OSC messages are directly treated by
        # SignaledSession in gui_session.py
        # in the function with the the name of the message
        # with '/' replaced with '_'
        # for example /ray/gui/session/name goes to
        # _ray_gui_session_name

        for path_types in (
                ('/ray/gui/patchbay/port_added', 'siih'),
                ('/ray/gui/patchbay/port_renamed', 'ss'),
                ('/ray/gui/patchbay/port_removed', 's'),
                ('/ray/gui/patchbay/connection_added', 'ss'),
                ('/ray/gui/patchbay/connection_removed', 'ss'),
                ('/ray/gui/patchbay/server_stopped', ''),
                ('/ray/gui/patchbay/metadata_updated', 'hss'),
                ('/ray/gui/patchbay/dsp_load', 'i'),
                ('/ray/gui/patchbay/add_xrun', ''),
                ('/ray/gui/patchbay/buffer_size', 'i'),
                ('/ray/gui/patchbay/sample_rate', 'i'),
                ('/ray/gui/patchbay/server_started', ''),
                ('/ray/gui/patchbay/big_packets', 'i'),
                ('/ray/gui/patchbay/server_lose', ''),
                ('/ray/gui/patchbay/fast_temp_file_memory', 's'),
                ('/ray/gui/patchbay/client_name_and_uuid', 'sh'),
                ('/ray/gui/patchbay/transport_position', 'iiiiiif'),
                ('/ray/gui/patchbay/update_group_position', 'i' + GroupPos.args_types()),
                ('/ray/gui/patchbay/views_changed', 's')):
            self.add_method(path_types[0], path_types[1],
                            self._generic_callback)
        
    def _generic_callback(self, path, args, types, src_addr):        
        if self.stopping:
            return

        # if CommandLineArgs.debug:
        #     sys.stderr.write('\033[93mOSC::gui_receives\033[0m (%s, %s, %s)\n'
        #                      % (path, args, types))

        self.signaler.osc_receive.emit(path, args)
    
    @ray_method('/ray/gui/patchbay/announce', 'iiis')
    def _ray_gui_patchbay_announce(self, path, args, types, src_addr):
        self.patchbay_addr = Address(args[3])
    
    @ray_method('/ray/gui/patchbay/update_portgroup', None)
    def _ray_gui_patchbay_update_portgroup(
            self, path, args, types: str, src_addr: Address):
        if not types.startswith('siiis'):
            return False

        types_end = types.replace('siiis', '', 1)
        for c in types_end:
            if c != 's':
                return False
    
    def stop(self):
        self.stopping = True


        if self.patchbay_addr is not None:
            self.send(
                self.patchbay_addr, '/ray/patchbay/gui_disannounce',
                get_net_url(self.port, protocol=TCP))

        super().stop()
    
    def set_daemon_tcp_url(self, url: str):
        try:
            self.daemon_addr = Address(url)
        except:
            _logger.error(f'Failed to instantiate Address from url {url}')
    
    def send_patchbay_daemon(self, *args):
        if self.patchbay_addr is None:
            return
        
        try:
            self.send(self.patchbay_addr, *args)
        except OSError:
            _logger.warning(
                'Failed to send message to patchbay daemon '
                f'{self.patchbay_addr.url}')
            self.patchbay_addr = None
        except BaseException as e:
            _logger.error(str(e))