from typing import TYPE_CHECKING

from patshared import PortMode

from .bases import ConnectionStr

if TYPE_CHECKING:
    from .scenarios_mng import ScenariosManager


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


def replace_aliases_on_place(
        mng: 'ScenariosManager', conns: set[ConnectionStr]):
    '''replace in `conns` all aliases (equivalences)
    with their first present port.
    If no port exists, keep the alias'''
    out_port_names = set(
        [p.name for p in mng.patcher.ports[PortMode.OUTPUT]])
    in_port_names = set(
        [p.name for p in mng.patcher.ports[PortMode.INPUT]])
    
    out_conns = set[ConnectionStr]()
    for conn in conns:
        out_conns.add(
            (mng.capture_eqvs.first(conn[0], out_port_names),
                mng.playback_eqvs.first(conn[1], in_port_names)))
    
    conns.clear()
    conns |= out_conns
    
def replace_ports_with_aliases(
        mng: 'ScenariosManager',
        conns: set[ConnectionStr]) -> set[ConnectionStr]:
    '''replace in `conns` port names with their alias if it exists'''
    out_conns = set[ConnectionStr]()
    
    for conn in conns:
        out_conns.add(
            (mng.capture_eqvs.alias(conn[0]),
                mng.playback_eqvs.alias(conn[1])))
    
    return out_conns

def replace_port_name(
        mng: 'ScenariosManager', conns: set[ConnectionStr], alias: str,
        new: str, port_mode: PortMode):
    '''replace in `conns` all port names which have `alias` for alias,
    with `new`. `port_mode` of the port is required.'''
    if port_mode not in (PortMode.OUTPUT, PortMode.INPUT):
        return
    
    out_conns = set[ConnectionStr]()
    process = False
    
    if port_mode is PortMode.OUTPUT:
        for conn in conns:
            if mng.capture_eqvs.alias(conn[0]) == alias:
                process = True
                out_conns.add((new, conn[1]))
            else:
                out_conns.add(conn)
    else:
        for conn in conns:
            if mng.playback_eqvs.alias(conn[1]) == alias:
                process = True
                out_conns.add((conn[0], new))
            else:
                out_conns.add(conn)

    if process:
        conns.clear()
        conns |= out_conns
