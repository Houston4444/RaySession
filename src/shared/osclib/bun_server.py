import json
import logging
import os
from queue import Queue
import random
import tempfile
import time
from threading import Thread, current_thread
from typing import Callable, Union, Optional

from osclib import OscTypes

from .bases import (
    OscArg, OscMulTypes, OscPack, Server, Address, Message, Bundle, MegaSend,
    get_types_with_args, types_validator, UDP)
from .funcs import are_on_same_machine
from .bun_tools import number_of_args, MethodsAdder, _SemDict

_logger = logging.getLogger(__name__)

_RESERVED_PORT = 47
'''Port reserved in OSC, used to try to send message to,
this way, no risk that any OSC port can receive it.'''

_process_port_queues = dict[int, Queue[OscPack]]()
'Contains the port numbers of all BunServer instantiated in this process'


class BunServer(Server):
    '''Class inheriting liblo.Server. Provides a server
    with the mega_send feature, which allows to send massive
    bundle of messages, in several sends if needed.'''
    def __init__(self, *args, **kwargs):
        self._methods_adder = MethodsAdder()
        self._director_methods = dict[
            str, tuple[OscMulTypes, Callable[[OscPack], None]]]()

        super().__init__(*args, **kwargs)

        self.add_method('/_bundle_head', 'iii', self.__bundle_head)
        self.add_method('/_bundle_head_reply', 'iii', self.__bundle_head_reply)
        self.add_method('/_local_mega_send', 's', self.__local_mega_send)
        
        self._sem_dict = _SemDict()
        _process_port_queues[self.port] = Queue()
    
    def _exec_func(self, func: Callable, osp: OscPack):
        'Used when OSC communication is fake, to execute the desired func'
        match number_of_args(func):
            case 1: func(osp.path)
            case 2: func(osp.path, osp.args)
            case 3: func(osp.path, osp.args, osp.types)
            case 4: func(osp.path, osp.args, osp.types, osp.src_addr)
            case 5: func(osp.path, osp.args, osp.types, osp.src_addr, None)
    
    def recv(self, timeout: Optional[int] = None) -> bool:
        while _process_port_queues[self.port].qsize():
            osp = _process_port_queues[self.port].get()
            types_func = self._methods_adder.get_func(osp.path, osp.args)
            if types_func is None:
                continue
            
            types, func = types_func
            osp.types = types
            self._exec_func(func, osp)
        
        return super().recv(timeout)
    
    def send(self, *args, **kwargs):
        dest = args[0]
        dest_port = 0

        if isinstance(dest, Address):
            if (dest.port in _process_port_queues
                    and are_on_same_machine(self.url, dest)
                    and dest.protocol == UDP):
                dest_port = dest.port
        elif isinstance(dest, int):
            if dest_port in _process_port_queues:
                dest_port = dest
        
        if dest_port:
            # communication between two BunServer in the same process
            # avoid OSC communication, directly enqueue the message
            # the receiver will take it at recv.
            dest, path, *other_args = args
            _process_port_queues[dest_port].put(
                OscPack(path, other_args, get_types_with_args(other_args),
                        Address(self.port)))
            return

        super().send(*args, **kwargs)
    
    def add_method(
            self, path: Optional[str], typespec: Optional[OscTypes],
            func: Callable[[], None], user_data=None):
        self._methods_adder.add(path, typespec, func, user_data)
        return super().add_method(path, typespec, func, user_data=user_data)
    
    def __bundle_head(
            self, path: str, args: list[int],
            types: OscTypes, src_addr: Address):
        self.send(src_addr, '/_bundle_head_reply', *args)
    
    def __bundle_head_reply(
            self, path: str, args: list[int],
            types: OscTypes, src_addr: Address):
        self._sem_dict.head_received(args[0])
    
    def __local_mega_send(
            self, path: str, args: list[str],
            types: OscTypes, src_addr: Address):
        ms_path = args[0]
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
            
            types_func = self._methods_adder.get_func(path, args_)
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
        with `add_nice_methods`'''
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
                self.add_method(path, None, self.__director)
                break
            else:
                self.add_method(path, types, self.__director)
        
    def add_nice_methods(
            self, methods_dict: dict[str, OscMulTypes],
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
        self.add_method(None, None, self.__director)
    
    def mega_send(self: 'Union[BunServer, BunServerThread]',
               url: Union[str, int, Address, list[str | int | Address]],
               mega_send: MegaSend, pack=10) -> bool:
        '''send a undeterminated number of messages to another BunServer
        (or BunServerThread).
        
        !!! the recepter MUST be a Bunserver or a BunServerThread !!!'''

        # check first if we are sending something to the same process
        dest = url
        dest_port = 0

        if isinstance(dest, Address):
            if (dest.port in _process_port_queues
                    and are_on_same_machine(self.url, dest)
                    and dest.protocol == UDP):
                dest_port = dest.port
        elif isinstance(dest, int):
            if dest_port in _process_port_queues:
                dest_port = dest

        if dest_port:
            # we are sending a MegaSend to another instance 
            # in the same process. No OSC communication is needed            
            for path, *args in mega_send.tuples:
                _process_port_queues[dest_port].put(
                OscPack(path, args, get_types_with_args(args),
                        Address(self.port)))
            return
        
        bundler_id = random.randrange(0x100, 0x100000)
        bundle_number_self = random.randrange(0x100, 0x100000)
        
        i = 0
        stocked_msgs = list[Message]()
        pending_msgs = list[Message]()
        head_msg_self = Message('/_bundle_head', bundle_number_self, 0, 0)
        head_msg = Message('/_bundle_head', bundler_id, 0, 0)
        
        urls = url if isinstance(url, list) else [url]
        if not urls:
            return True

        messages = mega_send.messages

        # first, try to send all in one bundle
        all_ok = True   
        urls_done = set[str | int | Address]()
        for url in urls:
            try:
                self.send(url, Bundle(*[head_msg]+messages))
                assert self.wait_mega_send_answer(bundler_id, mega_send.ref)
                urls_done.add(url)
            except:
                all_ok = False
                break
        
        if all_ok:
            return True
        
        for url in urls_done:
            urls.remove(url)
        urls_done.clear()
        
        for url in urls:
            is_local = False
            if isinstance(url, Address):
                is_local = are_on_same_machine(self.url, url.url)
            elif isinstance(url, str):
                is_local = are_on_same_machine(self.url, url)
            elif isinstance(url, int):
                is_local = True
            
            if is_local:
                tmp_file = tempfile.NamedTemporaryFile(
                    mode='w+t', delete=False)
                tmp_file.write(json.dumps(mega_send.tuples))
                tmp_file.seek(0)
                self.send(url, '/_local_mega_send', tmp_file.name)
                urls_done.add(url)
                
        for url in urls_done:
            urls.remove(url)
        
        for message in messages:
            pending_msgs.append(message)

            if (i+1) % pack == 0:
                success = True
                try:
                    self.send(
                        _RESERVED_PORT,
                        Bundle(*[head_msg_self]+stocked_msgs+pending_msgs))
                except:
                    success = False
                
                if success:
                    stocked_msgs += pending_msgs
                    pending_msgs.clear()
                else:
                    if stocked_msgs:
                        for url in urls:
                            self.send(url, Bundle(*[head_msg]+stocked_msgs))
                            self.wait_mega_send_answer(
                                bundler_id, mega_send.ref)
                        
                        stocked_msgs.clear()
                    else:
                        _logger.error(
                            f'pack of {pack} is too high '
                            f'for mega_send {mega_send.ref}')
                        return False
            
            i += 1
        
        success = True

        try:
            self.send(_RESERVED_PORT,
                      Bundle(*[head_msg_self]+stocked_msgs+pending_msgs))
        except:
            success = False
            
        if success:
            for url in urls:
                self.send(url, Bundle(*[head_msg]+stocked_msgs+pending_msgs))
                self.wait_mega_send_answer(bundler_id, mega_send.ref)
        else:
            for url in urls:
                self.send(url, Bundle(*[head_msg]+stocked_msgs))
                self.wait_mega_send_answer(bundler_id, mega_send.ref)
                self.send(url, Bundle(*[head_msg]+pending_msgs))
                self.wait_mega_send_answer(bundler_id)
        
        return True
    
    def wait_mega_send_answer(self, bundler_id: int, ref: str) -> bool:
        self._sem_dict.add_waiting(bundler_id)

        start = time.time()
        
        while self._sem_dict.count(bundler_id) >= 1:
            self.recv(1)
            if time.time() - start >= 0.200:
                _logger.error(
                    f'too long wait for bundle '
                    f'recv confirmation {bundler_id}. {ref}')
                return False 
        return True
 
 
class BunServerThread(BunServer):
    '''Class inheriting liblo.Server. Provides a server thread
    with the mega_send feature, which allows to send massive
    bundle of messages, in several sends if needed.'''
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
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
            self.recv(10)

    def wait_mega_send_answer(self, bundler_id: int, ref: str) -> bool:
        self._sem_dict.add_waiting(bundler_id)

        i = 0
        recv = current_thread() is self._thread
        
        while self._sem_dict.count(bundler_id) >= 1:
            if recv:
                self.recv(1)
            else:
                time.sleep(0.001)
            i += 1
            if i >= 100:
                _logger.warning(
                    f'too long wait for bundle '
                    f'recv confirmation {bundler_id}. {ref}')
                return False 
        return True