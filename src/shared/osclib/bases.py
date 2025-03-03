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