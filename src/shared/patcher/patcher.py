
import logging
import os
import sys
import xml.etree.ElementTree as ET
import yaml

from jack_renaming_tools import (
    port_belongs_to_client, port_name_client_replaced)
from nsm_client import NsmServer, NsmCallback, Err
import ray

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
            self, engine: ProtoEngine, nsm_server: NsmServer,
            logger: logging.Logger):
        self.glob = Glob()
        self.engine = engine
        self._logger = logger
        self.brothers_dict = dict[NsmClientName, JackClientBaseName]()
        self.connections = set[tuple[FullPortName, FullPortName]]()
        'current connections in the graph'
        self.saved_connections = set[tuple[FullPortName, FullPortName]]()
        'saved connections (from the config file or later)'
        self.forbidden_connections = set[tuple[FullPortName, FullPortName]]()
        'connections that user never want'
        self.to_disc_connections = set[tuple[FullPortName, FullPortName]]()
        'connections that have to be disconnected ASAP'
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

    def run_loop(self, stop_with_jack=True):
        self.engine.fill_ports_and_connections(
            self.jack_ports, self.connections)
        jack_stopped = False

        while True:
            if self.glob.terminate:
                break

            self.nsm_server.recv(50)

            for event, args in self.engine.ev_handler.new_events():
                match event:
                    case Event.PORT_ADDED:
                        self.port_added(*args)
                    case Event.PORT_REMOVED:
                        self.port_removed(*args)
                    case Event.PORT_RENAMED:
                        self.port_renamed(*args)
                    case Event.CONNECTION_ADDED:
                        self.connection_added(*args)
                    case Event.CONNECTION_REMOVED:
                        self.connection_removed(*args)
                    case Event.JACK_STOPPED:
                        jack_stopped = True
                        break
            
            if jack_stopped and stop_with_jack:
                break
            
            if self.timer_connect_check.elapsed():
                self.may_make_one_connection()

            if self.timer_dirty_check.elapsed():
                self.timer_dirty_finished()

        self.engine.quit()

    def stop(self, *args):
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
        for conn in self.connections:
            if not conn in self.saved_connections:
                # There is at least one present connection unsaved                
                return True

        for sv_con in self.saved_connections:
            if sv_con in self.connections:
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
        
        # dirty checker timer is longer than timer connect
        # prevent here that dirty check launched after open file
        # found a not yet done connection.
        self.timer_dirty_check.start()

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
        self.connections.add((port_str_a, port_str_b))

        if self.glob.pending_connection:
            self.may_make_one_connection()

        if (port_str_a, port_str_b) not in self.saved_connections:
            self.timer_dirty_check.start()
 
    def connection_removed(self, port_str_a: str, port_str_b: str):
        self.connections.discard((port_str_a, port_str_b))

        if self.glob.pending_connection:
            self.may_make_one_connection()

        self.timer_dirty_check.start()

    def may_make_one_connection(self):
        'can make one connection or disconnection'
        one_connected = False

        if self.glob.allow_disconnections:
            if self.to_disc_connections:
                for to_disc_con in self.to_disc_connections:
                    if to_disc_con in self.connections:
                        if one_connected:
                            self.glob.pending_connection = True
                            return
                        self._logger.info(f'disconnect ports: {to_disc_con}')
                        self.engine.disconnect_ports(*to_disc_con)
                        one_connected = True
                else:
                    self.to_disc_connections.clear()

        new_output_ports = set(
            [p.name for p in self.jack_ports[PortMode.OUTPUT] if p.is_new])
        new_input_ports = set(
            [p.name for p in self.jack_ports[PortMode.INPUT] if p.is_new])

        for fbd_con in self.forbidden_connections:
            if (fbd_con in self.connections
                    and (fbd_con[0] in new_output_ports
                         or fbd_con[1] in new_input_ports)):
                if one_connected:
                    self.glob.pending_connection = True
                    return
                
                self._logger.info(
                    f'disconnect forbidden connection: {fbd_con}')
                self.engine.disconnect_ports(*fbd_con)
                one_connected = True

        output_ports = set([p.name for p in self.jack_ports[PortMode.OUTPUT]])
        input_ports = set([p.name for p in self.jack_ports[PortMode.INPUT]])

        for sv_con in self.saved_connections:
            if (not sv_con in self.connections
                    and sv_con[0] in output_ports
                    and sv_con[1] in input_ports
                    and (sv_con[0] in new_output_ports
                         or sv_con[1] in new_input_ports)):
                if one_connected:
                    self.glob.pending_connection = True
                    break

                self._logger.info(f'connect ports: {sv_con}')
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
        _logger.info(f'Open file "{project_path}"')
        self.saved_connections.clear()

        file_path = project_path + '.xml'
        yaml_path = project_path + '.yaml'
        self.glob.file_path = file_path
        self._logger.info(f'open file: {file_path}')

        XML_TAG = self.engine.XML_TAG

        graph_ports = dict[PortMode, list[str]]()
        for port_mode in (PortMode.INPUT, PortMode.OUTPUT):
            graph_ports[port_mode] = list[str]()
        
        has_file = False

        if os.path.isfile(yaml_path):
            has_file = True

            try:
                with open(yaml_path, 'r') as f:
                    contents = f.read()
                    yaml_dict = yaml.safe_load(contents)
                    assert isinstance(yaml_dict, dict)
            except:
                self._logger.error(f'unable to read file {yaml_path}') 
                return (Err.BAD_PROJECT,
                        f'{file_path} is not a correct .yaml file')
            
            brothers = yaml_dict.get('nsm_brothers')
            brothers_ = dict[str, str]()

            if isinstance(brothers, dict):
                for key, value in brothers.items():
                    if isinstance(key, str) and isinstance(value, str):
                        brothers_[key] = value
            
            conns = yaml_dict.get('connections')
            if isinstance(conns, list):
                for conn in conns:
                    if not isinstance(conn, dict):
                        continue
                    
                    port_from: str = conn.get('from', '')
                    port_to: str = conn.get('to', '')
                    
                    if not (isinstance(port_from, str)
                            and isinstance(port_to, str)):
                        self._logger.warning(
                            f"{debug_conn_str((port_from, port_to))} "
                            "is incomplete or not correct.")
                        continue
                    
                    if self.glob.monitor_states_done is MonitorStates.DONE:
                        gp_from = port_from.partition(':')[0]
                        gp_to = port_to.partition(':')[0]
                        need_rm = False

                        for nsm_name, jack_name in brothers_.items():
                            if (jack_name in (gp_from, gp_to)
                                    and not nsm_name in self.brothers_dict):
                                self._logger.info(
                                    f"{debug_conn_str((port_from, port_to))}"
                                    " is removed "
                                    f"because NSM client {nsm_name}"
                                    " has been removed")
                                need_rm = True
                                break
                        
                        if need_rm:
                            print('need_rm', port_from, port_to)
                            continue
                        
                    self.saved_connections.add((port_from, port_to))
            
            forbidden_conns = yaml_dict.get('forbidden_connections')
            if isinstance(forbidden_conns, list):
                for fbd_conn in forbidden_conns:
                    if not isinstance(fbd_conn, dict):
                        continue
                    
                    fbd_from = fbd_conn.get('from')
                    fbd_to = fbd_conn.get('to')
                    if not (isinstance(fbd_from, str)
                            and isinstance(fbd_to, str)):
                        continue

                    self.forbidden_connections.add((fbd_from, fbd_to))
                    self.saved_connections.discard((fbd_from, fbd_to))

            graph = yaml_dict.get('graph')
            if isinstance(graph, dict):
                for group_name, gp_dict in graph.items():
                    if not (isinstance(group_name, str)
                            and isinstance(gp_dict, dict)):
                        continue

                    in_ports = gp_dict.get('in_ports')
                    if isinstance(in_ports, list):
                        for in_port in in_ports:
                            if isinstance(in_port, str):
                                graph_ports[PortMode.INPUT].append(
                                    f'{group_name}:{in_port}')

                    out_ports = gp_dict.get('out_ports')
                    if isinstance(out_ports, list):
                        for out_port in out_ports:
                            if isinstance(out_port, str):
                                graph_ports[PortMode.OUTPUT].append(
                                    f'{group_name}:{out_port}')

        elif os.path.isfile(file_path):
            has_file = True
            
            try:
                tree = ET.parse(file_path)
            except:
                self._logger.error(f'unable to read file {file_path}')
                return (Err.BAD_PROJECT,
                        f'{file_path} is not a correct .xml file')
            
            # read the DOM
            root = tree.getroot()
            if root.tag != XML_TAG:
                self._logger.error(f'{file_path} is not a {XML_TAG} .xml file')
                return (Err.BAD_PROJECT,
                        f'{file_path} is not a {XML_TAG} .xml file')
            
            for child in root:
                if child.tag == 'connection':
                    port_from: str = child.attrib.get('from', '')
                    port_to: str = child.attrib.get('to', '')
                    nsm_client_from: str = child.attrib.get(
                        'nsm_client_from', '')
                    nsm_client_to: str = child.attrib.get(
                        'nsm_client_to', '')

                    if not port_from and port_to:
                        self._logger.warning(
                            f"{debug_conn_str((port_from, port_to))} "
                            "is incomplete.")
                        continue

                    # ignore connection if NSM client
                    # has been definitely removed
                    if self.glob.monitor_states_done is MonitorStates.DONE:
                        if (nsm_client_from 
                                and nsm_client_from
                                    not in self.brothers_dict.keys()):
                            self._logger.info(
                                f"{debug_conn_str((port_from, port_to))}"
                                " is removed "
                                f"because NSM client {nsm_client_from}"
                                " has been removed")
                            continue
                        if (nsm_client_to
                                and nsm_client_to 
                                    not in self.brothers_dict.keys()):
                            self._logger.info(
                                f"{debug_conn_str((port_from, port_to))}"
                                " is removed "
                                f"because NSM client {nsm_client_to}"
                                " has been removed")
                            continue
                        
                    self.saved_connections.add((port_from, port_to))
            
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

        if has_file:
            # re-declare all ports as new in case we are switching session
            for port_mode in (PortMode.INPUT, PortMode.OUTPUT):
                for port in self.jack_ports[port_mode]:
                    port.is_new = True

            self.to_disc_connections.clear()
            # disconnect connections not existing at last save
            # if their both ports were present in the graph.
            for conn in self.connections:
                if (conn not in self.saved_connections
                        and conn[0] in graph_ports[PortMode.OUTPUT]
                        and conn[1] in graph_ports[PortMode.INPUT]):
                    self.to_disc_connections.add(conn)

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

        for connection in self.connections:
            self.saved_connections.add(connection)

        # delete from saved connected all connections 
        # when there ports are present and not currently connected    
        del_list = list[tuple[str, str]]()

        for sv_con in self.saved_connections:
            if (not sv_con in self.connections
                    and sv_con[0] in [
                        p.name for p in self.jack_ports[PortMode.OUTPUT]]
                    and sv_con[1] in [
                        p.name for p in self.jack_ports[PortMode.INPUT]]):
                del_list.append(sv_con)
                
        for del_con in del_list:
            self.saved_connections.discard(del_con)

        # # write the XML file
        # root = ET.Element(self.engine.XML_TAG)
        # for sv_con in self.saved_connections:
        #     conn_el = ET.SubElement(root, 'connection')
        #     conn_el.attrib['from'], conn_el.attrib['to'] = sv_con
        #     jack_con_from_name = sv_con[0].partition(':')[0].partition('/')[0]
        #     jack_con_to_name = sv_con[1].partition(':')[0].partition('/')[0]
        #     for key, value in self.brothers_dict.items():
        #         if jack_con_from_name == value:
        #             conn_el.attrib['nsm_client_from'] = key
        #         if jack_con_to_name == value:
        #             conn_el.attrib['nsm_client_to'] = key

        # graph = ET.SubElement(root, 'graph')
        # group_names = dict[str, ET.Element]()

        # for port_mode in (PortMode.INPUT, PortMode.OUTPUT):
        #     el_name = 'in_port' if port_mode is PortMode.INPUT else 'out_port'

        #     for jack_port in self.jack_ports[port_mode]:
        #         gp_name, colon, port_name = jack_port.name.partition(':')
        #         if group_names.get(gp_name) is None:
        #             group_names[gp_name] = ET.SubElement(graph, 'group')
        #             group_names[gp_name].attrib['name'] = gp_name

        #             gp_base_name = gp_name.partition('/')[0]
        #             for key, value in self.brothers_dict.items():
        #                 if value == gp_base_name:
        #                     group_names[gp_name].attrib['nsm_client'] = key
        #                     break

        #         out_port_el = ET.SubElement(group_names[gp_name], el_name)
        #         out_port_el.attrib['name'] = port_name
        
        # if sys.version_info >= (3, 9):
        #     # we can indent the xml tree since python3.9
        #     ET.indent(root, space='  ', level=0)

        # self._logger.info(f'save file: {self.glob.file_path}')
        # tree = ET.ElementTree(root)
        # try:
        #     tree.write(self.glob.file_path)
        # except:
        #     self._logger.error(f'unable to write file {self.glob.file_path}')
        #     self.glob.terminate = True
        #     return

        # write YAML str
        out_dict = {}
        out_dict['app'] = self.engine.XML_TAG
        out_dict['version'] = ray.VERSION
        out_dict['forbidden_connections'] = [
            {'from': c[0], 'to': c[1]} 
            for c in sorted(self.forbidden_connections)]
        out_dict['connections'] = [
            {'from': c[0], 'to': c[1]}
            for c in sorted(self.saved_connections)]
        groups_dict = dict[str, dict]()
        
        for port_mode in (PortMode.INPUT, PortMode.OUTPUT):
            el_name = 'in_ports' if port_mode is PortMode.INPUT else 'out_ports'

            for jack_port in self.jack_ports[port_mode]:
                gp_name, _, port_name = jack_port.name.partition(':')
                if groups_dict.get(gp_name) is None:
                    groups_dict[gp_name] = dict[str, dict[str, str | list[str]]]()

                if groups_dict[gp_name].get(el_name) is None:
                    groups_dict[gp_name][el_name] = list[str]()
                groups_dict[gp_name][el_name].append(port_name)

        out_dict['graph'] = groups_dict
        out_dict['nsm_brothers'] = self.brothers_dict.copy()
        
        yaml_file = self.glob.file_path.rpartition('.')[0] + '.yaml'
        try:
            with open(yaml_file, 'w') as f:
                f.write(yaml.dump(out_dict, sort_keys=False))
        except:
            self._logger.error(f'Unable to write {yaml_file}')
            # self.glob.terminate = True

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

                for rm_conn in rm_conns:
                    self.saved_connections.discard(rm_conn)
                for new_conn in new_conns:
                    self.saved_connections.add(new_conn)
                self.glob.client_changing_id = None
            
        else:
            n_clients = is_started
            if len(self.brothers_dict) != n_clients:
                self._logger.warning('list of monitored clients is incomplete !')
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
                self.saved_connections.discard(conn)

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