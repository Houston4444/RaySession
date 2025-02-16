from typing import TYPE_CHECKING, TypedDict, Union, TypeVar, Generic, Callable, overload, Optional
import typing_extensions


class ArgTyper(TypedDict):
    s: tuple[str]
    ss: tuple[str, str]
    i: tuple[int]
    ii : tuple[ii]
    
    

class Osp:
    types: str
    args : tuple
    
    def __init__(self, types: str):
        self.types = types
        
    def get_args(self):
        return self.args
    
    if TYPE_CHECKING and args == 'ss':
        @overload()        
        def get_args(self) -> tuple[str, str]:
            return self.args
    
    @overload()
    def get_args(self) -> tuple[str, int]:
        return self.args

arg_typer: ArgTyper = {}
    
osp = Osp('ss')
args = arg_typer['ss']

ss = 'ss'

T = TypeVar('T')
g = Generic

def clade(arg: T) -> Optional[T]:
    if arg:
        return arg
    return None

kok = clade(75.0)