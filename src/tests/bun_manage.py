import sys
from pathlib import Path
from typing import Union

sys.path.insert(1, str(Path(__file__).parents[1] / 'shared'))


from osclib import OscPack, BunServer, bun_manage, UDP

class NiniServer(BunServer):
    def __init__(self, port: Union[int, str] = 1, proto: int =UDP, reg_methods=True, total_fake=False):
        super().__init__(port, proto, reg_methods, total_fake)
        self.add_managed_methods()

    @bun_manage('/mok/pof/pif', 'ssi')
    def _mok_pof_pif(self, osp: OscPack):
        print('anioukadi', osp.path, osp.args)


class BunnyServer(BunServer):
    def __init__(self, port: Union[int, str] = 1, proto: int =UDP, reg_methods=True, total_fake=False):
        super().__init__(port, proto, reg_methods, total_fake)
        self.add_managed_methods()
    
    @bun_manage('/drili/nou', 'i')
    def _drili_nou(self, osp: OscPack):
        print('drizlefi', osp.path, osp.args)
    
    @bun_manage('/mok/pof/pif', 'ssi')
    def _mok_pof_pif(self, osp: OscPack):
        print('mokpôkeof', osp.path, osp.args)


if False:
    nini = NiniServer()
    bunny_server = BunnyServer()
else:
    nini = BunnyServer()
    bunny_server = NiniServer()

nini.send(bunny_server.port, '/mok/pof/pif', 'galet', 'saukis', 44)
nini.send(bunny_server.port, '/drili/nou', 45)


for i in range(1):
    bunny_server.recv(10)
    

