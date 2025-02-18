from dataclasses import dataclass
from typing import Union, overload
import logging
import random
import socket
import subprocess
from typing import Callable

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


_RESERVED_PORT = 47

def _mega_send(server: 'Union[BunServer, BunServerThread]',
               url: Union[str, int, Address, list[str | int | Address]],
               messages: list[Message], pack=10) -> bool:
    bundler_id = random.randrange(0x100, 0x100000)
    bundle_number_self = random.randrange(0x100, 0x100000)
    
    i = 0
    stocked_msgs = list[Message]()
    pending_msgs = list[Message]()
    head_msg_self = Message('/bundle_head', bundle_number_self, 0, 0)
    head_msg = Message('/bundle_head', bundler_id, 0, 0)
    
    urls = url if isinstance(url, list) else [url]
    
    for message in messages:
        pending_msgs.append(message)

        if (i+1) % pack == 0:
            success = True
            try:
                server.send(
                    _RESERVED_PORT,
                    Bundle(*[head_msg_self]+stocked_msgs+pending_msgs))
            except:
                success = False
            
            if success:
                stocked_msgs += pending_msgs
                pending_msgs.clear()
            else:
                if stocked_msgs:
                    for url in urls:
                        server.send(url, Bundle(*[head_msg]+stocked_msgs))
                        
                        server._sem_dict.add_waiting(bundler_id)

                        j = 0
                        
                        while server._sem_dict.count(bundler_id) >= 1:
                            if isinstance(server, BunServerThread):
                                time.sleep(0.001)
                            else:
                                server.recv(1)
                            j += 1
                            if j >= 200:
                                print('too long wait for bundle recv confirmation')
                                return False
                    
                    stocked_msgs.clear()
                else:
                    print(f'error pack of {pack} is too high')
                    return False
        
        i += 1
    
    success = True

    try:
        server.send(_RESERVED_PORT,
                    Bundle(*[head_msg_self]+stocked_msgs+pending_msgs))
    except:
        success = False
        
    if success:
        server.send(url, Bundle(*[head_msg]+stocked_msgs+pending_msgs))
    else:
        server.send(url, Bundle(*[head_msg]+stocked_msgs))
        server.send(url, Bundle(*[head_msg]+pending_msgs))
    
    return True


class _SemDict(dict[int, int]):
    def __init__(self):
        super().__init__()
    
    def head_received(self, bundler_id: int):
        if not bundler_id in self:
            return
        
        if self[bundler_id] > 0:
            self[bundler_id] -= 1
            
    def add_waiting(self, bundler_id: int):
        if bundler_id not in self:
            self[bundler_id] = 0
        self[bundler_id] += 1
        
    def count(self, bundler_id: int) -> int:
        return self.get(bundler_id, 0)

        
class BunServer(Server):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        self._methods = dict[tuple[str, str], Callable]()
        
        self.add_method('/bundle_head', 'iii', self._bundle_head)
        self.add_method('/bundle_head_reply', 'iii', self._bundle_head_reply)
        
        self._sem_dict = _SemDict()
    
    def add_method(self, path: str, typespec: str, func: Callable, user_data=None):
        self._methods[(path, typespec)] = func
        return super().add_method(path, typespec, func, user_data=user_data)
    
    def _bundle_head(self, path, args, types, src_addr):
        self.send(src_addr, '/bundle_head_reply', *args)
    
    def _bundle_head_reply(self, path, args, types, src_addr):
        self._sem_dict.head_received(args[0])
    
    def mega_send(self, url: str, messages: list[Message], pack=10) -> bool:
        return _mega_send(self, url, messages, pack=pack)
 
 
class BunServerThread(ServerThread):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # self._methods = dict[tuple(str, str), Callable]()
        
        self.add_method('/bundle_head', 'iii', self._bundle_head)
        self.add_method('/bundle_head_reply', 'iii', self._bundle_head_reply)
        
        self._sem_dict = _SemDict()
    
    # def add_method(self, path: str, typespec: str, func: Callable, user_data=None):
    #     self._methods[(path, typespec)] = func
    #     return super().add_method(path, typespec, func, user_data)
    
    def _bundle_head(self, path, args, types, src_addr):
        self.send(src_addr, '/bundle_head_reply', *args)
    
    def _bundle_head_reply(self, path, args, types, src_addr):
        self._sem_dict.head_received(args[0])
    
    def mega_send(self, url: str, messages: list[Message], pack=10) -> bool:
        return _mega_send(self, url, messages, pack=pack)


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

    @property
    def strings_only(self) -> bool:
        for c in self.types:
            if c != 's':
                return False
        return True
    
    @property
    def strict_strings(self) -> bool:
        if not self.types:
            return False
        return self.strings_only
    
    def argt(self, types: str):
        return tuple(self.args)
    
    def depack(self, types: str) -> tuple[str | int | float]:
        if types == self.types:
            return tuple(self.args)
        
        ret_list = []
        
        for i in range(len(types)):
            if types[i] == self.types[i]:
                ret_list.append(self.args[i])
            elif types[i] == 'i':
                try:
                    ret_list.append(int(self.args[i]))
                except:
                    ret_list.append(0)
            elif types[i] == 'f':
                try:
                    ret_list.append(float(self.args[i]))
                except:
                    ret_list.append(0.0)
            elif types[i] == 's':
                try:
                    ret_list.append(str(self.args[i]))
                except:
                    ret_list.append('')
            else:
                ret_list.append('')
        
        return tuple(ret_list)

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

def are_on_same_machine(
        url1: Union[str, Address], url2: Union[str, Address]) -> bool:
    if isinstance(url1, Address):
        url1 = url1.url
    if isinstance(url2, Address):
        url2 = url2.url
    
    if url1 == url2:
        return True

    try:
        address1 = Address(url1)
        address2 = Address(url2)
    except BaseException:
        return False

    if address1.hostname == address2.hostname:
        return True

    def resolve_host(name: str) -> str:
        for family in (socket.AF_INET, socket.AF_INET6):
            result = None
            try:
                result = socket.getaddrinfo(name, None, family, socket.SOCK_DGRAM)
            except socket.gaierror:
                continue
            if result:
                return result[0][4][0]
        return name

    host1 = resolve_host(address1.hostname)
    host2 = resolve_host(address2.hostname)

    if host1 == host2:
        return True

    LOCAL_ADDRS = ('127.0.0.1', '127.0.1.1', '::1')

    if host1 in LOCAL_ADDRS and host2 in LOCAL_ADDRS:
        return True

    ip = get_machine_192()

    if ip not in (resolve_host(address1.hostname),
                  resolve_host(address2.hostname)):
        return False

    if ip == resolve_host(address1.hostname) == resolve_host(address2.hostname):
        # on some systems (as fedora),
        # socket.gethostbyname returns a 192.168.. url
        return True

    for host in (address1.hostname, address2.hostname):
        if resolve_host(host) in LOCAL_ADDRS and host == ip:
            return True

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
