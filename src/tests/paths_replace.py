from typing import Callable, Optional
from pathlib import Path
import sys
import re

sys.path.insert(1, str(Path(__file__).parents[1] / 'shared'))

import osc_paths
import osc_paths.ray as r
import osc_paths.ray.gui as rg
import osc_paths.nsm as nsm


subs = {'rg': '/ray/gui/',
        'r': '/ray/',
        'nsm': '/nsm/'}

full_dict = dict[str, str]()
src_path = Path(__file__).parents[1]

all_paths_file = src_path / 'utils' / 'osc_paths' / 'all_paths'

with open(all_paths_file, 'r') as f:
    all_paths = f.read()
    
for osc_path in all_paths.splitlines():
    osc_path = osc_path.strip()
    if not osc_path.startswith('/'):
        continue

    for new, old in subs.items():
        if osc_path.startswith(old):
            follow = osc_path.replace(old, '', 1)
            splitted = follow.split('/')
            splitted[-1] = splitted[-1].upper()
            rep = new + '.' + '.'.join(splitted)
            break
    else:
        splitted = osc_path.split('/')
        splitted[-1] = splitted[-1].upper()
        rep = 'osc_paths' + '.'.join(splitted)

    full_dict[f"'{osc_path}'"] = rep
    full_dict[f'"{osc_path}"'] = rep

# def add_to_dict(module: str, k: str, v: str):
#     if key.startswith('_'):
#         return
    
#     full_dict[f'"{v}"'] = f'{module}.{key}'
#     full_dict[f"'{v}'"] = f'{module}.{key}'

# for key, value in vars(RGP).items():
#     add_to_dict('RGP', key, value)
# for key, value in vars(RP).items():
#     add_to_dict('RP', key, value)
# for key, value in vars(RP).items():
#     add_to_dict('RP', key, value)
#     # if key.startswith('_'):
#     #     continue

#     # full_dict[f'"{value}"'] = f'RP.{key}'
#     # full_dict[f"'{value}'"] = f'RP.{key}'


moduledir = src_path / 'control'

for module in moduledir.iterdir():
    if not module.name.endswith('.py'):
        continue

    with open(module, 'r') as f:
        contents = f.read()
        pattern = re.compile('|'.join(
            re.escape(k) for k in full_dict.keys()))
        new_contents = pattern.sub(lambda x : full_dict[x.group()], contents)
        print(new_contents)

    with open(module, 'w') as f:
        f.write(new_contents)