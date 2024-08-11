from dataclasses import dataclass

import liblo


@dataclass()
class OscPack:
    path: str
    args: list
    types: str
    src_addr: liblo.Address