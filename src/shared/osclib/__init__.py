from dataclasses import dataclass
from typing import Union
import logging

_logger = logging.getLogger(__name__)
    
# Do not remove any imports here !!!
try:
    from liblo import (
        UDP, UNIX, TCP, Message, Bundle, Address, Server, ServerThread,
        ServerError, AddressError, time, make_method)
except ImportError:
    try:
        from pyliblo3 import (
            UDP, UNIX, TCP, Message, Bundle, Address, Server, ServerThread,
            ServerError, AddressError, time, make_method)
    except BaseException as e:
        _logger.error(
            'Failed to find a liblo lib for OSC (liblo or pyliblo3)')
        _logger.error(str(e))


@dataclass()
class OscPack:
    path: str
    args: list[Union[str, int, float, bytes]]
    types: str
    src_addr: Address
    
    def reply(self) -> tuple[Address, str, str]:
        return (self.src_addr, '/reply', self.path)
    
    def error(self) -> tuple[Address, str, str]:
        return (self.src_addr, '/error', self.path)


def get_free_osc_port(default=16187) -> int:
    '''get a free OSC port for daemon, start from default'''

    if default >= 65536:
        default = 16187

    daemon_port = default
    used_port = True
    testport = None

    while used_port:
        try:
            testport = Server(daemon_port)
            used_port = False
        except BaseException:
            daemon_port += 1
            used_port = True

    del testport
    return daemon_port
