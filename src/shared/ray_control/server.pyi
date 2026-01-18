from typing import overload
import osc_paths.ray as r

def _osc(path: str):...


@_osc(r.server.ABORT_COPY)
def abort_copy() -> bool:
    ...

@_osc(r.server.ABORT_PARRALLEL_COPY)
def abort_parrallel_copy(arg_1: int) -> bool:
    ...

@_osc(r.server.ABORT_SNAPSHOT)
def abort_snapshot() -> bool:
    ...

@_osc(r.server.ASK_FOR_PATCHBAY)
def ask_for_patchbay(arg_1: str) -> bool:
    ...

@_osc(r.server.PATCHBAY_DAEMON_READY)
def patchbay_daemon_ready() -> bool:
    ...

@_osc(r.server.CHANGE_ROOT)
def change_root(arg_1: str) -> bool:
    ...

@_osc(r.server.CLEAR_CLIENT_TEMPLATES_DATABASE)
def clear_client_templates_database() -> bool:
    ...

@_osc(r.server.CONTROLLER_ANNOUNCE)
def controller_announce(arg_1: int) -> bool:
    ...

@_osc(r.server.CONTROLLER_DISANNOUNCE)
def controller_disannounce() -> bool:
    ...

@_osc(r.server.EXOTIC_ACTION)
def exotic_action(arg_1: str) -> bool:
    ...

@_osc(r.server.GET_SESSION_PREVIEW)
def get_session_preview(arg_1: str) -> str:
    ...

@_osc(r.server.GUI_ANNOUNCE)
def gui_announce(arg_1: str, arg_2: int, arg_3: str, arg_4: int, arg_5: int, arg_6: str) -> bool:
    ...

@_osc(r.server.GUI_DISANNOUNCE)
def gui_disannounce() -> bool:
    ...

@_osc(r.server.HAS_OPTION)
def has_option(arg_1: str) -> bool:
    ...

@_osc(r.server.HIDE_SCRIPT_INFO)
def hide_script_info() -> bool:
    ...

@_osc(r.server.LIST_FACTORY_CLIENT_TEMPLATES)
def list_factory_client_templates(*args: str) -> list[str]:
    ...

@_osc(r.server.LIST_PATH)
def list_path() -> list[str]:
    ...

@_osc(r.server.LIST_SESSION_TEMPLATES)
def list_session_templates() -> list[str]:
    ...

@_osc(r.server.LIST_SESSIONS)
@overload
def list_sessions() -> list[str]:
    ...
@overload
def list_sessions(arg_1: int) -> list[str]:
    ...

@_osc(r.server.LIST_USER_CLIENT_TEMPLATES)
def list_user_client_templates(*args: str) -> list[str]:
    ...

@_osc(r.server.MONITOR_ANNOUNCE)
def monitor_announce() -> bool:
    ...

@_osc(r.server.MONITOR_QUIT)
def monitor_quit() -> bool:
    ...

@_osc(r.server.NEW_SESSION)
@overload
def new_session(arg_1: str) -> bool:
    ...
@overload
def new_session(arg_1: str, arg_2: str) -> bool:
    ...

@_osc(r.server.OPEN_FILE_MANAGER_AT)
def open_file_manager_at(arg_1: str) -> bool:
    ...

@_osc(r.server.OPEN_SESSION)
@overload
def open_session(arg_1: str) -> bool:
    ...
@overload
def open_session(arg_1: str, arg_2: int) -> bool:
    ...
@overload
def open_session(arg_1: str, arg_2: int, arg_3: str) -> bool:
    ...

@_osc(r.server.OPEN_SESSION_OFF)
@overload
def open_session_off(arg_1: str) -> bool:
    ...
@overload
def open_session_off(arg_1: str, arg_2: int) -> bool:
    ...

@_osc(r.server.QUIT)
def quit() -> bool:
    ...

@_osc(r.server.REMOVE_CLIENT_TEMPLATE)
def remove_client_template(arg_1: str) -> bool:
    ...

@_osc(r.server.RENAME_SESSION)
def rename_session(arg_1: str, arg_2: str) -> bool:
    ...

@_osc(r.server.SAVE_SESSION_TEMPLATE)
@overload
def save_session_template(arg_1: str, arg_2: str) -> bool:
    ...
@overload
def save_session_template(arg_1: str, arg_2: str, arg_3: str) -> bool:
    ...

@_osc(r.server.SCRIPT_INFO)
def script_info(arg_1: str) -> bool:
    ...

@_osc(r.server.SCRIPT_USER_ACTION)
def script_user_action(arg_1: str) -> bool:
    ...

@_osc(r.server.SET_NSM_LOCKED)
def set_nsm_locked() -> bool:
    ...

@_osc(r.server.SET_OPTION)
def set_option(arg_1: int) -> bool:
    ...

@_osc(r.server.SET_OPTIONS)
def set_options(arg_1: str, *args: str) -> bool:
    ...

@_osc(r.server.SET_TERMINAL_COMMAND)
def set_terminal_command(arg_1: str) -> bool:
    ...

@_osc(r.server.EXPORT_CUSTOM_NAMES)
def export_custom_names() -> bool:
    ...

@_osc(r.server.IMPORT_PRETTY_NAMES)
def import_pretty_names() -> bool:
    ...

@_osc(r.server.CLEAR_PRETTY_NAMES)
def clear_pretty_names() -> bool:
    ...

@_osc(r.server.AUTO_EXPORT_CUSTOM_NAMES)
def auto_export_custom_names(arg_1: str) -> bool:
    ...

@_osc(r.server.SET_PATCH_KEYWORD)
def set_patch_keyword(arg_1: str) -> bool:
    ...
