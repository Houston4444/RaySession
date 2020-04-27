#!/usr/bin/python3 -u

import sys

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
state_file_path='/tmp/jack_current_parameters'

def convert_str_to_dbustype(value, dbus_type):
    try:
        dbus_type = str(dbus_type)
        
        if dbus_type == 'b':
            return bool(value == '1')
        elif dbus_type in ('i', 'u'):
            return int(value)
        elif dbus_type == 'y':
            return value.encode()
        elif dbus_type == 's':
            return value
        else:
            return None
        
    except:
        return None

def get_jack_parameters():
    # Check if JACK is started, start output_string store
    jack_started = control_iface.IsStarted()        
    output_string = "jack_started:%s\n" % str(jack_started)
    
    params = configure_iface.GetParametersInfo(['engine'])
    for param in params:
        isset, default, value = configure_iface.GetParameterValue(
            ['engine', param[1]])
        if isset:
            output_string += '/engine/%s:%s\n' % (param[1], value)
        
    params = configure_iface.GetParametersInfo(['driver'])
    for param in params:
        isset, default, value = configure_iface.GetParameterValue(
                                                        ['driver', param[1]])
        if isset:
            output_string += '/driver/%s:%s\n' % (param[1], value)
            
    is_leaf, internals = configure_iface.ReadContainer(['internals'])
    for internal in internals:
        params = configure_iface.GetParametersInfo(['internals', internal])
        for param in params:
            isset, default, value = configure_iface.GetParameterValue(
                                            ['internals', internal, param[1]])
            if isset:
                output_string += '/internals/%s/%s:%s\n' % (
                                                    internal, param[1], value)
                
    if output_string:
        return output_string[:-1]
    else:
        return ''

def set_jack_parameters(contents):
    all_input_parameters = {}
    for line in contents.split('\n'):
        if line.startswith(('/engine/', '/driver/', '/internals')):
            param, colon, value = line.partition(':')
            all_input_parameters[param] = value
            
    params = configure_iface.GetParametersInfo(['engine'])
    for param in params:
        isset, default, value = configure_iface.GetParameterValue(
                                                        ['engine', param[1]])
        full_param = '/engine/%s' % param[1]
        if full_param in all_input_parameters:
            if str(value) != all_input_parameters[full_param]:
                dbus_value = convert_str_to_dbustype(
                                all_input_parameters[full_param], param[0])
                if dbus_value is not None:
                    configure_iface.SetParameterValue(
                                            ['engine', param[1]], dbus_value)
    
    params = configure_iface.GetParametersInfo(['driver'])
    for param in params:
        isset, default, value = configure_iface.GetParameterValue(
                                                        ['driver', param[1]])
        
        full_param = '/driver/%s' % param[1]
        if full_param in all_input_parameters:
            if str(value) != all_input_parameters[full_param]:
                dbus_value = convert_str_to_dbustype(
                                all_input_parameters[full_param], param[0])
                if dbus_value is not None:
                    configure_iface.SetParameterValue(
                                            ['driver', param[1]], dbus_value)
    
    
    is_leaf, internals = configure_iface.ReadContainer(['internals'])
    for internal in internals:
        params = configure_iface.GetParametersInfo(['internals', internal])
        for param in params:
            isset, default, value = configure_iface.GetParameterValue(
                                            ['internals', internal, param[1]])
            
            full_param = '/internals/%s/%s' % (internal, param[1])
            if full_param in all_input_parameters:
                if str(value) != all_input_parameters[full_param]:
                    dbus_value = convert_str_to_dbustype(
                                all_input_parameters[full_param], param[0])
                    if dbus_value is not None:
                        configure_iface.SetParameterValue(
                                ['internals', internal, param[1]], dbus_value)

def get_parameters():
    # Check if JACK is started, start output_string store
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

if __name__ == '__main__':
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
        try:
            file = open(sys.argv[1], 'r')
            contents = file.read()
            file.close()
        except:
            sys.stderr.write("unable to read file %s\n" % sys.argv[1])
            sys.exit(1)
        
        sys.exit(set_jack_parameters(contents))
    else:
        #output_string = get_parameters()
        #sys.stdout.write(output_string)
        output_string = get_jack_parameters()
        print(output_string)
    
