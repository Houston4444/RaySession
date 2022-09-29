#!/usr/bin/python3 -u

from enum import IntEnum
import os
import signal
import sys
import liblo

from PyQt5.QtCore import (QCoreApplication, QObject, QTimer,
                          pyqtSignal, pyqtSlot)
from PyQt5.QtXml import QDomDocument

import jacklib
from jacklib.helpers import c_char_p_p_to_list
import nsm_client


class PortMode(IntEnum):
    NULL = 0
    OUTPUT = 1
    INPUT = 2


# It is here if we want to improve the saved file
# with the type of the port.
# At this stage, we only care about the port name.
class PortType(IntEnum):
    NULL = 0
    AUDIO = 1
    MIDI = 2


class JackPort:
    # is_new is used to prevent reconnections
    # when a disconnection has not been saved and one new port append.
    id = 0
    name = ''
    mode = PortMode.NULL
    type = PortType.NULL
    is_new = False


class ConnectTimer(QObject):
    def __init__(self):
        self.timer = QTimer()
        self.timer.setInterval(200)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(connect_timer_finished)

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
    
    def connect_signals(self):
        self.port_added.connect(port_added)
        self.port_removed.connect(port_removed)
        self.port_renamed.connect(port_renamed)
        self.connection_added.connect(connection_added)
        self.connection_removed.connect(connection_removed)
        self.server_sends_open.connect(open_file)
        self.server_sends_save.connect(save_file)


class MainObject:
    file_path = ''
    is_dirty = False
    pending_connection = False
    

def b2str(src_bytes: bytes) -> str:
    return str(src_bytes, encoding="utf-8")

def signal_handler(sig, frame):
    if sig in (signal.SIGINT, signal.SIGTERM):
        app.quit()

def set_dirty_clean():
    main_object.is_dirty = False
    nsm_server.sendDirtyState(False)

@pyqtSlot()
def timer_dirty_finish():
    if main_object.is_dirty:
        return

    if main_object.pending_connection:
        dirty_checker.start()
        return

    if is_dirty_now():
        main_object.is_dirty = True
        nsm_server.sendDirtyState(True)

def is_dirty_now() -> bool:
    for conn in connection_list:
        if not conn in saved_connections:
            # There is at least a present connection unsaved
            return True

    for sv_con in saved_connections:
        if sv_con in connection_list:
            continue

        if (sv_con[0] in [p.name for p in jack_ports[PortMode.OUTPUT]]
                and sv_con[1] in [p.name for p in jack_ports[PortMode.INPUT]]):
            # There is at least a saved connection not present
            # despite the fact its two ports are present.
            return True

    return False

# ---- JACK callbacks -----

def jack_shutdown_callback(arg=None) -> int:
    app.quit()
    return 0

def jack_port_registration_callback(port_id, register: bool, arg=None) -> int:
    port_ptr = jacklib.port_by_id(jack_client, port_id)
    port_flags = jacklib.port_flags(port_ptr)
    port_name = jacklib.port_name(port_ptr)

    if port_flags & jacklib.JackPortIsInput:
        port_mode = PortMode.INPUT
    elif port_flags & jacklib.JackPortIsOutput:
        port_mode = PortMode.OUTPUT
    else:
        port_mode = PortMode.NULL

    port_type_str = jacklib.port_type(port_ptr)
    if port_type_str == jacklib.JACK_DEFAULT_AUDIO_TYPE:
        port_type = PortType.AUDIO
    elif port_type_str == jacklib.JACK_DEFAULT_MIDI_TYPE:
        port_type = PortType.MIDI
    else:
        port_type = PortType.NULL

    if register:
        signaler.port_added.emit(port_name, port_mode, port_type)
    else:
        signaler.port_removed.emit(port_name, port_mode, port_type)

    return 0

def jack_port_rename_callback(port_id, old_name, new_name, arg=None) -> int:
    port_ptr = jacklib.port_by_id(jack_client, port_id)
    port_flags = jacklib.port_flags(port_ptr)

    port_mode = PortMode.NULL

    if port_flags & jacklib.JackPortIsInput:
        port_mode = PortMode.INPUT
    elif port_flags & jacklib.JackPortIsOutput:
        port_mode = PortMode.OUTPUT

    port_type = PortType.NULL

    port_type_str = jacklib.port_type(port_ptr)
    if port_type_str == jacklib.JACK_DEFAULT_AUDIO_TYPE:
        port_type = PortType.AUDIO
    elif port_type_str == jacklib.JACK_DEFAULT_MIDI_TYPE:
        port_type = PortType.MIDI

    signaler.port_renamed.emit(
        b2str(old_name), b2str(new_name), port_mode, port_type)
    return 0

def jack_port_connect_callback(port_id_a, port_id_b, connect: bool, arg=None) -> int:
    port_ptr_a = jacklib.port_by_id(jack_client, port_id_a)
    port_ptr_b = jacklib.port_by_id(jack_client, port_id_b)

    port_str_a = jacklib.port_name(port_ptr_a)
    port_str_b = jacklib.port_name(port_ptr_b)

    if connect:
        signaler.connection_added.emit(port_str_a, port_str_b)
    else:
        signaler.connection_removed.emit(port_str_a, port_str_b)

    return 0

# ----------------------

@pyqtSlot(str, int, int)
def port_added(port_name: str, port_mode: int, port_type: int):
    port = JackPort()
    port.name = port_name
    port.mode = PortMode(port_mode)
    port.type = PortType(port_type)
    port.is_new = True

    jack_ports[port_mode].append(port)

    connect_timer.start()

@pyqtSlot(str, int, int)
def port_removed(port_name, port_mode, port_type):
    for port in jack_ports[port_mode]:
        if port.name == port_name and port.type == port_type:
            jack_ports[port_mode].remove(port)
            break

