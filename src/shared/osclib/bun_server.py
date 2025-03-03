from inspect import signature, _ParameterKind
import json
import logging
import os
import random
import tempfile
import time
from threading import Thread
from typing import Callable, Union, Optional

from .bases import (
    Server, Address, Message, Bundle, MegaSend)
from .funcs import are_on_same_machine
from .bun_tools import MethodsAdder, _SemDict

_logger = logging.getLogger(__name__)
_RESERVED_PORT = 47


class BunServer(Server):
    def __init__(self, *args, **kwargs):
        self._methods_adder = MethodsAdder()
        super().__init__(*args, **kwargs)

        self.add_method('/_bundle_head', 'iii', self.__bundle_head)
        self.add_method('/_bundle_head_reply', 'iii', self.__bundle_head_reply)
        self.add_method('/_local_mega_send', 's', self.__local_mega_send)
        
        self._sem_dict = _SemDict()
    
    def add_method(
            self, path: str, typespec: str, func: Callable[[], None],
            user_data=None):
        self._methods_adder.add(path, typespec, func, user_data)
        return super().add_method(path, typespec, func, user_data=user_data)
    
    def __bundle_head(
            self, path: str, args: list[int], types: str, src_addr: Address):
        self.send(src_addr, '/_bundle_head_reply', *args)
    
    def __bundle_head_reply(
            self, path: str, args: list[int], types: str, src_addr: Address):
        self._sem_dict.head_received(args[0])
    
    def __local_mega_send(
            self, path: str, args: list[str], types: str, src_addr: Address):
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
            os.path.remove(ms_path)
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
            
            # execute function
            match number_of_args(func):
                case 1: func(path)
                case 2: func(path, nargs)
                case 3: func(path, nargs, types)
                case 4: func(path, nargs, types, src_addr)
                case 5: func(path, nargs, types, src_addr, None)
    
    def mega_send(self: 'Union[BunServer, BunServerThread]',
               url: Union[str, int, Address, list[str | int | Address]],
               mega_send: MegaSend, pack=10) -> bool:
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
        urls_done = set[str, int, Address]()
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
                tmp_file = tempfile.NamedTemporaryFile(mode='w+t', delete=False)
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
        
        while self._sem_dict.count(bundler_id) >= 1:
            time.sleep(0.001)
            i += 1
            if i >= 200:
                _logger.warning(
                    f'too long wait for bundle '
                    f'recv confirmation {bundler_id}. {ref}')
                return False 
        return True