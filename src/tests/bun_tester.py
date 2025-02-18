
from typing import Literal, Callable, overload
from pathlib import Path
import sys

sys.path.insert(1, str(Path(__file__).parents[1] / 'shared'))


from osclib import BunServer, Address, OscPack


_CHALA = '/chala'


class Server(BunServer):
    def __init__(self):
        self._path_funcs = dict[str, Callable]()
        super().__init__()
        
        self._uscat = 64
        
        self.add_methods('''
            /chala  ss
            /uscat  sf
            /zoefpf si sis sisi
        ''')
    
    def __director(self, path: str, args: list, types: str,
                   src_addr: Address, user_data=None):
        if path in self._path_funcs:
            self._path_funcs[path](OscPack(path, args, types, src_addr))
    
    # @overload
    def add_methods(self, methods: str):
        '''add methods with one string argument.
        each line contains a path and accepted types.
        Each path is connected to the method of this object
        having the same name than the path,
        replacing '/' and '-' with '_'.
        
        example:
        
            /my_method/path/to ss
            
        Here path is connected to self._my_method_path_to
        '''
        for line in methods.splitlines():
            sline = line.strip()
            if not sline.startswith('/'):
                continue
            
            words = line.split()
            path = words[0]
            types = words[1:]
            
            funcname = path.replace('/', '_').replace('-', '_')
            if not funcname in self.__dir__():
                print(f'no func named {funcname} for {path}')
                continue
            
            valid_types = set[str]()
            for type_ in types:
                if type_ in ('.', 's*', 'ss*'):
                    valid_types.add(type_)
                    continue
                
                for c in type_:
                    if c not in 'ihfdcsSmtTFNIb':
                        break
                else:
                    valid_types.add(type_)
            
            function = self.__getattribute__(funcname)
            if not callable(function):
                print(f'self.{funcname} is not callable, {function}')
                continue
            self._path_funcs[path] = function

            if not valid_types:
                self.add_method(path, None, self.__director)
                continue
            
            for type_ in valid_types:
                self.add_method(path, type_, self.__director)
        
    def _chala(self, osp: OscPack):
        print('makkko', osp.path, osp.args, osp.types)
        
    def _zoefpf(self, osp: OscPack):
        print('zoeof', osp.path, osp.args, osp.types)
        string: str
        intit: int
        strug: str
        inito: int

        match osp.types:
            case 'si':
                string, intit = osp.args
            case 'sis':
                string, intit, strug = osp.args
            case 'sisi':
                string, intit, strug, inito = osp.args
        
        print('eporfff', string, intit)

server_1 = Server()
server_2 = Server()

server_2.send(server_1.port, '/chala', 'roux', 'slip')
server_2.send(server_1.port, '/zoefpf', 'soij', 14, 45)
server_2.send(server_1.port, '/zoefpf', 'soij', 14, 'joif', 24)

while True:
    server_1.recv(10)
    # server_2.recv(10)