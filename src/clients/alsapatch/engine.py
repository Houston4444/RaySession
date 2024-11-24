from .alsa_engine import AlsaEngine

XML_TAG = 'RAY-ALSAPATCH'
EXECUTABLE = 'ray-alsapatch'
NSM_NAME = 'ALSA Connections'

class Engine(AlsaEngine):
    def __init__(self):
        super().__init__()