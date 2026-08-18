import os
from pathlib import Path
from io import StringIO

from ruamel.yaml import YAML
from ruamel.yaml.comments import LineCol, CommentedMap, Comment, CommentedSeq
from ruamel.yaml.tokens import CommentToken

def empty_line_before_key(map: CommentedMap, key: str):
    ele = map.get(key)
    print('OUSPIE', key, ele, type(ele))
    if isinstance(map.ca, Comment):
        if key in map.ca.items:
            print('keyef', key, map.ca.items[key])

    if isinstance(ele, CommentedMap):
        for key in ele:
            if key in ele.ca.items:
                print('', 'ouchpiyef', key, ele.ca.items[key])
    
    elif isinstance(ele, CommentedSeq):
        print('', 'atchouba', ele.ca.items)
        # for i in range(len(ele)):
        #     print('koooe', ele[i], ele.ca.items[i])


            # map.ca.items[key][1] = None
    # map.yaml_set_comment_before_after_key(key, before='\n')

def list_all_comments(map: CommentedMap):
    ...

def replace_key_comment_with(map: CommentedMap, key: str, comment: str):
    # Pfff, boring to find this !
    if isinstance(map.ca, Comment):
        if key in map.ca.items:
            map.ca.items[key][3] =  None
    map.yaml_set_comment_before_after_key(key, after=comment)

def transform_after(yaml_str: str):
    out_lines = list[str]()
    last_is_empty = False
    for line in yaml_str.splitlines():
        if line.startswith(('cle1:', 'cle2:', 'cle3:')):
            if not last_is_empty:
                out_lines.append('')
            out_lines.append(line)

        out_lines.append(line)
        last_is_empty = not bool(line)

    return '\n'.join(out_lines)

# file = Path('/home/houstonlzk5/Ray Sessions/tests/pokpprotl/JACK Connections.patchtest2.yaml')
# file2 = file.parent / 'JACK Connections.patchtest.yaml'
# yaml = YAML()
# with open(file, 'r') as f:
#     contents = f.read()

# docu: CommentedMap = yaml.load(contents)
# for key, value in docu.items():
#     # print('kf', key, value)
#     empty_line_before_key(docu, key)

# string_io = StringIO()
# yaml.dump(docu, string_io)
# print(transform_after(string_io.getvalue()))

# # outi = yaml.dump(docu, file2)
# # with open(file2, 'w') as f:
# #     f.write(outi)

import sys

ORIG = """


# rpoutk RaySIoa


satasse: # Rhho
# TU N'ÉDITES RIEN SINON ÇA VA CHIER POUR TA GUIE
- from: chouchou # mourir pour des idées
  to: slipas
- from: patoch # tu connais Patoch !
  to : patrak 
- from: padock
  # ou canap'
  to : kouskous # atteintnon au mueites
- from: nivilal
  to: mzuilaze
"""

yaml = YAML()
dissa = yaml.load(ORIG)
# dissa = dissa.get('moukas')

if isinstance(dissa, CommentedMap):
    l = dissa.get('satasse')
    if isinstance(l, CommentedSeq):
        new_list = [{'from': 'patoch', 'to': 'patrak'},
                    {'from': 'padock', 'to': 'kouskous'},
                    {'from': 'nivilal', 'to': 'mzuilaze'},
                    {'from': 'chouchou', 'to': 'slipas'}]
        
        # new_list = list[dict]()
        # for conn in l:
        #     if isinstance(conn, dict):
        #         new_list.append(conn)
        
        for i, el in enumerate(new_list.copy()):
            for seq_el in l:
                if seq_el == el:
                    new_list[i] = seq_el
                    break
        
        new_list_idxs = [(conn, i) for i, conn in enumerate(new_list)]
        new_list_idxs = sorted(new_list_idxs, key=lambda x: x[0]['from'])
        
        print('new_list_idxs', new_list_idxs)
        
        ex_items = {}
        if isinstance(l.ca, Comment) and isinstance(l.ca.items, dict):
            ex_items = l.ca.items.copy()
        
        for key, value in ex_items.items():
            print('keek', key, value)
        
        pre_comment = None
        if 0 in ex_items:
            pre_comment = ex_items[0][1]
            ex_items[0][1] = None

        # next_pre_comm = None
        # for key, value in ex_items.items():
        #     print(f'"{key}": {value}')
        #     if not (isinstance(value, list) and len(value) == 4):
        #         continue
            
        #     if next_pre_comm is not None:
        #         if value[1] is None:
        #             value[1] = next_pre_comm
            
        #     next_pre_comm = None
            
        #     if isinstance(value[0], CommentToken):
        #         string = value[0].value
        #         if '\n\n' in string:
        #             print('hopla string', string)
                    
        #             # go = CommentToken(string.partition('\n\n')[0],
        #             #                   start_mark=value[0].start_mark,
        #             #                   end_mark=value[0].end_mark)
        #             kept, _, follow = string.partition('\n\n')
        #             if follow:
        #                 next_pre_comm = CommentToken(
        #                     follow, value[0].start_mark, value[0].end_mark)
        #                 next_pre_comm.reset()
                    
        #             if kept:
        #                 value[0].value = f'{kept}\n'
        #             else:
        #                 value[0] = None
                    
        #     print('keye', key, value)

        l.clear()

        for i, word_idx in enumerate(new_list_idxs):
            conn, orig_idx = word_idx
            l.append(conn)
            
            if orig_idx in ex_items:
                l.ca.items[i] = ex_items[orig_idx]
                
        # if 0 in l.ca.items:
        #     l.ca.items[0][1] = pre_comment
        # else:
        #     l.ca.items[0] = [None, pre_comment, None, None]
        print(l.ca.items)
        if isinstance(dissa.ca, Comment):
            print('zpeof', dissa.ca.items)
            sap = dissa.ca.items.get('satasse')
            if isinstance(sap, list) and len(sap) == 4:
                sap[2] = None
        l.yaml_set_start_comment('La vie est pajaoz')

    yaml.dump(dissa, sys.stdout)