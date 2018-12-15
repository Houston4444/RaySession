
from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot
from liblo import Address

_instance = None

class Signaler(QObject):
    daemon_announce     = pyqtSignal(Address, str, int, int, str, int)
    daemon_announce_ok  = pyqtSignal()
    daemon_nsm_locked   = pyqtSignal(bool)
    server_copying      = pyqtSignal(bool)
    new_message_sig     = pyqtSignal(str)
    session_name_sig    = pyqtSignal(str, str)
    session_renameable  = pyqtSignal(bool)
    error_message       = pyqtSignal(list)
    
    new_client_added       = pyqtSignal(object)
    new_client_stopped     = pyqtSignal(str, str)
    client_removed         = pyqtSignal(str)
    client_status_changed  = pyqtSignal(str, int)
    client_switched        = pyqtSignal(str, str)
    client_progress        = pyqtSignal(str, float)
    client_dirty_sig       = pyqtSignal(str, bool)
    client_has_gui         = pyqtSignal(str)
    client_gui_visible_sig = pyqtSignal(str, int)
    client_still_running   = pyqtSignal(str)
    client_updated         = pyqtSignal(object)
    add_sessions_to_list   = pyqtSignal(list)
    new_executable         = pyqtSignal(list)
    session_template_found = pyqtSignal(list)
    user_client_template_found    = pyqtSignal(list)
    factory_client_template_found = pyqtSignal(list)
    server_progress        = pyqtSignal(float)
    server_status_changed  = pyqtSignal(int)
    clients_reordered      = pyqtSignal(list)
    opening_session    = pyqtSignal()
    
    trash_add    = pyqtSignal(object)
    trash_remove = pyqtSignal(str)
    trash_clear  = pyqtSignal()
    trash_dialog = pyqtSignal(str)
    
    daemon_url_request = pyqtSignal(int, str)
    daemon_url_changed = pyqtSignal(str)
    
    daemon_options = pyqtSignal(int)
    
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
        
    @pyqtSlot()
    def restoreClient(self):
        try:
            client_id = str(self.sender().data())
        except:
            return
        
        self.trash_dialog.emit(client_id)
