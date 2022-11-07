
from queue import Queue
import time
from enum import IntEnum
from typing import Iterator


class PortMode(IntEnum):
    NULL = 0
    OUTPUT = 1
    INPUT = 2


# It is here if we want to improve the saved file
# with the type of the port.
# At this stage, we only care about the port name.
class PortType(IntEnum):
    NULL = 0
    AUDIO = 1
    MIDI = 2


class Event(IntEnum):
    CLIENT_ADDED = 1
    CLIENT_REMOVED = 2
    PORT_ADDED = 3
    PORT_REMOVED = 4
    PORT_RENAMED = 5
    CONNECTION_ADDED = 6
    CONNECTION_REMOVED = 7
    JACK_STOPPED = 8


class JackPort:
    # is_new is used to prevent reconnections
    # when a disconnection has not been saved and one new port append.
    id = 0
    name = ''
    mode = PortMode.NULL
    type = PortType.NULL
    is_new = False
    

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
    _event_queue = Queue()
    
    @classmethod
    def add_event(cls, event: Event, *args: tuple):
        cls._event_queue.put((event, args))

    @classmethod
    def new_events(cls) -> Iterator[tuple[Event, tuple]]:
        while cls._event_queue.qsize():
            yield cls._event_queue.get()


class Glob:
    file_path = ''
    is_dirty = False
    pending_connection = False
    open_done_once = False
    allow_disconnections = False
    terminate = False
    jack_thread_running = False
    stopping_brothers = set[str]()


def b2str(src_bytes: bytes) -> str:
    ''' decodes bytes to string '''
    return str(src_bytes, encoding="utf-8")
