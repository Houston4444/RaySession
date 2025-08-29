import re
import logging
from typing import Optional

from .bases import ConnectionStr, ConnectionPattern

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
                    f"Incorrect from_pattern, Ignored. " + str(e))
                continue

            if isinstance(to_pattern, str):
                try:
                    to_patt = re.compile(to_pattern)
                except re.error as e:
                    _logger.warning(
                        f"Incorrect to_pattern, Ignored. " + str(e))
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