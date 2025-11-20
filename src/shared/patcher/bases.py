
# Imports from standard library
from queue import Queue
import time
from enum import IntEnum, Enum
import re
from typing import Iterator, TypeAlias

from patshared import PortMode, PortType
from patch_engine import PatchEvent

# Type aliases
NsmClientName: TypeAlias = str
'''simple NSM client id'''

JackClientBaseName: TypeAlias = str
'''base of a jack client name,
can be the full client name or just its prefix if there are
multiple JACK clients for the same NSM client'''

FullPortName: TypeAlias = str
'Full port name string under the form "jack_client_name:port_name"'

ConnectionStr: TypeAlias = tuple[FullPortName, FullPortName]
PatternOrName: TypeAlias = FullPortName|re.Pattern[str]
ConnectionPattern: TypeAlias = tuple[PatternOrName, PatternOrName]


class PortData:
    id = 0
    name = ''
    mode = PortMode.NULL
    type = PortType.NULL
    is_new = False
    '''used to prevent reconnections
    when a disconnection has not been saved and one new port append.'''


class ProtoEngine:
    XML_TAG = 'RAY-PATCH'
    EXECUTABLE = 'ray-patch'
    NSM_NAME = 'Connections'

    def __init__(self, event_handler: 'EventHandler'):
        self.ev_handler = event_handler

    def init(self) -> bool:
        return True

    def fill_ports_and_connections(
            self, port_list: dict[PortMode, list[PortData]],
            connections: set[tuple[str, str]]):
        ...
    def connect_ports(self, port_out: str, port_in: str):
        ...
    def disconnect_ports(self, port_out: str, port_in: str):
        ...
    def quit(self):
        ...


class MonitorStates(IntEnum):
    NEVER_DONE = 0
    UPDATING = 1
    DONE = 2


class TerminateState(Enum):
    NORMAL = 0
    ASKED = 1
    RESTORING = 2
    LEAVING = 3


class Timer:
    _last_ask = 0.0
    _duration: float
    
    def __init__(self, duration: float):
        self._duration = duration
        
    def start(self):
        self._last_ask = time.time()
        
    def elapsed(self) -> bool:
        if not self._last_ask:
            return False
        
        elapsed = time.time() - self._last_ask >= self._duration
        if elapsed:
            self._last_ask = 0.0
        return elapsed


class EventHandler:
    def __init__(self):
        self._event_queue = Queue()
    
    def add_event(self, event: PatchEvent, *args):
        self._event_queue.put((event, args))

    def new_events(self) -> Iterator[tuple[PatchEvent, tuple]]:
        while self._event_queue.qsize():
            yield self._event_queue.get()


def debug_conn_str(conn: tuple[str, str]):
    return f"connection from '{conn[0]}' to '{conn[1]}'"

