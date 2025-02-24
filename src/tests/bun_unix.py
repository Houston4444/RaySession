from os import mkdir
from typing import Callable, Optional
from pathlib import Path
import sys

sys.path.insert(1, str(Path(__file__).parents[1] / 'shared'))

from osclib import BunServer, Server, UNIX, Bundle, Message

main_path = Path('/tmp/ouzou')
path_1 = main_path / 'server1'
path_2 = main_path / 'server2'
if path_1.exists():
    path_1.unlink()

if path_2.exists():
    path_2.unlink()
# path_1.mkdir(parents=True, exist_ok=True)
# path_2.mkdir(parents=True, exist_ok=True)
s1_port = str(path_1)
s2_port = str(path_2)


class CustomServer(Server):
    def __init__(self, *args):
        super().__init__(*args)
        
        self.add_method('/mougou', 'ss', self._mougou)
        
    def _mougou(self, path, args, types, src_addr):
        print('oaef', path, args)
        

server_1 = CustomServer(s1_port, UNIX)
server_2 = CustomServer(s2_port, UNIX)

# server_1.start()
# server_2.start()

bundle = Bundle(*[Message('/mougou', 'oupu', f'pfok{i}') for i in range(1000)])

print('senndn')
for i in range(10000):
    print('ii', i)
    server_1.send('osc.unix://localhost:' + s2_port, '/mougou', 'oupu', f'pfok{i}')

while True:
    server_2.recv(10)