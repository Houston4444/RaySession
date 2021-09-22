
from PyQt5.QtCore import QObject, pyqtSignal
from liblo import Address

class Signaler(QObject):
    osc_receive = pyqtSignal(str, list)
    daemon_announce = pyqtSignal(Address, str, int, int, str, int)
    daemon_announce_ok = pyqtSignal()
    daemon_nsm_locked = pyqtSignal(bool)
    server_copying = pyqtSignal(bool)

    add_sessions_to_list = pyqtSignal(list)
    new_executable = pyqtSignal(list)
    session_template_found = pyqtSignal(list)
    user_client_template_found = pyqtSignal(list)
    factory_client_template_found = pyqtSignal(list)
    snapshots_found = pyqtSignal(list)
    reply_auto_snapshot = pyqtSignal(bool)
    server_progress = pyqtSignal(float)
    client_progress = pyqtSignal(str, float)
    server_status_changed = pyqtSignal(int)

    daemon_url_request = pyqtSignal(int, str)
    daemon_url_changed = pyqtSignal(str)

    client_template_update = pyqtSignal(list)
    client_template_ray_hack_update = pyqtSignal(list)
    client_template_ray_net_update = pyqtSignal(list)

    root_changed = pyqtSignal(str)

    session_preview_update = pyqtSignal()
    session_details = pyqtSignal(str, int, int, int)
    scripted_dir = pyqtSignal(str, int)

    client_added_reply = pyqtSignal(str)

    client_properties_state_changed = pyqtSignal(str, bool)

    favorite_added = pyqtSignal(str, str, bool)
    favorite_removed = pyqtSignal(str, bool)

    canvas_callback = pyqtSignal(int, int, int, str)

    def __init__(self):
        QObject.__init__(self)
