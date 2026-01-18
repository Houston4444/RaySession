from typing import overload
import osc_paths.ray as r

def _osc(path: str):...


@_osc(r.trashed_client.REMOVE_DEFINITELY)
def remove_definitely(client_id: str) -> bool:
    ...

@_osc(r.trashed_client.REMOVE_KEEP_FILES)
def remove_keep_files(client_id: str) -> bool:
    ...

@_osc(r.trashed_client.RESTORE)
def restore(client_id: str) -> bool:
    ...
