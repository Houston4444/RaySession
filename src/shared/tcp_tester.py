from typing import Union
import time
from pathlib import Path

from osclib import ServerThread, Server, get_free_osc_port, UNIX, make_method, Address, TCP
# from pyliblo3 import Server, UNIX, Address
# from osclib import UDP as TCP

kokopath = Path('/tmp/koko')
momopath = Path('/tmp/momo')
kokopath.mkdir(parents=True, exist_ok=True)
momopath.mkdir(parents=True, exist_ok=True)

class Koko(Server):
    def __init__(self):
        # port = get_free_osc_port(4747, protocol=TCP)
        # # print('koko', port)
        # super().__init__(port, proto=TCP)
        super().__init__(str(kokopath / 'po'), proto=UNIX)
        print('mozeomfkokourl', self.url)
        self.add_method('/chouchou', 's', self.chouchou)
    
    def chouchou(self, path, args, types, src_addr: Address):
        print('chouchou', path, args, types)
        # self.send(momo.url, '/meco')
         
    # @make_method('/slip', None)
    # def slip(self, path, args, types, src_addr: Address):
    #     print('slippp', src_addr.url)
        
        
class Momo(Server):
    def __init__(self):
        # port = get_free_osc_port(5555, protocol=TCP)
        # print('momo', port)
        # super().__init__(str(momopath / 'mo'), proto=UNIX)
        super().__init__()
        
    @make_method('/meco', '')
    def meko(self, path, args, types, src_addr):
        print('szpo meko')
    
koko = Koko()
momo = Momo()

# koko.start()
# momo.start()

momo.send(koko.url, '/chouchou', 'sizz')

for i in range(1000):
    # time.sleep(0.002)
    koko.recv(2)
    momo.recv(2)

# koko.stop()
# momo.stop()
