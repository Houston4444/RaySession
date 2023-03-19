
class PortData:
    name: str
    type: int
    flags: int
    uuid: int
    
    def __init__(self, name: str, type: int, flags: int, uuid: int):
        self.name = name
        self.type = type
        self.flags = flags
        self.uuid = uuid