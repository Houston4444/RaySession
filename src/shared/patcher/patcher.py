
import logging
import os
import sys
import xml.etree.ElementTree as ET

from jack_renaming_tools import (
    port_belongs_to_client, port_name_client_replaced)
from nsm_client import NsmServer, NsmCallback, Err

from .bases import (
    Glob,
    NsmClientName,
    JackClientBaseName,
    FullPortName,
    PortMode,
    PortType,
    JackPort,
    MonitorStates,
    ProtoEngine,
    Timer,
    Event,
    debug_conn_str)

_logger = logging.getLogger(__name__)


class Patcher:
    def __init__(
            self, engine: ProtoEngine, nsm_server: NsmServer):
        self.glob = Glob()
        self.engine = engine
        self.brothers_dict = dict[NsmClientName, JackClientBaseName]()
        self.connection_list = list[tuple[FullPortName, FullPortName]]()
        self.saved_connections = list[tuple[FullPortName, FullPortName]]()
        self.to_disc_connections = list[tuple[FullPortName, FullPortName]]()
        self.jack_ports = dict[PortMode, list[JackPort]]()
        for port_mode in (PortMode.NULL, PortMode.INPUT, PortMode.OUTPUT):
            self.jack_ports[port_mode] = list[JackPort]()

        self.timer_dirty_check = Timer(0.300)
        self.timer_connect_check = Timer(0.200)
        
        self.nsm_server = nsm_server
        self.nsm_server.set_callbacks({
            NsmCallback.OPEN: self.open_file,
            NsmCallback.SAVE: self.save_file,
            NsmCallback.MONITOR_CLIENT_STATE: self.monitor_client_state,
            NsmCallback.MONITOR_CLIENT_EVENT: self.monitor_client_event,
            NsmCallback.MONITOR_CLIENT_UPDATED: self.monitor_client_updated,
            NsmCallback.SESSION_IS_LOADED: self.session_is_loaded
        })
        self.nsm_server.announce(
            self.engine.NSM_NAME, ':dirty:switch:monitor:', engine.EXECUTABLE)

    def run_loop(self):
        self.engine.fill_ports_and_connections(
            self.jack_ports, self.connection_list)
        
        jack_stopped = False

        while True:
            if self.glob.terminate:
                break

            self.nsm_server.recv(50)
            for event, args in self.engine.ev_handler.new_events():
                if event is Event.PORT_ADDED:
                    self.port_added(*args)
                elif event is Event.PORT_REMOVED:
                    self.port_removed(*args)
                elif event is Event.PORT_RENAMED:
                    self.port_renamed(*args)
                elif event is Event.CONNECTION_ADDED:
                    self.connection_added(*args)
                elif event is Event.CONNECTION_REMOVED:
                    self.connection_removed(*args)
                elif event is Event.JACK_STOPPED:
                    jack_stopped = True
                    break
            
            if self.timer_dirty_check.elapsed():
                self.timer_dirty_finished()
            
            if self.timer_connect_check.elapsed():
                self.may_make_one_connection()

        print('finiiiissh')

        if not jack_stopped:
            self.engine.quit()
            
        

    def stop(self, *args):
        print('oula stop', *args)
        self.glob.terminate = True

    def set_dirty_clean(self):
        self.glob.is_dirty = False
        self.nsm_server.send_dirty_state(False)

    def timer_dirty_finished(self):
        if self.glob.is_dirty:
            return

        if self.glob.pending_connection:
            self.timer_dirty_check.start()
            return

        if self.is_dirty_now():
            self.glob.is_dirty = True
            self.nsm_server.send_dirty_state(True)
        elif not self.glob.dirty_state_sent:
            self.nsm_server.send_dirty_state(False)
            self.glob.dirty_state_sent = True

    def is_dirty_now(self) -> bool:
        for conn in self.connection_list:
            if not conn in self.saved_connections:
                # There is at least a present connection unsaved
                return True

        for sv_con in self.saved_connections:
            if sv_con in self.connection_list:
                continue

            if (sv_con[0] in [
                        p.name for p in self.jack_ports[PortMode.OUTPUT]]
                    and sv_con[1] in [
                        p.name for p in self.jack_ports[PortMode.INPUT]]):
                # There is at least one saved connection not present
                # despite the fact its two ports are present.
                return True

        return False

    def port_added(self, port_name: str, port_mode: int, port_type: int):
        port = JackPort()
        port.name = port_name
        port.mode = PortMode(port_mode)
        port.type = PortType(port_type)
        port.is_new = True

        self.jack_ports[port.mode].append(port)
        self.timer_connect_check.start()

    def port_removed(
            self, port_name: str, port_mode: PortMode, port_type: PortType):
        for port in self.jack_ports[port_mode]:
            if port.name == port_name and port.type == port_type:
                self.jack_ports[port_mode].remove(port)
                break
        
        else:
            # strange, but in some cases,
            # JACK does not sends the good port mode at remove time.
            for pmode in (PortMode.INPUT, PortMode.OUTPUT):
                if pmode is port_mode:
                    continue
                
                for port in self.jack_ports[pmode]:
                    if port.name == port_name and port.type == port_type:
                        self.jack_ports[pmode].remove(port)
                        break
                break

    def port_renamed(
            self, old_name: str, new_name: str,
            port_mode: PortMode, port_type: PortType):
        for port in self.jack_ports[port_mode]:
            if port.name == old_name and port.type == port_type:
                port.name = new_name
                port.is_new = True
                self.timer_connect_check.start()
                break
        
    def connection_added(self, port_str_a: str, port_str_b: str):
        self.connection_list.append((port_str_a, port_str_b))

        if self.glob.pending_connection:
            self.may_make_one_connection()

        if (port_str_a, port_str_b) not in self.saved_connections:
            self.timer_dirty_check.start()
            
    def connection_removed(self, port_str_a: str, port_str_b: str):
        if (port_str_a, port_str_b) in self.connection_list:
            self.connection_list.remove((port_str_a, port_str_b))

        if self.to_disc_connections:
            self.may_make_one_connection()

        self.timer_dirty_check.start()

    def may_make_one_connection(self):
        if self.glob.allow_disconnections:
            if self.to_disc_connections:
                for to_disc_con in self.to_disc_connections:
                    if to_disc_con in self.connection_list:
                        _logger.info(f'disconnect ports: {to_disc_con}')
                        self.engine.disconnect_ports(*to_disc_con)
                        return
                else:
                    self.to_disc_connections.clear()

        output_ports = [p.name for p in self.jack_ports[PortMode.OUTPUT]]
        input_ports = [p.name for p in self.jack_ports[PortMode.INPUT]]
        new_output_ports = [p.name for p in self.jack_ports[PortMode.OUTPUT]
                            if p.is_new]
        new_input_ports = [p.name for p in self.jack_ports[PortMode.INPUT]
                           if p.is_new]

        one_connected = False

        for sv_con in self.saved_connections:
            if (not sv_con in self.connection_list
                    and sv_con[0] in output_ports
                    and sv_con[1] in input_ports
                    and (sv_con[0] in new_output_ports
                         or sv_con[1] in new_input_ports)):
                if one_connected:
                    self.glob.pending_connection = True
                    break

                _logger.info(f'connect ports: {sv_con}')
                self.engine.connect_ports(*sv_con)
                one_connected = True
        else:
            self.glob.pending_connection = False

            for port_mode in (PortMode.INPUT, PortMode.OUTPUT):
                for port in self.jack_ports[port_mode]:
                    port.is_new = False

    # ---- NSM callbacks ----

    def open_file(self, project_path: str, session_name: str,
                  full_client_id: str) -> tuple[Err, str]:
        self.saved_connections.clear()

        file_path = project_path + '.xml'
        self.glob.file_path = file_path
        _logger.info(f'open file: {file_path}')

        XML_TAG = self.engine.XML_TAG

        if os.path.isfile(file_path):
            try:
                tree = ET.parse(file_path)
            except:
                _logger.error(f'unable to read file {file_path}')
                return (Err.BAD_PROJECT,
                        f'{file_path} is not a correct .xml file')
            
            # read the DOM
            root = tree.getroot()
            if root.tag != XML_TAG:
                _logger.error(f'{file_path} is not a {XML_TAG} .xml file')
                return (Err.BAD_PROJECT,
                        f'{file_path} is not a {XML_TAG} .xml file')
            
            graph_ports = dict[PortMode, list[str]]()
            for port_mode in (PortMode.INPUT, PortMode.OUTPUT):
                graph_ports[port_mode] = list[str]()
            
            for child in root:
                if child.tag == 'connection':
                    port_from: str = child.attrib.get('from', '')
                    port_to: str = child.attrib.get('to', '')
                    nsm_client_from: str = child.attrib.get(
                        'nsm_client_from', '')
                    nsm_client_to: str = child.attrib.get(
                        'nsm_client_to', '')

                    if not port_from and port_to:
                        _logger.warning(
                            f"{debug_conn_str((port_from, port_to))} "
                            "is incomplete.")
                        continue

                    # ignore connection if NSM client
                    # has been definitely removed
                    if self.glob.monitor_states_done is MonitorStates.DONE:
                        if (nsm_client_from 
                                and nsm_client_from
                                    not in self.brothers_dict.keys()):
                            _logger.info(
                                f"{debug_conn_str((port_from, port_to))}"
                                " is removed "
                                f"because NSM client {nsm_client_from}"
                                " has been removed")
                            continue
                        if (nsm_client_to
                                and nsm_client_to 
                                    not in self.brothers_dict.keys()):
                            _logger.info(
                                f"{debug_conn_str((port_from, port_to))}"
                                " is removed "
                                f"because NSM client {nsm_client_to}"
                                " has been removed")
                            continue
                        
                    self.saved_connections.append((port_from, port_to))
            
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
                for port in self.jack_ports[port_mode]:
                    port.is_new = True

            self.to_disc_connections.clear()
            # disconnect connections not existing at last save
            # if their both ports were present in the graph.
            for conn in self.connection_list:
                if (conn not in self.saved_connections
                        and conn[0] in graph_ports[PortMode.OUTPUT]
                        and conn[1] in graph_ports[PortMode.INPUT]):
                    self.to_disc_connections.append(conn)

            if self.glob.open_done_once:
                self.glob.allow_disconnections = True

            self.may_make_one_connection()

        self.glob.is_dirty = False
        self.glob.open_done_once = True
        self.timer_dirty_check.start()
        return (Err.OK, '')

    def save_file(self):
        if not self.glob.file_path:
            return

        for connection in self.connection_list:
            if not connection in self.saved_connections:
                self.saved_connections.append(connection)

        # delete from saved connected all connections 
        # when there ports are present and not currently connected    
        del_list = list[tuple[str, str]]()

        for sv_con in self.saved_connections:
            if (not sv_con in self.connection_list
                    and sv_con[0] in [
                        p.name for p in self.jack_ports[PortMode.OUTPUT]]
                    and sv_con[1] in [
                        p.name for p in self.jack_ports[PortMode.INPUT]]):
                del_list.append(sv_con)
                
        for del_con in del_list:
            self.saved_connections.remove(del_con)

        # write the XML file
        root = ET.Element(self.engine.XML_TAG)
        for sv_con in self.saved_connections:
            conn_el = ET.SubElement(root, 'connection')
            conn_el.attrib['from'], conn_el.attrib['to'] = sv_con
            jack_con_from_name = sv_con[0].partition(':')[0].partition('/')[0]
            jack_con_to_name = sv_con[1].partition(':')[0].partition('/')[0]
            for key, value in self.brothers_dict.items():
                if jack_con_from_name == value:
                    conn_el.attrib['nsm_client_from'] = key
                if jack_con_to_name == value:
                    conn_el.attrib['nsm_client_to'] = key

        graph = ET.SubElement(root, 'graph')
        group_names = dict[str, ET.Element]()

        for port_mode in (PortMode.INPUT, PortMode.OUTPUT):
            el_name = 'in_port' if port_mode is PortMode.INPUT else 'out_port'

            for jack_port in self.jack_ports[port_mode]:
                gp_name, colon, port_name = jack_port.name.partition(':')
                if group_names.get(gp_name) is None:
                    group_names[gp_name] = ET.SubElement(graph, 'group')
                    group_names[gp_name].attrib['name'] = gp_name

                    gp_base_name = gp_name.partition('/')[0]
                    for key, value in self.brothers_dict.items():
                        if value == gp_base_name:
                            group_names[gp_name].attrib['nsm_client'] = key
                            break

                out_port_el = ET.SubElement(group_names[gp_name], el_name)
                out_port_el.attrib['name'] = port_name
        
        if sys.version_info >= (3, 9):
            # we can indent the xml tree since python3.9
            ET.indent(root, space='  ', level=0)

        print('logger info', _logger.level, _logger.parent.level)
        _logger.info(f'save file: {self.glob.file_path}')
        tree = ET.ElementTree(root)
        try:
            tree.write(self.glob.file_path)
        except:
            _logger.error(f'unable to write file {self.glob.file_path}')
            self.glob.terminate = True
            return

        self.set_dirty_clean()
        return (Err.OK, 'Done')

    def monitor_client_state(
            self, client_id: str, jack_name: str, is_started: int):
        if self.glob.monitor_states_done is not MonitorStates.UPDATING:
            self.brothers_dict.clear()

        self.glob.monitor_states_done = MonitorStates.UPDATING
        
        if client_id:
            self.brothers_dict[client_id] = jack_name
            
            if (self.glob.client_changing_id is not None
                    and self.glob.client_changing_id[1] == client_id):
                # we are here only in the case a client id was just changed
                # we modify the saved connections in consequence.
                # Note that this client can't be started.
                ex_jack_name = self.glob.client_changing_id[0]
                rm_conns = list[tuple[str, str]]()
                new_conns = list[tuple[str, str]]()

                for conn in self.saved_connections:
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
                    self.saved_connections.remove(conn)
                self.saved_connections.extend(new_conns)
                self.glob.client_changing_id = None
            
        else:
            n_clients = is_started
            if len(self.brothers_dict) != n_clients:
                _logger.warning('list of monitored clients is incomplete !')
                ## following line would be the most obvious thing to do,
                ## but in case of problem, we could have 
                # an infinite messages loop 
                # nsm_server.send_monitor_reset()
                return

            self.glob.monitor_states_done = MonitorStates.DONE

    def monitor_client_event(self, client_id: str, event: str):
        if event == 'removed':
            if client_id in self.brothers_dict:
                jack_client_name = self.brothers_dict.pop(client_id)
            else:
                return
            
            # remove all saved connections from and to its client
            conns_to_unsave = list[tuple[str, str]]()
                
            for conn in self.saved_connections:
                out_port, in_port = conn
                if (port_belongs_to_client(out_port, jack_client_name)
                        or port_belongs_to_client(in_port, jack_client_name)):
                    conns_to_unsave.append(conn)
            
            for conn in conns_to_unsave:
                self.saved_connections.remove(conn)

        elif event.startswith('id_changed_to:'):
            if client_id in self.brothers_dict.keys():
                self.glob.client_changing_id = (
                    self.brothers_dict[client_id], event.partition(':')[2])
            self.nsm_server.send_monitor_reset()

    def monitor_client_updated(
            self, client_id: str, jack_name: str, is_started: int):
        self.brothers_dict[client_id] = jack_name

    def session_is_loaded(self):
        self.glob.allow_disconnections = True
        self.may_make_one_connection()