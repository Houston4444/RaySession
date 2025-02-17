
from typing import Literal, Callable
from osclib import BunServer, Address, OscPack


_CHALA = '/chala'


class Server(BunServer):
    def __init__(self):
        super().__init__()
        
        self.add_method('/chala', 'ss', self._chala)
        self._path_funcs = dict[str, Callable]()

    def _director(self, path: str, args: list, types: str,
                  src_addr: Address, user_data=None):
        
        
        
    def add_method(self, path: str, typespec: str, func: Callable, user_data=None):
        if func in self.__dir__():
            function = self.__getattribute__(func)
            self._path_funcs[path] = function
        
        return super().add_method(path, typespec, self._director, user_data)

    def _chala(self, path: str, args: list, types: Literal['ss']):
        print('aziergj', path)