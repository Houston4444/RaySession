
# Local imports
from jack_engine import JackEngine


XML_TAG = 'RAY-JACKPATCH'
EXECUTABLE = 'ray-jackpatch'
NSM_NAME = 'JACK Connections'


class Engine(JackEngine):
    def __init__(self):
        super().__init__()
