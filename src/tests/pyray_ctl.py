from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / 'shared'))

import ray_control

print('go start')
ray_control.start()
print('go list')
print('zeorgp', ray_control.list_daemons())
print('tozolopi', ray_control.server.list_session_templates())
# print('go stop')
# ray_control.stop()

ray_control.server.open_session('tests/toudilaf_bis')
print('ok done')
ray_control.session.add_executable('ray-jackpatch')
ray_control.session.close()
ray_control.server.open_session('tests/toudilaf_bis')
# clients = ray_control.session.list_clients()
# print(f'{clients=}')

# print('plaunte', ray_control.get_pid())
# print('all done')