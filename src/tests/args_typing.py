from types import NoneType
from typing import TYPE_CHECKING, TypeAlias, overload, reveal_type, Any, Literal, Callable
from typing_extensions import TypeIs
from dataclasses import dataclass

RUNTIME_TYPE_CHECKING = True


Tup: TypeAlias = tuple[int | float | str, ...]




# def is_type(obj: Any, types: str, fmt: Literal['']) -> TypeIs[NoneType]: ...
@overload
def is_type(obj: Any, types: str, fmt: Literal['i']) -> TypeIs[int]: ...
@overload
def is_type(obj: Any, types: str, fmt: Literal['f']) -> TypeIs[float]: ...
@overload
def is_type(obj: Any, types: str, fmt: Literal['s']) -> TypeIs[str]: ...
@overload
def is_type(
    obj: Any, types: str, fmt: Literal['ifs']) -> TypeIs[tuple[int, float, str]]: ...
@overload
def is_type(obj: Any, types: str, fmt: Literal['ffi']) -> TypeIs[tuple[float, float, int]]: ...
def is_type[T](obj: Any, types: str, fmt: str) -> TypeIs[T]:
    ...
    # if not RUNTIME_TYPE_CHECKING:
    #     return types == fmt

    match fmt:
        case 'i':
            return isinstance(obj, int)
        case 'f':
            return isinstance(obj, float)
        case 's':
            return isinstance(obj, str)
        case _:
            if isinstance(obj, tuple) and len(fmt) == len(obj):
                for item, char_types, char_fmt in zip(obj, types, fmt):
                    # char_fmt is not a literal, so type checkers will not like
                    # this following check. However, it will work as expected
                    # when strictly checking types. So just tell type checker
                    # to ignore this line.
                    if not is_type(item, char_types, char_fmt): # type: ignore
                        return False
                return True
            else:
                return False

def get_data() -> tuple[tuple[int | float | str, ...], str]:
    return (1, 2.5, 'string'), 'ifs'

def main() -> None:
    obj, types = get_data()
    print('ezorpg', obj, types)
    reveal_type(obj) # Revealed type is "tuple[Union[int, float, str], ...]"

    # this guard will narrow the type according to the type format
    if is_type(obj, types, 'ifs'):
        x, y, z = obj
        reveal_type(obj) # Revealed type is "tuple[int, float, str]"
        reveal_type(x)   # Revealed type is "int"
        reveal_type(y)   # Revealed type is "float"
        reveal_type(z)   # Revealed type is "str"
        print('zorila', obj)
    elif is_type(obj, types, 'ffi'):
        x, y, z = obj
    
    # after guard, the type widens to its previous value
    reveal_type(obj) # Revealed type is "tuple[Union[int, float, str], ...]"
    
main()
print('youpila')

@overload
def tuptyp(types: Literal['iis']):
    return tuple[int, int, str]
@overload
def tuptyp(types: Literal['ifs']):
    return tuple[int, float, str]
def tuptyp(types: str):
    return tuple

class Osp:
    # args: tuple[int | float | str, ...]
    types: str
    
    @overload
    def __init__(self, args, types: Literal['ifs']):
        # assert(is_type(args, types, types))
        self.args = args
        self.argt = tuple[int, float, str]()
        # args: tuple[int, float, str]

    @overload
    def __init__(self, args, types: Literal['ffi']):
        self.args = args
        self.argt = tuple[float, float, int]()
        # assert(is_type(args, types, types))
        # args: tuple[float, float, int]

    def __init__(self, args, types: str):
        self.args: Tup = args
        self.types = types
        self.argt = Tup()
    
    @overload
    def chou(self, patate: str):
        '''chou patate str'''
        ...
    
    @overload  
    def chou(self, patate: int):
        '''chou patate integrale'''
        ...
        
    def chou(self, patate):
        '''chou patate inconnue'''
        ...
        
    
        # if types == 'ifs':
        #     assert is_type(self.args, types, 'ifs')
        # elif types == 'ffi':
        #     assert is_type(self.args, types, 'ffi')
    
        
    
Ty_ifs: TypeAlias = Literal['ifs']
Tpl_iis: TypeAlias = tuple[int, int, str]
            
def main_deux(tata: Ty_ifs):
    osp = Osp((7, 4.5, 'slofi'), 'ifs')
    osp.chou(48)
    reveal_type(osp.args)
    
    args = osp.args
    types = osp.types
    argt = osp.argt
    
    # args, types = get_data()
    # args: tuptyp(tata)
    
    if TYPE_CHECKING:
        assert is_type(osp.args, types, tata)
    num, fla, stra = osp.args
    

# def typargs(func: Callable):
#     def wrapper(path: str, args: tuple[int | float |str, ...], types):
#         is_type(args, types, types)
#         return func(path, args, types)
   


# @typargs
# def plapla(path: str, args: tuple[int | float | str, ...], types: Ty_ifs):
#     if is_type(args, types, types):
#         i, f, s = args