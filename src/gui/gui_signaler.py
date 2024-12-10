
# Imports from standard library
import enum

# third party imports
from qtpy.QtCore import QObject, Signal

# Imports from src/shared
from osclib import Address
import ray


class Signaler(QObject):
    osc_receive = Signal(str, list)
    daemon_announce = Signal(
        Address, str, ray.ServerStatus, ray.Option, str, int)
    daemon_announce_ok = Signal()
    daemon_nsm_locked = Signal(bool)
    server_copying = Signal(bool)

    add_sessions_to_list = Signal(list)
    new_executable = Signal(list)
    session_template_found = Signal(list)
    user_client_template_found = Signal(list)
    factory_client_template_found = Signal(list)
    snapshots_found = Signal(list)
    reply_auto_snapshot = Signal(bool)
    server_progress = Signal(float)
    client_progress = Signal(str, float)
    server_status_changed = Signal(object)

    daemon_url_request = Signal(int, str)
    daemon_url_changed = Signal(str)

    client_template_update = Signal(list)
    client_template_ray_hack_update = Signal(list)
    client_template_ray_net_update = Signal(list)

    root_changed = Signal(str)

    session_preview_update = Signal(int)
    session_details = Signal(str, int, int, int)
    scripted_dir = Signal(str, int)
    parrallel_copy_state = Signal(int, int)
    parrallel_copy_progress = Signal(int, float)
    parrallel_copy_aborted = Signal()
    other_session_renamed = Signal()
    other_session_duplicated = Signal()
    other_session_templated = Signal()

    client_added_reply = Signal(str)

    client_properties_state_changed = Signal(str, bool)

    favorite_added = Signal(str, str, bool, str)
    favorite_removed = Signal(str, bool)

    hiddens_changed = Signal(int)

    canvas_callback = Signal(enum.IntEnum, tuple)

    def __init__(self):
        QObject.__init__(self)
