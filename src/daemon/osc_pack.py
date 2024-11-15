from dataclasses import dataclass

try:
    import liblo
except:
    import pyliblo3 as liblo


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
