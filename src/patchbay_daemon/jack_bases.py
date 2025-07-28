from dataclasses import dataclass
from enum import IntEnum, Enum, auto
from queue import Queue
import time
from typing import Iterator, TypeAlias, Optional

from port_data import PortData


PatchEventArg: TypeAlias = str | PortData | tuple[str, str] | tuple[int, str, str]


@dataclass
class TransportPosition:
    frame: int
    rolling: bool
    valid_bbt: bool
    bar: int
    beat: int
    tick: int
    beats_per_minutes: float


class TransportWanted(IntEnum):
    NO = 0
    'do not send any transport info'
    
    STATE_ONLY = 1
    'send transport info only when play/pause changed'

    FULL = 2
    'send all transport infos'


class PatchEvent(Enum):
    CLIENT_ADDED = auto()
    CLIENT_REMOVED = auto()
    PORT_ADDED = auto()
    PORT_REMOVED = auto()
    PORT_RENAMED = auto()
    CONNECTION_ADDED = auto()
    CONNECTION_REMOVED = auto()
    METADATA_CHANGED = auto()
    SHUTDOWN = auto()


class PatchEventQueue(Queue[tuple[PatchEvent, PatchEventArg, float]]):
    def __init__(self, maxsize: int = 0):
        super().__init__(maxsize)
        self.oldies_queue = Queue()
        
    def add(self, *args):
        nargs = len(args)
        if nargs > 2:
            event, *rest = args
        elif nargs == 2:
            event, rest = args
        elif nargs == 1:
            event = args[0]
            rest = None
        else:
            raise TypeError
        self.put((event, rest))
        self.oldies_queue.put((event, rest, time.time()))
        
    def __iter__(self) -> Iterator[tuple[PatchEvent, PatchEventArg]]:
        while self.qsize():
            event, event_arg = self.get()
            yield (event, event_arg)
    
    def oldies(self, required_time: float = 0.200) \
            -> Iterator[tuple[PatchEvent, PatchEventArg]]:
        '''Iter only events older than required_time'''
        while self.oldies_queue.qsize():
            if time.time() - self.oldies_queue.queue[0][2] < required_time:
                break

            event, event_arg, time_ = self.oldies_queue.get()
            yield (event, event_arg)


class ClientNamesUuids(dict[str, int]):
    def __init__(self):
        super().__init__()
        self._revd = dict[int, str]()
        
    def __setitem__(self, key: str, value: int):
        super().__setitem__(key, value)
        self._revd[value] = key
        
    def __delitem__(self, key):
        self._revd.pop(self[key])
        super().__delitem__(key)
    
    def name_from_uuid(self, uuid: int) -> Optional[str]:
        return self._revd.get(uuid)