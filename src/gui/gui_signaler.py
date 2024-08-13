import enum
from PyQt5.QtCore import QObject, pyqtSignal
from liblo import Address

import ray


class Signaler(QObject):
    osc_receive = pyqtSignal(str, list)
    daemon_announce = pyqtSignal(
        Address, str, ray.ServerStatus, ray.Option, str, int)
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
    server_status_changed = pyqtSignal(object)

    daemon_url_request = pyqtSignal(int, str)
    daemon_url_changed = pyqtSignal(str)

    client_template_update = pyqtSignal(list)
    client_template_ray_hack_update = pyqtSignal(list)
    client_template_ray_net_update = pyqtSignal(list)

    root_changed = pyqtSignal(str)

    session_preview_update = pyqtSignal()
    session_details = pyqtSignal(str, int, int, int)
    scripted_dir = pyqtSignal(str, int)
    parrallel_copy_state = pyqtSignal(int, int)
    parrallel_copy_progress = pyqtSignal(int, float)
    parrallel_copy_aborted = pyqtSignal()
    other_session_renamed = pyqtSignal()
    other_session_duplicated = pyqtSignal()
    other_session_templated = pyqtSignal()

    client_added_reply = pyqtSignal(str)

    client_properties_state_changed = pyqtSignal(str, bool)

    favorite_added = pyqtSignal(str, str, bool, str)
    favorite_removed = pyqtSignal(str, bool)

    hiddens_changed = pyqtSignal(int)

    canvas_callback = pyqtSignal(enum.IntEnum, tuple)

    def __init__(self):
        QObject.__init__(self)
