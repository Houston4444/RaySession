import time
import sys
import threading
from pathlib import Path
# import qtpy.QtGui
# import numpy

# shared = '/' + '/'.join(__file__.split('/')[:-2]) + '/shared'
sys.path.insert(1, str(Path(__file__).parents[1] / 'patchbay_daemon'))
sys.path.insert(1, str(Path(__file__).parents[1] / 'shared'))

from proc_name import set_proc_name
set_proc_name('ray-threaderr')

def togo():
    for j in range(2000):
        time.sleep(0.01)
        # assert j < 500
        if j % 22 == 0:
            print('j', j)

zpe_thread = threading.Thread(target=togo)
zpe_thread.start()

for i in range(1000):
    time.sleep(0.01)
    if i % 20 == 0:
        print('i', i)
    assert i < 500

# zpe_thread.join()