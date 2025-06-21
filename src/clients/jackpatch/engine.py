
from patcher.bases import EventHandler

# Local imports
from .jack_engine_remote import JackEngine


class Engine(JackEngine):
    XML_TAG = 'RAY-JACKPATCH'
    EXECUTABLE = 'ray-jackpatch'
    NSM_NAME = 'JACK Connections'

    def __init__(self, event_handler: EventHandler):
        super().__init__(event_handler)
