#!/usr/bin/python3 -u

# ray-jackpatch is an executable launchable in NSM (or Ray) session.
# It restores JACK connections.
# To avoid many problems, the connection processus is slow.
# Connections are made one by one, waiting to receive from jack
# the callback that a connection has been made to make the 
# following one.
# It also disconnects connections undesired in the session.
# To determinate that a connection is undesired, all the present ports
# are saved in the save file. If a connection is not saved in the file,
# and its ports were present at save time, this connection will be disconnected
# at session open.
# This disconnect behavior is (probably) not suitable if we start the 
# ray-jackpatch client once the session is already loaded.
# The only way we've got to know that the entire session is opening, 
# is to check if session_is_loaded message is received.


import os
import signal
import sys
import liblo
import logging
import xml.etree.ElementTree as ET

import jacklib
from jacklib.helpers import c_char_p_p_to_list
from jacklib.api import JackPortFlags, JackOptions
from nsm_client_noqt import NsmServer, NsmCallback, Err
from bases import (EventHandler, MonitorStates, PortMode, PortType,
                   Event, JackPort, Timer, Glob, debug_conn_str)
from jack_renaming_tools import (
    port_belongs_to_client, port_name_client_replaced)
import jack_callbacks

_logger = logging.getLogger(__name__)
_logger.setLevel(logging.DEBUG)

present_client_names = set[str]()
brothers_dict = dict[str, str]()
connection_list = list[tuple[str, str]]()
saved_connections = list[tuple[str, str]]()
to_disc_connections = list[tuple[str, str]]()
jack_ports = dict[PortMode, list[JackPort]]()
for port_mode in (PortMode.NULL, PortMode.INPUT, PortMode.OUTPUT):
    jack_ports[port_mode] = list[JackPort]()

def signal_handler(sig, frame):
    if sig in (signal.SIGINT, signal.SIGTERM):
        Glob.terminate = True

def set_dirty_clean():
    Glob.is_dirty = False
    nsm_server.send_dirty_state(False)

def timer_dirty_finished():
    if Glob.is_dirty:
        return

    if Glob.pending_connection:
        timer_dirty_check.start()
        return

    if is_dirty_now():
        Glob.is_dirty = True
        nsm_server.send_dirty_state(True)
    elif not Glob.dirty_state_sent:
        nsm_server.send_dirty_state(False)
        Glob.dirty_state_sent = True

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
            # There is at least one saved connection not present
            # despite the fact its two ports are present.
            return True

    return False

def port_added(port_name: str, port_mode: int, port_type: int):
    port = JackPort()
    port.name = port_name
    port.mode = PortMode(port_mode)
    port.type = PortType(port_type)
    port.is_new = True

    jack_ports[port_mode].append(port)
    present_client_names.add(port_name.partition(':')[0])
    timer_connect_check.start()

def port_removed(port_name: str, port_mode: PortMode, port_type: PortType):
    for port in jack_ports[port_mode]:
        if port.name == port_name and port.type == port_type:
            jack_ports[port_mode].remove(port)
            break
    
    else:
        # strange, but in some cases,
        # JACK does not sends the good port mode at remove time.
        for pmode in (PortMode.INPUT, PortMode.OUTPUT):
            if pmode is port_mode:
                continue
            
            for port in jack_ports[pmode]:
                if port.name == port_name and port.type == port_type:
                    jack_ports[pmode].remove(port)
                    break
            break

def port_renamed(old_name: str, new_name: str,
                 port_mode: PortMode, port_type: PortType):
    for port in jack_ports[port_mode]:
        if port.name == old_name and port.type == port_type:
            port.name = new_name
            port.is_new = True
            timer_connect_check.start()
            break
    
def connection_added(port_str_a: str, port_str_b: str):
    connection_list.append((port_str_a, port_str_b))

    if Glob.pending_connection:
        may_make_one_connection()

    if (port_str_a, port_str_b) not in saved_connections:
        timer_dirty_check.start()
        
def connection_removed(port_str_a, port_str_b):
    if (port_str_a, port_str_b) in connection_list:
        connection_list.remove((port_str_a, port_str_b))

    if to_disc_connections:
        may_make_one_connection()

    timer_dirty_check.start()

def may_make_one_connection():
    if Glob.allow_disconnections:
        if to_disc_connections:
            for to_disc_con in to_disc_connections:
                if to_disc_con in connection_list:
                    jacklib.disconnect(jack_client, *to_disc_con)
                    return
            else:
                to_disc_connections.clear()

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
                Glob.pending_connection = True
                break

            jacklib.connect(jack_client, *sv_con)
            one_connected = True
    else:
        Glob.pending_connection = False

        for port_mode in (PortMode.INPUT, PortMode.OUTPUT):
            for port in jack_ports[port_mode]:
                port.is_new = False

# ---- NSM callbacks ----

