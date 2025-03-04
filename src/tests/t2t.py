
from typing import Optional
from pathlib import Path
from collections import defaultdict
import sys

sys.path.insert(1, str(Path(__file__).parents[1] / 'shared'))

def types_to_types(input: str) -> tuple[Optional[str], ...]:
    output = set[Optional[str]]()
    for types in input.split('|'):
        if '*' in types:
            output.add(None)
        else:
            output.add(types)
        
    return tuple(output)

def types_validator(input_types: str, avl_types_full: str) -> bool:
    avl_typess = set(avl_types_full.split('|'))
    if input_types in avl_typess:
        return True
    if '.*' in avl_typess or '*' in avl_typess:
        return True
    
    for avl_types in avl_typess:
        if not ('*' in avl_types or '.' in avl_types):
            continue

        wildcard = ''
        mt = ''

        # print(' nir', avl_types)
        for i in range(len(avl_types)):
            mt = avl_types[i]
            if i + 1 < len(avl_types) and avl_types[i+1] == '*':
                if mt in ('', '.'):
                    return True
                wildcard = mt
                
            else:
                wildcard = ''

            # print('  x', f'i={i} avl_types[{i}]={avl_types[i]} mt={mt} wild={wildcard}')

            if wildcard:
                j = i
                compat = True
                while j < len(input_types):
                    if input_types[j] != wildcard:
                        compat = False
                        break
                    j += 1
                
                if compat:
                    return True
                else:
                    break
            
            if i >= len(input_types):
                break
            
            if mt == '.':
                continue
            
            if input_types[i] != mt:
                break
        else:
            # input_types is compatible with this avl_types
            return True
    
    return False

chi = [
    ('s', 's*'),
    ('sisi', 'ss*'),
    ('', 'ss*'),
    ('', 's*'),
    ('i', 'i|s'),
    ('i', 'ii*'),
    ('sssss', 's*'),
    ('sssss', 'ss*'),
    ('sss', 'sssi*'),
    ('sss', 'ss.*'),
    ('sss', 'sss.*'),
    ('s', '..*'),
    ('i', '.'),
    ('ssis', '|ss|ssis*|sss*'),
    ('ssis', 'ssis*'),
    ('ssssis', 'ss*')
]
# for inp, av in chi:
#     # types_validator(inp, av)
#     print('a', f"'{inp}'", f"'{av}'", types_validator(inp, av))
# chichi = 's*'
# chacha = 's|ssi'
# zouzou = '|si'

# for zou in chichi, chacha, zouzou:
#     print('hou', zou, types_to_types(zou))
if True:
    src_dir = Path(__file__).parents[1]
    daemon_file = src_dir / 'daemon' / 'osc_server_thread.py'

    with open(daemon_file, 'r') as f:
        contents = f.read()

    path_types = defaultdict[str, set[str]](set)

    # read_ = 0
    # for line in contents.splitlines():
    #     line = line.strip()
    #     if line == "self._SIMPLE_OSC_PATHS = {":
    #         read_ = 1
    #         continue
        
    #     elif line == "self._STRINGS_OSC_PATHS = {":
    #         read_ = 2
    #         continue
        
    #     if read_ == 1:
    #         if line == '}':
    #             read_ = 0
    #             continue
    #         path_types_str = line[1:-3]
    #         path, _, types = path_types_str.partition(", '")
    #         path_types[path].add(types)
        
    #     elif read_ == 2:
    #         if line == '}':
    #             break
    #         line = line[:-1]
    #         path, _, str_num = line.partition(': ')
    #         types = 's*'
    #         match str_num:
    #             case '1':
    #                 types = 'ss*'
    #             case '2':
    #                 types = 'sss*'

    #         path_types[path].add(types)

    for line in contents.splitlines():
        if not line.strip().startswith('@osp_method('):
            continue
    
        path_and_types = line.partition('(')[2].partition(')')[0]
        const_path, _, bigtype = path_and_types.partition(',')
        # print(const_path)
        # first = const_path.partition('.')[0]
        # prefix = ''
        # match first:
        #     case 'osc_paths':
        #         prefix = '/'
        #     case 'nsm':
        #         prefix = '/nsm/'
        #     case 'r':
        #         prefix = '/ray/'
        #     case 'rg':
        #         prefix = '/ray/gui/'
        #     case _:
        #         print('nonnonon pas bon', const_path)
        
        # split_path = const_path.split('.')
        # split_path[-1] = split_path[-1].lower()
        
        bigtype = bigtype.strip()
        if bigtype == 'None':
            type_ = '*'
        else:
            type_ = bigtype[1:-1]
            
        # print(prefix + '/'.join(split_path[1:]), f"'{type_}'")
        # print(f"{const_path}: '{type_}',")
        path_types[const_path].add(type_)
    
    func_names = dict[str, str]()
    session_sign = daemon_file.parent / 'session_signaled.py'
    with open(session_sign, 'r') as f:
        contents = f.read()
    
    session_sign_funcs = set[str]()
    for line in contents.splitlines():
        if line.strip().startswith('def '):
            session_sign_funcs.add(line.strip().partition('(')[0][4:])
    
    direct_links = list[str]()
    checkers = list[str]()

    for path, types_set in path_types.items():
        full_types = '|'.join(types_set)
        
        split_path = path.split('.')
        match split_path[0]:
            case 'osc_paths':
                split_path[0] = ''
            case 'r':
                split_path[0] = '_ray'
            case 'nsm':
                split_path[0] = '_nsm'
        split_path[-1] = split_path[-1].lower()
        func_name = '_'.join(split_path)
        func_names[func_name] = full_types
        
        if not path.startswith('r.'):
            continue
        
        out_line = f"{path}:\n    ('{full_types}', self.{func_name}),"
        if func_name in session_sign_funcs:
            checkers.append(out_line)
        else:
            direct_links.append(out_line)
        # print(f"{path}:\n    ('{full_types}', self.{func_name}),")
    
    print('CHECKERS')
    print('\n'.join(checkers))
    print('DIRECT_LINKS')
    print('\n'.join(direct_links))
    print('')
    
    
    for func_name, full_types in func_names.items():
        if func_name.startswith('_nsm_'):
            continue
        followed = func_name in session_sign_funcs
        out_type = ' -> bool' if followed else ''
        print(f'def {func_name}(self, osp: OscPack){out_type}:')
        if full_types:
            print(f'    # types: {full_types}')
        if followed:
            print(f'    return True')
        else:
            print(f'    ...')
        print(f'')

        
        
        