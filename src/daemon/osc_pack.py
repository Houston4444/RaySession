from dataclasses import dataclass

import liblo


@dataclass()
class OscPack:
    path: str
    args: list
    types: str
    src_addr: liblo.Address
    
    def reply(self) -> tuple[liblo.Address, str, str]:
        return (self.src_addr, '/reply', self.path)
    
    def error(self) -> tuple[liblo.Address, str, str]:
        return (self.src_addr, '/error', self.path)