def open_file(project_path: str, session_name: str,
              full_client_id: str) -> tuple[Err, str]:
    saved_connections.clear()

    file_path = project_path + '.xml'
    Glob.file_path = file_path

    if os.path.isfile(file_path):
        try:
            tree = ET.parse(file_path)
        except:
            sys.stderr.write('unable to read file %s\n' % file_path)
            # Glob.terminate = True
            return (Err.BAD_PROJECT, f'{file_path} is not a correct .xml file')
        
        # read the DOM
        root = tree.getroot()
        if root.tag != 'RAY-JACKPATCH':
            return (Err.BAD_PROJECT, f'{file_path} is not a RAY-JACKPATCH .xml file')
        
        graph_ports = dict[PortMode, list[str]]()
        for port_mode in (PortMode.INPUT, PortMode.OUTPUT):
            graph_ports[port_mode] = list[str]()
        
        for child in root:
            if child.tag == 'connection':
                port_from: str = child.attrib.get('from')
                port_to: str = child.attrib.get('to')
                nsm_client_from: str = child.attrib.get('nsm_client_from')
                nsm_client_to: str = child.attrib.get('nsm_client_to')

                if not port_from and port_to:
                    _logger.warning(
                        f"{debug_conn_str((port_from, port_to))} is incomplete.")
                    continue

                # ignore connection if NSM client has been definitely removed
                if Glob.monitor_states_done is MonitorStates.DONE:
                    if nsm_client_from and not nsm_client_from in brothers_dict.keys():
                        _logger.info(
                            f"{debug_conn_str((port_from, port_to))} is removed "
                            f"because NSM client {nsm_client_from} has been removed")
                        continue
                    if nsm_client_to and not nsm_client_to in brothers_dict.keys():
                        _logger.info(
                            f"{debug_conn_str((port_from, port_to))} is removed "
                            f"because NSM client {nsm_client_to} has been removed")
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
        for port_mode in (PortMode.INPUT, PortMode.OUTPUT):
            for port in jack_ports[port_mode]:
                port.is_new = True

        to_disc_connections.clear()
        # disconnect connections not existing at last save
        # if their both ports were present in the graph.
        for conn in connection_list:
            if (conn not in saved_connections
                    and conn[0] in graph_ports[PortMode.OUTPUT]
                    and conn[1] in graph_ports[PortMode.INPUT]):
                to_disc_connections.append(conn)

        if Glob.open_done_once:
            Glob.allow_disconnections = True

        may_make_one_connection()

    Glob.is_dirty = False
    Glob.open_done_once = True
    timer_dirty_check.start()
    return (Err.OK, '')

def save_file():
    if not Glob.file_path:
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
        jack_con_from_name = sv_con[0].partition(':')[0].partition('/')[0]
        jack_con_to_name = sv_con[1].partition(':')[0].partition('/')[0]
        for key, value in brothers_dict.items():
            if jack_con_from_name == value:
                conn_el.attrib['nsm_client_from'] = key
            if jack_con_to_name == value:
                conn_el.attrib['nsm_client_to'] = key

    graph = ET.SubElement(root, 'graph')
    group_names = dict[str, ET.Element]()

    for port_mode in (PortMode.INPUT, PortMode.OUTPUT):
        el_name = 'in_port' if port_mode is PortMode.INPUT else 'out_port'

        for jack_port in jack_ports[port_mode]:
            gp_name, colon, port_name = jack_port.name.partition(':')
            if group_names.get(gp_name) is None:
                group_names[gp_name] = ET.SubElement(graph, 'group')
                group_names[gp_name].attrib['name'] = gp_name

                gp_base_name = gp_name.partition('/')[0]
                for key, value in brothers_dict.items():
                    if value == gp_base_name:
                        group_names[gp_name].attrib['nsm_client'] = key
                        break

            out_port_el = ET.SubElement(group_names[gp_name], el_name)
            out_port_el.attrib['name'] = port_name
    
    if sys.version_info >= (3, 9):
        # we can indent the xml tree since python3.9
        ET.indent(root, space='  ', level=0)

    tree = ET.ElementTree(root)
    try:
        tree.write(Glob.file_path)
    except:
        sys.stderr.write('unable to write file %s\n' % Glob.file_path)
        Glob.terminate = True
        return

    set_dirty_clean()
    return (Err.OK, 'Done')

