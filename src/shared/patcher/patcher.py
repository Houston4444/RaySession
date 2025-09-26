
from io import StringIO
import logging
import os
import re
import time
from typing import Optional
import xml.etree.ElementTree as ET

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from patshared import PortMode, PortType

from jack_renaming_tools import (
    port_belongs_to_client, port_name_client_replaced)
from nsm_client import NsmServer, NsmCallback, Err
import ray

from .bases import (
    NsmClientName,
    JackClientBaseName,
    FullPortName,
    ConnectionStr,
    ConnectionPattern,
    PortData,
    MonitorStates,
    ProtoEngine,
    TerminateState,
    Timer,
    PatchEvent,
    debug_conn_str)
from . import yaml_tools
from . import scenarios
from .yaml_comments import GRAPH, NSM_BROTHERS

_logger = logging.getLogger(__name__)


class Patcher:
    def __init__(
            self, engine: ProtoEngine, nsm_server: NsmServer,
            logger: logging.Logger):
        self.engine = engine
        self._logger = logger

        self.project_path = ''
        'NSM client project path'
        self.is_dirty = False
        'is dirty for NSM'
        self.dirty_state_sent = False
        self.monitor_states_done = MonitorStates.NEVER_DONE
        self.client_changing_id: Optional[tuple[str, str]] = None
        self.terminate = TerminateState.NORMAL
        
        self.slow_connect = False
        self.pending_connection = False

        self.brothers_dict = dict[NsmClientName, JackClientBaseName]()
        self.present_clients = set[str]()

        self.connections = set[ConnectionStr]()
        'current connections in the graph'
        self.conns_to_connect = set[ConnectionStr]()
        'connections that have to be done now or when its ports are created'
        self.conns_to_disconnect = set[ConnectionStr]()
        'connections that have to be disconnected ASAP'
        self.ports_creation = dict[FullPortName, float]()
        'Stores the creation time of the ports'

        self.disconnections_time = dict[ConnectionStr, float]()
        'Store the time since epoch of each disconnection'
        self.conns_rm_by_port = set[ConnectionStr]()
        '''all disconnections that occurred just before
        the destruction of one of their ports'''

        self.saved_graph = dict[PortMode, set[FullPortName]]()
        '''ports existing at last save. When patch file is open,
        diconnections are possible if ports of existing connections
        were existing at last save.'''
        for port_mode in (PortMode.INPUT, PortMode.OUTPUT):
            self.saved_graph[port_mode] = set[FullPortName]()

        self.scenarios = scenarios.ScenariosManager(self)
        self.switching_scenario = False

        self.ports = dict[PortMode, list[PortData]]()
        for port_mode in (PortMode.NULL, PortMode.INPUT, PortMode.OUTPUT):
            self.ports[port_mode] = list[PortData]()

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
        
        self.yaml_dict = CommentedMap()

    def run_loop(self, stop_with_jack=True):
        self.engine.fill_ports_and_connections(
            self.ports, self.connections)
        
        for port_mode in (PortMode.OUTPUT, PortMode.INPUT):
            for port in self.ports[port_mode]:
                self.present_clients.add(port.name.partition(':')[0])
        
        jack_stopped = False

        while True:
            if self.terminate is TerminateState.ASKED:
                self.terminate = TerminateState.RESTORING
                self.scenarios.restore_initial_connections()
                self.may_make_one_connection()

            if self.terminate is TerminateState.LEAVING:
                break

            self.nsm_server.recv(50)

            for event, args in self.engine.ev_handler.new_events():
                match event:
                    case PatchEvent.CLIENT_ADDED:
                        self.client_added(*args)
                    case PatchEvent.CLIENT_REMOVED:
                        self.client_removed(*args)
                    case PatchEvent.PORT_ADDED:
                        self.port_added(*args)
                    case PatchEvent.PORT_REMOVED:
                        self.port_removed(*args)
                    case PatchEvent.PORT_RENAMED:
                        self.port_renamed(*args)
                    case PatchEvent.CONNECTION_ADDED:
                        self.connection_added(*args)
                    case PatchEvent.CONNECTION_REMOVED:
                        self.connection_removed(*args)
                    case PatchEvent.SHUTDOWN:
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
        if self.terminate is TerminateState.NORMAL:
            self.terminate = TerminateState.ASKED

    def set_dirty_clean(self):
        self.is_dirty = False
        self.nsm_server.send_dirty_state(False)

    def timer_dirty_finished(self):
        if self.is_dirty:
            return

        if self.pending_connection:
            self.timer_dirty_check.start()
            return

        if self.is_dirty_now():
            self.is_dirty = True
            self.nsm_server.send_dirty_state(True)
        elif not self.dirty_state_sent:
            self.nsm_server.send_dirty_state(False)
            self.dirty_state_sent = True

    def is_dirty_now(self) -> bool:
        for conn in self.connections:
            if conn not in self.conns_to_connect:
                # There is at least one present connection unsaved                
                return True

        for sv_con in self.conns_to_connect:
            if sv_con in self.connections:
                continue

            if (sv_con[0] in [
                        p.name for p in self.ports[PortMode.OUTPUT]]
                    and sv_con[1] in [
                        p.name for p in self.ports[PortMode.INPUT]]):
                # There is at least one saved connection not present
                # despite the fact its two ports are present.
                return True

        return False

    def client_added(self, client_name: str):
        self.present_clients.add(client_name)
        ret = self.scenarios.choose(self.present_clients)
        if ret:
            self.nsm_server.send_message(2, ret)
            self.may_make_one_connection()

    def client_removed(self, client_name: str):
        self.present_clients.discard(client_name)
        ret = self.scenarios.choose(self.present_clients)
        if ret:
            self.nsm_server.send_message(2, ret)
            self.may_make_one_connection()

    def port_added(self, port_name: str, port_mode: int, port_type: int):
        self.ports_creation[port_name] = time.time()
        port = PortData()
        port.name = port_name
        port.mode = PortMode(port_mode)
        port.type = PortType(port_type)
        port.is_new = True

        self.ports[port.mode].append(port)

        self.scenarios.port_depattern(port)
        self.timer_connect_check.start()
        
        # dirty checker timer is longer than timer connect
        # prevent here that dirty check launched after open file
        # found a not yet done connection.
        self.timer_dirty_check.start()

    def port_removed(
            self, port_name: str, port_mode: PortMode, port_type: PortType):
        for port in self.ports[port_mode]:
            if port.name == port_name and port.type == port_type:
                self.ports[port_mode].remove(port)
                break

        else:
            # strange, but in some cases,
            # JACK does not sends the good port mode at remove time.
            for pmode in (PortMode.INPUT, PortMode.OUTPUT):
                if pmode is port_mode:
                    continue
                
                for port in self.ports[pmode]:
                    if port.name == port_name and port.type == port_type:
                        self.ports[pmode].remove(port)
                        break
                break

        now = time.time()
        for conn, time_ in self.disconnections_time.items():
            if port_name in conn:
                if now - time_ < 0.250:
                    self.conns_rm_by_port.add(conn)
                else:
                    self.conns_rm_by_port.discard(conn)

        self.timer_connect_check.start()

    def port_renamed(
            self, old_name: str, new_name: str,
            port_mode: PortMode, port_type: PortType):
        for port in self.ports[port_mode]:
            if port.name == old_name and port.type == port_type:
                port.name = new_name
                port.is_new = True
                self.scenarios.port_depattern(port)
                self.timer_connect_check.start()
                break

    def connection_added(self, port_from: str, port_to: str):
        now = time.time()
        out_port_new = now - self.ports_creation.get(port_from, 0.0) < 0.250
        in_port_new = now - self.ports_creation.get(port_to, 0.0) < 0.250
        
        self.connections.add((port_from, port_to))
        self.conns_rm_by_port.discard((port_from, port_to))
        self.scenarios.recent_connections.add((port_from, port_to))

        if self.pending_connection or in_port_new or out_port_new:
            if out_port_new:
                for jport in self.ports[PortMode.OUTPUT]:
                    if jport.name == port_from:
                        jport.is_new = True
                        break
            if in_port_new:
                for jport in self.ports[PortMode.INPUT]:
                    if jport.name == port_to:
                        jport.is_new = True
                        break

            self.may_make_one_connection()

        if not (port_from, port_to) in self.conns_to_connect:
            self.timer_dirty_check.start()
 
    def connection_removed(self, port_str_a: str, port_str_b: str):
        self.connections.discard((port_str_a, port_str_b))
        self.disconnections_time[(port_str_a, port_str_b)] = time.time()
        self.scenarios.recent_connections.add((port_str_a, port_str_b))

        if self.pending_connection:
            self.may_make_one_connection()

        self.timer_dirty_check.start()

    def _startup_conns_cache(
            self, conns: set[ConnectionStr],
            patterns: list[ConnectionPattern]):
        for from_, to_ in patterns:
            if isinstance(from_, re.Pattern):
                for outport in self.ports[PortMode.OUTPUT]:
                    if not from_.fullmatch(outport.name):
                        continue
                    if isinstance(to_, re.Pattern):
                        for inport in self.ports[PortMode.INPUT]:
                            if to_.fullmatch(inport.name):
                                conns.add((outport.name, inport.name))
                    else:
                        for inport in self.ports[PortMode.INPUT]:
                            if to_ == inport.name:
                                conns.add((outport.name, inport.name))
                                break
            else:
                for outport in self.ports[PortMode.OUTPUT]:
                    if outport.name == from_:
                        if isinstance(to_, re.Pattern):
                            for inport in self.ports[PortMode.INPUT]:
                                if to_.fullmatch(inport.name):
                                    conns.add((outport.name, inport.name))
                        else:
                            for inport in self.ports[PortMode.INPUT]:
                                if to_ == inport.name:
                                    conns.add((outport.name, inport.name))
                                    break
                        break

    def _add_port_to_conns_cache(
            self, conns_cache: set[ConnectionStr],
            patterns: list[ConnectionPattern], port: PortData):
        if port.mode is PortMode.OUTPUT:
            for from_, to_ in patterns:
                if isinstance(from_, re.Pattern):
                    if not from_.fullmatch(port.name):
                        continue
                elif from_ != port.name:
                    continue
                
                if isinstance(to_, re.Pattern):
                    for input_port in self.ports[PortMode.INPUT]:
                        if to_.fullmatch(input_port.name):
                            conns_cache.add((port.name, input_port.name))
                else:
                    for input_port in self.ports[PortMode.INPUT]:
                        if to_ == input_port.name:
                            conns_cache.add((port.name, input_port.name))
                            break

        elif port.mode is PortMode.INPUT:
            for from_, to_ in patterns:
                if isinstance(to_, re.Pattern):
                    if not to_.fullmatch(port.name):
                        continue
                elif to_ != port.name:
                    continue

                if isinstance(from_, re.Pattern):
                    for output_port in self.ports[PortMode.OUTPUT]:
                        if from_.fullmatch(output_port.name):
                            conns_cache.add((output_port.name, port.name))
                else:
                    for output_port in self.ports[PortMode.OUTPUT]:
                        if from_ == output_port.name:
                            conns_cache.add((output_port.name, port.name))
                            break

    def set_all_ports_new(self, new=True):
        for port_mode in (PortMode.OUTPUT, PortMode.INPUT):
            for port in self.ports[port_mode]:
                port.is_new = new

    def may_make_one_connection(self):
        'can make one connection or disconnection'
        output_ports = set([p.name for p in self.ports[PortMode.OUTPUT]])
        input_ports = set([p.name for p in self.ports[PortMode.INPUT]])
        new_output_ports = set(
            [p.name for p in self.ports[PortMode.OUTPUT] if p.is_new])
        new_input_ports = set(
            [p.name for p in self.ports[PortMode.INPUT] if p.is_new])

        if self.slow_connect:
            one_connected = False
            
            for disconn in self.conns_to_disconnect:
                if (disconn in self.connections
                        and (disconn[0] in new_output_ports
                            or disconn[1] in new_input_ports)):
                    if one_connected:
                        self.pending_connection = True
                        return
                    
                    _logger.info(f'disconnect ports: {disconn}')
                    self.engine.disconnect_ports(*disconn)
                    one_connected = True

            for sv_con in self.conns_to_connect:
                if (sv_con not in self.connections
                        and sv_con not in self.conns_to_disconnect
                        and sv_con[0] in output_ports
                        and sv_con[1] in input_ports
                        and (sv_con[0] in new_output_ports
                            or sv_con[1] in new_input_ports)):
                    if one_connected:
                        self.pending_connection = True
                        return

                    _logger.info(f'connect ports: {sv_con}')
                    self.engine.connect_ports(*sv_con)
                    one_connected = True
        else:
            for disconn in self.conns_to_disconnect:
                if (disconn in self.connections
                        and (disconn[0] in new_output_ports
                            or disconn[1] in new_input_ports)):
                    _logger.info(f'disconnect ports: {disconn}')
                    self.engine.disconnect_ports(*disconn)

            for sv_con in self.conns_to_connect:
                if (sv_con not in self.connections
                        and sv_con not in self.conns_to_disconnect
                        and sv_con[0] in output_ports
                        and sv_con[1] in input_ports
                        and (sv_con[0] in new_output_ports
                            or sv_con[1] in new_input_ports)):
                    _logger.info(f'connect ports: {sv_con}')
                    self.engine.connect_ports(*sv_con)

        self.pending_connection = False
        self.set_all_ports_new(False)
        self.switching_scenario = False
        
        if self.terminate is TerminateState.RESTORING:
            self.terminate = TerminateState.LEAVING

    # ---- NSM callbacks ----

    def open_file(self, project_path: str, session_name: str,
                  full_client_id: str) -> tuple[Err, str]:
        _logger.info(f'Open project "{project_path}"')
        self.conns_to_connect.clear()
        self.conns_to_disconnect.clear()

        xml_path = project_path + '.xml'
        yaml_path = project_path + '.yaml'
        self.project_path = project_path

        XML_TAG = self.engine.XML_TAG
        
        has_file = False

        if os.path.isfile(yaml_path):
            has_file = True

            try:
                with open(yaml_path, 'r') as f:
                    contents = f.read()
                    yaml = YAML()
                    yaml_dict = yaml.load(contents)
                    assert isinstance(yaml_dict, CommentedMap)
            except:
                _logger.error(f'unable to read file {yaml_path}') 
                return (Err.BAD_PROJECT,
                        f'{yaml_path} is not a correct .yaml file')
            
            yaml_tools.file_path = yaml_path

            brothers = yaml_dict.get('nsm_brothers')
            brothers_ = dict[str, str]()

            if isinstance(brothers, dict):
                for key, value in brothers.items():
                    if isinstance(key, str) and isinstance(value, str):
                        brothers_[key] = value

            graph = yaml_dict.get('graph')
            if isinstance(graph, CommentedMap):
                for group_name, gp_dict in graph.items():
                    if not (isinstance(group_name, str)
                            and isinstance(gp_dict, dict)):
                        continue

                    in_ports = gp_dict.get('in_ports')
                    if isinstance(in_ports, list):
                        for in_port in in_ports:
                            if isinstance(in_port, str):
                                self.saved_graph[PortMode.INPUT].add(
                                    f'{group_name}:{in_port}')

                    out_ports = gp_dict.get('out_ports')
                    if isinstance(out_ports, list):
                        for out_port in out_ports:
                            if isinstance(out_port, str):
                                self.saved_graph[PortMode.OUTPUT].add(
                                    f'{group_name}:{out_port}')
            
            self.scenarios.load_yaml(yaml_dict)
            
            if self.monitor_states_done is MonitorStates.DONE:
                pass
                # TODO reput this
                # rm_list = list[tuple[FullPortName, FullPortName]]()
                # for port_from, port_to in self.saved_connections:
                #     gp_from = port_from.partition(':')[0]
                #     gp_to = port_to.partition(':')[0]
                #     for nsm_name, jack_name in brothers_.items():
                #         if (jack_name in (gp_from, gp_to)
                #                 and not nsm_name in self.brothers_dict):
                #             rm_list.append((port_from, port_to))
                #             _logger.info(
                #                 f"{debug_conn_str((port_from, port_to))}"
                #                 " is removed "
                #                 f"because NSM client {nsm_name}"
                #                 " has been removed")
                
                # for rm_conn in rm_list:
                #     self.saved_connections.discard(rm_conn)
            
            self.yaml_dict = yaml_dict

        elif os.path.isfile(xml_path):
            has_file = True
            
            try:
                tree = ET.parse(xml_path)
            except:
                _logger.error(f'unable to read file {xml_path}')
                return (Err.BAD_PROJECT,
                        f'{xml_path} is not a correct .xml file')
            
            # read the DOM
            root = tree.getroot()
            if root.tag != XML_TAG:
                _logger.error(f'{xml_path} is not a {XML_TAG} .xml file')
                return (Err.BAD_PROJECT,
                        f'{xml_path} is not a {XML_TAG} .xml file')
            
            connections = set[ConnectionStr]()
            
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
                    if self.monitor_states_done is MonitorStates.DONE:
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
                        
                    connections.add((port_from, port_to))
            
                elif child.tag == 'graph':
                    for gp in child:
                        if gp.tag != 'group':
                            continue
                        gp_name = gp.attrib['name']
                        for pt in gp:
                            if pt.tag == 'out_port':
                                self.saved_graph[PortMode.OUTPUT].add(
                                    ':'.join((gp_name, pt.attrib['name'])))
                            elif pt.tag == 'in_port':
                                self.saved_graph[PortMode.INPUT].add(
                                    ':'.join((gp_name, pt.attrib['name'])))
            
            self.scenarios.load_xml_connections(connections)

        if has_file:
            # re-declare all ports as new in case we are switching session
            self.scenarios.open_default()
            ret = self.scenarios.choose(self.present_clients)
            if ret:
                self.nsm_server.send_message(2, ret)

            self.may_make_one_connection()

        self.is_dirty = False
        self.timer_dirty_check.start()
        return (Err.OK, '')

    def save_file(self):
        if not self.project_path:
            return

        self.scenarios.save()

        # for connection in self.connections:
        #     if connection not in self.conns_to_connect:
        #         self.saved_connections.add(connection)

        # # delete from saved connected all connections 
        # # when there ports are present and not currently connected    
        # del_list = list[tuple[str, str]]()

        # for sv_con in self.saved_connections:
        #     if (not sv_con in self.connections
        #             and sv_con[0] in [
        #                 p.name for p in self.ports[PortMode.OUTPUT]]
        #             and sv_con[1] in [
        #                 p.name for p in self.ports[PortMode.INPUT]]):
        #         del_list.append(sv_con)
                
        # for del_con in del_list:
        #     self.saved_connections.discard(del_con)
        #     self.conns_to_connect.discard(del_con)

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
        out_dict = self.yaml_dict
        out_dict['app'] = self.engine.XML_TAG
        out_dict['version'] = ray.VERSION
        self.scenarios.fill_yaml(out_dict)

        # fill the 'graph' section
        groups_dict = CommentedMap()
        
        for port_mode in (PortMode.INPUT, PortMode.OUTPUT):
            if port_mode is PortMode.INPUT:
                el_name = 'in_ports'
            else:
                el_name = 'out_ports'

            for jack_port in self.ports[port_mode]:
                gp_name, _, port_name = jack_port.name.partition(':')
                if gp_name not in groups_dict:
                    groups_dict[gp_name] = CommentedMap()

                if el_name not in groups_dict[gp_name]:
                    groups_dict[gp_name][el_name] = CommentedSeq()

                groups_dict[gp_name][el_name].append(port_name)

        out_dict['graph'] = groups_dict
        out_dict['nsm_brothers'] = self.brothers_dict.copy()

        yaml_tools.replace_key_comment_with(
            out_dict, 'graph', GRAPH)
        yaml_tools.replace_key_comment_with(
            out_dict, 'nsm_brothers', NSM_BROTHERS)

        yaml_file = f'{self.project_path}.yaml'
        string_io = StringIO()
        yaml = YAML()
        yaml.dump(out_dict, string_io)
        out_contents = yaml_tools.add_empty_lines(string_io.getvalue())

        try:
            with open(yaml_file, 'w') as f:
                f.write(out_contents)
        except BaseException as e:
            _logger.error(f'Unable to write {yaml_file}\n\t{e}')

        self.set_dirty_clean()
        return (Err.OK, 'Done')

    def monitor_client_state(
            self, client_id: str, jack_name: str, is_started: int):
        if self.monitor_states_done is not MonitorStates.UPDATING:
            self.brothers_dict.clear()

        self.monitor_states_done = MonitorStates.UPDATING
        
        if client_id:
            self.brothers_dict[client_id] = jack_name
            
            if (self.client_changing_id is not None
                    and self.client_changing_id[1] == client_id):
                # we are here only in the case a client id was just changed
                # we modify the saved connections in consequence.
                # Note that this client can't be started.
                ex_jack_name = self.client_changing_id[0]
                rm_conns = list[tuple[str, str]]()
                new_conns = list[tuple[str, str]]()

                # for conn in self.saved_connections:
                #     out_port, in_port = conn
                #     if (port_belongs_to_client(out_port, ex_jack_name)
                #             or port_belongs_to_client(in_port, ex_jack_name)):
                #         rm_conns.append(conn)
                #         new_conns.append(
                #             (port_name_client_replaced(
                #                 out_port, ex_jack_name, jack_name),
                #             port_name_client_replaced(
                #                 in_port, ex_jack_name, jack_name)))

                # for rm_conn in rm_conns:
                #     self.saved_connections.discard(rm_conn)
                # for new_conn in new_conns:
                #     self.saved_connections.add(new_conn)
                self.client_changing_id = None
            
        else:
            n_clients = is_started
            if len(self.brothers_dict) != n_clients:
                _logger.warning('list of monitored clients is incomplete !')
                ## following line would be the most obvious thing to do,
                ## but in case of problem, we could have 
                # an infinite messages loop 
                # nsm_server.send_monitor_reset()
                return

            self.monitor_states_done = MonitorStates.DONE

    def monitor_client_event(self, client_id: str, event: str):
        if event == 'removed':
            if client_id in self.brothers_dict:
                jack_client_name = self.brothers_dict.pop(client_id)
            else:
                return
            
            # remove all saved connections from and to its client
            conns_to_unsave = list[tuple[str, str]]()
                
            # for conn in self.saved_connections:
            #     out_port, in_port = conn
            #     if (port_belongs_to_client(out_port, jack_client_name)
            #             or port_belongs_to_client(in_port, jack_client_name)):
            #         conns_to_unsave.append(conn)
            
            # for conn in conns_to_unsave:
            #     self.saved_connections.discard(conn)

        elif event.startswith('id_changed_to:'):
            if client_id in self.brothers_dict.keys():
                self.client_changing_id = (
                    self.brothers_dict[client_id], event.partition(':')[2])
            self.nsm_server.send_monitor_reset()

    def monitor_client_updated(
            self, client_id: str, jack_name: str, is_started: int):
        self.brothers_dict[client_id] = jack_name

    def session_is_loaded(self):
        ...
