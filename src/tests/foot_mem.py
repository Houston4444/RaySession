import time
import sys

# import qtpy.QtGui
# import numpy

shared = '/' + '/'.join(__file__.split('/')[:-2]) + '/shared'
sys.path.insert(1, shared)

from proc_name import set_proc_name
set_proc_name('ray-footmem')

for i in range(2000):
    time.sleep(0.01)
    if i == 250:
        import numpy as np
    elif i == 750:
        del np