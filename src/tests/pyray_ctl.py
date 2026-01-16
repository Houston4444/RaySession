from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / 'shared'))

import ray_control

print('go start')
ray_control.start()
print('go list')
print('zeorgp', ray_control.list_daemons())
print('go stop')
ray_control.stop()
print('plaunte', ray_control.get_pid())
print('all done')