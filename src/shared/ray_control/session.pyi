from typing import overload
import osc_paths.ray as r

def _osc(path: str):...


@_osc(r.session.ABORT)
def abort() -> bool:
    ...

@_osc(r.session.ADD_CLIENT_TEMPLATE)
def add_client_template(arg_1: int, arg_2: str, arg_3: str, arg_4: str) -> str:
    ...

@_osc(r.session.ADD_EXEC)
@overload
def add_exec(arg_1: str, arg_2: int, arg_3: int, arg_4: int, arg_5: str, arg_6: str, arg_7: int) -> str:
    ...
@overload
def add_exec(arg_1: str, *args: str) -> str:
    ...

@_osc(r.session.ADD_EXECUTABLE)
@overload
def add_executable(arg_1: str, arg_2: int, arg_3: int, arg_4: int, arg_5: str, arg_6: str, arg_7: int) -> str:
    ...
@overload
def add_executable(arg_1: str, *args: str) -> str:
    ...

@_osc(r.session.ADD_FACTORY_CLIENT_TEMPLATE)
def add_factory_client_template(arg_1: str, *args: str) -> str:
    ...

@_osc(r.session.ADD_OTHER_SESSION_CLIENT)
def add_other_session_client(arg_1: str, arg_2: str) -> str:
    ...

@_osc(r.session.ADD_USER_CLIENT_TEMPLATE)
def add_user_client_template(arg_1: str, *args: str) -> str:
    ...

@_osc(r.session.CANCEL_CLOSE)
def cancel_close() -> bool:
    ...

@_osc(r.session.CLEAR_CLIENTS)
def clear_clients(*args: str) -> bool:
    ...

@_osc(r.session.CLOSE)
def close() -> bool:
    ...

@_osc(r.session.DUPLICATE)
def duplicate(arg_1: str) -> bool:
    ...

@_osc(r.session.DUPLICATE_ONLY)
def duplicate_only(arg_1: str, arg_2: str, arg_3: str) -> bool:
    ...

@_osc(r.session.GET_NOTES)
def get_notes() -> str:
    ...

@_osc(r.session.GET_SESSION_NAME)
def get_session_name() -> str:
    ...

@_osc(r.session.HIDE_NOTES)
def hide_notes() -> bool:
    ...

@_osc(r.session.LIST_CLIENTS)
def list_clients(*args: str) -> list[str]:
    ...

@_osc(r.session.LIST_SNAPSHOTS)
def list_snapshots() -> list[str]:
    ...

@_osc(r.session.LIST_TRASHED_CLIENTS)
def list_trashed_clients() -> list[str]:
    ...

@_osc(r.session.OPEN_FOLDER)
def open_folder() -> bool:
    ...

@_osc(r.session.OPEN_SNAPSHOT)
def open_snapshot(arg_1: str) -> bool:
    ...

@_osc(r.session.RENAME)
def rename(arg_1: str) -> bool:
    ...

@_osc(r.session.REORDER_CLIENTS)
def reorder_clients(arg_1: str, *args: str) -> bool:
    ...

@_osc(r.session.RUN_STEP)
def run_step(*args: str) -> bool:
    ...

@_osc(r.session.SAVE)
def save() -> bool:
    ...

@_osc(r.session.SAVE_AS_TEMPLATE)
def save_as_template(arg_1: str) -> bool:
    ...

@_osc(r.session.SET_AUTO_SNAPSHOT)
def set_auto_snapshot(arg_1: int) -> bool:
    ...

@_osc(r.session.SET_NOTES)
def set_notes(arg_1: str) -> bool:
    ...

@_osc(r.session.SHOW_NOTES)
def show_notes() -> bool:
    ...

@_osc(r.session.SKIP_WAIT_USER)
def skip_wait_user() -> bool:
    ...

@_osc(r.session.TAKE_SNAPSHOT)
@overload
def take_snapshot(arg_1: str) -> bool:
    ...
@overload
def take_snapshot(arg_1: str, arg_2: int) -> bool:
    ...
