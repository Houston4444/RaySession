#!/usr/bin/python3 -u

import sys
sys.stderr.write('efzkoefkefkofko\n')
try:
    import dbus
except:
    sys.stderr.write('python3-dbus is missing !\n')
    sys.exit(1)

name_base = 'org.jackaudio'
control_interface_name = name_base + '.JackControl'
configure_interface_name = name_base + '.Configure'
patchbay_interface_name = name_base + '.JackPatchbay'
service_name = name_base + '.service'

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

def get_parameters():
    # Check if JACK is started, start output_string store
    sys.stderr.write('refkoorkok\n')
    jack_started = control_iface.IsStarted()        
    output_string = "jack_started:%s\n" % str(jack_started)

    # Check JACK configuration
    for key in all_parameters:
        isset, default, value = configure_iface.GetParameterValue(key.split('/')[1:])
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

    # check number of pulseaudio JACK ports (only if JACK is started obviously)
    pulseaudio_sources = 0
    pulseaudio_sinks = 0

    if jack_started:
        all_ports = patchbay_iface.GetAllPorts()

        for port in all_ports:
            if str(port).startswith('PulseAudio JACK Source:'):
                pulseaudio_sources+=1
            elif str(port).startswith('PulseAudio JACK Sink:'):
                pulseaudio_sinks+=1

    output_string += "pulseaudio_sources:%s\n" % pulseaudio_sources
    output_string += "pulseaudio_sinks:%s\n" % pulseaudio_sinks
    return output_string

def set_parameters(stdin):
    set_error = 0
    
    for line in stdin.split('\n'):
        parameter, colon, value = line.partition(':')
        if not parameter in all_parameters:
            continue
        
        if parameter in ('/engine/realtime'):
            # value is a boolean
            value = bool(value != '0')
        elif parameter in ('/engine/realtime-priority', '/driver/period'
                           '/driver/nperiods', '/driver/rate',
                           '/driver/inchannels', '/driver/outchannels'):
            # value is an int
            if not value.isdigit():
                continue
            value = int(value)
        elif parameter in ('/engine/self-connect-mode'):
            # value is bytes
            value = value.encode()
        
        param_paths = parameter.split('/')[1:]
        
        try:
            configure_iface.SetParameterValue(param_paths, value)
        except:
            set_error = 1
    
    return set_error

sys.stderr.write('fzrfzokfokk\n')

if __name__ == '__main__':
    sys.stderr.write('ezeff214\n')
    try:
        bus = dbus.SessionBus()
        controller = bus.get_object(service_name, "/org/jackaudio/Controller")
        control_iface = dbus.Interface(controller, control_interface_name)
        configure_iface = dbus.Interface(controller, configure_interface_name)
        patchbay_iface = dbus.Interface(controller, patchbay_interface_name)
    except:
        sys.stderr.write('Impossible to connect to JACK dbus\n')
        sys.exit(1)
    
    if len(sys.argv) >= 2:
        sys.exit(set_parameters(sys.argv[1]))
    else:
        sys.stderr.write('fzeplf145\n')
        output_string = get_parameters()
        sys.stdout.write(output_string)
    
