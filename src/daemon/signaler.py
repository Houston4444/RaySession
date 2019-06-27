from PyQt5.QtCore import QObject, pyqtSignal
#from session import DummySession

instance = None

class Signaler(QObject):
    server_announce    = pyqtSignal(str, list, object)
    server_reply       = pyqtSignal(str, list, object)
    server_rename      = pyqtSignal(str)
    server_duplicate   = pyqtSignal(str, list, object)
    server_duplicate_only = pyqtSignal(str, list, object)
    server_save_session_template = pyqtSignal(str, list, object, bool)
    server_abort       = pyqtSignal(str, list, object)
    server_close       = pyqtSignal(str, list, object)
    server_new         = pyqtSignal(str, list, object)
    server_new_from_tp = pyqtSignal(str, list, object, bool)
    server_open        = pyqtSignal(str, list, object)
    server_save        = pyqtSignal(str, list, object)
    take_snapshot = pyqtSignal(str)
    server_save_from_client = pyqtSignal(str, list, object, str)
    server_list_sessions = pyqtSignal(object, bool)
    server_open_snapshot = pyqtSignal(str, list, object)
    server_add       = pyqtSignal(str, list, object)
    server_add_proxy = pyqtSignal(str, list, object)
    server_add_client_template = pyqtSignal(str, list, object)
    server_add_user_client_template    = pyqtSignal(str, list, object)
    server_add_factory_client_template = pyqtSignal(str, list, object)
    server_reorder_clients = pyqtSignal(str, list)
    server_list_snapshots = pyqtSignal(object)
    server_set_auto_snapshot = pyqtSignal(bool)
    gui_client_stop    = pyqtSignal(str, list)
    gui_client_kill    = pyqtSignal(str, list)
    gui_client_trash  = pyqtSignal(str, list)
    gui_client_resume  = pyqtSignal(str, list)
    gui_client_save    = pyqtSignal(str, list)
    gui_client_save_template = pyqtSignal(str, list)
    gui_client_label = pyqtSignal(str, str)
    gui_client_icon  = pyqtSignal(str, str)
    gui_update_client_properties = pyqtSignal(object)
    copy_aborted = pyqtSignal()
    gui_trash_restore           = pyqtSignal(str)
    gui_trash_remove_definitely = pyqtSignal(str)
    
    bookmark_option_changed = pyqtSignal(bool)
    
    client_net_properties = pyqtSignal(str, str, str)
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
        #self.dummy_load_and_template.connect(self.dummyLoadAndTemplate)
        #self.dummy_duplicate.connect(self.dummyDuplicate)
        
    #def dummyLoadAndTemplate(self, session_name, template_name, sess_root):
        #tmp_session = DummySession(sess_root)
        #tmp_session.dummyLoadAndTemplate(session_name, template_name)
        
    #def dummyDuplicate(self, src_addr, session_to_load,
                       #new_session, sess_root):
        #tmp_session = DummySession(sess_root)
        #tmp_session.osc_src_addr = src_addr
        #tmp_session.dummyDuplicate(session_to_load, new_session)
        
#Signaler.dummy_load_and_template.connect(dummyLoadAndTemplate)
#Signaler.dummy_duplicate.connect(dummyDuplicate)


