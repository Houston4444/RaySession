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
    
    def first(self, alias: str, present_ports: set[str]) -> str:
        '''return the first present port name for `alias` if it exists,
        otherwise return directly `alias` for convenience'''
        if alias in self:
            for port_name in self[alias]:
                if port_name in present_ports:
                    return port_name
        return alias
    
    def corrected(self, name: str, present_ports: set[str]) -> str:
        '''if name is an alias, return first port name of its equivalence,
        or `name` if no port is present.
        
        If `name` is a port name (it contains ':'),
        return the first present port name for alias of `port_name`, or 
        `port_name` if it has no alias.'''
        if ':' in name:
            # port_name is not an alias
            return self.first(self.alias(name), present_ports)
        return self.first(name, present_ports)

