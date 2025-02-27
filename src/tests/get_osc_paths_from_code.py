

# class RayServer:
#     _p = '/ray/server/'
#     QUIT = _p + 'quit'
#     abort_copy = _p  + 'abort_copy'
    

# class Ray:
#     server = RayServer()


# ray = Ray()
# print('choupio', ray.server.QUIT)
from pathlib import Path
import sys

root = Path(__file__)
while root.name != 'RaySession':
    root = root.parent
    if root.name == '/':
        print('Not in a RaySession dir')
        sys.exit(1)

daemon_dir = root / 'src' / 'daemon'
gui_dir = root / 'src' / 'gui'
jackpatch_dir = root / 'src' / 'clients' / 'jackpatch'
paths = set[str]()

file_paths = [p for p in daemon_dir.iterdir()]
file_paths += [p for p in gui_dir.iterdir()]
file_paths += [p for p in jackpatch_dir.iterdir()]

for file_path in file_paths:
    if not file_path.name.endswith('.py'):
        continue
    
    with open(file_path, 'r') as f:
        contents = f.read()
        lines = contents.splitlines()

    for line in lines:
        if '/' not in line:
            continue
        # print(line)
        if "'/" in line:
            paths.add('/' + line.partition("'/")[2].partition("'")[0])
        elif '"/' in line:
            paths.add('/' + line.partition('"/')[2].partition('"')[0])

path_list = sorted(paths)
for path in path_list:
    if path == '/':
        continue
    if path.startswith(('/.', '//', '/ardour_tp/', '/etc/', '/proc/', '/tmp/', '/usr/')):
        continue
    if path.endswith('/'):
        continue
    if '\\' in path or '{' in path:
        continue
    print(path)