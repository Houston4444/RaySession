from enum import Enum
import logging
import subprocess
import sys

from osclib import BunServer, OscPack, Address
import osc_paths
import osc_paths.ray as r


_logger = logging.getLogger(__name__)


class RayError(Exception):
    def __init__(self) -> None:
        super().__init__(f"Operation failed !!!")


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
    
    def _reply(self, osp: OscPack):
        reply_path: str = osp.args[0] # type:ignore
        
        if reply_path == r.server.QUIT:
            if osp.src_addr.port == self._stop_port_list[0]:
                stopped_port = self._stop_port_list.pop(0)

                if self._stop_port_list:
                    self._stop_daemon(self._stop_port_list[0])
                return
        
        self.op_done = True
        ret = osp.args[1:]
        match len(ret):
            case 0:
                self.ret = None
            case 1:
                self.ret = ret[0]
            case _:
                self.ret = ret
        
    def _error(self, osp: OscPack):
        self.op_done = True
    
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

def send_and_wait(path: str, *args):
    rc_proc = subprocess.run(
        ['ray_control', 'get_port'], capture_output=True)
    sport_bytes = rc_proc.stdout
    print(f'{sport_bytes=}')
    if sport_bytes is None:
        return
    
    sport_str = sport_bytes.decode()
    if sport_str.endswith('\n'):
        sport_str = sport_str[:-1]
    if not sport_str.isdigit():
        return
    
    server_port = int(sport_str)
    print(f'{server_port=}')
    osc_server = OscServer()
    osc_server.send(server_port, path, *args)
    while not osc_server.op_done:
        osc_server.recv(50)
    
    return osc_server.ret
