import re
import logging
from typing import Optional

from .bases import (
    ConnectionStr, ConnectionPattern, PatternOrName, PriorityConnection, PriorityConnElement)

_logger = logging.getLogger(__name__)


def load_conns_from_yaml(
        yaml_list: list, conns: set[ConnectionStr],
        patterns: list[ConnectionPattern]):
    for conn_d in yaml_list:
        if not isinstance(conn_d, dict):
            continue
        
        port_from = conn_d.get('from')
        port_to = conn_d.get('to')
        from_pattern = conn_d.get('from_pattern')
        to_pattern = conn_d.get('to_pattern')
        from_patt: Optional[re.Pattern] = None
        to_patt: Optional[re.Pattern] = None
        
        if isinstance(from_pattern, str):
            try:
                from_patt = re.compile(from_pattern)
            except re.error as e:
                _logger.warning(
                    f"Incorrect from_pattern '{from_pattern}', Ignored. " + str(e))
                continue

            if isinstance(to_pattern, str):
                try:
                    to_patt = re.compile(to_pattern)
                except re.error as e:
                    _logger.warning(
                        f"Incorrect to_pattern '{to_pattern}', Ignored. " + str(e))
                    continue
                
                patterns.append((from_patt, to_patt))

            elif isinstance(port_to, str):
                patterns.append((from_patt, port_to))
            else:
                _logger.warning(
                    f'incorrect pattern connection '
                    f'with "{conn_d}"')

        elif isinstance(to_pattern, str):
            try:
                to_patt = re.compile(to_pattern)
            except re.error as e:
                _logger.warning(
                    f"Incorrect to_pattern, Ignored.\n" + str(e))
                continue
            
            if isinstance(port_from, str):
                patterns.append((port_from, to_patt))
            else:
                _logger.warning(
                    f'incorrect pattern connection '
                    f'with "{conn_d}"')
        
        elif isinstance(port_from, str) and isinstance(port_to, str):
            conns.add((port_from, port_to))

        else:
            _logger.warning(
                f"{conn_d} is incomplete or not correct.")
            continue

def patterns_to_dict(patt: list[ConnectionPattern]) -> list[dict]:
    patterns = list[dict]()
    for from_, to_ in patt:
        pattern = {}
        if isinstance(from_, re.Pattern):
            pattern['from_pattern'] = from_.pattern
        else:
            pattern['from'] = from_
        
        if isinstance(to_, re.Pattern):
            pattern['to_pattern'] = to_.pattern
        else:
            pattern['to'] = to_
        patterns.append(pattern)
    return patterns

def _read_prio(
        I: str, output: bool, patt, port) \
            -> PatternOrName | list[PatternOrName] | None:
    if output:
        port_key = 'from'
        patt_key = 'from_pattern'
    else:
        port_key = 'to'
        patt_key = 'to_pattern'

    if patt is not None:
        if not isinstance(patt, str):
            _logger.warning(
                f'{I} "{patt_key}" must be a str')
            return

        if port is not None:
            _logger.warning(
                f'{I} use of "{port_key}" and "{patt_key}"')
            return
        
        try:
            ret_ = re.compile(patt)
        except:
            _logger.warning(f'{I} invalid "from_pattern".')
            return

    elif port is not None:
        if isinstance(port, str):
            ret_ = port
        elif isinstance(port, list):
            ret_ = list[str | re.Pattern[str]]()
            for el in port:
                if isinstance(el, str):
                    ret_.append(el)
                elif isinstance(el, dict):
                    patt = el.get('pattern')
                    if not isinstance(patt, str):
                        _logger.warning(
                            f'{I} list element can be a dict '
                            f'only if it contains "pattern"')
                        return
                    
                    try:
                        ret_.append(re.compile(patt))
                    except:
                        _logger.warning(f'{I} invalid pattern: {patt}')
                        return
                else:
                    _logger.warning(
                        f'{I} Unknown element in "{port_key}" list.')
                    return
        else:
            _logger.warning(
                f'{I} "{port_key}" unrecognized format.')
            return
    
    else:
        _logger.warning(f'{I} "{port_key}" section missing.')
        return
    
    return ret_

def priority_connection_from_dict(prio_dict) -> Optional[PriorityConnection]:
    I = f'priority_connection ignored in {prio_dict}.\n '
    if not isinstance(prio_dict, dict):
        _logger.warning(' is not a dict.')
        return

    from_ = _read_prio(
        I, True, prio_dict.get('from_pattern'), prio_dict.get('from'))
    if from_ is None:
        return
    
    to_ = _read_prio(
        I, False, prio_dict.get('to_pattern'), prio_dict.get('to'))
    if to_ is None:
        return
    
    if isinstance(from_, (str, re.Pattern)):
        if isinstance(to_, list):
            return (from_, to_)
    elif isinstance(to_, (str, re.Pattern)):
        return (from_, to_)
    
            
    
    