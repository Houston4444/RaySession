from typing import Optional
from pathlib import Path
from collections import defaultdict
import sys

sys.path.insert(1, str(Path(__file__).parents[1] / 'shared'))

server_file = Path(__file__).parents[1] / 'daemon' / 'osc_server_thread.py'

with open(server_file, 'r') as f:
    contents = f.read()

reading = False
path_types_d = dict[str, str]()

for line in contents.splitlines():
    line = line.strip()
    if line == "methods_dict = {":
        reading = True
        continue
    
    if reading:
        if line == '}':
            reading = False
            break
        path, _, bigtypes = line.partition(':')
        path_types_d[path] = bigtypes.strip()[0:-1]

for line in contents.splitlines():
    line = line.strip()
    if line.startswith('@validator('):
        string = line.partition('(')[2].partition(')')[0]
        path, _, end = string.partition(', ')
        types = end.partition(', ')[0]
        path_types_d[path] = types

# for path, types in path_types_d.items():
#     print(f"@decosess({path}, {types})")
    
funcs_path = dict[str, str]()
for path in path_types_d.keys():
    if path.startswith('r.'):
        func_name = '_ray_' + path.partition('.')[2].replace('.', '_').lower()
    elif path.startswith('nsm.'):
        func_name = '_nsm_' + path.partition('.')[2].replace('.', '_').lower()

    elif path.startswith('osc_paths.'):
        func_name = '_' + path.partition('.')[2].replace('.', '_').lower()
    else:
        print('trilili', path)
        continue

    funcs_path[func_name] = path

# for func_name, path in funcs_path.items():
#     print(func_name)

signa_file = server_file.parent / 'session_signaled.py'

with open(signa_file, 'r') as f:
    signa_contents = f.read()

out_lines = list[str]()
previous_action = ''

for line in signa_contents.splitlines():
    line_strip = line.strip()
    if line_strip.startswith('def '):
        func_name = line_strip.partition(' ')[2].partition('(')[0]
        if func_name in funcs_path:
            path = funcs_path[func_name]
            if path in path_types_d:
                types = path_types_d[path]
                
                if previous_action:
                    out_lines.append(f"    {previous_action}({path}, {types})")
                else:
                    out_lines.append(f"    @manage({path}, {types})") 
    
    if line_strip in ('@client_action', '@session_operation'):
        previous_action = line_strip
    else:
        previous_action = ''
        out_lines.append(line)
    
# print('\n'.join(out_lines))   
signal_file2 = server_file.parent / 'session_signaled_tmp.py'
with open(signal_file2, 'w') as f:
    f.write('\n'.join(out_lines))