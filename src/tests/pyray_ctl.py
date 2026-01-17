from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / 'shared'))

import ray_control

print('go start')
ray_control.start()
print('go list')
print('zeorgp', ray_control.list_daemons())
print('tozolopi', ray_control.list_session_templates())

ray_control.auto_export_custom_names('false')
print('ok done')
change_root = ray_control.change_root('/home/Koalo Géant')
print(f'{change_root=}')
# ray_control.open_session('tests/encore_t')
# ray_control.clear_pretty_names()
# client_id = ray_control.add_executable('ray-jackpatch')
# print(f'{client_id=}')
# msg = ray_control.client.get_properties(client_id)
# print('mmmmsg')
# print(msg)
# print('go stop')
# ray_control.stop()

# ray_control.server.open_session('tests/toudilaf_bis')
# print('ok done')
# ray_control.session.add_executable('ray-jackpatch')
# ray_control.session.close()
# ray_control.server.open_session('tests/toudilaf_bis')
# clients = ray_control.session.list_clients()
# print(f'{clients=}')

# print('plaunte', ray_control.get_pid())
# print('all done')