#!/usr/bin/python3 -u

from ctypes import c_char_p
from enum import IntEnum
from queue import Queue
import os
import signal
import sys
import time
import liblo
import xml.etree.ElementTree as ET

import jacklib
from jacklib.helpers import c_char_p_p_to_list
from nsm_client_noqt import NsmThread, NsmCallback


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


class Event(IntEnum):
    PORT_ADDED = 1
    PORT_REMOVED = 2
    PORT_RENAMED = 3
    CONNECTION_ADDED = 4
    CONNECTION_REMOVED = 5


class JackPort:
    # is_new is used to prevent reconnections
    # when a disconnection has not been saved and one new port append.
    id = 0
    name = ''
    mode = PortMode.NULL
    type = PortType.NULL
    is_new = False


class MainObject:
    file_path = ''
    is_dirty = False
    pending_connection = False
    terminate = False
    
    event_queue = Queue()
    _dirty_check_asked_at = 0.0
    _connect_asked_at = 0.0
    
    def check_dirty_later(self):
        self._dirty_check_asked_at = time.time()
        
    def check_connect_later(self):
        self._connect_asked_at = time.time()
        
    def each_loop(self):
        while self.event_queue.qsize():
            event, args = self.event_queue.get()
            if event is Event.PORT_ADDED:
                port_added(*args)
            elif event is Event.PORT_REMOVED:
                port_removed(*args)
            elif event is Event.PORT_RENAMED:
                port_renamed(*args)
            elif event is Event.CONNECTION_ADDED:
                connection_added(*args)
            elif event is Event.CONNECTION_REMOVED:
                connection_removed(*args)
            
        if (self._connect_asked_at
                and time.time() - self._connect_asked_at > 0.200):
            may_make_one_connection()
            self._connect_asked_at = 0
            
        if (self._dirty_check_asked_at
                and time.time() - self._dirty_check_asked_at > 0.300):
            timer_dirty_finish()
            self._dirty_check_asked_at = 0


def b2str(src_bytes: bytes) -> str:
    return str(src_bytes, encoding="utf-8")

def signal_handler(sig, frame):
    if sig in (signal.SIGINT, signal.SIGTERM):
        main_object.terminate = True

def set_dirty_clean():
    main_object.is_dirty = False
    nsm_server.send_dirty_state(False)

def timer_dirty_finish():
    if main_object.is_dirty:
        return

    if main_object.pending_connection:
        main_object.check_dirty_later()
        return

    if is_dirty_now():
        main_object.is_dirty = True
        nsm_server.send_dirty_state(True)

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

# ---- JACK callbacks executed in JACK thread -----

def jack_shutdown_callback(arg=None) -> int:
    main_object.terminate = True
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
        main_object.event_queue.put(
            (Event.PORT_ADDED, (port_name, port_mode, port_type)))
    else:
        main_object.event_queue.put(
            (Event.PORT_REMOVED, (port_name, port_mode, port_type)))

    return 0

def jack_port_rename_callback(
        port_id, old_name: c_char_p, new_name: c_char_p, arg=None) -> int:
    port_ptr = jacklib.port_by_id(jack_client, port_id)
    port_flags = jacklib.port_flags(port_ptr)

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

    main_object.event_queue.put(
        (Event.PORT_RENAMED,
         (b2str(old_name), b2str(new_name), port_mode, port_type))
    )
    return 0

def jack_port_connect_callback(port_id_a, port_id_b, connect: bool, arg=None) -> int:
    port_ptr_a = jacklib.port_by_id(jack_client, port_id_a)
    port_ptr_b = jacklib.port_by_id(jack_client, port_id_b)

    port_str_a = jacklib.port_name(port_ptr_a)
    port_str_b = jacklib.port_name(port_ptr_b)

    main_object.event_queue.put(
        (Event.CONNECTION_ADDED if connect else Event.CONNECTION_REMOVED,
         (port_str_a, port_str_b))
    )

    return 0

# --- end of JACK callbacks ----

def port_added(port_name: str, port_mode: int, port_type: int):
    port = JackPort()
    port.name = port_name
    port.mode = PortMode(port_mode)
    port.type = PortType(port_type)
    port.is_new = True

    jack_ports[port_mode].append(port)
    main_object.check_connect_later()

def port_removed(port_name: str, port_mode: PortMode, port_type: PortType):
    for port in jack_ports[port_mode]:
        if port.name == port_name and port.type == port_type:
            jack_ports[port_mode].remove(port)
            break

def port_renamed(old_name: str, new_name: str,
                 port_mode: PortMode, port_type: PortType):
    for port in jack_ports[port_mode]:
        if port.name == old_name and port.type == port_type:
            port.name = new_name
            port.is_new = True
            main_object.check_connect_later()
            break
    
def connection_added(port_str_a: str, port_str_b: str):
    connection_list.append((port_str_a, port_str_b))

    if main_object.pending_connection:
        may_make_one_connection()

    if (port_str_a, port_str_b) not in saved_connections:
        main_object.check_dirty_later()

