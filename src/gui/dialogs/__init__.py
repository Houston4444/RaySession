import time

from .child_dialog import ChildDialog

from .abort_copy import AbortServerCopyDialog, AbortClientCopyDialog
from .abort_session import AbortSessionDialog
from .about_raysession import AboutRaySessionDialog
from .add_application import AddApplicationDialog
from .client_properties import ClientPropertiesDialog
from .client_prop_adv import AdvancedPropertiesDialog
from .client_rename import ClientRenameDialog
from .client_trash import ClientTrashDialog
from .daemon_url import DaemonUrlDialog
from .donations import DonationsDialog
from .error import ErrorDialog
from .jack_config_info import JackConfigInfoDialog
from .new_executable import NewExecutableDialog
from .new_session import NewSessionDialog
from .open_nsm_info import OpenNsmSessionInfoDialog
from .open_session import OpenSessionDialog
from .preferences import PreferencesDialog
from .quit_app import QuitAppDialog
from .save_template import SaveTemplateClientDialog, SaveTemplateSessionDialog
from .script_info import ScriptInfoDialog
from .session_notes import SessionNotesDialog
from .session_scripts_info import SessionScriptsInfoDialog
from .script_user_action import ScriptUserActionDialog
from .snapshot_progress import SnapShotProgressDialog
from .snapshots import (SessionSnapshotsDialog, ClientSnapshotsDialog,
                        Snapshot, SnapGroup, SnGroup)
from .startup_dialog import StartupDialog
from .stop_client import StopClientDialog, StopClientNoSaveDialog
from .systray_close import SystrayCloseDialog
from .waiting_close_user import WaitingCloseUserDialog
from .wrong_version_local import WrongVersionLocalDialog
