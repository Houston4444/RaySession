import logging
from typing import Callable, Optional

from osclib import OscArg

from .bases import OscTypes, OscMulTypes

_logger = logging.getLogger(__name__)
_AVAILABLE_TYPES = 'ihfdcsSmtTFNIb'


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
            self, path: str, typespec: OscTypes) \
                -> Optional[tuple[str | None, OscTypes | None]]:
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
        
    def add(self, path: Optional[str], typespec: Optional[OscTypes],
            func: Callable[[], None], user_data=None):
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

    def _get_types_with_args(self, args: list) -> OscTypes:
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

    def _get_func_in_list(
            self, args: list[OscArg],
            type_funcs: list[tuple[OscTypes, Callable[[], None]]]) \
                -> Optional[tuple[OscTypes, Callable[[], None]]]:
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
            self, path: str, args: list[OscArg]) \
                -> Optional[tuple[OscTypes, Callable[[], None]]]:
        type_funcs = self._dict.get(path)
        if type_funcs is not None:
            types_func = self._get_func_in_list(args, type_funcs)
            if types_func is not None:
                return types_func
        
        none_type_funcs = self._dict.get(None)
        if none_type_funcs is not None:
            return self._get_func_in_list(args, none_type_funcs)

