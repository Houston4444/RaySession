import time
import sys
import gc
import importlib

# import qtpy.QtGui
# import numpy

shared = '/' + '/'.join(__file__.split('/')[:-2]) + '/shared'
sys.path.insert(1, shared)

from proc_name import set_proc_name
set_proc_name('ray-footmem')

falap = set(sys.modules.keys())

for i in range(3000):
    time.sleep(0.01)
    if i == 250:
        import numpy
    elif i == 750:
        print('paf')
        keys_to_del = set[str]()
        
        for key, value in sys.modules.items():
            if key not in falap:
                keys_to_del.add(key)
        
        print('keys to del', keys_to_del)
        
        for key in keys_to_del:
            del sys.modules[key]
            
        gc.collect()
        print('pouf')