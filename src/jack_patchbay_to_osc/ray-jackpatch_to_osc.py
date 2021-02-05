#!/usr/bin/python3 -u

import os
import signal
import sys

from PyQt5.QtCore import QCoreApplication, QObject, QTimer, pyqtSignal
from PyQt5.QtXml import QDomDocument

#from shared import *
import jacklib
import osc_server

connection_list = []
port_list = []

PORT_MODE_OUTPUT = 0
PORT_MODE_INPUT = 1
PORT_MODE_NULL = 2

PORT_TYPE_AUDIO = 0
PORT_TYPE_MIDI = 1
PORT_TYPE_NULL = 2

EXISTENCE_PATH = '/tmp/RaySession/patchbay_infos'

file_path = ""

is_dirty = False

pending_connection = False

def signalHandler(sig, frame):
    if sig in (signal.SIGINT, signal.SIGTERM):
        app.quit()

class JackPort:
    id = 0
    name = ''
    mode = PORT_MODE_NULL
    type = PORT_TYPE_NULL
    alias_1 = ''
    alias_2 = ''

def portExists(name, mode):
    for port in port_list:
        if port.name == name and port.mode == mode:
            return True
    return False

class Signaler(QObject):
    port_added = pyqtSignal(str, int, int)
    port_removed = pyqtSignal(str, int, int)
    port_renamed = pyqtSignal(str, str, int, int)
    connection_added = pyqtSignal(str, str)
    connection_removed = pyqtSignal(str, str)

def JackShutdownCallback(arg=None):
    app.quit()
    return 0

def JackPortRegistrationCallback(port_id, registerYesNo, arg=None):
    portPtr = jacklib.port_by_id(jack_client, port_id)
    portFlags = jacklib.port_flags(portPtr)
    port_name = str(jacklib.port_name(portPtr), encoding="utf-8")

    port_mode = PORT_MODE_NULL

    if portFlags & jacklib.JackPortIsInput:
        port_mode = PORT_MODE_INPUT
    elif portFlags & jacklib.JackPortIsOutput:
        port_mode = PORT_MODE_OUTPUT

    port_type = PORT_TYPE_NULL

    portTypeStr = str(jacklib.port_type(portPtr), encoding="utf-8")
    if portTypeStr == jacklib.JACK_DEFAULT_AUDIO_TYPE:
        port_type = PORT_TYPE_AUDIO
    elif portTypeStr == jacklib.JACK_DEFAULT_MIDI_TYPE:
        port_type = PORT_TYPE_MIDI

    if registerYesNo:
        signaler.port_added.emit(port_id, port_name, port_mode, port_type)
    else:
        signaler.port_removed.emit(port_id, port_name, port_mode, port_type)

    return 0

def JackPortRenameCallback(portId, oldName, newName, arg=None):
    portPtr = jacklib.port_by_id(jack_client, portId)
    portFlags = jacklib.port_flags(portPtr)

    port_mode = PORT_MODE_NULL

    if portFlags & jacklib.JackPortIsInput:
        port_mode = PORT_MODE_INPUT
    elif portFlags & jacklib.JackPortIsOutput:
        port_mode = PORT_MODE_OUTPUT

    port_type = PORT_TYPE_NULL

    portTypeStr = str(jacklib.port_type(portPtr), encoding="utf-8")
    if portTypeStr == jacklib.JACK_DEFAULT_AUDIO_TYPE:
        port_type = PORT_TYPE_AUDIO
    elif portTypeStr == jacklib.JACK_DEFAULT_MIDI_TYPE:
        port_type = PORT_TYPE_MIDI

    signaler.port_renamed.emit(str(oldName, encoding='utf-8'),
                               str(newName, encoding='utf-8'),
                               port_mode,
                               port_type)

    return 0

def JackPortConnectCallback(port_id_A, port_id_B, connect_yesno, arg=None):
    port_ptr_A = jacklib.port_by_id(jack_client, port_id_A)
    port_ptr_B = jacklib.port_by_id(jack_client, port_id_B)

    port_str_A = str(jacklib.port_name(port_ptr_A), encoding="utf-8")
    port_str_B = str(jacklib.port_name(port_ptr_B), encoding="utf-8")

    if connect_yesno:
        signaler.connection_added.emit(port_str_A, port_str_B)
    else:
        signaler.connection_removed.emit(port_str_A, port_str_B)

    return 0

