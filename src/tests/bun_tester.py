
from typing import Callable, Optional
from pathlib import Path
import sys

sys.path.insert(1, str(Path(__file__).parents[1] / 'shared'))


from osclib import Bundle, Message, Server, Address, OscPack


class Server(Server):
    def __init__(self, port=0):
        self._path_funcs = dict[str, Callable]()
        self._path_str_only = dict[str, int]()
        if port:
            super().__init__(port)
        else:
            super().__init__()
        
        self._uscat = 64

        self.add_methods('''
            /chala  ss
            /uscat  sf
            /zoefpf si sis sisi
            /quedustring ss*
            /quedurien .
        ''')
    
    def __generic_callback(self, osp: OscPack):
        print('__generic_callback', osp.path, osp.args, osp.types, osp.src_addr.url)
    
    def __director(self, path: str, args: list, types: str,
                   src_addr: Address, user_data=None):
        if path in self._path_funcs:
            osp = OscPack(path, args, types, src_addr)

            if path in self._path_str_only:
                if self._path_str_only[path]:
                    if not osp.strict_strings:
                        return
                else:
                    if not osp.strings_only:
                        return
                
            self._path_funcs[path](osp)

    # @overload
    def add_methods_from_dict(self, methods_dict: dict[str, str]):
        for path, typess in methods_dict.items():
            for types in typess.split('|'):
                valid_types = set[Optional[str]]()
                types_broken = False
                for type_ in types:
                    if not valid_types and type_ in ('.', 's*', 'ss*'):
                        if type_ == '.':
                            valid_types.add('')
                        else:
                            valid_types.add(None)
                            self._path_str_only[path] = 0 if type_ == 's*' else 1

                        break
                    
                    for c in type_:
                        if c not in 'ihfdcsSmtTFNIb':
                            types_broken = True
                            break
                    else:
                        valid_types.add(type_)
                    
                    if types_broken:
                        break
    
    def add_methods(self, methods: str):
        '''add methods with one string argument.
        each line contains a path and accepted types.
        Each path is connected to the method of this object
        having the same name than the path,
        replacing '/' and '-' with '_'.
        
        special types can be :
            .   : No argument
            s*  : Only strings arguments
            ss* : Only strings arguments, but at least one
        
        example:
        
        self.add_methods("""
            /my_method/path/to ss

            /my_method/path/toto .
        """)

        /my_method/path/to is connected to self._my_method_path_to
        '''
        for line in methods.splitlines():
            sline = line.strip()
            if not sline.startswith('/'):
                continue
            
            words = sline.split()
            path = words[0]
            types = words[1:]
            
            valid_types = set[Optional[str]]()
            types_broken = False
            for type_ in types:
                if not valid_types and type_ in ('.', 's*', 'ss*'):
                    if type_ == '.':
                        valid_types.add('')
                    else:
                        valid_types.add(None)
                        self._path_str_only[path] = 0 if type_ == 's*' else 1

                    break
                
                for c in type_:
                    if c not in 'ihfdcsSmtTFNIb':
                        types_broken = True
                        break
                else:
                    valid_types.add(type_)
                
                if types_broken:
                    break
            
            use_generic = True
            funcname = path.replace('/', '_').replace('-', '_')
            
            if funcname in self.__dir__():
                function = self.__getattribute__(funcname)
                if callable(function):
                    use_generic = False
                    
            if use_generic:
                self._path_funcs[path] = self.__generic_callback
            else:
                self._path_funcs[path] = function

            if not valid_types:
                self.add_method(path, None, self.__director)
                continue
            
            for type_ in valid_types:
                self.add_method(path, type_, self.__director)
        
    def _chala(self, osp: OscPack):
        print('makkko', osp.path, osp.args, osp.types, osp.src_addr.url)
        
    def _zoefpf(self, osp: OscPack):
        print('zoeof', osp.path, osp.args, osp.types, osp.src_addr.url)
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

server_1 = Server(7894)
server_2 = Server()
print('server 1 hostname', server_1.url, server_2.url)


server_2.send(server_1.port, '/chala', 'roux', 'slip')
server_2.send(server_1.port, '/zoefpf', 'soij', 14, 45)
server_2.send(server_1.port, '/zoefpf', 'soij', 14, 'joif', 24)
server_2.send(server_1.port, '/quedustring', 'soil', 'mmalz', 'ldam')
server_2.send(server_1.port, '/quedustring', 'soila', 24, 'zoak', 'aps')
server_2.send('osc.udp://127.0.1.1:7894/', '/quedurien')
bundle = Bundle()
bundle.add(Message('/chala', 'sou', 'siir'))
bundle.add(Message('/chala', 'soux', 'siirx'))
bundle.add(Message('/chala', 'soupo', 'siirpo'))
server_2.send(server_1.port, bundle)

import time

for i in range(20):
    server_1.recv(10)
    print('moga', time.time())
    # server_2.recv(10)