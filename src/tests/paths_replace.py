from typing import Callable, Optional
from pathlib import Path
import sys
import re

sys.path.insert(1, str(Path(__file__).parents[1] / 'shared'))

print('maieu', str(Path(__file__).parents[1] / 'shared'))
import osc_paths.ray.gui.patchbay as rgp
# import osc_paths.ray as r

full_dict = dict[str, str]()
# print('hhheiin !!!')
src_path = Path(__file__).parents[1]
for key, value in vars(rgp).items():
    if key.startswith('_'):
        continue
    
    # if not isinstance(value, str):
    #     continue

    # print('kke', key, value)
    full_dict[f'"{value}"'] = f'rgp.{key}'
    full_dict[f"'{value}'"] = f'rgp.{key}'
    
canvas_saver = src_path / 'daemon' / 'canvas_saver.py'

with open(canvas_saver, 'r') as f:
    contents = f.read()
    pattern = re.compile('|'.join(
        re.escape(k) for k in full_dict.keys()))
    new_contents = pattern.sub(lambda x : full_dict[x.group()], contents)
    print(new_contents)