from pathlib import Path

all_paths_path = Path(__file__).parents[1] / 'osc_paths' / 'all_paths'
ost_path = Path(__file__).parents[2] / 'daemon' / 'osc_server_thread.py'

with open(all_paths_path, 'r') as f:
    contents = f.read()

with open(ost_path, 'r') as f:
    ost_contents = f.read()

out_lines = list[str]()

def check_types(types_: str) -> bool:
    for t in types_:
        if t not in 'sifb.*|':
            return False
    return True

def find_types(search_: str) -> str | None:
    for ost_line in ost_contents.splitlines():
        if search_ in ost_line:
            ost_line_strip = ost_line.strip()
            if (ost_line_strip.startswith(search_ + ':')
                    and ost_line_strip.endswith(',')):
                o, _, guil_types = ost_line_strip[:-1].partition(': ')
                return guil_types[1:-1]
            
            if ost_line_strip.startswith(('@directos(', '@validator(')):
                if not ost_line_strip.endswith(')'):
                    print('--  Attnenntion !!! ---')
                    print(ost_line_strip)
                    return None

                hop = ost_line_strip.partition('(')[2][:-1]
                if hop.startswith(search_ + ', '):
                    guil_types = hop.split(', ')[1]
                    return guil_types[1:-1]

for line in contents.splitlines():
    if not line.startswith('/'):
        out_lines.append(line)
        continue

    osc_path, _, pre_types_ = line.partition(' ')
    if osc_path.startswith('/ray/'):
        s_min = osc_path[5:].replace('/', '.')
        beg, _, end = s_min.rpartition('.')
        search_ = f'r.{beg}.{end.upper()}'
        types_ = find_types(search_)

        
        if pre_types_ and types_ is not None and pre_types_ != types_:
            print('-Attnenntion chg de types')
            print(osc_path, pre_types_, '->', types_)
        
        if types_ is None:
            out_lines.append(line)
            if not osc_path.startswith(('/ray/gui/', '/ray/patchbay/',
                                        '/ray/control/', '/ray/monitor/')):
                print('rien trouvé pour:')
                print(osc_path)
        elif types_ == '':
            out_lines.append(osc_path)
        elif not check_types(types_):
            out_lines.append(line)
            print('--- Attnenntion types foireux')
            print(osc_path, types_)
        else:
            out_lines.append(f'{osc_path} {types_}')
    else:
        out_lines.append(line)

print('')
print('')
print('\n'.join(out_lines))

with open(all_paths_path, 'w') as f:
    f.write('\n'.join(out_lines))
        
                    