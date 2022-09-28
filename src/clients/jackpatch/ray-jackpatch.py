#!/usr/bin/python3 -u

import os
import signal
import sys

from PyQt5.QtCore import QCoreApplication, QObject, QTimer, pyqtSignal
from PyQt5.QtXml import QDomDocument

import jacklib
import nsm_client
import liblo

PORT_MODE_OUTPUT = 0
PORT_MODE_INPUT = 1
PORT_MODE_NULL = 2

PORT_TYPE_AUDIO = 0
PORT_TYPE_MIDI = 1
PORT_TYPE_NULL = 2


class JackPort:
    # is_new is used to prevent reconnections
    # when a disconnection has not been saved and one new port append.
    id = 0
    name = ''
    mode = PORT_MODE_NULL
    type = PORT_TYPE_NULL
    is_new = False


class ConnectTimer(QObject):
    def __init__(self):
        self.timer = QTimer()
        self.timer.setInterval(200)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(may_make_connections)

    def start(self):
        self.timer.start()


class DirtyChecker(QObject):
    timer = QTimer()

    def __init__(self):
        self.timer.setInterval(500)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(timer_dirty_finish)

    def start(self):
        self.timer.start()


class Signaler(nsm_client.NSMSignaler):
    port_added = pyqtSignal(str, int, int)
    port_removed = pyqtSignal(str, int, int)
    port_renamed = pyqtSignal(str, str, int, int)
    connection_added = pyqtSignal(str, str)
    connection_removed = pyqtSignal(str, str)


def signal_handler(sig, frame):
    if sig in (signal.SIGINT, signal.SIGTERM):
        app.quit()

def port_exists(name: str, mode: int) -> bool:
    for port in port_list:
        if port.name == name and port.mode == mode:
            return True
    return False

def set_dirty_clean():
    global is_dirty
    is_dirty = False
    NSMServer.sendDirtyState(False)

def timer_dirty_finish():
    global is_dirty

    if is_dirty:
        return

    if is_dirty_now():
        is_dirty = True
        NSMServer.sendDirtyState(True)

def is_dirty_now() -> bool:
    for connection in connection_list:
        if not connection in saved_connections:
            return True

    output_ports = list[str]()
    input_ports = list[str]()

    for port in port_list:
        if port.mode == PORT_MODE_OUTPUT:
            output_ports.append(port.name)
        elif port.mode == PORT_MODE_INPUT:
            input_ports.append(port.name)

    for connection in saved_connections:
        if connection in connection_list:
            continue

        if connection[0] in output_ports and connection[1] in input_ports:
            return True

    return False

def jack_shutdown_callback(arg=None) -> int:
    app.quit()
    return 0

def jack_port_registration_callback(portId, registerYesNo, arg=None) -> int:
    portPtr = jacklib.port_by_id(jack_client, portId)
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
        signaler.port_added.emit(port_name, port_mode, port_type)
    else:
        signaler.port_removed.emit(port_name, port_mode, port_type)

    return 0

def jack_port_rename_callback(portId, oldName, newName, arg=None) -> int:
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

def jack_port_connect_callback(port_id_A, port_id_B, connect_yesno, arg=None) -> int:
    port_ptr_A = jacklib.port_by_id(jack_client, port_id_A)
    port_ptr_B = jacklib.port_by_id(jack_client, port_id_B)

    port_str_A = str(jacklib.port_name(port_ptr_A), encoding="utf-8")
    port_str_B = str(jacklib.port_name(port_ptr_B), encoding="utf-8")

    if connect_yesno:
        signaler.connection_added.emit(port_str_A, port_str_B)
    else:
        signaler.connection_removed.emit(port_str_A, port_str_B)

    return 0

def port_added(port_name, port_mode, port_type):
    port = JackPort()
    port.name = port_name
    port.mode = port_mode
    port.type = port_type
    port.is_new = True

    port_list.append(port)

    connect_timer.start()

def port_removed(port_name, port_mode, port_type):
    for i in range(len(port_list)):
        port = port_list[i]
        if (port.name == port_name
                and port.mode == port_mode
                and port.type == port_type):
            break
    else:
        return

    port_list.__delitem__(i)

def port_renamed(old_name, new_name, port_mode, port_type):
    for port in port_list:
        if (port.name == old_name
                and port.mode == port_mode
                and port.type == port_type):
            port.name = new_name
            port.is_new = True
            connect_timer.start()
            break

