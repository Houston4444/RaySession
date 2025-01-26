
from patcher.bases import EventHandler

# Local imports
from .alsa_engine import AlsaEngine


class Engine(AlsaEngine):
    XML_TAG = 'RAY-ALSAPATCH'
    EXECUTABLE = 'ray-alsapatch'
    NSM_NAME = 'ALSA Connections'

    def __init__(self, event_handler: EventHandler):
        super().__init__(event_handler)