#!/usr/bin/python3 -u

import os
import signal
import sys
import warnings

import jacklib
import osc_server

connection_list = []
port_list = []

PORT_TYPE_NULL = 0
PORT_TYPE_AUDIO = 1
PORT_TYPE_MIDI = 2

EXISTENCE_PATH = '/tmp/RaySession/patchbay_infos'

TERMINATE = False

def signalHandler(sig, frame):
    global TERMINATE
    if sig in (signal.SIGINT, signal.SIGTERM):
        TERMINATE = True

class JackPort:
    id = 0
    name = ''
    type = PORT_TYPE_NULL
    flags = 0
    alias_1 = ''
    alias_2 = ''
    
    def __init__(self, port_name:str):
        self.name = port_name
        port_ptr = jacklib.port_by_name(jack_client, port_name)
        self.flags = jacklib.port_flags(port_ptr)

        port_type_str = str(jacklib.port_type(port_ptr), encoding="utf-8")
        if port_type_str == jacklib.JACK_DEFAULT_AUDIO_TYPE:
            self.type = PORT_TYPE_AUDIO
        elif port_type_str == jacklib.JACK_DEFAULT_MIDI_TYPE:
            self.type = PORT_TYPE_MIDI
        
        ret, alias_1, alias_2 = jacklib.port_get_aliases(port_ptr)
        if ret:
            self.alias_1 = alias_1
            self.alias_2 = alias_2

def JackShutdownCallback(arg=None):
    global TERMINATE
    osc_server.server_stopped()
    TERMINATE = True
    return 0

def JackPortRegistrationCallback(port_id, register_yes_no, arg=None):
    port_ptr = jacklib.port_by_id(jack_client, port_id)
    port_name = str(jacklib.port_name(port_ptr), encoding="utf-8")
    
    if register_yes_no:
        jport = JackPort(port_name)
        port_list.append(jport)
        osc_server.port_added(jport)
    else:
        for jport in port_list:
            if jport.name == port_name:
                port_list.remove(jport)
                osc_server.port_removed(jport)
                break
    return 0

def JackPortRenameCallback(port_id, old_name, new_name, arg=None):
    print('jackk poort rename callback', port_id, old_name, new_name, arg)
    for jport in port_list:
        if jport.name == str(old_name, encoding="utf-8"):
            ex_name = jport.name
            jport.name = str(new_name, encoding="utf-8")
            #print('sent to ssoosl', old_name, new_name)
            osc_server.port_renamed(jport, ex_name)
            break
    return 0

def JackPortConnectCallback(port_id_A, port_id_B, connect_yesno, arg=None):
    port_ptr_A = jacklib.port_by_id(jack_client, port_id_A)
    port_ptr_B = jacklib.port_by_id(jack_client, port_id_B)

    port_str_A = str(jacklib.port_name(port_ptr_A), encoding="utf-8")
    port_str_B = str(jacklib.port_name(port_ptr_B), encoding="utf-8")

    connection = (port_str_A, port_str_B)

    if connect_yesno:
        connection_list.append(connection)
        osc_server.connection_added(connection)
    else:
        if connection in connection_list:
            connection_list.remove(connection)
            osc_server.connection_removed(connection)

    return 0

def c_char_p_p_to_list(c_char_p_p):
    i = 0
    retList = []

    if not c_char_p_p:
        return retList

    while True:
        new_char_p = c_char_p_p[i]
        if new_char_p:
            retList.append(str(new_char_p, encoding="utf-8"))
            i += 1
        else:
            break

    jacklib.free(c_char_p_p)
    return retList

def write_existence_file(port: int):
    try:
        file = open(EXISTENCE_PATH, 'w')
    except PermissionError:
        sys.stderr.write(
            'ray-patchbay_to_osc: Error, no permission for existence file\n')
        sys.exit(1)

    contents = 'pid:%i\n' % os.getpid()
    contents += 'port:%i\n' % port

    file.write(contents)
    file.close()

def remove_existence_file():
    if not os.path.exists(EXISTENCE_PATH):
        return 

    try:
        os.remove(EXISTENCE_PATH)
    except PermissionError:
        sys.stderr.write(
            'ray-patchbay_to_osc: Error, unable to remove %s\n'
            % EXISTENCE_PATH)

if __name__ == '__main__':
    # prevent deprecation warnings python messages
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    jack_client = jacklib.client_open(
        "ray-patch_to_osc",
        jacklib.JackNoStartServer | jacklib.JackSessionID,
        None)

    if not jack_client:
        sys.stderr.write('Unable to make a jack client !\n')
        sys.exit()

    print('ze suis lààà')

    jacklib.set_port_registration_callback(jack_client,
                                           JackPortRegistrationCallback,
                                           None)
    jacklib.set_port_connect_callback(jack_client,
                                      JackPortConnectCallback,
                                      None)
    jacklib.set_port_rename_callback(jack_client,
                                     JackPortRenameCallback,
                                     None)
    jacklib.on_shutdown(jack_client, JackShutdownCallback, None)
    jacklib.activate(jack_client)

    #connect signals
    signal.signal(signal.SIGINT, signalHandler)
    signal.signal(signal.SIGTERM, signalHandler)

    #get all currents Jack ports and connections
    port_name_list = c_char_p_p_to_list(
        jacklib.get_ports(jack_client, "", "", 0))
    
    for port_name in port_name_list:
        jport = JackPort(port_name)
        port_list.append(jport)

        if jport.flags & jacklib.JackPortIsInput:
            continue

        port_ptr = jacklib.port_by_name(jack_client, jport.name)
        
        # this port is output, list its connections
        port_connection_names = c_char_p_p_to_list(
            jacklib.port_get_all_connections(jack_client, port_ptr))

        for port_con_name in port_connection_names:
            connection_list.append((jport.name, port_con_name))

    osc_server = osc_server.OscJackPatch(jack_client, port_list, connection_list)
    write_existence_file(osc_server.port)
    
    if len(sys.argv) > 1:
        for gui_url in sys.argv[1:]:
            osc_server.add_gui(gui_url)

    # MAIN Loop
    while True:
        osc_server.recv(50)

        if TERMINATE or osc_server.is_terminate():
            break

    jacklib.deactivate(jack_client)
    jacklib.client_close(jack_client)
    remove_existence_file()