def connection_added(port_str_A: str, port_str_B: str):
    connection_list.append((port_str_A, port_str_B))

    if pending_connection:
        may_make_connections()

    if (port_str_A, port_str_B) not in saved_connections:
        dirty_checker.start()

def connection_removed(port_str_A, port_str_B):
    for i in range(len(connection_list)):
        if (connection_list[i][0] == port_str_A
                and connection_list[i][1] == port_str_B):
            connection_list.__delitem__(i)
            break

    dirty_checker.start()

def make_all_saved_connections(port: JackPort):
    if port.mode == PORT_MODE_OUTPUT:
        connect_all_inputs(port)
    elif port.mode == PORT_MODE_INPUT:
        connect_all_outputs(port)

def connect_all_inputs(port: JackPort):
    if port.mode != PORT_MODE_OUTPUT:
        return

    input_ports = list[str]()

    for jack_port in port_list:
        if jack_port.mode == PORT_MODE_INPUT:
            input_ports.append(jack_port.name)

    for connection in saved_connections:
        if connection in connection_list:
            continue

        if connection[0] == port.name and connection[1] in input_ports:
            jacklib.connect(jack_client, port.name, connection[1])

def connect_all_outputs(port: JackPort):
    if port.mode != PORT_MODE_INPUT:
        return

    output_ports = list[str]()

    for jack_port in port_list:
        if jack_port.mode == PORT_MODE_OUTPUT:
            output_ports.append(jack_port.name)

    for connection in saved_connections:
        if connection in connection_list:
            continue

        if connection[0] in output_ports and connection[1] == port.name:
            jacklib.connect(jack_client, connection[0], port.name)

def may_make_connections():
    output_ports = list[str]()
    input_ports = list[str]()
    new_output_ports = list[str]()
    new_input_ports = list[str]()

    for port in port_list:
        if port.mode == PORT_MODE_OUTPUT:
            output_ports.append(port.name)
            if port.is_new:
                new_output_ports.append(port.name)

        elif port.mode == PORT_MODE_INPUT:
            input_ports.append(port.name)
            if port.is_new:
                new_input_ports.append(port.name)

    global pending_connection
    one_connected = False

    for connection in saved_connections:
        if (not connection in connection_list
                and connection[0] in output_ports
                and connection[1] in input_ports
                and (connection[0] in new_output_ports
                     or connection[1] in new_input_ports)):

            if one_connected:
                pending_connection = True
                break

            jacklib.connect(jack_client, connection[0], connection[1])
            one_connected = True
    else:
        pending_connection = False

        for port in port_list:
            port.is_new = False

def c_char_p_p_to_list(c_char_p_p) -> list[str]:
    i = 0
    retList = list[str]()

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

def open_file(project_path, session_name, full_client_id):
    saved_connections.clear()

    global file_path
    file_path = "%s.xml" % project_path

    if os.path.isfile(file_path):
        try:
            file = open(file_path, 'r')
        except:
            sys.stderr.write('unable to read file %s\n' % file_path)
            app.quit()
            return

        xml = QDomDocument()
        xml.setContent(file.read())

        content = xml.documentElement()

        if content.tagName() != "RAY-JACKPATCH":
            file.close()
            NSMServer.openReply()
            return

        cte = content.toElement()
        node = cte.firstChild()

        while not node.isNull():
            el = node.toElement()
            if el.tagName() != "connection":
                continue

            port_from = el.attribute('from')
            port_to = el.attribute('to')

            saved_connections.append((port_from, port_to))

            node = node.nextSibling()

        may_make_connections()

    NSMServer.openReply()
    set_dirty_clean()
    dirty_checker.start()

