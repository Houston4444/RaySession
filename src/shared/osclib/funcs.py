import socket
import subprocess
from typing import Union

from .bases import Server, UDP, TCP, UNIX, Address, send

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
        url1: str | Address, url2: str | Address) -> bool:
    if isinstance(url1, Address):
        address1 = url1
        url1 = address1.url
    else:
        try:
            address1 = Address(url1)
        except BaseException:
            return False

    if isinstance(url2, Address):
        address2 = url2
        url2 = address2.url
    else:
        try:
            address2 = Address(url2)
        except BaseException:
            return False

    if url1 == url2:
        return True

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

def are_same_osc_port(url1: str | Address, url2: str | Address) -> bool:
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