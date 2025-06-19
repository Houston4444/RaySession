from dataclasses import dataclass
from types import NoneType
from typing import TYPE_CHECKING, TypeAlias, Union

if TYPE_CHECKING:
    from dum_imports import (
        UDP, UNIX, TCP, Message, Bundle, Address, Server, ServerThread,
        ServerError, AddressError, make_method, send)
else:
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
    - `'.'` for any arg type
    - `'*'` for any number of args of type specified by the previous
    character
    
for example:
    - `'s|si'`: will accept as arguments 1 str, or 1 str + 1 int
    - `'s*'  `: will accept any number of string arguments (even 0)
    - `'ii*' `: will accept any number of int arguments (at least 1)
    - `'s.*' `: first arg is a str, next are any number of args of any types
    - `'*'   `: any number of arguments of any type
    '''


class MegaSend:
    '''container for multiple messages to send
    with `mega_send` method of a BunServer (or BunServerThread)'''
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
        '''False if at least one arg is not a str'''
        for c in self.types:
            if c != 's':
                return False
        return True
    
    @property
    def strict_strings(self) -> bool:
        '''False if args is empty or at least one arg is not a str'''
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

_AVAILABLE_TYPES = 'ihfdcsSmtTFNIb'

def get_types_with_args(args: list) -> OscTypes:
    'for funcs with "None" types in add_method, create the types string'
    types = ''
    for arg in args:
        if (isinstance(arg, tuple) 
                and len(arg) == 2
                and arg[0] in _AVAILABLE_TYPES):
            types += arg[0]
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

def types_validator(input_types: OscTypes, multypes: OscMulTypes) -> bool:
    '''return True if `input_types` is compatible with `multypes`.
    OscTypes and OscMulTypes are `str` aliases.'''
    avl_typess = set(multypes.split('|'))
    if input_types in avl_typess:
        return True
    if '.*' in avl_typess or '*' in avl_typess:
        return True
    
    for avl_types in avl_typess:
        if not ('*' in avl_types or '.' in avl_types):
            continue

        wildcard = ''
        mt = ''

        for i in range(len(avl_types)):
            mt = avl_types[i]
            if i + 1 < len(avl_types) and avl_types[i+1] == '*':
                if mt in ('', '.'):
                    return True
                wildcard = mt
                
            else:
                wildcard = ''

            if wildcard:
                j = i
                compat = True
                while j < len(input_types):
                    if input_types[j] != wildcard:
                        compat = False
                        break
                    j += 1
                
                if compat:
                    return True
                else:
                    break
            
            if i >= len(input_types):
                break
            
            if mt == '.':
                continue
            
            if input_types[i] != mt:
                break
        else:
            # input_types is compatible with this avl_types
            return True
    
    return False