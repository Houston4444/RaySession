
from typing import Callable, Optional, Union
from pathlib import Path
import sys

sys.path.insert(1, str(Path(__file__).parents[1] / 'shared'))


from osclib import Bundle, Message, Server, Address, OscPack, BunServer

def server1_recco(osp: OscPack):
    print('reococ', osp.path, osp.args, osp.types)

class MokoServer(BunServer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.add_nice_methods(
            {'/chili/choup': 'si|sss',
             '/chili/nouri': 'ss*',
             '/chili/zipi': 'sis|f|ss*|i*'},
            self.rocco)

    def rocco(self, osp: OscPack):
        print('rocco', osp.path, osp.args, osp.types)

server1 = MokoServer()

server2 = BunServer()
server2.send(server1.url, '/chili/choup', 'roupi', 'roupin', 'roupette')
server2.send(server1.url, '/chili/choup', 'rouli', 'roulin', 'roulette', 'roue')
server2.send(server1.url, '/chili/choup', 'rouxi', 14)
server2.send(server1.url, '/chili/nouri')
server2.send(server1.url, '/chili/nouri', 'slip', 'garini')
server2.send(server1.url, '/chili/nouri', 'culo', 'garou', 87)
server2.send(server1.url, '/chili/zipi', 'moka', 84, 12)
server2.send(server1.url, '/chili/zipi', 0.12, 4.25)
server2.send(server1.url, '/chili/zipi')
server2.send(server1.url, '/chili/zipi', 'fili', 'foulu', 'faoll', 'misiin')
server2.send(server1.url, '/chili/zipi', 'mroa', 1984, 'rouxa')
server2.send(server1.url, '/chili/zipi', 0.12)
server2.send(server1.url, '/chili/zipi', 75, 95, 12, 45, 99, 13)

for i in range(24):
    server1.recv(10)