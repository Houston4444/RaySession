import re
from typing import TYPE_CHECKING

from patshared import PortMode

from .bases import ConnectionStr, PatternOrName, PortData, PriorityConnection

def str_match(a: PatternOrName, b: str) -> bool:
    if isinstance(a, str):
        return a == b
    return bool(a.match(b))

def priority_connections_startup(
        prio_conns: list[PriorityConnection],
        ports: dict[PortMode, list[PortData]],
        prio_ups: set[ConnectionStr],
        prio_downs: dict[ConnectionStr, ConnectionStr]):
    for from_, to_ in prio_conns:        
        if isinstance(from_, (str, re.Pattern)):
            for outport in ports[PortMode.OUTPUT]:
                if not str_match(from_, outport.name):
                    continue
                
                if TYPE_CHECKING and not isinstance(to_, list):
                    # impossible
                    continue
                
                prio_found = None
                
                for to__ in to_:
                    for inport in ports[PortMode.INPUT]:
                        if not str_match(to__, inport.name):
                            continue
                        
                        conn = (outport.name, inport.name)
                        
                        if prio_found is not None:
                            prio_downs[conn] = prio_found
                        else:
                            prio_ups.add(conn)
                            prio_found = conn
        else:
            if TYPE_CHECKING and isinstance(to_, list):
                # impossible
                continue
            
            for inport in ports[PortMode.INPUT]:
                if not str_match(to_, inport.name):
                    continue
                
                prio_found = None
                
                for from__ in from_:
                    for outport in ports[PortMode.OUTPUT]:
                        if not str_match(from__, outport.name):
                            continue
                        
                        conn = (outport.name, inport.name)
                        
                        if prio_found is not None:
                            prio_downs[conn] = prio_found
                        else:
                            prio_ups.add(conn)
                            prio_found = conn
