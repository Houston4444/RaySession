import re

from patshared import PortMode

from .bases import ConnectionStr, ConnectionPattern, PatternOrName, PortData


def str_match(a: PatternOrName, b: str) -> bool:
    if isinstance(a, str):
        return a == b
    return bool(a.match(b))

def startup(
        ports: dict[PortMode, list[PortData]],
        conns: set[ConnectionStr],
        patterns: list[ConnectionPattern]):
    '''add to conns all possible connections matching with patterns
    regarding the ports in presence'''
    for from_, to_ in patterns:
        if isinstance(from_, re.Pattern):
            for outport in ports[PortMode.OUTPUT]:
                if not from_.fullmatch(outport.name):
                    continue
                if isinstance(to_, re.Pattern):
                    for inport in ports[PortMode.INPUT]:
                        if to_.fullmatch(inport.name):
                            conns.add((outport.name, inport.name))
                else:
                    for inport in ports[PortMode.INPUT]:
                        if to_ == inport.name:
                            conns.add((outport.name, inport.name))
                            break
        else:
            for outport in ports[PortMode.OUTPUT]:
                if outport.name == from_:
                    if isinstance(to_, re.Pattern):
                        for inport in ports[PortMode.INPUT]:
                            if to_.fullmatch(inport.name):
                                conns.add((outport.name, inport.name))
                    else:
                        for inport in ports[PortMode.INPUT]:
                            if to_ == inport.name:
                                conns.add((outport.name, inport.name))
                                break
                    break

def add_port(
        ports: dict[PortMode, list[PortData]],
        conns_cache: set[ConnectionStr],
        patterns: list[ConnectionPattern],
        port: PortData):
    '''add to conns all possible connections matching with patterns
    and new added port regarding the ports in presence'''
    if port.mode is PortMode.OUTPUT:
        for from_, to_ in patterns:
            if isinstance(from_, re.Pattern):
                if not from_.fullmatch(port.name):
                    continue
            elif from_ != port.name:
                continue
            
            if isinstance(to_, re.Pattern):
                for input_port in ports[PortMode.INPUT]:
                    if to_.fullmatch(input_port.name):
                        conns_cache.add((port.name, input_port.name))
            else:
                for input_port in ports[PortMode.INPUT]:
                    if to_ == input_port.name:
                        conns_cache.add((port.name, input_port.name))
                        break

    elif port.mode is PortMode.INPUT:
        for from_, to_ in patterns:
            if isinstance(to_, re.Pattern):
                if not to_.fullmatch(port.name):
                    continue
            elif to_ != port.name:
                continue

            if isinstance(from_, re.Pattern):
                for output_port in ports[PortMode.OUTPUT]:
                    if from_.fullmatch(output_port.name):
                        conns_cache.add((output_port.name, port.name))
            else:
                for output_port in ports[PortMode.OUTPUT]:
                    if from_ == output_port.name:
                        conns_cache.add((output_port.name, port.name))
                        break

def to_yaml_connection_dicts(
        patterns: list[ConnectionPattern],
        conns: set[ConnectionStr]) -> list[dict[str, str]]:
    '''take patterns and conns, and return a list of dicts
    usable in yaml file.
    Connections with patterns are returned on top, then connections
    are sorted, note that connections already matching with a pattern
    are removed.'''
    pats = list[dict]()
    
    # write first all ConnectionPatterns
    for from_, to_ in patterns:
        d = {}
        if isinstance(from_, re.Pattern):
            d['from_pattern'] = from_.pattern
        else:
            d['from'] = from_
        if isinstance(to_, re.Pattern):
            d['to_pattern'] = to_.pattern
        else:
            d['to'] = to_
        pats.append(d)

    conns_list = list[ConnectionStr]()

    # write connections   
    for port_from, port_to in conns:
        for from_, to_ in patterns:
            if str_match(from_, port_from) and str_match(to_, port_to):
                # connection match with a ConnectionPattern,
                # do not save it.
                break
        else:
            conns_list.append((port_from, port_to))

    conns_list.sort()
    return pats + [{'from': c[0], 'to': c[1]} for c in conns_list]

def domain_to_yaml(
        domain: list[tuple[PatternOrName, PatternOrName]]) -> \
            list[dict[str, str]]:
    out_list = list[dict]()
    for from_, to_ in domain:
        out_dict = dict[str, str]()
        if isinstance(from_, re.Pattern):
            if from_.pattern != '.*':
                out_dict['from_pattern'] = from_.pattern
        else:
            out_dict['from'] = from_
        
        if isinstance(to_, re.Pattern):
            if to_.pattern != '.*':
                out_dict['to_pattern'] = to_.pattern
        else:
            out_dict['to'] = to_
            
        out_list.append(out_dict)

    return out_list

def connection_in_domain(domain: list[tuple[PatternOrName, PatternOrName]],
                         conn: ConnectionStr) -> bool:
    port_from, port_to = conn
    
    for from_, to_ in domain:
        if (str_match(from_, port_from)
                and str_match(to_, port_to)):
            return True
    return False