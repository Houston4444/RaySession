from dataclasses import dataclass
from threading import Thread
from types import NoneType
from typing import Iterable, Optional, TypeAlias, Union, Any
import logging
import random
import socket
import subprocess
from typing import Callable
import time
import json
import tempfile
import os
from inspect import signature, _ParameterKind

_logger = logging.getLogger(__name__)
    
# Do not remove any imports here !!!
try:
    from liblo import (
        UDP, UNIX, TCP, Message, Bundle, Address, Server, ServerThread,
        ServerError, AddressError, make_method, send)
except ImportError:
    try:
        from pyliblo3 import (
            UDP, UNIX, TCP, Message, Bundle, Address, Server, ServerThread,
            ServerError, AddressError, make_method, send)
    except BaseException as e:
        _logger.error(
            'Failed to find a liblo lib for OSC (liblo or pyliblo3)')
        _logger.error(str(e))


_RESERVED_PORT = 47


OscArg: TypeAlias = Union[
    str, bytes, float, int, NoneType, bool, tuple[int, int, int, int]]


class MegaSend:
    messages: list[Message]
    def __init__(self, ref: str):
        self.ref = ref
        self.tuples = list[tuple[int | str | float]]()
        self.messages = list[Message]()
    
    def add(self, *args):
        self.tuples.append(args)
        self.messages.append(Message(*args))


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


class MethodsAdder:
    def __init__(self):
        self._dict = dict[str | None, list[tuple[str | None, Callable]]]()
        
    def _already_associated_by(
            self, path: str, typespec: str) \
                -> Optional[tuple[str | None, str | None]]:
        '''check if add_method path types association will be effective or
        already managed by a previous add_method.
        
        return None if Ok, otherwise return tuple[path, types]'''
        none_type_funcs = self._dict.get(None)
        if none_type_funcs is not None:
            for types, func_ in none_type_funcs:
                if types is None:
                    return (None, None)
                if types == typespec:
                    return (None, types)

        type_funcs = self._dict.get(path)
        if type_funcs is None:
            return None
        
        for types, func_ in type_funcs:
            if types is None:
                return (path, None)
            if types == typespec:
                return (path, types)
        
        return None
        
    def add(self, path: str, typespec: str, func: Callable[[], None],
            user_data=None):
        already_ass = self._already_associated_by(path, typespec)
        if already_ass is not None:
            ass_path, ass_types = already_ass
            _logger.warning(
                f"Add method {path} '{typespec}' {func.__name__} "
                f"Will not be effective, association is already defined"
                f" by {ass_path} '{ass_types}'.")
            return
        
        type_funcs = self._dict.get(path)
        if type_funcs is None:
            self._dict[path] = [(typespec, func)]
        else:
            type_funcs.append((typespec, func))

    def _get_types_with_args(self, args: list) -> str:
        'for funcs with "None" types in add_method, create the types string'
        types = ''
        for arg in args:
            if isinstance(arg, tuple):
                types += args[0]
            elif isinstance(arg, str):
                types += 's'
            elif isinstance(arg, float):
                types += 'f'
            elif arg is True:
                types += 'T'
            elif arg is False:
                types += 'F'
            elif isinstance(arg, int):
                if - 0x80000000 <= arg < 0x80000000:
                    types += 'i'
                else:
                    types += 'h'
            elif arg is None:
                types += 'N'
            else:
                types += 'b'
        
        return types

    def _get_func_in_list(
            self, args: list[int | float | str | bytes],
            type_funcs: list[tuple[str, Callable[[], None]]]) \
                -> Optional[tuple[str, Callable[[], None]]]:
        for types, func in type_funcs:
            if types is None:
                return self._get_types_with_args(args), func
            
            if len(types) != len(args):
                continue
            
            for i in range(len(types)):
                c = types[i]
                a = args[i]
                if isinstance(a, tuple) and len(a) == 2:
                    if a[0] != c:
                        break
                
                match c:
                    case 'c':
                        if not (isinstance(a, str) and len(a) == 1):
                            break
                    case 's'|'S':
                        if not isinstance(a, str):
                            break
                    case 'f'|'d'|'t'|'I':
                        if not isinstance(a, float):
                            break
                    case 'i'|'h':
                        if not isinstance(a, int):
                            break
                    case 'b':
                        if not isinstance(a, bytes):
                            break
                    case 'N':
                        if a is not None:
                            break
                    case 'T':
                        if a is not True:
                            break
                    case 'F':
                        if a is not False:
                            break
                    case 'm':
                        if not (isinstance(a, tuple)
                                and len(a) == 4):
                            break
            else:
                return types, func

    def get_func(
            self, path: str, args: list[int | float | str | bytes]) \
                -> Optional[tuple[str, Callable[[], None]]]:
        type_funcs = self._dict.get(path)
        if type_funcs is not None:
            types_func = self._get_func_in_list(args, type_funcs)
            if types_func is not None:
                return types_func
        
        none_type_funcs = self._dict.get(None)
        if none_type_funcs is not None:
            return self._get_func_in_list(args, none_type_funcs)
                            
        
