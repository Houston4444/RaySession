from enum import Enum
import subprocess
from typing import Any

from osclib import BunServer, OscPack


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
        
        self.add_nice_method('/reply', 's.*', self.get_reply)
        self.add_nice_method('/error', 'sis', self.get_error)
        self.op_done = False
        self.ret = None
        self.expected_rets = dict[str, ExpectedRetType]()
    
    def get_reply(self, osp: OscPack):
        self.op_done = True
        ret = osp.args[1:]
        match len(ret):
            case 0:
                self.ret = None
            case 1:
                self.ret = ret[0]
            case _:
                self.ret = ret
        
    def get_error(self, osp: OscPack):
        print('ohnonnn', osp.path, osp.args)
        self.op_done = True
        
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