def connection_removed(port_str_a, port_str_b):
    if (port_str_a, port_str_b) in connection_list:
        connection_list.remove((port_str_a, port_str_b))

    main_object.check_dirty_later()

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

# ---- NSM callbacks ----

def open_file(project_path: str, session_name: str, full_client_id: str):
    saved_connections.clear()

    file_path = project_path + '.xml'
    main_object.file_path = file_path

    if os.path.isfile(file_path):
        try:
            tree = ET.parse(file_path)
        except:
            sys.stderr.write('unable to read file %s\n' % file_path)
            main_object.terminate = True
            return
        
        # read the DOM
        
        root = tree.getroot()
        if root.tag != 'RAY-JACKPATCH':
            nsm_server.open_reply()
            return
        
        graph_ports = dict[PortMode, list[str]]()
        for port_mode in PortMode:
            graph_ports[port_mode] = list[str]()
        
        for child in root:
            if child.tag == 'connection':
                port_from: str = child.attrib.get('from')
                port_to: str = child.attrib.get('to')
                if not port_from and port_to:
                    #TODO print something
                    continue
                saved_connections.append((port_from, port_to))
        
            elif child.tag == 'graph':
                for gp in child:
                    if gp.tag != 'group':
                        continue
                    gp_name = gp.attrib['name']
                    for pt in gp:
                        if pt.tag == 'out_port':
                            graph_ports[PortMode.OUTPUT].append(
                                ':'.join((gp_name, pt.attrib['name'])))
                        elif pt.tag == 'in_port':
                            graph_ports[PortMode.INPUT].append(
                                ':'.join((gp_name, pt.attrib['name'])))

        # re-declare all ports as new in case we are switching session
        for port_mode in PortMode:
            for port in jack_ports[port_mode]:
                port.is_new = True

        # disconnect connections not existing at last save
        # if their both ports were present in the graph.
        for conn in connection_list:
            if (conn not in saved_connections
                    and conn[0] in graph_ports[PortMode.OUTPUT]
                    and conn[1] in graph_ports[PortMode.INPUT]):
                jacklib.disconnect(jack_client, *conn)

        may_make_one_connection()

    nsm_server.open_reply()
    set_dirty_clean()
    main_object.check_dirty_later()

def save_file():
    if not main_object.file_path:
        return

    for connection in connection_list:
        if not connection in saved_connections:
            saved_connections.append(connection)

    # delete from saved connected all connections when there ports are present
    # and not currently connected    
    del_list = list[tuple[str, str]]()

    for sv_con in saved_connections:
        if (not sv_con in connection_list
                and sv_con[0] in [p.name for p in jack_ports[PortMode.OUTPUT]]
                and sv_con[1] in [p.name for p in jack_ports[PortMode.INPUT]]):
            del_list.append(sv_con)
            
    for del_con in del_list:
        saved_connections.remove(del_con)

    # write the XML file
    root = ET.Element('RAY-JACKPATCH')
    for sv_con in saved_connections:
        conn_el = ET.SubElement(root, 'connection')
        conn_el.attrib['from'], conn_el.attrib['to'] = sv_con
    
    graph = ET.SubElement(root, 'graph')
    group_names = dict[str, ET.Element]()

    for port_mode in PortMode:
        if port_mode is PortMode.NULL:
            continue
        
        el_name = 'in_port' if port_mode is PortMode.INPUT else 'out_port'
        
        for out_port in jack_ports[port_mode]:
            gp_name, colon, port_name = out_port.name.partition(':')
            if group_names.get(gp_name) is None:
                group_names[gp_name] = ET.SubElement(graph, 'group')
                group_names[gp_name].attrib['name'] = gp_name

            out_port_el = ET.SubElement(group_names[gp_name], el_name)
            out_port_el.attrib['name'] = port_name
    
    if sys.version_info >= (3, 9):
        # we can indent the xml tree since python3.9
        ET.indent(root, space='  ', level=0)

    tree = ET.ElementTree(root)
    try:
        tree.write(main_object.file_path)
    except:
        sys.stderr.write('unable to write file %s\n' % main_object.file_path)
        main_object.terminate = True
        return

    nsm_server.save_reply()
    set_dirty_clean()

def monitor_client_state(client_id: str, is_started: int):
    print('bullo', client_id, bool(is_started))
    

# --- end of NSM callbacks --- 

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

    nsm_server = NsmThread(daemon_address)
    nsm_server.set_callback(NsmCallback.OPEN, open_file)
    nsm_server.set_callback(NsmCallback.SAVE, save_file)
    nsm_server.set_callback(NsmCallback.MONITOR_CLIENT_STATE, monitor_client_state)
    nsm_server.announce('JACK Connections', ':dirty:switch:monitor:', 'ray-jackpatch')

    #connect program interruption signals
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    fill_ports_and_connections()
    
    while True:
        if main_object.terminate:
            break
        
        nsm_server.recv(50)
        main_object.each_loop()

    jacklib.deactivate(jack_client)
    jacklib.client_close(jack_client)
