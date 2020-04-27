#!/usr/bin/python3 -u

import os
import signal
import sys
import time

try:
    import dbus
    import dbus.mainloop.glib
    from gi.repository import GLib
except:
    sys.stderr.write('python3-dbus is missing !\n')
    sys.exit(1)

state_file_path='/tmp/RaySession/jack_current_parameters'

name_base = 'org.jackaudio'
control_interface_name = name_base + '.JackControl'
configure_interface_name = name_base + '.Configure'
patchbay_interface_name = name_base + '.JackPatchbay'
service_name = name_base + '.service'
last_file_write = 0.0

all_parameters = {
    '/engine/driver': '',
    '/engine/realtime': '',
    '/engine/realtime-priority': '',
    '/engine/self-connect-mode': '',
    '/engine/slave-drivers': '',
    '/driver/period': '',
    '/driver/nperiods': '',
    '/driver/rate': '',
    '/driver/inchannels': '',
    '/driver/outchannels': '',
    '/internals/audioadapter/device': ''}

def dbus_signal_receiver(*args, **kwds):
    global last_file_write
    
    # dbus signal for something else than JACK, do nothing
    if not kwds['interface'].startswith('org.jackaudio.'):
        return
    
    if not kwds['member'] in ('ServerStarted', 'ServerStopped',
                              'PortAppeared'):
        return
    
    if kwds['member']  == 'PortAppeared':
        # file already saved in last 10s 
        if time.time() - last_file_write < 10:
            return
        
        # PortAppeared doesn't concerns a physical port, do nothing
        if not args[5] & 0x4:
            return
    
    write_the_file()
    
def write_the_file(at_start=False):
    output_string = "daemon_pid:%i\n" % os.getpid()
    
    # Check if JACK is started, start output_string store
    jack_started = control_iface.IsStarted()
    output_string += "jack_started:%s\n" % str(jack_started)
    
    if not (at_start and jack_started):
        # Check JACK configuration
        for key in all_parameters:
            isset, default, value = configure_iface.GetParameterValue(
                                                        key.split('/')[1:])
            all_parameters[key] = str(value)

        # Because buffersize is switchable without restarting JACK
        # the buffersize in configuration may differs from the real buffersize
        # So, check real buffersize
        try:
            buffersize = control_iface.GetBufferSize()
            if buffersize:
                all_parameters['/driver/period'] = str(buffersize)
        except:
            pass
        
        for key in all_parameters:
            output_string += "%s:%s\n" % (key, all_parameters[key])
            
    if not os.path.exists(os.path.dirname(state_file_path)):
        os.makedirs(os.path.dirname(state_file_path))
        
    file = open(state_file_path, 'w')
    file.write(output_string)
    file.close()
    last_file_write = time.time()


if __name__ == '__main__':
    if os.path.exists(state_file_path):
        file = open(state_file_path, 'r')
        file_contents = file.read()
        file.close()
        
        jack_checker_pid = 0
        for line in file_contents.split('\n'):
            if line.startswith('daemon_pid:'):
                pid_str = line.replace('daemon_pid:', '', 1)
                if pid_str.isdigit():
                    jack_checker_pid = int(pid_str)
                    break
        
        if os.path.isdir('/proc/%i' % jack_checker_pid):
            # this daemon is already running, just exit
            sys.stderr.write('jack checker daemon already running\n')
            sys.exit()
        else:
            os.remove(state_file_path)
            
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    
    loop = GLib.MainLoop()
    
    bus = dbus.SessionBus()
    controller = bus.get_object(service_name, "/org/jackaudio/Controller")
    control_iface = dbus.Interface(controller, control_interface_name)
    configure_iface = dbus.Interface(controller, configure_interface_name)
    patchbay_iface = dbus.Interface(controller, patchbay_interface_name)
    
    bus.add_signal_receiver(dbus_signal_receiver,
                            destination_keyword="dest",
                            path_keyword="path",
                            member_keyword="member",
                            interface_keyword="interface",
                            sender_keyword="sender")
    
    write_the_file(True)
    loop.run()
    sys.exit()
    
