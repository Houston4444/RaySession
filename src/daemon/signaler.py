from PyQt5.QtCore import QObject, pyqtSignal

instance = None

class Signaler(QObject):
    osc_recv = pyqtSignal(str, list, str, object)
    copy_aborted = pyqtSignal()
    net_duplicate_state   = pyqtSignal(object, int)
        
    dummy_load_and_template = pyqtSignal(str, str, str)
    dummy_duplicate         = pyqtSignal(object, str, str, str)
    
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