def save_file():
    if not file_path:
        return

    for connection in connection_list:
        if not connection in saved_connections:
            saved_connections.append(connection)

    delete_list = list[int]()

    # delete connection of the saved_connections
    # if its two ports are still presents and not connected
    for i in range(len(saved_connections)):
        if (port_exists(saved_connections[i][0], PORT_MODE_OUTPUT)
                and port_exists(saved_connections[i][1], PORT_MODE_INPUT)):
            if not saved_connections[i] in connection_list:
                delete_list.append(i)

    delete_list.reverse()
    for i in delete_list:
        saved_connections.__delitem__(i)

    try:
        file = open(file_path, 'w')
    except:
        sys.stderr.write('unable to write file %s\n' % file_path)
        app.quit()
        return

    xml = QDomDocument()
    p = xml.createElement('RAY-JACKPATCH')

    for con in saved_connections:
        ct = xml.createElement('connection')
        ct.setAttribute('from', con[0])
        ct.setAttribute('to', con[1])
        p.appendChild(ct)

    xml.appendChild(p)

    file.write(xml.toString())
    file.close()

    NSMServer.saveReply()

    set_dirty_clean()

if __name__ == '__main__':
    NSM_URL = os.getenv('NSM_URL')
    if not NSM_URL:
        sys.stderr.write('Could not register as NSM client.\n')
        sys.exit(1)

    try:
        daemon_address = liblo.Address(NSM_URL)
    except:
        sys.stderr.write('NSM_URL seems to be invalid.\n')
        sys.exit(1)

    jack_client = jacklib.client_open(
        "ray-patcher",
        jacklib.JackNoStartServer | jacklib.JackSessionID,
        None)

    if not jack_client:
        sys.stderr.write('Unable to make a jack client !\n')
        sys.exit(2)
        
    connection_list = list[tuple[str, str]]()
    saved_connections = list[tuple[str, str]]()
    port_list = list[JackPort]()

    file_path = ""

    is_dirty = False

    pending_connection = False

    jacklib.set_port_registration_callback(
        jack_client, jack_port_registration_callback, None)
    jacklib.set_port_connect_callback(
        jack_client, jack_port_connect_callback, None)
    jacklib.set_port_rename_callback(
        jack_client, jack_port_rename_callback, None)
    jacklib.on_shutdown(jack_client, jack_shutdown_callback, None)
    jacklib.activate(jack_client)

    signaler = Signaler()
    signaler.port_added.connect(port_added)
    signaler.port_removed.connect(port_removed)
    signaler.port_renamed.connect(port_renamed)
    signaler.connection_added.connect(connection_added)
    signaler.connection_removed.connect(connection_removed)
    signaler.server_sends_open.connect(open_file)
    signaler.server_sends_save.connect(save_file)

    NSMServer = nsm_client.NSMThread('ray-jackpatch', signaler,
                                     daemon_address, False)
    NSMServer.start()
    NSMServer.announce('JACK Connections', ':dirty:switch:', 'ray-jackpatch')

    #connect signals
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    #get all currents Jack ports and connections
    port_name_list = c_char_p_p_to_list(
        jacklib.get_ports(jack_client, "", "", 0))

    for port_name in port_name_list:
        jack_port = JackPort()
        jack_port.name = port_name

        port_ptr = jacklib.port_by_name(jack_client, port_name)
        port_flags = jacklib.port_flags(port_ptr)

        if port_flags & jacklib.JackPortIsInput:
            jack_port.mode = PORT_MODE_INPUT
        elif port_flags & jacklib.JackPortIsOutput:
            jack_port.mode = PORT_MODE_OUTPUT
        else:
            jack_port.mode = PORT_MODE_NULL

        port_type_str = str(jacklib.port_type(port_ptr), encoding="utf-8")
        if port_type_str == jacklib.JACK_DEFAULT_AUDIO_TYPE:
            jack_port.type = PORT_TYPE_AUDIO
        elif port_type_str == jacklib.JACK_DEFAULT_MIDI_TYPE:
            jack_port.type = PORT_TYPE_MIDI
        else:
            jack_port.type = PORT_TYPE_NULL

        jack_port.is_new = True

        port_list.append(jack_port)

        if jacklib.port_flags(port_ptr) & jacklib.JackPortIsInput:
            continue

        port_connection_names = c_char_p_p_to_list(
            jacklib.port_get_all_connections(jack_client, port_ptr))

        for port_con_name in port_connection_names:
            connection_list.append((port_name, port_con_name))

    app = QCoreApplication(sys.argv)

    #needed for signals SIGINT, SIGTERM
    timer = QTimer()
    timer.start(200)
    timer.timeout.connect(lambda: None)

    connect_timer = ConnectTimer()
    dirty_checker = DirtyChecker()

    app.exec()

    jacklib.deactivate(jack_client)
    jacklib.client_close(jack_client)
