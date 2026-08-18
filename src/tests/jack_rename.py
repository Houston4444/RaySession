import jack
import time
import signal

terminate = False

def signal_handler(sig, frame):
    global terminate
    terminate = True


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    client = jack.Client('kate')
    client.inports.register('input_1')
    client.outports.register('output_1')
    client.activate()

    for i in range(40):
        time.sleep(0.050)
        if terminate:
            break

    for inport in client.inports:
        inport.shortname = inport.shortname.replace('input_', 'InPut_')
        print('hop renamed ', inport.shortname)

    while not terminate:
        time.sleep(0.050)

    client.close()
    del client