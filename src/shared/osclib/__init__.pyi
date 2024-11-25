from typing import Callable, Union, overload, Optional
from dataclasses import dataclass

UDP: int
UNIX: int
TCP: int


class Message:
    def __init__(self, path: str, *args: tuple) -> None: ...
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
def make_method(path: str, typespec: str, user_data=None): ...

# Custom ADD ons

@dataclass()
class OscPack:
    path: str
    args: list[Union[str, int, float, bytes]]
    types: str
    src_addr: Address
    
    def reply(self) -> tuple[Address, str, str]:
        ...
    
    def error(self) -> tuple[Address, str, str]:
        ...

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

def are_on_same_machine(url1: str, url2: str) -> bool:
    ...

def are_same_osc_port(url1: str, url2: str) -> bool:
    ...
    
def get_net_url(port: int) -> str:
    '''get the url address of a port under a form where
    it is usable by programs on another machine.
    Can be an empty string in some cases.'''
    ...