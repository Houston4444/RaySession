import time
import sys

# import qtpy.QtGui


shared = '/' + '/'.join(__file__.split('/')[:-2]) + '/shared'
sys.path.insert(1, shared)

from proc_name import set_proc_name
set_proc_name('ray-footmem')

for i in range(1000):
    time.sleep(0.01)