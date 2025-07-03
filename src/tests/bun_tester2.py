
from typing import Callable, Optional, Union
from pathlib import Path
import sys
import time



sys.path.insert(1, str(Path(__file__).parents[1] / 'shared'))


from osclib import Bundle, Message, Server, Address, OscPack, BunServer, BunServerThread, MegaSend, bun_manage

class BunRecepter(BunServerThread):
    def __init__(self, port: Union[int, str] = 1, proto=..., reg_methods=True, total_fake=False):
        super().__init__(port, proto, reg_methods, total_fake)
        # self.add_method('/moko/maki', 'ifss', self._moko_maki)
        self.add_managed_methods()
    
    @bun_manage('/moko/maki', 'ifsssi')
    def _moko_maki(self, osp: OscPack):
        # print('ord', self.url, args[0])
        time.sleep(0.00001)
        ...


server1 = BunServer()
servers = [BunRecepter() for i in range(3)]

time_dict = dict[str, float]()
time_dict['start'] = time.time()

ms = MegaSend('shampoing')
for i in range(50000):
    ms.add('/moko/maki', i, float(i), str(i), 'mousslaizkdk', 'matool', 75654)

time_dict['added'] = time.time()

for server in servers:
    server.start()
    
time_dict['serve started'] = time.time()
server1.mega_send([s.url for s in servers], ms)
time_dict['mega_send done'] = time.time()

print('hop done')
# time.sleep(1)

for server in servers:
    server.stop()
    
time_dict['end'] = time.time()

for key, value in time_dict.items():
    print('od', value, key)