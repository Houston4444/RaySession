from PyQt5.QtCore import QObject, pyqtSignal

instance = None

class Signaler(QObject):
    osc_recv = pyqtSignal(object)
    '''Emitted when OSC message is received.
    Then, the function associated with the OSC path in session_signaled
    will be executed in the main thread.'''
    
    dummy_load_and_template = pyqtSignal(str, str, str)

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