@pyqtSlot(str, str, int, int)
def port_renamed(old_name, new_name, port_mode, port_type):
    for port in jack_ports[port_mode]:
        if port.name == old_name and port.type == port_type:
            port.name = new_name
            port.is_new = True
            connect_timer.start()
            break
    
@pyqtSlot(str, str)
def connection_added(port_str_a: str, port_str_b: str):
    connection_list.append((port_str_a, port_str_b))

    if main_object.pending_connection:
        may_make_one_connection()

    if (port_str_a, port_str_b) not in saved_connections:
        dirty_checker.start()

@pyqtSlot(str, str)
def connection_removed(port_str_a, port_str_b):
    if (port_str_a, port_str_b) in connection_list:
        connection_list.remove((port_str_a, port_str_b))

    dirty_checker.start()

@pyqtSlot()
def connect_timer_finished():
    may_make_one_connection()

def may_make_one_connection():
    output_ports = [p.name for p in jack_ports[PortMode.OUTPUT]]
    input_ports = [p.name for p in jack_ports[PortMode.INPUT]]
    new_output_ports = [p.name for p in jack_ports[PortMode.OUTPUT] if p.is_new]
    new_input_ports = [p.name for p in jack_ports[PortMode.INPUT] if p.is_new]

    one_connected = False

    for sv_con in saved_connections:
        if (not sv_con in connection_list
                and sv_con[0] in output_ports
                and sv_con[1] in input_ports
                and (sv_con[0] in new_output_ports
                     or sv_con[1] in new_input_ports)):

            if one_connected:
                main_object.pending_connection = True
                break
            
            jacklib.connect(jack_client, *sv_con)
            one_connected = True
    else:
        main_object.pending_connection = False

        for port_mode in PortMode:
            for port in jack_ports[port_mode]:
                port.is_new = False

@pyqtSlot(str, str, str)
def open_file(project_path: str, session_name, full_client_id):
    saved_connections.clear()

    file_path = project_path + '.xml'
    main_object.file_path = file_path

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
            nsm_server.openReply()
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

        may_make_one_connection()

    nsm_server.openReply()
    set_dirty_clean()
    dirty_checker.start()

@pyqtSlot()
def save_file():
    if not main_object.file_path:
        return

    for connection in connection_list:
        if not connection in saved_connections:
            saved_connections.append(connection)
    
    del_list = list[tuple[str, str]]()
    
    for sv_con in saved_connections:
        if (not sv_con in connection_list
                and sv_con[0] in [p.name for p in jack_ports[PortMode.OUTPUT]]
                and sv_con[1] in [p.name for p in jack_ports[PortMode.INPUT]]):
            del_list.append(sv_con)
            
    for del_con in del_list:
        saved_connections.remove(del_con)
    
    try:
        file = open(main_object.file_path, 'w')
    except:
        sys.stderr.write('unable to write file %s\n' % main_object.file_path)
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

    nsm_server.saveReply()

    set_dirty_clean()

def fill_ports_and_connections():
    ''' get all current JACK ports and connections at startup '''
    port_name_list = c_char_p_p_to_list(
        jacklib.get_ports(jack_client, "", "", 0))

    for port_name in port_name_list:
        jack_port = JackPort()
        jack_port.name = port_name

        port_ptr = jacklib.port_by_name(jack_client, port_name)
        port_flags = jacklib.port_flags(port_ptr)

        if port_flags & jacklib.JackPortIsInput:
            jack_port.mode = PortMode.INPUT
        elif port_flags & jacklib.JackPortIsOutput:
            jack_port.mode = PortMode.OUTPUT
        else:
            jack_port.mode = PortMode.NULL

        port_type_str = jacklib.port_type(port_ptr)
        if port_type_str == jacklib.JACK_DEFAULT_AUDIO_TYPE:
            jack_port.type = PortType.AUDIO
        elif port_type_str == jacklib.JACK_DEFAULT_MIDI_TYPE:
            jack_port.type = PortType.MIDI
        else:
            jack_port.type = PortType.NULL

        jack_port.is_new = True

        jack_ports[jack_port.mode].append(jack_port)

        if jack_port.mode is PortMode.OUTPUT:
            port_connection_names = jacklib.port_get_all_connections(
                jack_client, port_ptr)

            for port_con_name in port_connection_names:
                connection_list.append((port_name, port_con_name))


if __name__ == '__main__':
    nsm_url = os.getenv('NSM_URL')
    if not nsm_url:
        sys.stderr.write('Could not register as NSM client.\n')
        sys.exit(1)

    try:
        daemon_address = liblo.Address(nsm_url)
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
    
    main_object = MainObject()
    connection_list = list[tuple[str, str]]()
    saved_connections = list[tuple[str, str]]()
    jack_ports = dict[PortMode, list[JackPort]]()
    for port_mode in PortMode:
        jack_ports[port_mode] = list[JackPort]()

    jacklib.set_port_registration_callback(
        jack_client, jack_port_registration_callback, None)
    jacklib.set_port_connect_callback(
        jack_client, jack_port_connect_callback, None)
    jacklib.set_port_rename_callback(
        jack_client, jack_port_rename_callback, None)
    jacklib.on_shutdown(jack_client, jack_shutdown_callback, None)
    jacklib.activate(jack_client)

    signaler = Signaler()
    signaler.connect_signals()

    nsm_server = nsm_client.NSMThread('ray-jackpatch', signaler,
                                      daemon_address, False)
    nsm_server.start()
    nsm_server.announce('JACK Connections', ':dirty:switch:', 'ray-jackpatch')

    #connect program interruption signals
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    fill_ports_and_connections()

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
