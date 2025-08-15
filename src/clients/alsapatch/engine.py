
from patcher.bases import EventHandler

# Local imports
from .check_internal import IS_INTERNAL

if IS_INTERNAL:
    from .alsa_engine_remote import AlsaEngine
else:
    from .alsa_engine import AlsaEngine


class Engine(AlsaEngine): # type:ignore
    XML_TAG = 'RAY-ALSAPATCH'
    EXECUTABLE = 'ray-alsapatch'
    NSM_NAME = 'ALSA Connections'

    def __init__(self, event_handler: EventHandler):
        super().__init__(event_handler)