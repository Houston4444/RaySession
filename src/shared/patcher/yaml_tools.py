import re
import logging

from .bases import PortMode

_logger = logging.getLogger(__name__)


def load_conns_from_yaml(
        yaml_list: list, conns: set[tuple[str, str]],
        patterns: list[tuple[PortMode, str, str]]):
    for conn_d in yaml_list:
        if not isinstance(conn_d, dict):
            continue
        
        port_from = conn_d.get('from')
        port_to = conn_d.get('to')
        from_patt = conn_d.get('from_pattern')
        to_patt = conn_d.get('to_pattern')
        
        if isinstance(from_patt, str):
            try:
                re.fullmatch(from_patt, '')
            except re.error as e:
                _logger.warning(
                    f"Incorrect from_pattern, Ignored. " + str(e))
                continue

            if isinstance(to_patt, str):
                try:
                    re.fullmatch(to_patt, '')
                except re.error as e:
                    _logger.warning(
                        f"Incorrect to_pattern, Ignored. " + str(e))
                    continue
                
                patterns.append(
                    (PortMode.BOTH, from_patt, to_patt))

            elif isinstance(port_to, str):
                patterns.append(
                    (PortMode.OUTPUT, from_patt, port_to))
            else:
                _logger.warning(
                    f'incorrect pattern connection '
                    f'with "{conn_d}"')

        elif isinstance(to_patt, str):
            try:
                re.fullmatch(to_patt, '')
            except re.error as e:
                _logger.warning(
                    f"Incorrect to_pattern, Ignored.\n" + str(e))
                continue
            
            if isinstance(port_from, str):
                patterns.append(
                    (PortMode.INPUT, port_from, to_patt))
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
