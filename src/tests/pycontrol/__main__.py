from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).parents[2] / 'shared'))

from osclib import BunServer, OscPack
import osc_paths.ray.server as sv

import server
import sender

voula = sender.send_and_wait('/ray/session/get_notes')
print(f'{voula=}')
# print(sv.__dict__)
server_paths = list[str]()

with open(Path(__file__).parents[2] / 'utils' / 'osc_paths' / 'all_paths') as f:
    all_paths = f.read()


class PrePath:
    def __init__(self):
        self.types = ''
        self.doc = ''


paths_dict = dict[str, PrePath]()

last_pre_path: PrePath | None = None

for line in all_paths.splitlines():
    if line.startswith('/'):
        cur_path, _, types = line.partition(' ')
        last_pre_path = PrePath()
        last_pre_path.types = types
        paths_dict[cur_path] = last_pre_path
    elif last_pre_path is not None:
        last_pre_path.doc += line.strip() + '\n'

for key, pre_path in paths_dict.items():
    if key.startswith('/ray/server/'):
        # print('kee', key)
        # print(value)
        # func_name = key.rpartition('/')[2]
        func_name = key[12:]
        if '/' in func_name:
            continue
        ts = list[str]()
        if pre_path.types:
            for i, t in enumerate(pre_path.types):
                match t:
                    case 's':
                        ts.append(f'arg{i+1}: str')
                    case 'i':
                        ts.append(f'arg{i+1}: int')
                    case 'f':
                        ts.append(f'arg{i+1}: float')
                
        args_str = ', '.join(ts)
        ret_str = ''
        match func_name.partition('_')[0]:
            case 'has':
                ret_str = ' -> bool'
            case 'get':
                ret_str = ' -> str'
            case 'list':
                ret_str = ' -> list[str]'
        
        print(f'def {func_name}({args_str}){ret_str}:')
        if pre_path.doc:
            print(f'""""{pre_path.doc[:-1]}"""')
        # print(f"    return sender.send_and_wait('{key}', *args)")
        print('    ...')
        print('')
        
def choupi(tata: str):
    print(f'appz {tata} zppa')

def create_function(osc_path: str):
    return lambda *args: sender.send_and_wait(osc_path, *args)

for pt in paths_dict:
    if pt.startswith('/ray/session/'):
        print('prpr', pt, pt.rpartition('/')[2])
        setattr(server, pt.rpartition('/')[2],
                create_function(pt))

print('nikija', pt)
toutout = server.save_as_template('Mounika')
print(f'{toutout=}')

# for key, value in sv.__dict__.items():
#     # print('k', key, 'vv', value)
#     if isinstance(value, str) and value.startswith('/ray/server/'):
#         # print(value)
#         server_paths.append(value)
#         print(key)
# # print(sv.__dict__)



# for server_path in server_paths:
#     path_name = server_path.rpartition('/')[2]
#     # print(f'def {path_name}(*args): ...')

