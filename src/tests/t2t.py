
from typing import Optional
from pathlib import Path

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
for inp, av in chi:
    # types_validator(inp, av)
    print('a', f"'{inp}'", f"'{av}'", types_validator(inp, av))
# chichi = 's*'
# chacha = 's|ssi'
# zouzou = '|si'

# for zou in chichi, chacha, zouzou:
#     print('hou', zou, types_to_types(zou))
if False:
    src_dir = Path(__file__).parents[1]
    daemon_file = src_dir / 'daemon' / 'osc_server_thread.py'

    with open(daemon_file, 'r') as f:
        contents = f.read()

    path_types = dict[str, set[str]]()

    for line in contents.splitlines():
        if line.strip().startswith('@osp_method('):
            path_and_types = line.partition('(')[2].partition(')')[0]
            const_path, _, bigtype = path_and_types.partition(',')
            # print(const_path)
            first = const_path.partition('.')[0]
            prefix = ''
            match first:
                case 'osc_paths':
                    prefix = '/'
                case 'nsm':
                    prefix = '/nsm/'
                case 'r':
                    prefix = '/ray/'
                case 'rg':
                    prefix = '/ray/gui/'
                case _:
                    print('nonnonon pas bon', const_path)
            
            split_path = const_path.split('.')
            split_path[-1] = split_path[-1].lower()
            
            bigtype = bigtype.strip()
            if bigtype == 'None':
                type_ = '.*'
            else:
                type_ = bigtype[1:-1]
                
            print(prefix + '/'.join(split_path[1:]), f"'{type_}'")
        
        
        
        