class BunServer(Server):
    def __init__(self, *args, **kwargs):
        # self._methods = dict[str | None, list[tuple[str | None, Callable]]]()
        self._methods_adder = MethodsAdder()
        super().__init__(*args, **kwargs)

        self.add_method('/_bundle_head', 'iii', self.__bundle_head)
        self.add_method('/_bundle_head_reply', 'iii', self.__bundle_head_reply)
        self.add_method('/_local_mega_send', 's', self.__local_mega_send)
        
        self._sem_dict = _SemDict()
    
    def add_method(
            self, path: str, typespec: str, func: Callable[[], None],
            user_data=None):
        self._methods_adder.add(path, typespec, func, user_data)
        return super().add_method(path, typespec, func, user_data=user_data)
    
    def __bundle_head(
            self, path: str, args: list[int], types: str, src_addr: Address):
        self.send(src_addr, '/_bundle_head_reply', *args)
    
    def __bundle_head_reply(
            self, path: str, args: list[int], types: str, src_addr: Address):
        self._sem_dict.head_received(args[0])
    
    def __local_mega_send(
            self, path: str, args: list[str], types: str, src_addr: Address):
        def number_of_args(func: Callable) -> int:
            sig = signature(func)
            num = 0
            for param in sig.parameters.values():
                match param.kind:
                    case _ParameterKind.VAR_POSITIONAL:
                        return 5
                    case (_ParameterKind.POSITIONAL_ONLY
                          | _ParameterKind.POSITIONAL_OR_KEYWORD):
                        num += 1
            return num

        ms_path = args[0]
        try:
            with open(ms_path, 'r') as f:
                events: list[tuple[str, float, int]] = json.load(f)
        except BaseException as e:
            _logger.error(
                f'__local_mega_send: failed to open file "{ms_path}"')
            return
        
        if not isinstance(events, list):
            _logger.error(
                f'__local_mega_send: wrong data in "{ms_path}"')
            return
        
        try:
            os.path.remove(ms_path)
        except:
            _logger.info(
                f'__local_mega_send: Failed to remove tmp file {ms_path}')
        
        for event in events:
            if not (isinstance(event, list) and len(event) > 0):
                _logger.error(
                    f'__local_mega_send: wrong data in "{ms_path}"')
                return
            
            path, args_ = event[0], event[1:]
            
            types_func = self._methods_adder.get_func(path, args_)
            if types_func is None:
                continue
            
            types, func = types_func
            
            # transform args_ to nargs,
            # especially if tuples are used to send arguments
            # for example: ('d', 0.455751122211)
            # here received in json, there are no tuples, only lists
            # all other arg types seems to be kept.
            nargs = []
            for arg in args_:
                if isinstance(arg, list) and len(arg) == 2:
                    if arg[0] == 'm' and isinstance(arg[1], list):
                        nargs.append(tuple(arg[1]))
                    else:
                        nargs.append(arg[1])
                else:
                    nargs.append(arg)
            
            # execute function
            match number_of_args(func):
                case 1: func(path)
                case 2: func(path, nargs)
                case 3: func(path, nargs, types)
                case 4: func(path, nargs, types, src_addr)
                case 5: func(path, nargs, types, src_addr, None)
    
    def mega_send(self: 'Union[BunServer, BunServerThread]',
               url: Union[str, int, Address, list[str | int | Address]],
               mega_send: MegaSend, pack=10) -> bool:
        bundler_id = random.randrange(0x100, 0x100000)
        bundle_number_self = random.randrange(0x100, 0x100000)
        
        i = 0
        stocked_msgs = list[Message]()
        pending_msgs = list[Message]()
        head_msg_self = Message('/_bundle_head', bundle_number_self, 0, 0)
        head_msg = Message('/_bundle_head', bundler_id, 0, 0)
        
        urls = url if isinstance(url, list) else [url]
        if not urls:
            return True

        messages = mega_send.messages

        # first, try to send all in one bundle
        all_ok = True   
        urls_done = set[str, int, Address]()
        for url in urls:
            try:
                self.send(url, Bundle(*[head_msg]+messages))
                assert self.wait_mega_send_answer(bundler_id, mega_send.ref)
                urls_done.add(url)
            except:
                all_ok = False
                break
        
        if all_ok:
            return True
        
        for url in urls_done:
            urls.remove(url)
        urls_done.clear()
        
        for url in urls:
            is_local = False
            if isinstance(url, Address):
                is_local = are_on_same_machine(self.url, url.url)
            elif isinstance(url, str):
                is_local = are_on_same_machine(self.url, url)
            elif isinstance(url, int):
                is_local = True
            
            if is_local:
                tmp_file = tempfile.NamedTemporaryFile(mode='w+t', delete=False)
                tmp_file.write(json.dumps(mega_send.tuples))
                tmp_file.seek(0)
                self.send(url, '/_local_mega_send', tmp_file.name)
                urls_done.add(url)
                
        for url in urls_done:
            urls.remove(url)
        
        for message in messages:
            pending_msgs.append(message)

            if (i+1) % pack == 0:
                success = True
                try:
                    self.send(
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
                            self.send(url, Bundle(*[head_msg]+stocked_msgs))
                            self.wait_mega_send_answer(
                                bundler_id, mega_send.ref)
                        
                        stocked_msgs.clear()
                    else:
                        _logger.error(
                            f'pack of {pack} is too high '
                            f'for mega_send {mega_send.ref}')
                        return False
            
            i += 1
        
        success = True

        try:
            self.send(_RESERVED_PORT,
                        Bundle(*[head_msg_self]+stocked_msgs+pending_msgs))
        except:
            success = False
            
        if success:
            for url in urls:
                self.send(url, Bundle(*[head_msg]+stocked_msgs+pending_msgs))
                self.wait_mega_send_answer(bundler_id, mega_send.ref)
        else:
            for url in urls:
                self.send(url, Bundle(*[head_msg]+stocked_msgs))
                self.wait_mega_send_answer(bundler_id, mega_send.ref)
                self.send(url, Bundle(*[head_msg]+pending_msgs))
                self.wait_mega_send_answer(bundler_id)
        
        return True
    
    def wait_mega_send_answer(self, bundler_id: int, ref: str) -> bool:
        self._sem_dict.add_waiting(bundler_id)

        start = time.time()
        
        while self._sem_dict.count(bundler_id) >= 1:
            self.recv(1)
            if time.time() - start >= 0.200:
                _logger.error(
                    f'too long wait for bundle '
                    f'recv confirmation {bundler_id}. {ref}')
                return False 
        return True
 
 
class BunServerThread(BunServer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        self._terminated = False
        self._thread: Optional[Thread] = None
    
    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        
        if self._thread is None:
            self._thread = Thread(target=self._main_loop)
        self._thread.start()
        
    def stop(self):
        if self._thread is None:
            return
        self._terminated = True
        self._thread.join()
        self._thread = None
    
    def _main_loop(self):
        while not self._terminated:
            self.recv(10)

    def wait_mega_send_answer(self, bundler_id: int, ref: str) -> bool:
        self._sem_dict.add_waiting(bundler_id)

        i = 0
        
        while self._sem_dict.count(bundler_id) >= 1:
            time.sleep(0.001)
            i += 1
            if i >= 200:
                _logger.warning(
                    f'too long wait for bundle '
                    f'recv confirmation {bundler_id}. {ref}')
                return False 
        return True


@dataclass()
class OscPack:
    path: str
    args: list[OscArg]
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
