import functools
import inspect
from multiprocessing.managers import Server
from typing import Callable, Optional
from pathlib import Path
import sys
import time

sys.path.insert(1, str(Path(__file__).parents[1] / 'shared'))


from osclib import BunServer, BunServerThread, Bundle, Message, Address, OscPack, make_method
import osc_paths as p

# def osclib_method(path: str, *types: str):
#     def decorated(func: Callable):
#         def wrapper(*args, **kwargs):
#             t_thread, t_path, t_args, t_types, src_addr, rest = args
#             osp = OscPack(t_path, t_args, t_types, src_addr)
#             return func(t_thread, osp, **kwargs)
#         return wrapper
#     return decorated

class _MethStock(tuple[str | None, str | None, Callable]):
    def __lt__(self, other: '_MethStock') -> bool:
        spath, stypes, sfunc = self
        opath, otypes, ofunc = other

        if spath is not opath:
            if spath is None:
                return False
            if opath is None:
                return True
            return spath < opath

        if stypes is None:
            return False
        if otypes is None:
            return True
        return stypes < otypes



# def _exec_(*args, **kwargs):
#     print('aroo', args)

# class osclib_method:
#     _all_meths = list[_MethStock]()
#     _server_instance = None
#     _instances: 'list[osclib_method]' = []
#     # _counter = 0

#     def __init__(self, path: str | None, *many_types: str | None):
#         self.path = path
#         self.many_types = many_types
#         self.func = None
#         self._serv_class = None

#         # print('init osclibmet', 'path:', self.path, 'types:', self.many_types, self)
#             # self._counter += 1
    
#     def __call__(self, func: Callable, *argsss):
#         for types in self.many_types:
#             self._all_meths.append(
#                 _MethStock((self.path, types, self._exec_)))
#             # self._all_meths.append((self.path, types, self._exec_))

#         self.func = func
#         self._instances.append(self)
#         print('calll', func, argsss, self)

#         # def wrapper(*args, **kwargs):
#         #     print('wass it', args)
#         #     t_thread, t_path, t_args, t_types, src_addr, rest = args
#         #     osp = OscPack(t_path, t_args, t_types, src_addr)
#         #     return func(t_thread, osp, **kwargs)
#         # return wrapper

#     def _exec_(self, *args, **kwargs):
#         # print('EXEC', args, kwargs)
#         path, args, types, src_addr, rest = args
#         osp = OscPack(path, args, types, src_addr)
#         print('  ', osp)
#         print('   ', self.func)
#         return self.func(self._server_instance, osp, **kwargs)
    
#     @classmethod
#     def add_methods(cls, server: 'BunServer | BunServerThread'):
#         cls._all_meths.sort()
#         cls._server_instance = server                
        
#         for path, types, _exec_ in cls._all_meths:
#             print('add mmeth', path, types, _exec_)
#             server.add_method(path, types, _exec_)


# _all_meths = list[tuple[str, str, Callable]]()

# def osclib_method(path: str, types: str):
#     def decorated(func: Callable):
#         @make_method(path, types)
#         def wrapper(*args, **kwargs):
#             t_thread, t_path, t_args, t_types, src_addr, rest = args
#             # _logger.debug(
#             #     '\033[94mOSC::daemon_receives\033[0m '
#             #     f'{t_path}, {t_types}, {t_args}, %{src_addr.url}'
#             # )

#             osp = OscPack(t_path, t_args, t_types, src_addr)
#             response = func(t_thread, osp, **kwargs)

#             # if response != False:
#             #     signaler.osc_recv.emit(osp)

#             return response
#         return wrapper
#     return decorated

# def osclib_method(path: str, *many_types: str):
#     print('allors osclib')
#     def decorated(func: Callable, *argsss):
#         print('allors decorated', func, argsss)
#         # _all_meths.append((path, types, func))
#         for types in many_types:
#             @make_method(path, types)
#             def wrapper(*args, **kwargs):
#                 print('alors executed')
#                 t_thread, t_path, t_args, t_types, src_addr, rest = args

#                 osp = OscPack(t_path, t_args, t_types, src_addr)
#                 response = func(t_thread, osp, **kwargs)

#                 # if response != False:
#                 #     signaler.osc_recv.emit(osp)

#                 return response
#         return wrapper
#     return decorated
chanchans = list[tuple[str|None, str|None, Callable]]()

class ServerA(BunServerThread):
    _instances = list['ServerA']()
    
    def __init__(self, *args):
        super().__init__(*args)
        
        self.add_method('/chichi', None, self._chichi)
        self.add_method('/chocho', 'sh', self._chocho)
        self.add_method('/chocho', 'si', self._chocho)
        # osclib_method.add_methods(self)
        # for path, types, func in _all_meths:
        #     self.add_method(path, types, func)
        # self.moukou('choucou')
        
        for chanchan in chanchans:
            self.add_method(*chanchan)
    
    def osp(path: str, *many_types: str):
        def decorated(func, *largs):
            print('doco', func, largs)
            
            def wrapper(*args_):
                print('wrappp', path, many_types, args_)
                return func(*args_)
            for types in many_types:
                chanchans.append((path, types, wrapper))
            return wrapper
        return decorated
    
    def _chichi(self, path, args, types, src_addr):
        print('chichi', path, args, types)
        # print([type(arg) for arg in args])
        
    def _chocho(self, path, args, types, src_addr):
        print('chocho', types, args)
    
    @osp('/moroso', 'ss')
    def moukou(self, *args):
        print('moukou', self, args)
    
    
    # @osclib_method('/moroso', 'si', 'ss')
    # def _moroso(self, *args):
    #     print('moroso', self, args)

    # @osclib_method('/poko', 'ss')
    # def _poko(self, *args):
    #     print('poko SS', self, args)
    
    # @osclib_method('/moroso', None)
    # def _moroso_none(self, *args):
    #     print('morosoNone', self, args)

    # @make_method(None, None)
    # def _none_methh(self, path, args, types, src_addr):
    #     print('yooull', path, args, types)
        
server_1 = BunServerThread()
server_2 = ServerA()
server_1.start()
server_2.start()

server_1.send(server_2.url, '/chichi', 'manger', True, False, ('c', 'n'), float('inf'), ('m', (45, 87, 12, 14)))
server_1.send(server_2.url, '/chocho', 'slip', 24)
server_1.send(server_2.url, '/moroso', 'slipas', 'zpoe')
server_1.send(server_2.url, '/moroso', 'slipas', 47)
server_1.send(server_2.url, '/moroso', 'chifoumi', True, ('m', (14, 87, 12, 94)))
server_1.send(server_2.url, '/poko', 'joie', 'bonheur')

print('ca va stoop')

server_1.stop()
server_2.stop()

# del server_1
# del server_2