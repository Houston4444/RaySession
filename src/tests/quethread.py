import time
from queue import Queue
from threading import Thread

jolie_queue = Queue()

def lire_la_queue():
    for i in range(4):
        huhu = jolie_queue.get()
        huhutime = time.time()
        print('lire la quiee:', huhu)
        print('lueeee', huhutime)
        
th = Thread(target=lire_la_queue)
th.start()

for i in range(10):
    print(f'tape {i}')
    jolie_queue.put(f'tapie {i}')
    ecritime = time.time()
    print('écrite', ecritime)
    time.sleep(0.5)

print('fini pour nous')

th.join()

print('fini pour tous')