def portAdded(port_name, port_mode, port_type):
    port = JackPort()
    port.name = port_name
    port.mode = port_mode
    port.type = port_type
    port.is_new = True

    port_list.append(port)
    osc_server.port_added(port)

def portRemoved(port_name, port_mode, port_type):
    for i in range(len(port_list)):
        port = port_list[i]
        if (port.name == port_name
                and port.mode == port_mode
                and port.type == port_type):
            break
    else:
        return

    port_list.__delitem__(i)
    osc_server.port_removed(port)

def portRenamed(old_name, new_name, port_mode, port_type):
    for port in port_list:
        if (port.name == old_name
                and port.mode == port_mode
                and port.type == port_type):
            port.name = new_name
            osc_server.port_renamed(port)
            break

def connectionAdded(port_str_A, port_str_B):
    connection_list.append((port_str_A, port_str_B))
    osc_server.connection_added((port_str_A, port_str_B))

def connectionRemoved(port_str_A, port_str_B):
    for i in range(len(connection_list)):
        if (connection_list[i][0] == port_str_A
                and connection_list[i][1] == port_str_B):
            connection_list.__delitem__(i)
            osc_server.connection_removed((port_str_A, port_str_B))
            break

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
    try:
        os.remove(EXISTENCE_PATH)
    except PermissionError:
        sys.stderr.write(
            'ray-patchbay_to_osc: Error, unable to remove %s\n'
            % EXISTENCE_PATH)

if __name__ == '__main__':
    jack_client = jacklib.client_open(
        "ray-patch_to_osc",
        jacklib.JackNoStartServer | jacklib.JackSessionID,
        None)

    if not jack_client:
        sys.stderr.write('Unable to make a jack client !\n')
        sys.exit()

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

    signaler = Signaler()
    signaler.port_added.connect(portAdded)
    signaler.port_removed.connect(portRemoved)
    signaler.port_renamed.connect(portRenamed)
    signaler.connection_added.connect(connectionAdded)
    signaler.connection_removed.connect(connectionRemoved)

    #connect signals
    signal.signal(signal.SIGINT, signalHandler)
    signal.signal(signal.SIGTERM, signalHandler)

    #get all currents Jack ports and connections
    portNameList = c_char_p_p_to_list(jacklib.get_ports(jack_client,
                                                        "", "", 0))

    for portName in portNameList:
        jack_port = JackPort()
        jack_port.name = portName

        portPtr = jacklib.port_by_name(jack_client, portName)
        portFlags = jacklib.port_flags(portPtr)

        if portFlags & jacklib.JackPortIsInput:
            jack_port.mode = PORT_MODE_INPUT
        elif portFlags & jacklib.JackPortIsOutput:
            jack_port.mode = PORT_MODE_OUTPUT
        else:
            jack_port.mode = PORT_MODE_NULL

        portTypeStr = str(jacklib.port_type(portPtr), encoding="utf-8")
        if portTypeStr == jacklib.JACK_DEFAULT_AUDIO_TYPE:
            jack_port.type = PORT_TYPE_AUDIO
        elif portTypeStr == jacklib.JACK_DEFAULT_MIDI_TYPE:
            jack_port.type = PORT_TYPE_MIDI
        else:
            jack_port.type = PORT_TYPE_NULL

        jack_port.is_new = True

        port_list.append(jack_port)

        if jacklib.port_flags(portPtr) & jacklib.JackPortIsInput:
            continue

        portConnectionNames = c_char_p_p_to_list(
                                jacklib.port_get_all_connections(jack_client,
                                                                 portPtr))

        for portConName in portConnectionNames:
            connection_list.append((portName, portConName))

    osc_server = osc_server.OscJackPatch(jack_client, port_list, connection_list)
    write_existence_file(osc_server.port)
    osc_server.start()
    
    if len(sys.argv) > 1:
        for gui_url in sys.argv[1:]:
            osc_server.add_gui(gui_url)

    app = QCoreApplication(sys.argv)

    #needed for signals SIGINT, SIGTERM
    timer = QTimer()
    timer.start(200)
    timer.timeout.connect(lambda: None)

    app.exec()

    jacklib.deactivate(jack_client)
    jacklib.client_close(jack_client)
    remove_existence_file()
