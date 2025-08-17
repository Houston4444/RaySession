from dataclasses import dataclass
import inspect
import json
import logging
from operator import is_
import os
from queue import Queue, Empty
import random
import tempfile
import time
from threading import Thread, current_thread
from typing import Callable, Type, Union, Optional

from osclib import OscTypes

from .bases import (
    OscArg, OscMulTypes, OscPack, OscPath, Server, Address, Message, Bundle,
    MegaSend, get_types_with_args, types_validator, UDP)
from .funcs import are_on_same_machine
from .bun_tools import number_of_args, MethodsAdder, MegaSendChecker

_logger = logging.getLogger(__name__)

_MANAGE_ATTR = '_manage_wrapper_num'

_RESERVED_PORT = 47
'''Port reserved in OSC, used to try to send message to,
this way, no risk that any OSC port can receive it.'''

IS_NOT_LAST = 0
IS_LAST = 1

_process_port_queues = dict[int, Queue[OscPack]]()
'Contains the port numbers of all BunServer instantiated in this process'

_last_fake_num = 0x1000000


@dataclass()
class ManageWrapper:
    path: OscPath
    multypes: OscMulTypes
    wrapper: Callable[[OscPack], None]


_manage_wrappers = list[ManageWrapper]()


def bun_manage(path: OscPath, multypes: OscMulTypes):
    '''Decorator working like the @make_method decorator,
    but send methods with OscPack as argument.
    
    `path`: OSC str path

    `multypes`: str containing all accepted arg types
    '''
    def decorated(func: Callable):
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
    
        manage_wrapper = ManageWrapper(path, multypes, wrapper)
        setattr(wrapper, _MANAGE_ATTR, len(_manage_wrappers))
        _manage_wrappers.append(manage_wrapper)

        return wrapper
    return decorated


