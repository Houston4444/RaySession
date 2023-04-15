

def group_belongs_to_client(group_name: str, jack_client_name: str):
    if group_name == jack_client_name:
        return True

    if group_name.startswith(jack_client_name + '/'):
        return True

    if (group_name.startswith(jack_client_name + ' (')
            and group_name.endswith(')')):
        # Non-Mixer way
        return True

    if group_name == jack_client_name + '-midi':
        # Hydrogen specific
        return True
    
    if (jack_client_name.startswith('Carla')
            and '.' not in jack_client_name
            and (group_name == jack_client_name + '.0'
                 or group_name.startswith(jack_client_name + '.0/'))):
        # Carla bug workaround without long jack name
        # RS uses long jack naming by default with carla templates
        return True

    return False

def port_belongs_to_client(port_name: str, jack_client_name: str) -> bool:
    jclient_name, _, short_name = port_name.partition(':')

    if not jclient_name.startswith((jack_client_name, 'a2j', 'Midi-Bridge')):
        return False

    if jclient_name in ('a2j', 'Midi-Bridge'):
        bridge = jclient_name
        if ' [' in short_name:
            group_name = short_name.partition(' [')[0]
        else:
            if ' (capture)' in short_name:
                group_name = short_name.partition(' (capture)')[0]
            else:
                group_name = short_name.partition(' (playback)')[0]

        if bridge == 'a2j':
            search_str = jack_client_name.replace('.', ' ')
            if group_name == search_str or group_name.startswith(search_str + '/'):
                jclient_name = group_name.replace(search_str, jack_client_name, 1)
        else:
            jclient_name = group_name

    return group_belongs_to_client(jclient_name, jack_client_name)

def port_name_client_replaced(
        port_name: str, old_client_name: str, new_client_name: str) -> str:
    if not port_belongs_to_client(port_name, old_client_name):
        return port_name
    
    if port_name.startswith(old_client_name):
        return port_name.replace(old_client_name, new_client_name, 1)
    
    if port_name.startswith(('a2j:', 'Midi-Bridge:')):
        bridge, _, ub_port_name = port_name.partition(':')
        if bridge == 'a2j':
            if ub_port_name.startswith(old_client_name.replace('.', ' ')):
                ub_port_name = ub_port_name.replace(
                    old_client_name.replace('.', ' '),
                    new_client_name.replace('.', ' '),
                    1)
                return "a2j:" + ub_port_name
        
        if bridge == 'Midi-Bridge':
            if ub_port_name.startswith(old_client_name):
                ub_port_name = ub_port_name.replace(
                    old_client_name, new_client_name, 1)
                return "Midi-Bridge:" + ub_port_name
    
    return port_name