

class Equivalences(dict[str, list[str]]):
    def __init__(self):
        super().__init__()
        self._by_port = dict[str, str]()
    
    def __setitem__(self, key: str, value: list[str]):
        for port_name in value:
            self._by_port[port_name] = key
        super().__setitem__(key, value)
    
    def alias(self, port_name: str) -> str:
        '''return the alias of the port if it exists,
        otherwise return directly `port_name` for convenience'''
        alias = self._by_port.get(port_name)
        if alias is not None:
            return alias
        return port_name
    
    def first(self, alias: str, present_ports: set[str]) -> str | None:
        '''return the first present port for alias if it exists,
        otherwise return None'''
        if alias in self:
            for port_name in self[alias]:
                if port_name in present_ports:
                    return port_name

    
