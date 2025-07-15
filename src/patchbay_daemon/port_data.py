
from typing import Optional


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
        

class PortDataList(list[PortData]):
    def __init__(self):
        super().__init__()
        self._name_d = dict[str, PortData]()
        self._uuid_d = dict[int, PortData]()
    
    def append(self, port_data: PortData):
        self._name_d[port_data.name] = port_data
        self._uuid_d[port_data.uuid] = port_data
        super().append(port_data)
        
    def remove(self, port_data: PortData):
        self._name_d.pop(port_data.name)
        self._uuid_d.pop(port_data.uuid)
        super().remove(port_data)

    def clear(self):
        self._name_d.clear()
        self._uuid_d.clear()
        super().clear()

    def remove_from_name(self, name: str):
        port_data = self._name_d.get(name)
        if port_data is None:
            return
        self.remove(port_data)

    def rename(self, old: str, new: str):
        port_data = self._name_d.get(old)
        if port_data is None:
            return
        port_data.name = new
        self._name_d[new] = self._name_d.pop(old)
        
    def from_name(self, name: str) -> Optional[PortData]:
        return self._name_d.get(name)
    
    def from_uuid(self, uuid: int) -> Optional[PortData]:
        return self._uuid_d.get(uuid)