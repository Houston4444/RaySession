from distutils.log import error
from enum import Enum
import logging
import sys
import time

from osclib import BunServer, OscPack, Address
import osc_paths
import osc_paths.ray as r


_logger = logging.getLogger(__name__)


class ExpectedRetType(Enum):
    NONE = 0
    BOOL = 1
    SINGLE = 2
    LIST = 3


class OscServer(BunServer):
    def __init__(self):
        super().__init__()
        
        self._daemon_address: Address | None = None

        self._stop_ports = list[int]()
        self.wait_for_start = False
        self.starting_ports = set[int]()
        
        self.add_nice_method(osc_paths.REPLY, 's.*', self._reply)
        self.add_nice_method(osc_paths.ERROR, 'sis', self._error)
        self.add_nice_method(osc_paths.MINOR_ERROR, 'sis', self._minor_error)
        self.add_nice_method(r.control.MESSAGE, 's', self._message)
        self.add_nice_method(
            r.control.SERVER_ANNOUNCE, 'siisi', self._server_announce)
        self.op_done = False
        self.ret = None
        self.expected_rets = dict[str, ExpectedRetType]()
        self._waited_path = ''
    
    def _reply(self, osp: OscPack):
        reply_path: str = osp.args[0] # type:ignore
        
        # print(osp.path, osp.args)
        
        if reply_path == r.server.QUIT:
            if osp.src_addr.port == self._stop_port_list[0]:
                self._stop_port_list.pop(0)
                if self._stop_port_list:
                    self._stop_daemon(self._stop_port_list[0])
                return
        
        if reply_path != self._waited_path:
            _logger.warning(f'waiting {self._waited_path}, '
                            f'reply from {reply_path}')
            return
        
        match reply_path.rpartition('/')[2].partition('_')[0]:
            case 'list':
                if len(osp.args) >= 2:
                    if not isinstance(self.ret, list):
                        self.ret = []
                    self.ret += osp.args[1:]
                else:
                    self.op_done = True
                return

            case 'get':
                if len(osp.args) == 2:
                    self.ret = osp.args[1]
                    return
                if len(osp.args) == 1:
                    self.op_done = True
                    return
        
        self.op_done = True
        self.ret = True
        
    def _error(self, osp: OscPack):
        # print(osp.path, osp.args)
        
        error_path: str = osp.args[0] # type:ignore
        if error_path != self._waited_path:
            _logger.warning(f'waiting {self._waited_path}, '
                            f'error from {error_path}')
            return

        self.op_done = True
        self.ret = False
    
    def _minor_error(self, osp: OscPack):
        ...
    
    def _message(self, osp: OscPack):
        ...
    
    def _server_announce(self, osp: OscPack):
        _logger.info(
            f'Daemon started at port {osp.src_addr.port}')

        self.wait_for_start = False
        self._daemon_address = osp.src_addr
    
    def _stop_daemon(self, port: int):
        sys.stderr.write(f'--- Stopping daemon at port {port} ---\n')
        self.send(port, r.server.QUIT)

    def stop_daemons(self, stop_port_list: list[int]):
        self._stop_port_list = stop_port_list
        if self._stop_port_list:
            self._stop_daemon(self._stop_port_list[0])
    
    def send(self, port: int | Address, path: str, *args):
        self.op_done = False

        self._waited_path: str = path
        match path.rpartition('/')[2].partition('_')[0]:
            case 'list':
                self.ret = []
            case 'get', 'has':
                self.ret = ''
            case _:
                self.ret = False
        super().send(port, path, *args)
    
    def send_it(self, daemon_addr, path: str, *args):
        match path.rpartition('/')[2].partition('_')[0]:
            case 'has':
                exp_ret = ExpectedRetType.BOOL
            case 'list':
                exp_ret = ExpectedRetType.LIST
            case 'get':
                exp_ret = ExpectedRetType.SINGLE
            case _:
                exp_ret = ExpectedRetType.NONE
        
        self.expected_rets[path] = exp_ret


