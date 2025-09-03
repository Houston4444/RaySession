import re

from patshared import PortMode

from .bases import ConnectionStr, ConnectionPattern, PortData

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
