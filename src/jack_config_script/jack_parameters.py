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

def convert_str_to_dbustype(value, dbus_type):
    try:
        dbus_type = str(dbus_type)

        if dbus_type == 'b':
            return bool(value in ('1', 'true', 'True'))
        if dbus_type == 'u':
            return dbus.UInt32(value)
        if dbus_type == 'i':
            return int(value)
        if dbus_type == 'y':
            return value.encode()
        if dbus_type == 's':
            return value
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
        return output_string

    return '\n'

def set_jack_parameters(contents):
    all_input_parameters = {}
    for line in contents.split('\n'):
        if line.startswith(('/engine/', '/driver/', '/internals/')):
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
        if sys.argv[1] == '--diff':
            if len(sys.argv) >= 4:
                try:
                    file1 = open(sys.argv[2], 'r')
                    contents1 = file1.read()
                    file1.close()
                    file2 = open(sys.argv[3], 'r')
                    contents2 = file2.read()
                    file2.close()
                except:
                    sys.stderr.write("unable to read file %s or %s\n" % (
                                                    sys.argv[2], sys.argv[3]))
                    sys.exit(1)

                output = diff(contents1, contents2)
                sys.stdout.write(output)
                sys.exit(0)
            else:
                sys.stderr.write('not enough arguments\n')
                sys.exit(1)

        try:
            file = open(sys.argv[1], 'r')
            contents = file.read()
            file.close()
        except:
            sys.stderr.write("unable to read file %s\n" % sys.argv[1])
            sys.exit(1)

        sys.exit(set_jack_parameters(contents))
    else:
        output_string = get_jack_parameters()
        sys.stdout.write(output_string)
