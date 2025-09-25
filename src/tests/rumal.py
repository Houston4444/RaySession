import os
from pathlib import Path
from io import StringIO

from ruamel.yaml import YAML
from ruamel.yaml.comments import LineCol, CommentedMap, Comment, CommentedSeq

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

file = Path('/home/houstonlzk5/Ray Sessions/tests/pokpprotl/JACK Connections.patchtest2.yaml')
file2 = file.parent / 'JACK Connections.patchtest.yaml'
yaml = YAML()
with open(file, 'r') as f:
    contents = f.read()

docu: CommentedMap = yaml.load(contents)
for key, value in docu.items():
    # print('kf', key, value)
    empty_line_before_key(docu, key)

string_io = StringIO()
yaml.dump(docu, string_io)
print(transform_after(string_io.getvalue()))

# outi = yaml.dump(docu, file2)
# with open(file2, 'w') as f:
#     f.write(outi)