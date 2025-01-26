
from osclib import OscPack, Address

osp = OscPack('/ray/gui/nanana',
              ['shamopo', 47, 'suvam', 12.84],
              'sisf',
              Address(1984))

sham, age, suva, wieh = osp.args
kom, az, apz, dzo = osp.arg_types()