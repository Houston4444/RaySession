
from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot
from liblo import Address

_instance = None


class Signaler(QObject):
    osc_receive = pyqtSignal(str, list)
    daemon_announce = pyqtSignal(Address, str, int, int, str, int)
    daemon_announce_ok = pyqtSignal()
    daemon_nsm_locked = pyqtSignal(bool)
    server_copying = pyqtSignal(bool)
    error_message = pyqtSignal(list)

    add_sessions_to_list = pyqtSignal(list)
    new_executable = pyqtSignal(list)
    session_template_found = pyqtSignal(list)
    user_client_template_found = pyqtSignal(list)
    factory_client_template_found = pyqtSignal(list)
    snapshots_found = pyqtSignal(list)
    reply_auto_snapshot = pyqtSignal(bool)
    server_progress = pyqtSignal(float)
    server_status_changed = pyqtSignal(int)

    daemon_url_request = pyqtSignal(int, str)
    daemon_url_changed = pyqtSignal(str)
    
    root_changed = pyqtSignal(str)

    def __init__(self):
        QObject.__init__(self)
        global _instance
        _instance = self

    @staticmethod
    def instance():
        global _instance
        if not _instance:
            _instance = Signaler()
        return _instance
