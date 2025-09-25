import re
import logging
from typing import Optional, TypeVar, Type

from ruamel.yaml.comments import CommentedSeq, CommentedMap, Comment, LineCol

from .bases import ConnectionStr, ConnectionPattern

_logger = logging.getLogger(__name__)
file_path = ''
'Contains the path of the yaml patch file, only for logging.'

T = TypeVar('T')

def _err_reading_yaml(
        el: CommentedMap | CommentedSeq,
        key: str | int, msg: str):
    '''log a warning because something in the yaml file was not
    properly written. It retrieves the line where the error is.
    
    If `el` is a CommentedMap (dict), key must be a str, else if
    `el` is a CommentedSeq (list), key is an int (the index in the list)'''
    if not isinstance(el.lc, LineCol):
        return

    if isinstance(el, CommentedMap):
        linecol = el.lc.key(key)
    elif isinstance(el, CommentedSeq):
        linecol = el.lc.item(key)
    else:
        return
        
    if (not isinstance(linecol, tuple)
            or not linecol):
        _logger.error(
            f"Error in error report with key {key}:{linecol},{type(linecol)}")
        return
    
    _logger.warning(f'File {file_path},\n\tLine {linecol[0]+1}: {msg}')

def _type_to_str_(wanted_type: type) -> str:
    if wanted_type is list:
        return 'list'
    if wanted_type is dict:
        return 'dict/map'
    if wanted_type is str:
        return 'string'
    return ''

def _type_to_str(wanted_type: type | tuple[type, ...]) -> str:
    if isinstance(wanted_type, tuple):
        type_strs = [_type_to_str_(t) for t in wanted_type]
        match len(type_strs):
            case 0:
                return ''
            case 1:
                return type_strs[0]
            case 2:
                return ' or '.join(type_strs)
            case _:
                return ', '.join(type_strs[:-1]) + ' or ' + type_strs[-1]
    
    return _type_to_str_(wanted_type)

def log_wrong_type_in_map(
        map: CommentedMap, key: str, wanted_type: type | tuple[type, ...]):
    _err_reading_yaml(
        map, key, f'"{key}" must be a {_type_to_str(wanted_type)}')

def log_wrong_type_in_seq(
        el : CommentedSeq, index: int, name: str,
        wanted_type: type | tuple[type, ...]):
    _err_reading_yaml(
        el, index, f'{name} must be a {_type_to_str(wanted_type)}')

def item_at(map: CommentedMap, key: str, wanted_type: Type[T]) -> T | None:
    item = map.get(key)
    if item is None:
        return

    if isinstance(item, wanted_type):
        return item
    log_wrong_type_in_map(map, key, wanted_type)

def load_conns_from_yaml(
        yaml_list: CommentedSeq, conns: set[ConnectionStr],
        patterns: list[ConnectionPattern]):
    for i, conn_d in enumerate(yaml_list):
        if not isinstance(conn_d, CommentedMap):
            _err_reading_yaml(
                yaml_list, i, 'connection is not a dict/map')            
            continue

        port_from = conn_d.get('from')
        port_to = conn_d.get('to')
        from_pattern = conn_d.get('from_pattern')
        to_pattern = conn_d.get('to_pattern')
        from_patt: Optional[re.Pattern] = None
        to_patt: Optional[re.Pattern] = None
        incomplete = False
        
        if isinstance(from_pattern, str):
            try:
                from_patt = re.compile(from_pattern)
            except re.error as e:
                _err_reading_yaml(
                    conn_d, 'from_pattern',
                    f"Incorrect pattern '{from_pattern}', ignored.\n\t{e}")
                continue

            if isinstance(to_pattern, str):
                try:
                    to_patt = re.compile(to_pattern)
                except re.error as e:
                    _err_reading_yaml(
                        conn_d, 'to_pattern',
                        f"Incorrect pattern '{to_pattern}', ignored.\n\t{e}")
                    continue
                
                patterns.append((from_patt, to_patt))

            elif isinstance(port_to, str):
                patterns.append((from_patt, port_to))
            else:
                incomplete = True

        elif isinstance(to_pattern, str):
            try:
                to_patt = re.compile(to_pattern)
            except re.error as e:
                _err_reading_yaml(
                    conn_d, 'to_pattern',
                    f"Incorrect pattern '{to_pattern}', ignored.\n\t{e}")
                continue
            
            if isinstance(port_from, str):
                patterns.append((port_from, to_patt))
            else:
                incomplete = True
        
        elif isinstance(port_from, str) and isinstance(port_to, str):
            conns.add((port_from, port_to))

        else:
            incomplete = True
        
        if incomplete:
            _err_reading_yaml(
                yaml_list, i,
                'Connection incomplete or not correct')

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

def load_connect_domain(
        yaml_list: CommentedSeq,
        cdomain: list[ConnectionPattern]):
    for i, el in enumerate(yaml_list):
        if not isinstance(el, CommentedMap):
            _err_reading_yaml(
                yaml_list, i,
                'connect_domain is not a dict/map.')
            continue
        
        port_from = el.get('from')
        port_to = el.get('to')
        from_pattern = el.get('from_pattern')
        to_pattern = el.get('to_pattern')
    
        if isinstance(from_pattern, str):
            try:
                from_patt = re.compile(from_pattern)
            except re.error as e:
                _err_reading_yaml(
                    el, 'from_pattern',
                    f"Incorrect pattern '{from_pattern}', ignored.\n\t{e}")
                continue
        
        elif isinstance(port_from, str):
            from_patt = port_from
        else:
            from_patt = re.compile(r'.*')

        if isinstance(to_pattern, str):
            try:
                to_patt = re.compile(to_pattern)
            except re.error as e:
                _err_reading_yaml(
                    el, 'to_pattern',
                    f"Incorrect pattern '{from_pattern}', ignored.\n\t{e}")
                continue
        
        elif isinstance(port_to, str):
            to_patt = port_to
        else:
            to_patt = re.compile(r'.*')
        
        cdomain.append((from_patt, to_patt))

def replace_key_comment_with(map: CommentedMap, key: str, comment: str):
    # Pfff, boring to find this !
    if isinstance(map.ca, Comment):
        if key in map.ca.items:
            map.ca.items[key][3] =  None
    map.yaml_set_comment_before_after_key(key, after=comment)

def add_empty_lines(input_str: str) -> str:
    '''add empty lines in full yaml str before some main keys.'''
    # Methods to achieve this from ruamel directly seems to not be reliable,
    # (often, set comment does not remove the existing comment, and we don't
    # want here to add empty line if it already exists
    out_lines = list[str]()
    last_is_empty = False
    for line in input_str.splitlines():
        if line.startswith(
                ('scenarios:', 'connections:', 'forbidden_connections:',
                 'graph:', 'nsm_brothers:')):
            if not last_is_empty:
                out_lines.append('')

        out_lines.append(line)
        last_is_empty = bool(line == '')

    return '\n'.join(out_lines)

