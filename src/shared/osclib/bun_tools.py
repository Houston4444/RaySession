from inspect import signature, _ParameterKind
import logging
from typing import Callable, Optional


from .bases import OscArg, OscTypes, get_types_with_args


_logger = logging.getLogger(__name__)


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


class MegaSendChecker(dict[tuple[int, int], int]):
    _NO_RECV = 0
    _HEAD_RECV = 1
    _QUEUE_RECV = 2
    
    def __init__(self):
        super().__init__()

    def head_recv(self, mega_send_id: int, pack_num: int):
        bundler_id = (mega_send_id, pack_num)
        if not bundler_id in self:
            return
        
        self[bundler_id] = self._HEAD_RECV

    def tail_recv(self, mega_send_id: int, pack_num: int):
        bundler_id = (mega_send_id, pack_num)
        if not bundler_id in self:
            return
        
        self[bundler_id] = self._QUEUE_RECV
            
    def add_waiting(self, mega_send_id: int, pack_num: int):
        bundler_id = (mega_send_id, pack_num)
        self[bundler_id] = self._NO_RECV

    def head_received(self, mega_send_id: int, pack_num: int) -> bool:
        bundler_id = (mega_send_id, pack_num)
        if bundler_id not in self:
            return True
        
        return self[bundler_id] != self._NO_RECV
        
    def previous_tail_received(
            self, mega_send_id: int, pack_num: int) -> bool:
        if pack_num == 0:
            return True
        bundler_id = (mega_send_id, pack_num - 1)
        if bundler_id not in self:
            return True
        return self[bundler_id] == self._QUEUE_RECV


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

    def _get_func_in_list(
            self, args: list[OscArg],
            type_funcs: list[tuple[OscTypes, Callable[[], None]]]) \
                -> Optional[tuple[OscTypes, Callable[[], None]]]:
        for types, func in type_funcs:
            if types is None:
                return get_types_with_args(args), func
            
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

