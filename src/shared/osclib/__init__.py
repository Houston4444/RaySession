from dataclasses import dataclass
from typing import Union
import logging
import socket
import subprocess

_logger = logging.getLogger(__name__)
    
# Do not remove any imports here !!!
try:
    from liblo import (
        UDP, UNIX, TCP, Message, Bundle, Address, Server, ServerThread,
        ServerError, AddressError, time, make_method, send)
except ImportError:
    try:
        from pyliblo3 import (
            UDP, UNIX, TCP, Message, Bundle, Address, Server, ServerThread,
            ServerError, AddressError, time, make_method, send)
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


_mach192_dict = {'ip': '', 'read_done': False}

def _read_machine_192() -> str:
    try:
        ips = subprocess.check_output(
            ['ip', 'route', 'get', '1']).decode()
        ip_line = ips.partition('\n')[0]
        ip_end = ip_line.rpartition('src ')[2]
        ip = ip_end.partition(' ')[0]

    except BaseException:
        try:
            ips = subprocess.check_output(['hostname', '-I']).decode()
            ip = ips.split(' ')[0]
        except BaseException:
            return ''

    if ip.count('.') != 3:
        return ''
    
    return ip

def get_machine_192() -> str:
    '''return the string address of this machine, starting with 192.168.
    Value is saved, so, calling this function is longer the first time
    than the next ones.'''

    if _mach192_dict['read_done']:
        return _mach192_dict['ip']
    
    _mach192_dict['ip'] = _read_machine_192()
    _mach192_dict['read_done'] = True
    return _mach192_dict['ip']

def is_osc_port_free(port: int) -> bool:
    try:
        testport = Server(port)
    except BaseException:
        return False

    del testport
    return True

def get_free_osc_port(default=16187, protocol=UDP) -> int:
    '''get a free OSC port for daemon, start from default'''

    if default > 0x9999 or default < 0x400:
        default = 16187

    port_num = default
    testport = None

    while True:
        try:
            testport = Server(port_num, proto=protocol)
            break
        except BaseException:
            port_num += 1
            if port_num > 0x9999:
                port_num = 0x400

    del testport
    return port_num

def is_valid_osc_url(url: str) -> bool:
    try:
        address = Address(url)
        return True
    except BaseException:
        return False
    
def verified_address(url: str) -> Union[Address, str]:
    '''check osc Address with the given url.
    return an Address if ok, else return an error message'''

    try:
        address = Address(url)
    except BaseException:
        return f"{url} is not a valid osc url"

    try:
        send(address, '/ping')
        return address
    except BaseException:
        return f"{url} is an unknown osc url"

def verified_address_from_port(port: int) -> Union[Address, str]:
    '''check osc Address with the given port number.
    return an Address if ok, else return an error message'''

    try:
        port = int(port)
    except:
        return f"{port} port must be an int"

    try:
        address = Address(port)
    except BaseException:
        return f"{port} is not a valid osc port"

    try:
        send(address, '/ping')
        return address
    except BaseException:
        return f"{port} is an unknown osc port"

def are_on_same_machine(url1: str, url2: str) -> bool:
    if url1 == url2:
        return True

    try:
        address1 = Address(url1)
        address2 = Address(url2)
    except BaseException:
        return False

    hostname_1, hostname_2 = address1.hostname, address2.hostname
    if hostname_1 == hostname_2:
        return True

    # check if address is IPv6 (between brackets)
    addr1_ipv6, addr2_ipv6 = False, False
    if hostname_1.startswith('[') and hostname_1.endswith(']'):
        hostname_1 = hostname_1[1:-1]
        addr1_ipv6 = True
    if hostname_2.startswith('[') and hostname_2.endswith(']'):
        hostname_2 = hostname_2[1:-1]
        addr2_ipv6 = True

    if addr1_ipv6 and addr2_ipv6:
        try:
            if (socket.gethostbyaddr(hostname_1)
                    == socket.gethostbyaddr(hostname_2)):
                return True

        except BaseException as e:
            _logger.warning(
                f'Failed to find IPv6 host by addr '
                f'for "{hostname_1}" or "{hostname_2}"\n'
                f'{str(e)}')

    elif not addr1_ipv6 and not addr2_ipv6:
        try:
            addr1 = socket.gethostbyname(hostname_1)
            addr2 = socket.gethostbyname(hostname_2)
            if (addr1 in ('127.0.0.1', '127.0.1.1')
                    and addr2 in ('127.0.0.1', '127.0.1.1')):
                return True

            try:
                if socket.gethostbyaddr(addr1) == socket.gethostbyaddr(addr2):
                    return True

            except BaseException as e:
                _logger.warning(
                    f'Failed to find host by addr'
                    f'for "{addr1}" or "{addr2}"\n'
                    f'{str(e)}')

        except BaseException as e:
            _logger.warning(
                f'Failed to find host by name for '
                f'"{hostname_1}" or "{hostname_2}"\n'
                f'{str(e)}')
            
    # if (socket.gethostbyname(address1.hostname)
    #             in ('127.0.0.1', '127.0.1.1')
    #         and socket.gethostbyname(address2.hostname)
    #             in ('127.0.0.1', '127.0.1.1')):
    #     return True            
    
    elif addr1_ipv6:
        try:
            if (socket.gethostbyaddr(hostname_1)[0] == 'localhost'
                    and socket.gethostbyname(hostname_2)
                        in ('127.0.0.1', '127.0.1.1')):
                return True

        except BaseException as e:
            _logger.warning(str(e))
            
    elif addr2_ipv6:
        try:
            if (socket.gethostbyaddr(hostname_2)[0] == 'localhost'
                    and socket.gethostbyname(hostname_1)
                        in ('127.0.0.1', '127.0.1.1')):
                return True

        except BaseException as e:
            _logger.warning(str(e))

    ip = get_machine_192()

    print('are_on_same_machine', url1, url2)
    print(f"    '{ip}' '{address1.hostname}' '{address2.hostname}")

    if ip not in (hostname_1, hostname_2):
        return False

    try:
        if (ip == socket.gethostbyname(hostname_1)
                == socket.gethostbyname(hostname_2)):
            # on some systems (as fedora),
            # socket.gethostbyname returns a 192.168.. url
            return True

    except BaseException as e:
        _logger.warning(str(e))

    try:
        if (socket.gethostbyname(hostname_1)
                in ('127.0.0.1', '127.0.1.1')):
            if hostname_2 == ip:
                return True

    except BaseException as e:
        _logger.warning(str(e))

    try:
        if (socket.gethostbyname(hostname_2)
                in ('127.0.0.1', '127.0.1.1')):
            if hostname_1 == ip:
                return True
    except BaseException as e:
        _logger.warning(str(e))

    return False

def are_same_osc_port(url1: str, url2: str) -> bool:
    if url1 == url2:
        return True

    try:
        address1 = Address(url1)
        address2 = Address(url2)
    except BaseException:
        return False

    if address1.port != address2.port:
        return False

    if are_on_same_machine(url1, url2):
        return True

    return False

def get_net_url(port: Union[int, str], protocol=UDP) -> str:
    '''get the url address of a port under a form where
    it is usable by programs on another machine.
    Can be an empty string in some cases.'''

    ip = get_machine_192()
    if not ip:
        return ''

    proto_str = 'udp'
    if protocol == TCP:
        proto_str = 'tcp'
    elif protocol == UNIX:
        # in this case, impossible to call it from another machine
        return ''
    
    return f"osc.{proto_str}://{ip}:{port}/"
