from dataclasses import dataclass
import logging
from types import NoneType
from typing import TypeAlias, Union, Callable, Optional

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
    - '*': any number of arguments of any type
    '''


class MegaSend:
    messages: list[Message]
    def __init__(self, ref: str):
        self.ref = ref
        self.tuples = list[tuple[OscArg | tuple[str, OscArg], ...]]()
        self.messages = list[Message]()
    
    def add(self, *args):
        self.tuples.append(args)
        self.messages.append(Message(*args))


@dataclass()
class OscPack:
    path: str
    args: list[OscArg]
    types: OscTypes
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