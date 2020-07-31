from PyQt5.QtCore import QObject, pyqtSignal

instance = None

class Signaler(QObject):
    osc_recv = pyqtSignal(str, list, str, object)
    #script_finished = pyqtSignal(str, int, str)
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
