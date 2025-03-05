from types import NoneType
from typing import (
    Callable, TypeAlias, Union, overload, Optional, Literal, TypeAlias)
from dataclasses import dataclass

UDP: int
UNIX: int
TCP: int

OscArg: TypeAlias = Union[
    str, bytes, float, int, NoneType, bool, tuple[int, int, int, int]]
'Generic type of an OSC argument'

OscTypes: TypeAlias = str
'''Types string of an OSC message, containing one letter per argument.
Available letters are 'ihfdcsSmtTFNIb'.'''

OscMulTypes: TypeAlias = str
'''More flexible than OscTypes, used to add an OSC method. It contains
all accepted arg types separated with '|'.

It also accepts special characters:
    - '.' for any arg type
    - '*' for any number of args of type specified by the previous
    character
    
for example:
    - 's|si': will accept as arguments 1 str, or 1 str + 1 int
    - 's*': will accept any number of string arguments (even 0)
    - 'ii*': will accept any number of int arguments (at least 1)
    - 's.*': first arg is a str, next are any number of args of any types
    - '*': any number of arguments of any type'''


class Message:
    path: str
    args: list[int | float | str | bytes]
    types: str
    
    def __init__(self, path: str, *args: tuple) -> None: ...
    def deserialise(self, buf) -> 'Message': ...
    def serialise(self): ...
    def add(self, *args: tuple): ...


class Bundle:
    @overload
    def __init__(self, timetag: float, *messages: tuple[Message]) -> None: ...
    @overload
    def __init__(self, *messages: tuple[Message]): ...

    @overload
    def add(self, path: str, *messages: tuple[Message]): ...
    @overload
    def add(self, *args: tuple): ...


class Address:
    url: str
    hostname: str
    port: Union[int, str]
    protocol: int
    
    @overload
    def __init__(self, hostname: str, port: Union[int, str], proto: int =UDP): ...
    @overload
    def __init__(self, port: Union[int, str]): ...
    @overload
    def __init__(self, url: str): ...


class __AbstractServer:
    url: str
    port: Union[int, str]
    protocol: int
    
    def __init__(self, port: Union[int, str] =1, proto: int =UDP, reg_methods=True): ...
    def recv(self, timeout: Optional[int] =None) -> bool: ...
    def add_method(self, path: str, typespec: str, func: Callable, user_data=None): ...
    def del_method(self, path: str, typespec: str): ...
    def register_methods(self, obj=None): ...
    def add_bundle_handlers(
        self, start_handler: Callable, end_handler: Callable, user_data=None): ...
    
    @overload
    def send(self, address: Address, path: str, *args: tuple): ...
    @overload
    def send(self, address: Address, *messages: tuple[Message]): ...

    def fileno(self) -> int: ...
    def free(self): ...


class Server(__AbstractServer):
    def recv(self, timeout: Optional[int] =None) -> bool: ...


class ServerThread(__AbstractServer):
    def start(self): ...
    def stop(self): ...


class MegaSend():
    '''container for multiple messages to send
    with `mega_send` method of a BunServer (or BunServerThread)'''
    messages: list[Message]
    ref: str
    def __init__(self, ref: str): ...
    def add(self, *args): ...


class BunServer(Server):
    '''Class inheriting liblo.Server. Provides a server
    with the mega_send feature, which allows to send massive
    bundle of messages, in several sends if needed.'''
    def mega_send(
            self,
            url: Union[str, int, Address, list[Union[str, int, Address]]],
            mega_send: MegaSend) -> bool:
        '''send a undeterminated number of messages to another BunServer
        (or BunServerThread).
        
        !!! the recepter MUST be a Bunserver or a BunServerThread !!!'''
        ...
        
    def add_nice_method(
            self, path: str, multypes: OscMulTypes,
            func: Callable[[OscPack], None]):
        '''Nice way to add an OSC method to the server,
        
        The function `func` MUST accept only one OscPack argument.
        '''
        ...

    def add_nice_methods(
            self, methods_dict: dict[str, str],
            func: Callable[[OscPack], None]):
        '''Nice way to add several OSC methods to the server,
        all routed to the same function.
        
        The function `func` MUST accept only one OscPack argument.
        
        `methods_dict` MUST be a dict where keys are osc paths
        and value an OscMulTypes (str).        
        '''
        ...
    
    def set_fallback_nice_method(self, func: Callable[[OscPack], None]):
        '''set the fallback function for all messages non matching with
        any defined method.'''
        ...

class BunServerThread(BunServer):
    '''Class inheriting liblo.Server. Provides a server thread
    with the mega_send feature, which allows to send massive
    bundle of messages, in several sends if needed.'''
    def start(): ...
    def stop(): ...


class ServerError(BaseException): ...


class AddressError(BaseException): ...


@overload
def send(target: Union[Address, int, tuple[str, int], str],
         path: str,
         *args: tuple): ...
@overload
def send(target: Union[Address, int, tuple[str, int], str],
         *messages: tuple[Message]): ...

def time() -> float: ...
def make_method(path: str, typespec: OscTypes, user_data=None): ...

# Custom ADD ons

@dataclass()
class OscPack:
    path: str
    args: list[OscArg]
    types: OscTypes
    src_addr: Address
    
    def reply(self) -> tuple[Address, str, str]:
        ...
    
    def error(self) -> tuple[Address, str, str]:
        ...
    
    @property
    def strings_only(self) -> bool:
        '''False if at least one arg is not a str'''
        ...

    @property
    def strict_strings(self) -> bool:
        '''False if args is empty or at least one arg is not a str'''

    @overload
    def argt(self, types: Literal['ss']) -> tuple[str, str]: ...
    @overload
    def argt(self, types: Literal['si']) -> tuple[str, int]: ...
    @overload
    def argt(self, types: Literal['ii']) -> tuple[int, int]: ...
    def argt(self, types: str) -> tuple:
        return tuple(self.args)
    
def is_osc_port_free(port: int) -> bool:
    ...

def get_free_osc_port(default=16187, protocol=UDP) -> int:
    '''get a free OSC port for daemon, start from default'''
    ...
    
def is_valid_osc_url(url: str) -> bool:
    ...
    
def verified_address(url: str) -> Union[Address, str]:
    '''check osc Address with the given url.
    return an Address if ok, else return an error message'''
    ...

def verified_address_from_port(port: int) -> Union[Address, str]:
    '''check osc Address with the given port number.
    return an Address if ok, else return an error message'''

def get_machine_192() -> str:
    '''return the string address of this machine, starting with 192.168.
    Value is saved, so, calling this function is longer the first time
    than the next ones.'''
    ...

def are_on_same_machine(url1: str | Address, url2: str | Address) -> bool:
    ...

def are_same_osc_port(url1: str, url2: str) -> bool:
    ...
    
def get_net_url(port: int, protocol=UDP) -> str:
    '''get the url address of a port under a form where
    it is usable by programs on another machine.
    Can be an empty string in some cases.'''
    ...