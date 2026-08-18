from typing import overload
import osc_paths.ray as r

def _osc(path: str):...


@_osc(r.client.CHANGE_ADVANCED_PROPERTIES)
def change_advanced_properties(client_id: str, arg_2: str, arg_3: int, arg_4: str, arg_5: int) -> bool:
    ...

@_osc(r.client.CHANGE_ID)
def change_id(client_id: str, arg_2: str) -> bool:
    ...

@_osc(r.client.CHANGE_PREFIX)
@overload
def change_prefix(client_id: str, arg_2: int) -> bool:
    ...
@overload
def change_prefix(client_id: str, arg_2: str) -> bool:
    ...
@overload
def change_prefix(client_id: str, arg_2: int, arg_3: str) -> bool:
    ...
@overload
def change_prefix(client_id: str, arg_2: str, arg_3: str) -> bool:
    ...

@_osc(r.client.FULL_RENAME)
def full_rename(client_id: str, arg_2: str) -> bool:
    ...

@_osc(r.client.SWITCH_ALTERNATIVE)
def switch_alternative(client_id: str, arg_2: str) -> bool:
    ...

@_osc(r.client.GET_CUSTOM_DATA)
def get_custom_data(client_id: str, arg_2: str) -> str:
    ...

@_osc(r.client.GET_DESCRIPTION)
def get_description(client_id: str) -> str:
    ...

@_osc(r.client.GET_PID)
def get_pid(client_id: str) -> str:
    ...

@_osc(r.client.GET_PROPERTIES)
def get_properties(client_id: str) -> str:
    ...

@_osc(r.client.GET_TMP_DATA)
def get_tmp_data(client_id: str, arg_2: str) -> str:
    ...

@_osc(r.client.HIDE_OPTIONAL_GUI)
def hide_optional_gui(client_id: str) -> bool:
    ...

@_osc(r.client.IS_STARTED)
def is_started(client_id: str) -> bool:
    ...

@_osc(r.client.KILL)
def kill(client_id: str) -> bool:
    ...

@_osc(r.client.LIST_FILES)
def list_files(client_id: str) -> list[str]:
    ...

@_osc(r.client.LIST_SNAPSHOTS)
def list_snapshots(client_id: str) -> list[str]:
    ...

@_osc(r.client.OPEN)
def open(client_id: str) -> bool:
    ...

@_osc(r.client.OPEN_SNAPSHOT)
def open_snapshot(client_id: str, arg_2: str) -> bool:
    ...

@_osc(r.client.RESUME)
def resume(client_id: str) -> bool:
    ...

@_osc(r.client.SAVE)
def save(client_id: str) -> bool:
    ...

@_osc(r.client.SAVE_AS_TEMPLATE)
def save_as_template(client_id: str, arg_2: str) -> bool:
    ...

@_osc(r.client.SEND_SIGNAL)
def send_signal(client_id: str, arg_2: int) -> bool:
    ...

@_osc(r.client.SET_CUSTOM_DATA)
def set_custom_data(client_id: str, arg_2: str, arg_3: str) -> bool:
    ...

@_osc(r.client.SET_DESCRIPTION)
def set_description(client_id: str, arg_2: str) -> bool:
    ...

@_osc(r.client.SET_PROPERTIES)
def set_properties(client_id: str, arg_2: str, *args: str) -> bool:
    ...

@_osc(r.client.SET_TMP_DATA)
def set_tmp_data(client_id: str, arg_2: str, arg_3: str) -> bool:
    ...

@_osc(r.client.SHOW_OPTIONAL_GUI)
def show_optional_gui(client_id: str) -> bool:
    ...

@_osc(r.client.START)
def start(client_id: str) -> bool:
    ...

@_osc(r.client.STOP)
def stop(client_id: str) -> bool:
    ...

@_osc(r.client.TRASH)
def trash(client_id: str) -> bool:
    ...

@_osc(r.client.UPDATE_PROPERTIES)
def update_properties(client_id: str, arg_2: int, arg_3: str, arg_4: str, arg_5: str, arg_6: str, arg_7: int, arg_8: str, arg_9: str, arg_10: str, arg_11: str, arg_12: str, arg_13: str, arg_14: int, arg_15: str, arg_16: str, arg_17: str, arg_18: int, arg_19: int) -> bool:
    ...

@_osc(r.client.UPDATE_RAY_HACK_PROPERTIES)
def update_ray_hack_properties(client_id: str, arg_2: str, arg_3: int, arg_4: int, arg_5: int, arg_6: int, arg_7: str, arg_8: int) -> bool:
    ...

@_osc(r.client.UPDATE_RAY_NET_PROPERTIES)
def update_ray_net_properties(client_id: str, arg_2: str, arg_3: str, arg_4: str) -> bool:
    ...
