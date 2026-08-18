from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / 'shared'))

import ray_control



    

print('go start')
ray_control.start()
print('go list')
# print('zeorgp', ray_control.list_daemons())
# print('tozolopi', ray_control.list_session_templates())

zoupi = ray_control.auto_export_custom_names('false')
print('ok done', zoupi)
# change_root = ray_control.change_root('/home/houstonlzk5/Koalo Géant')
# print(f'{change_root=}')

# ray_control.abort()
# ray_control.open_session_off('mignognon')
# for facto in ray_control.list_factory_client_templates():
#     print('client tp', facto)
#     # client_id = ray_control.add_factory_client_template(facto)
#     # print(ray_control.client.get_properties(client_id))
#     # break
    
ray_control.open_session('tests/feel_good')
# client_id = ray_control.add_factory_client_template('Ardour')
# ray_control.client.open(client_id)
# print('tout il est prêt !')

client = ray_control.Client('ardour_4')
print('yoappz', client.client_id, client.executable)
print('toulili', ray_control.clients(started=True))

import time
beg = time.time()
execut = client.executable
# print(f'{execut=}')
client.executable = '/usr/bin/ardour'
execut2 = client.executable
# print(f'{execut2=}')

aft = time.time()
print(aft - beg)
# client = ray_control.Client('ardour_4')
# client.start()
# client.stop()
# client.open()

# ray_control.client.stop('ardour_4')
# ray_control.client.open('ardour_4')

# for client_id in ray_control.list_clients():
#     ray_control.client.stop(client_id)
# for client_template in ray_control.list_user_client_templates():
    # ray_control.add_exe

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