def monitor_client_state(client_id: str, jack_name: str, is_started: int):
    print('MONST', client_id, jack_name, is_started)
    
    if Glob.monitor_states_done is not MonitorStates.UPDATING:
        brothers_dict.clear()

    Glob.monitor_states_done = MonitorStates.UPDATING
    
    if client_id:
        brothers_dict[client_id] = jack_name
        
        if (Glob.client_changing_id is not None
                and Glob.client_changing_id[1] == client_id):
            # we are here only in the case a client id was just changed
            # we modify the saved connections in consequence.
            # Note that this client can't be started.
            ex_jack_name = Glob.client_changing_id[0]
            rm_conns = list[tuple[str, str]]()
            new_conns = list[tuple[str, str]]()

            for conn in saved_connections:
                out_port, in_port = conn
                if (port_belongs_to_client(out_port, ex_jack_name)
                        or port_belongs_to_client(in_port, ex_jack_name)):
                    rm_conns.append(conn)
                    new_conns.append(
                        (port_name_client_replaced(
                            out_port, ex_jack_name, jack_name),
                         port_name_client_replaced(
                             in_port, ex_jack_name, jack_name)))

            for conn in rm_conns:
                saved_connections.remove(conn)
            saved_connections.extend(new_conns)
            Glob.client_changing_id = None
        
    else:
        n_clients = is_started
        if len(brothers_dict) != n_clients:
            _logger.warning('list of monitored clients is incomplete !')
            ## following line would be the most obvious thing to do,
            ## but in case of problem, we could have an infinite messages loop 
            # nsm_server.send_monitor_reset()
            return

        Glob.monitor_states_done = MonitorStates.DONE

def monitor_client_event(client_id: str, event: str):
    # TODO remove stopping_brothers key and all
    # it was a test to see if session quit fails less
    # if ray-jackpatch is the last client to stop.

    if event == 'stop_request':
        if (client_id in brothers_dict
                and brothers_dict[client_id]
                    in [c.partition('/')[0] for c in present_client_names]):        
            Glob.stopping_brothers.add(client_id)

    elif event in ('stopped_by_server', 'stopped_by_itself'):
        if client_id in Glob.stopping_brothers:
            Glob.stopping_brothers.remove(client_id)

    elif event == 'removed':
        if client_id in brothers_dict:
            jack_client_name = brothers_dict.pop(client_id)
        else:
            return
        
        # remove all saved connections from and to its client
        conns_to_unsave = list[tuple[str, str]]()
            
        for conn in saved_connections:
            out_port, in_port = conn
            if (port_belongs_to_client(out_port, jack_client_name)
                    or port_belongs_to_client(in_port, jack_client_name)):
                conns_to_unsave.append(conn)
        
        for conn in conns_to_unsave:
            saved_connections.remove(conn)

    elif event.startswith('id_changed_to:'):
        if client_id in brothers_dict.keys():
            Glob.client_changing_id = (
                brothers_dict[client_id], event.partition(':')[2])
        nsm_server.send_monitor_reset()

def session_is_loaded():
    Glob.allow_disconnections = True
    may_make_one_connection()

# --- end of NSM callbacks --- 

def fill_ports_and_connections():
    '''get all current JACK ports and connections at startup'''
    port_name_list = c_char_p_p_to_list(
        jacklib.get_ports(jack_client, "", "", 0))

    for port_name in port_name_list:
        jack_port = JackPort()
        jack_port.name = port_name
        
        present_client_names.add(port_name.partition(':')[0])

        port_ptr = jacklib.port_by_name(jack_client, port_name)
        port_flags = jacklib.port_flags(port_ptr)

        if port_flags & JackPortFlags.IS_INPUT:
            jack_port.mode = PortMode.INPUT
        elif port_flags & JackPortFlags.IS_OUTPUT:
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
            for port_con_name in jacklib.port_get_all_connections(
                    jack_client, port_ptr):
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
        "ray-jackpatch",
        JackOptions.NO_START_SERVER,
        None)

    if not jack_client:
        sys.stderr.write('Unable to make a jack client !\n')
        sys.exit(2)
    
    timer_dirty_check = Timer(0.300)
    timer_connect_check = Timer(0.200)

    jack_callbacks.set_callbacks(jack_client)
    jacklib.activate(jack_client)

    nsm_server = NsmServer(daemon_address)
    nsm_server.set_callback(NsmCallback.OPEN, open_file)
    nsm_server.set_callback(NsmCallback.SAVE, save_file)
    nsm_server.set_callback(NsmCallback.MONITOR_CLIENT_STATE, monitor_client_state)
    nsm_server.set_callback(NsmCallback.MONITOR_CLIENT_EVENT, monitor_client_event)
    nsm_server.set_callback(NsmCallback.SESSION_IS_LOADED, session_is_loaded)
    nsm_server.announce('JACK Connections', ':dirty:switch:monitor:', 'ray-jackpatch')
    
    #connect program interruption signals
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    fill_ports_and_connections()
    
    jack_stopped = False
    
    while True:
        if Glob.terminate:
        # if Glob.terminate and not Glob.stopping_brothers:
            break

        nsm_server.recv(50)
        for event, args in EventHandler.new_events():
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
            elif event is Event.JACK_STOPPED:
                jack_stopped = True
                break
        
        if timer_dirty_check.elapsed():
            timer_dirty_finished()
        
        if timer_connect_check.elapsed():
            may_make_one_connection()

    if not jack_stopped:
        jacklib.deactivate(jack_client)
        jacklib.client_close(jack_client)
