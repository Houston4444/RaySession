
# third party imports
from qtpy.QtCore import QObject, Signal

instance = None

class Signaler(QObject):
    osc_recv = Signal(object)
    '''Emitted when OSC message is received.
    Then, the function associated with the OSC path in session_signaled
    will be executed in the main thread.'''
    
    dummy_load_and_template = Signal(str, str, str)

    @staticmethod
    def instance():
        global instance

        if not instance:
            instance = Signaler()
        return instance

    def __init__(self):
        QObject.__init__(self)
        global instance
        instance = self