class BunServer:
    '''Class inheriting liblo.Server. Provides a server
    with more features.
    
    - mega_send: send massive bundle of messages (in several sends
    if needed)
    
    - direct communication: no OSC messages if the two instances are on the same
    process
    
    - total_fake: No OSC port is created if argument total_fake=True,
    possible if the goal of this server is to communicate only with servers
    on the same process''' 
    def __init__(self, port: Union[int, str] =1, proto=UDP,
                 reg_methods=True, total_fake=False):
        self._methods_adder = MethodsAdder()
        self._director_methods = dict[
            str, tuple[OscMulTypes, Callable[[OscPack], None]]]()
        self._mw_path_wrap = dict[OscPath, ManageWrapper]()
        '''will contain all ManageWrapper objects to be used by methods
        decorated with @bun_manage'''

        self._dummy_port = 0

        if not total_fake:
            if port == 1:
                self.sv = Server()
            else:
                self.sv = Server(port=port, proto=proto,
                                 reg_methods=reg_methods)

            self.add_method('/_bundle_head', 'hii',
                            self.__bundle_head) # type:ignore
            self.add_method('/_bundle_head_reply', 'hii',
                            self.__bundle_head_reply) # type:ignore
            self.add_method('/_bundle_tail', 'hii',
                            self.__bundle_tail) # type:ignore
            self.add_method('/_bundle_tail_reply', 'hii',
                            self.__bundle_tail_reply) # type:ignore
            self.add_method('/_local_mega_send', 'hs',
                            self.__local_mega_send) # type:ignore
        else:
            global _last_fake_num
            self.sv = None
            _last_fake_num += 1
            self._dummy_port = _last_fake_num
        
        self._ms_checker = MegaSendChecker()
        self._mega_send_recv = dict[int, int]()
        _process_port_queues[self.port] = Queue()
    
    @property
    def url(self) -> str:
        if self.sv is None:
            return f'osc.udp://localhost:{self.port}/'
        return self.sv.url
    
    @property
    def port(self) -> int:
        if self.sv is None:
            return self._dummy_port
        
        if not isinstance(self.sv.port, int):
            raise Exception 

        return self.sv.port
    
    @property
    def protocol(self) -> int:
        if self.sv is None:
            return UDP
        return self.sv.protocol
    
    def _exec_func(self, func: Callable, osp: OscPack):
        'Used when OSC communication is fake, to execute the desired func'
        match number_of_args(func):
            case 1: func(osp.path)
            case 2: func(osp.path, osp.args)
            case 3: func(osp.path, osp.args, osp.types)
            case 4: func(osp.path, osp.args, osp.types, osp.src_addr)
            case 5: func(osp.path, osp.args, osp.types, osp.src_addr, None)
    
    def add_managed_methods(self):
        for name, method in inspect.getmembers(self):
            if not inspect.ismethod(method):
                continue
            
            func = method.__func__
            
            if not hasattr(func, _MANAGE_ATTR):
                continue
            
            meth_num = getattr(func, _MANAGE_ATTR, None)
            if not isinstance(meth_num, int):
                continue

            mw = _manage_wrappers[meth_num]
            self._mw_path_wrap[mw.path] = mw

        for mw in self._mw_path_wrap.values():
            self.add_nice_method(mw.path, mw.multypes, self.__generic_method)
    
    def __generic_method(self, osp: OscPack):
        '''Except the unknown messages, all messages received
         for functions decorated with @bun_manage go through here.'''
        if osp.path in self._mw_path_wrap:
            self._mw_path_wrap[osp.path].wrapper(self, osp) # type:ignore
    
    def recv(self, timeout: Optional[int] = None) -> bool:
        if self.sv is None and timeout:
            has_osp = False
            while True:
                try:
                    osp = _process_port_queues[self.port].get(
                        timeout=timeout*0.001)
                    has_osp = True
                except Empty:
                    break
                except BaseException as e:
                    _logger.error(f'Unknown problem in fake recv {str(e)}')
                    return False

                types_func = self._methods_adder.get_func(osp.path, osp.args)
                if types_func is None:
                    continue
                
                types, func = types_func
                osp.types = types
                self._exec_func(func, osp)
            
            return has_osp
        
        while _process_port_queues[self.port].qsize():
            osp = _process_port_queues[self.port].get()
            types_func = self._methods_adder.get_func(osp.path, osp.args)
            if types_func is None:
                continue
            
            types, func = types_func
            osp.types = types
            self._exec_func(func, osp)
        
        if self.sv is None:
            return False
        
        return self.sv.recv(timeout)
    
    def send(self, *args, **kwargs):
        if len(args) < 2:
            raise TypeError

        dest = args[0]
        dest_port = 0

        if isinstance(dest, Address):
            if (dest.port in _process_port_queues
                    and are_on_same_machine(self.url, dest)
                    and dest.protocol == UDP):
                dest_port: int = dest.port # type:ignore
        elif isinstance(dest, int):
            if dest in _process_port_queues:
                dest_port = dest
        
        if isinstance(args[1], (Message, Bundle)):
            if self.sv is None:
                raise TypeError(
                    'Impossible to send Bundle or Message from a fake server')            

            if dest_port >= 0x1000000:
                raise TypeError(
                    'Impossible to send Bundle or Message '
                    'to a fake server')
        
        elif dest_port:
            # communication between two BunServer in the same process
            # avoid OSC communication, directly enqueue the message
            # the receiver will take it at recv.
            dest, path, *other_args = args
            _process_port_queues[dest_port].put(
                OscPack(path, other_args, get_types_with_args(other_args),
                        Address(self.port)))
            return

        if self.sv is None:
            return

        self.sv.send(*args, **kwargs)
    
    def add_method(
            self, path: Optional[str], typespec: Optional[OscTypes],
            func: Callable[[], None], user_data=None):
        self._methods_adder.add(path, typespec, func, user_data)
        if self.sv is None:
            return
        self.sv.add_method(path, typespec, func, user_data=user_data)
    
    def __bundle_head(
            self, path: str, args: list[int],
            types: OscTypes, src_addr: Address):
        mega_send_id, pack_num, is_last = args
        self.send(src_addr, '/_bundle_head_reply', *args)
        if is_last:
            if self._mega_send_recv.get(mega_send_id) is not None:
                self._mega_send_recv.pop(mega_send_id)
        else:
            if pack_num != 0:
                last_pack_num = self._mega_send_recv.get(mega_send_id)
                if self._mega_send_recv.get(mega_send_id) != pack_num - 1:
                    _logger.error(f'mega send id {mega_send_id} '
                                  f'missing package between {last_pack_num} '
                                  f'and {pack_num}')
            self._mega_send_recv[mega_send_id] = pack_num
    
    def __bundle_head_reply(
            self, path: str, args: list[int],
            types: OscTypes, src_addr: Address):
        self._ms_checker.head_recv(args[0], args[1])
    
    def __bundle_tail(
            self, path: str, args: list[int],
            types: OscTypes, src_addr: Address):
        self.send(src_addr, '/_bundle_tail_reply', *args)
    
    def __bundle_tail_reply(
            self, path: str, args: list[int],
            types: OscTypes, src_addr: Address):
        mega_send_id, pack_num, is_last = args
        self._ms_checker.tail_recv(mega_send_id, pack_num)
    
    def __local_mega_send(
            self, path: str, args: tuple[int, str],
            types: OscTypes, src_addr: Address):
        mega_send_id, ms_path = args

        if mega_send_id in self._mega_send_recv:
            # this mega_send has been already received
            # ignore it
            _logger.info(
                f'local mega send {mega_send_id} ignored, already received')
            return

        try:
            with open(ms_path, 'r') as f:
                events: list[tuple[str, float, int]] = json.load(f)
        except BaseException as e:
            _logger.error(
                f'__local_mega_send: failed to open file "{ms_path}"')
            return
        
        if not isinstance(events, list):
            _logger.error(
                f'__local_mega_send: wrong data in "{ms_path}"')
            return
        
        try:
            os.remove(ms_path)
        except:
            _logger.info(
                f'__local_mega_send: Failed to remove tmp file {ms_path}')
        
        for event in events:
            if not (isinstance(event, list) and len(event) > 0):
                _logger.error(
                    f'__local_mega_send: wrong data in "{ms_path}"')
                return
            
            path, args_ = event[0], event[1:]
            
            types_func = self._methods_adder.get_func(path, list(args_))
            if types_func is None:
                continue
            
            types, func = types_func
            
            # transform args_ to nargs,
            # especially if tuples are used to send arguments
            # for example: ('d', 0.455751122211)
            # here received in json, there are no tuples, only lists
            # all other arg types seems to be kept.
            nargs = []
            for arg in args_:
                if isinstance(arg, list) and len(arg) == 2:
                    if arg[0] == 'm' and isinstance(arg[1], list):
                        nargs.append(tuple(arg[1]))
                    else:
                        nargs.append(arg[1])
                else:
                    nargs.append(arg)
            
            osp = OscPack(path, nargs, types, src_addr)
            self._exec_func(func, osp)
    
    def __director(self, path: str, args: list[OscArg],
                   types: OscTypes, src_addr: Address):
        '''transmit messages received from methods added
        with `add_nice_method`'''
        multypes_func = self._director_methods.get(path)
        if multypes_func is None:
            any_rejected_m = self._director_methods.get('')
            if any_rejected_m is not None:
                wildcard, rejected_func = any_rejected_m
                rejected_func(OscPack(path, args, types, src_addr))
            return

        multypes, func = multypes_func
        if not types_validator(types, multypes):
            any_rejected_m = self._director_methods.get('')
            if any_rejected_m is not None:
                wildcard, rejected_func = any_rejected_m
                rejected_func(OscPack(path, args, types, src_addr))
            return

        func(OscPack(path, args, types, src_addr))
    
    def add_nice_method(
            self, path: str, multypes: OscMulTypes,
            func: Callable[[OscPack], None]):
        '''Nice way to add an OSC method to the server,
        
        The function `func` MUST accept only one OscPack argument.
        '''
        if path in self._director_methods:
            _logger.warning(
                f'add_nice_method() already defined '
                f'for path: {path}, {multypes} ignored')
            return

        self._director_methods[path] = (multypes, func)
        for types in multypes.split('|'):
            if '.' in types or '*' in types:
                self.add_method(path, None, self.__director) # type:ignore
                break
            else:
                self.add_method(path, types, self.__director) # type:ignore
        
    def add_nice_methods(
            self, methods_dict: dict[OscPath, OscMulTypes],
            func: Callable[[OscPack], None]):
        '''Nice way to add several OSC methods to the server,
        all routed to the same function.
        
        The function `func` MUST accept only one OscPack argument.
        
        `methods_dict` MUST be a dict where keys are osc paths
        and value an OscMulTypes (str).        
        '''
        for path, full_types in methods_dict.items():
            self.add_nice_method(path, full_types, func)
    
    def set_fallback_nice_method(self, func: Callable[[OscPack], None]):
        '''set the fallback function for all messages non matching with
        any defined method.'''
        self._director_methods[''] = ('*', func)
        self.add_method(None, None, self.__director) # type:ignore
    
    def _mega_send_same_process(self, urls: list[str | int | Address],
                                mega_send: MegaSend):
        same_proc_urls = list[str | int | Address]()

        for url in urls:
            dest_port = 0

            if isinstance(url, Address):
                if (url.port in _process_port_queues
                        and are_on_same_machine(self.url, url)
                        and url.protocol == UDP):
                    dest_port: int = url.port # type:ignore
            elif isinstance(url, int):
                if url in _process_port_queues:
                    dest_port = url
            elif isinstance(url, str):
                dport = url.rpartition(':')[2].partition('/')[0]
                proto_str = url.partition('.')[2].partition(':')[0]
                if (dport.isdigit() and int(dport) in _process_port_queues
                        and are_on_same_machine(self.url, url)
                        and proto_str.lower() == 'udp'):
                    dest_port = int(dport)

            if dest_port:
                # we are sending a MegaSend to another instance 
                # in the same process. No OSC communication is needed            
                for path, *args in mega_send.tuples:
                    _process_port_queues[dest_port].put(
                        OscPack(path, args, get_types_with_args(args), # type:ignore
                                Address(self.port)))
                same_proc_urls.append(url)

        for same_proc_url in same_proc_urls:
            urls.remove(same_proc_url)
    
    def _mega_send_one_bundle(
            self, urls: list[str | int | Address], mega_send: MegaSend):
        head_msg = Message('/_bundle_head', mega_send.id, 0, IS_LAST) # type:ignore
        urls_done = set[str | int | Address]()

        for url in urls:
            try:
                self.sv.send(url, Bundle(*[head_msg]+mega_send.messages)) # type:ignore
            except:
                break
            else:
                self.wait_mega_send_answer(mega_send, 0)
                urls_done.add(url)
        
        for url in urls_done:
            urls.remove(url)
    
    def _mega_send_local_json(
            self, urls: list[str | int | Address], mega_send: MegaSend):
        '''for url on the same machine, create a .json file and send 
        a message linking to it.'''
        urls_done = set[str | int | Address]()
        
        for url in urls:
            is_local = False
            if isinstance(url, int):
                is_local = True
            elif isinstance(url, (str, Address)):
                is_local = are_on_same_machine(self.url, url)
            
            if is_local:
                tmp_file = tempfile.NamedTemporaryFile(
                    mode='w+t', delete=False)
                tmp_file.write(json.dumps(mega_send.tuples))
                tmp_file.seek(0)
                self.send(url, '/_local_mega_send', mega_send.id, tmp_file.name)
                urls_done.add(url)
                
        for url in urls_done:
            urls.remove(url)
    
    def mega_send(self: 'Union[BunServer, BunServerThread]',
               url: Union[str, int, Address, list[str | int | Address]],
               mega_send: MegaSend) -> bool:
        '''send a undeterminated number of messages to another BunServer
        (or BunServerThread).
        
        !!! the recepter MUST be a Bunserver or a BunServerThread !!!'''

        urls = url if isinstance(url, list) else [url]
        if not urls:
            return True

        self._mega_send_same_process(urls, mega_send)
        if self.sv is None or not urls:
            return True
        
        self._mega_send_one_bundle(urls, mega_send)
        if not urls:
            return True
        
        self._mega_send_local_json(urls, mega_send)
        if not urls:
            return True

        pack_len = min(len(mega_send.tuples) // 2, 100)
        cutting = list[int]()
        pack_can_grow = True

        while True:
            start = 0
            if cutting:
                start = cutting[-1] + 1
            
            end = min(start + pack_len, len(mega_send.messages)) - 1
            
            try:
                self.sv.send(
                    _RESERVED_PORT, # type:ignore
                    Bundle(*[Message('/_bundle_head', 0x100000000, 0, 0)] # type:ignore
                           + mega_send.messages[start:end]
                           +[Message('/_bundle_tail', 0x100000000, 0, 0)])) # type:ignore
            except:
                if pack_len == 1:
                    _logger.critical(
                        f'One message is too big to be send'
                        f'by the mega send {mega_send.ref}')
                    break
                
                pack_len //= 2
                pack_can_grow = False
            else:
                if pack_can_grow:
                    pack_len *= 2
                cutting.append(end)
                if end == len(mega_send.messages) - 1:
                    break
        
        if not cutting:
            return False

        for url in urls:
            start = 0
            pack_num = 0

            for c in cutting:
                is_last = IS_LAST if c == cutting[-1] else IS_NOT_LAST
            
                self.sv.send(
                    url,
                    Bundle(
                        *[Message('/_bundle_head', mega_send.id, # type:ignore
                                  pack_num, is_last)] # type:ignore
                        + mega_send.messages[start:c]
                        +[Message('/_bundle_tail', mega_send.id, # type:ignore
                                  pack_num, is_last)])) # type:ignore
                regc = self.wait_mega_send_answer(mega_send, pack_num)
                if not regc:
                    break
            
                start = c + 1
                pack_num += 1
        
        return True
    
    def wait_mega_send_answer(
            self, mega_send: MegaSend, pack_num: int) -> bool:
        self._ms_checker.add_waiting(mega_send.id, pack_num)

        start = time.time()
        
        while not self._ms_checker.head_received(mega_send.id, pack_num):
            self.recv(10)
            if time.time() - start >= 0.050:
                break
            
        while not self._ms_checker.previous_tail_received(
                mega_send.id, pack_num):
            self.recv(100)
            if time.time() - start >= 5.000:
                _logger.info(
                    f'too long wait for bundle '
                    f'recv confirmation {mega_send.id}. {mega_send.ref}')
                return False
        return True
 

class BunServerThread(BunServer):
    '''Class inheriting liblo.Server. Provides a server thread
    with the mega_send feature, which allows to send massive
    bundle of messages, in several sends if needed.'''
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        self.timeout = 50
        self._terminated = False
        self._thread: Optional[Thread] = None
    
    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        
        if self._thread is None:
            self._thread = Thread(target=self._main_loop)
        self._thread.start()
        
    def stop(self):
        if self._thread is None:
            return
        self._terminated = True
        self._thread.join()
        self._thread = None
    
    def _main_loop(self):
        while not self._terminated:
            self.recv(self.timeout)
    
    def wait_mega_send_answer(
            self, mega_send: MegaSend, pack_num: int) -> bool:
        if self.sv is None:
            return True
        
        self._ms_checker.add_waiting(mega_send.id, pack_num)

        start = time.time()
        recv = current_thread() is self._thread
        
        while not self._ms_checker.head_received(mega_send.id, pack_num):
            if recv:
                self.sv.recv(10)
            else:
                time.sleep(0.001)
            if time.time() - start >= 0.050:
                break
            
        while not self._ms_checker.previous_tail_received(
                mega_send.id, pack_num):
            if recv:
                self.sv.recv(100)
            else:
                time.sleep(0.001)

            if time.time() - start >= 5.000:
                _logger.info(
                    f'too long wait for bundle '
                    f'recv confirmation {mega_send.id}. {mega_send.ref}')
                return False
        return True
