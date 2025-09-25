from enum import Enum, auto
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from ruamel.yaml.comments import CommentedMap, CommentedSeq

from patshared import PortMode

from .bases import ConnectionPattern, ConnectionStr, PortData
from . import depattern
from . import yaml_tools

if TYPE_CHECKING:
    from .patcher import Patcher


_logger = logging.getLogger(__name__)


class ScenarioMode(Enum):
    '''Defines the scenario connections behavior.'''

    AUTO = auto()
    '''Scenario will be REDIRECTIONS if there are redirections and
    no connect domain, else CONNECT_DOMAIN'''
    
    REDIRECTIONS = auto()
    '''Scenario applies projections of connections in BaseScenario
    within the capture_redirections and playback_redirections. Only the
    connections to a redirection origin are saved specificaly in the
    scenario'''
    
    CONNECT_DOMAIN = auto()
    '''Connections allowed to be stored in the connect domain will be stored
    in the scenario. Other connections will be depend on the BaseScenario'''
    
    @staticmethod
    def from_input(input: str | None) -> 'ScenarioMode':
        if input is None:
            return ScenarioMode.AUTO
        if input.lower() == 'redirections':
            return ScenarioMode.REDIRECTIONS
        if input.lower() == 'connect_domain':
            return ScenarioMode.CONNECT_DOMAIN
        return ScenarioMode.AUTO


class ScenarioRules:
    def __init__(self):
        self.present_clients = list[str]()
        self.absent_clients = list[str]()
        
    def match(self, present_clients: set[str]) -> bool:
        for sc_pres_cl in self.present_clients:
            if sc_pres_cl not in present_clients:
                return False
        
        for sc_abst_cl in self.absent_clients:
            if sc_abst_cl in present_clients:
                return False
        return True
    
    def to_yaml_dict(self) -> dict:
        out_d = {}
        if self.present_clients:
            out_d['present_clients'] = self.present_clients
        if self.absent_clients:
            out_d['absent_clients'] = self.absent_clients
        return out_d


class BaseScenario:
    '''Mother Class of Scenario. Is used by the default scenario.
    Does not contains rules and redirections'''
    def __init__(self):
        self.name = 'Default'
        self.forbidden_patterns = list[ConnectionPattern]()
        '''Patterns affecting forbidden connections in this scenario.
        Never change since another project is loaded'''
        self.forbidden_conns = set[ConnectionStr]()
        '''Connections forbidden in this scenario.
        Can be modified each time a port is added, regarding the
        forbidden patterns'''
        
        self.saved_patterns = list[ConnectionPattern]()
        '''Patterns affecting saved connections in this scenario.
        Never change since another project is loaded'''
        self.saved_conns = set[ConnectionStr]()
        '''Connections saved in this scenario. Saved state here does not
        reflects the project file but the current save state.'''
        
    def __repr__(self) -> str:
        return 'DefaultScenario'

    def must_stock_conn(self, conn: ConnectionStr) -> bool:
        return False
    
    def redirecteds(self, conn: ConnectionStr,
                    restored=False) -> list[ConnectionStr]:
        '''return all connections that could be a redirection of conn.'''
        return []
    
    def projections(self, conn: ConnectionStr,
                    restored=False) -> list[ConnectionStr]:
        '''return all connections that could be a redirection of conn,
        or a list containing only conn if no redirection was found.'''
        return [conn]
    
    def to_yaml_map(self) -> CommentedMap:
        out_d = CommentedMap()
        forbidden_conns = depattern.to_yaml_list(
            self.forbidden_patterns, self.forbidden_conns)
        if forbidden_conns:
            out_d['forbidden_connections'] = forbidden_conns
        saved_conns = depattern.to_yaml_list(
            self.saved_patterns, self.saved_conns)        
        if saved_conns:
            out_d['connections'] = saved_conns

        return out_d
    
    def startup_depattern(self, ports: dict[PortMode, list[PortData]]):
        depattern.startup(
            ports, self.saved_conns, self.saved_patterns)
        depattern.startup(
            ports, self.forbidden_conns, self.forbidden_patterns)
        
    def port_depattern(
            self, ports: dict[PortMode, list[PortData]], port: PortData):
        depattern.add_port(
            ports, self.saved_conns, self.saved_patterns, port)
        depattern.add_port(
            ports, self.forbidden_conns, self.forbidden_patterns, port)


class Scenario(BaseScenario):
    def __init__(self, rules: ScenarioRules):
        super().__init__()
        self.name = ''
        self.rules = rules
        self.mode = ScenarioMode.AUTO
        self.playback_redirections = list[ConnectionStr]()
        self.capture_redirections = list[ConnectionStr]()
        self.connect_domain = list[ConnectionPattern]()
        self.no_connect_domain = list[ConnectionPattern]()
        
        self.yaml_map = CommentedMap()

    def __repr__(self) -> str:
        return f'Scenario({self.name}:{self.mode.name})'
    
    def get_final_mode(self, mode: ScenarioMode) -> ScenarioMode:
        '''Choose the ScenarioMode depending on scenario attributes
        in case mode is AUTO'''
        if mode is not ScenarioMode.AUTO:
            return mode
        
        if self.connect_domain or self.no_connect_domain:
            return ScenarioMode.CONNECT_DOMAIN
        
        if self.capture_redirections or self.playback_redirections:
            return ScenarioMode.REDIRECTIONS
        
        return ScenarioMode.CONNECT_DOMAIN

    def _belongs_to_domain(self, conn: ConnectionStr) -> bool:
        if self.mode is not ScenarioMode.CONNECT_DOMAIN:
            raise Exception

        if self.connect_domain:
            if self.no_connect_domain:
                if depattern.connection_in_domain(
                        self.no_connect_domain, conn):
                    return False
                
            return depattern.connection_in_domain(
                self.connect_domain, conn)
        
        if self.no_connect_domain:
            if depattern.connection_in_domain(
                    self.no_connect_domain, conn):
                return False
            return True        
        return True

    def must_stock_conn(self, conn: ConnectionStr) -> bool:
        'True if one of the conn ports is the origin of a redirection'
        port_from , port_to = conn
        for cp_red in self.capture_redirections:
            if port_from == cp_red[0]:
                return True
        
        for cp_red in self.playback_redirections:
            if port_to == cp_red[0]:
                return True

        return False

    def redirecteds(self, conn: ConnectionStr,
                    restored=False) -> list[ConnectionStr]:
        port_from, port_to = conn
        if restored:
            orig, dest = 1, 0
        else:
            orig, dest = 0, 1
            
        r_outs = [ct[dest] for ct in self.capture_redirections
                  if ct[orig] == port_from]
        r_ins = [ct[dest] for ct in self.playback_redirections
                 if ct[orig] == port_to]
        
        if not (r_outs or r_ins):
            return []
        
        port_from, port_to = conn
        
        ret = list[ConnectionStr]()
        if r_outs and r_ins:
            for r_out in r_outs:
                for r_in in r_ins:
                    ret.append((r_out, r_in))
        elif r_outs:
            for r_out in r_outs:
                ret.append((r_out, port_to))
        elif r_ins:
            for r_in in r_ins:
                ret.append((port_from, r_in))
        return ret
    
    def projections(self, conn: ConnectionStr,
                    restored=False) -> list[ConnectionStr]:
        ret = self.redirecteds(conn, restored)
        if ret:
            return ret
        return [conn]    

    def to_yaml_map(self) -> CommentedMap:
        out_d = self.yaml_map
        
        forbidden_conns = depattern.to_yaml_list(
            self.forbidden_patterns, self.forbidden_conns)
        if forbidden_conns:
            out_d['forbidden_connections'] = forbidden_conns

        saved_conns = depattern.to_yaml_list(
            self.saved_patterns, self.saved_conns)        
        if saved_conns:
            out_d['connections'] = saved_conns
                
        return out_d


class ScenariosManager:
    def __init__(self, patcher: 'Patcher'):
        self.scenarios = list[BaseScenario]()
        self.scenarios.append(BaseScenario())
        self.current_num = 0
        self.patcher = patcher
        
        self.ex_connections = set[ConnectionStr]()
        '''Connections at time of last scenario switch.
        Can be used in case successive scenarios are switching
        too fastly, and reconnections are not completed.'''
        self.recent_connections = set[ConnectionStr]()
        '''All connections or disconnections done
        since last scenario switch'''
        self.initial_connections = set[ConnectionStr]()
        'Connections already existing at startup'
        

    @property
    def current(self) -> BaseScenario:
        return self.scenarios[self.current_num]

    def _load_yaml_scenarios(self, yaml_list: CommentedSeq):
        if not isinstance(yaml_list, CommentedSeq):
            return

        for i in range(len(yaml_list)):
            el = yaml_list[i]
            
            if not isinstance(el, CommentedMap):
                yaml_tools._err_reading_yaml(
                    yaml_list, i, f'Scenario is not a dict/map, ignored.')
                continue
            
            rules = el.get('rules')
            if not isinstance(rules, CommentedMap):
                yaml_tools._err_reading_yaml(
                    yaml_list, i, f'Scenario must have "rules", ignored.')
                continue
            
            sc_rules = ScenarioRules()
            present_clients = rules.get('present_clients')

            valid = True
            if isinstance(present_clients, str):
                sc_rules.present_clients.append(present_clients)
            elif isinstance(present_clients, CommentedSeq):
                for present_client in present_clients:
                    if not isinstance(present_client, str):
                        valid = False
                        break
                    sc_rules.present_clients.append(present_client)
            elif present_clients is not None:
                valid = False
            
            if not valid:
                yaml_tools._err_reading_yaml(
                    rules, 'present_clients',
                    'Invalid "present_clients", must be a dict/map or string')
                continue
            
            absent_clients = rules.get('absent_clients')
            valid = True
            if isinstance(absent_clients, str):
                sc_rules.absent_clients.append(absent_clients)
            elif isinstance(absent_clients, CommentedSeq):
                for absent_client in absent_clients:
                    if not isinstance(absent_client, str):
                        valid = False
                        break
                    sc_rules.absent_clients.append(absent_client)
            elif absent_clients is not None:
                valid = False

            if not valid:
                yaml_tools._err_reading_yaml(
                    rules, 'present_clients',
                    'Invalid "absent_clients", must be a dict/map or string')
                continue
            
            scenario = Scenario(sc_rules)
            scenario.yaml_map = el
            
            name = el.get('name')
            if isinstance(name, str):
                scenario.name = name
                
            conns = el.get('connections')
            if isinstance(conns, CommentedSeq):
                yaml_tools.load_conns_from_yaml(
                    conns, scenario.saved_conns,
                    scenario.saved_patterns)
            elif conns is not None:
                yaml_tools.log_wrong_type_in_map(
                    el, 'connections', list)

            fbd_conns = el.get('forbidden_connections')
            if isinstance(fbd_conns, CommentedSeq):
                yaml_tools.load_conns_from_yaml(
                    fbd_conns, scenario.forbidden_conns,
                    scenario.forbidden_patterns)
            elif fbd_conns is not None:
                yaml_tools.log_wrong_type_in_map(
                    el, 'forbidden_connections', list)

            pb_redirections = el.get('playback_redirections')
            if isinstance(pb_redirections, CommentedSeq):
                for j in range(len(pb_redirections)):
                    pb_red = pb_redirections[j]
                    if not isinstance(pb_red, CommentedMap):
                        yaml_tools.log_wrong_type_in_seq(
                            pb_redirections, j, 'playback_redirection', dict)
                        continue
                    
                    origin = pb_red.get('origin')
                    destination = pb_red.get('destination')
                    
                    if not (isinstance(origin, str)
                            and isinstance(destination, str)):
                        yaml_tools._err_reading_yaml(
                            pb_redirections, j, 'incomplete redirection')
                        continue
                    
                    scenario.playback_redirections.append(
                        (origin, destination))
            
            ct_redirections = el.get('capture_redirections')
            if isinstance(ct_redirections, CommentedSeq):
                for j in range(len(ct_redirections)):
                    ct_red = ct_redirections[j]
                    if not isinstance(ct_red, CommentedMap):
                        yaml_tools.log_wrong_type_in_seq(
                            ct_redirections, j, 'capture_redirection', dict)
                        continue
                    
                    origin = ct_red.get('origin')
                    destination = ct_red.get('destination')
                    
                    if not (isinstance(origin, str)
                            and isinstance(destination, str)):
                        yaml_tools._err_reading_yaml(
                            pb_redirections, j, 'incomplete redirection')
                        continue
                    
                    scenario.capture_redirections.append(
                        (origin, destination))
            
            domain = el.get('connect_domain')
            if isinstance(domain, CommentedSeq):
                yaml_tools.load_connect_domain(
                    domain, scenario.connect_domain)
                
            no_domain = el.get('no_connect_domain')
            if isinstance(no_domain, CommentedSeq):
                yaml_tools.load_connect_domain(
                    domain, scenario.no_connect_domain)
            
            scenario.mode = scenario.get_final_mode(
                ScenarioMode.from_input(el.get('mode')))
            
            self.scenarios.append(scenario)

    def load_yaml(self, yaml_dict: CommentedMap):        
        conns = yaml_dict.get('connections')
        default = self.scenarios[0]
        if isinstance(conns, CommentedSeq):
            yaml_tools.load_conns_from_yaml(
                conns, default.saved_conns, default.saved_patterns)
        elif conns is not None:
            yaml_tools.log_wrong_type_in_map(yaml_dict, 'connections', list)
        
        forbidden_conns = yaml_dict.get('forbidden_connections')
        if isinstance(forbidden_conns, CommentedSeq):
            yaml_tools.load_conns_from_yaml(
                forbidden_conns, default.forbidden_conns,
                default.forbidden_patterns)
        elif forbidden_conns is not None:
            yaml_tools.log_wrong_type_in_map(
                yaml_dict, 'forbidden_connections', list)
        
        scenars = yaml_dict.get('scenarios')
        if isinstance(scenars, CommentedSeq):
            self._load_yaml_scenarios(scenars)
            
        for scenario in self.scenarios:
            scenario.startup_depattern(self.patcher.ports)

    def fill_yaml(self, yaml_dict: CommentedMap):
        if len(self.scenarios) > 1:
            yaml_dict['scenarios'] = [
                sc.to_yaml_map() for sc in self.scenarios[1:]]
        for key, value in self.scenarios[0].to_yaml_map().items():
            yaml_dict[key] = value

    def load_xml_connections(self, conns: set[ConnectionStr]):
        default = self.scenarios[0]
        default.saved_conns = conns
        default.startup_depattern(self.patcher.ports)

    def open_default(self):
        default = self.scenarios[0]
        self.initial_connections = self.patcher.connections.copy()
        self.patcher.conns_to_connect.clear()
        self.patcher.conns_to_disconnect.clear()
        
        all_conns = (self.patcher.connections
                     | default.saved_conns
                     | default.forbidden_conns)
        
        for conn in all_conns:
            if conn in default.forbidden_conns:
                self.patcher.conns_to_disconnect.add(conn)
                continue
            
            if conn in default.saved_conns:
                self.patcher.conns_to_connect.add(conn)
                continue
            
            if (conn[0] in self.patcher.saved_graph[PortMode.OUTPUT]
                    and conn[1] in self.patcher.saved_graph[PortMode.INPUT]):
                self.patcher.conns_to_disconnect.add(conn)

        self.recent_connections.clear()
        self.patcher.conns_rm_by_port.clear()
        self.patcher.set_all_ports_new()
        self.patcher.switching_scenario = True

    def restore_initial_connections(self):
        self.patcher.conns_to_connect.clear()
        self.patcher.conns_to_disconnect.clear()
        all_conns = self.patcher.connections | self.initial_connections
        for conn in all_conns:
            if conn in self.initial_connections:
                self.patcher.conns_to_connect.add(conn)
            else:
                self.patcher.conns_to_disconnect.add(conn)
        
        self.patcher.set_all_ports_new()
        self.patcher.switching_scenario = True

    def port_depattern(self, port: PortData):
        for scenario in self.scenarios:
            scenario.port_depattern(self.patcher.ports, port)

    def save(self):
        scenario = self.current
        default = self.scenarios[0]
        
        input_ports = set([
            p.name for p in self.patcher.ports[PortMode.INPUT]])
        output_ports = set([
            p.name for p in self.patcher.ports[PortMode.OUTPUT]])
        
        if not isinstance(scenario, Scenario):
            for conn in self.patcher.connections:
                default.saved_conns.add(conn)
            
            for svd_conn in list(default.saved_conns):
                if (svd_conn not in self.patcher.connections
                        and svd_conn[0] in output_ports
                        and svd_conn[1] in input_ports):
                    default.saved_conns.discard(svd_conn)
            
        else:
            match scenario.mode:
                case ScenarioMode.REDIRECTIONS:
                    for conn in self.patcher.connections:
                        if scenario.must_stock_conn(conn):
                            scenario.saved_conns.add(conn)
                            continue
                        
                        redirected = scenario.redirecteds(conn, restored=True)
                        if redirected:
                            for red_conn in redirected:
                                default.saved_conns.add(red_conn)
                        else:
                            default.saved_conns.add(conn)
                
                case ScenarioMode.CONNECT_DOMAIN:
                    for conn in self.patcher.connections:
                        if scenario._belongs_to_domain(conn):
                            scenario.saved_conns.add(conn)
                        else:
                            default.saved_conns.add(conn)

            for svd_conn in list(scenario.saved_conns):
                if (svd_conn not in self.patcher.connections
                        and svd_conn[0] in output_ports
                        and svd_conn[1] in input_ports):
                    scenario.saved_conns.discard(svd_conn)

    def choose(self, present_clients: set[str]) -> str:
        num = 0
        for scenario in self.scenarios[1:]:
            num += 1
            if (isinstance(scenario, Scenario)
                    and scenario.rules.match(present_clients)):
                break
        else:
            num = 0

        ret = ''
        if num != self.current_num:
            if num:
                ret = (f'Switch to scenario {num}: '
                    f'{self.scenarios[num].name}')
            elif self.current_num:
                ret = (f'Close scenario {num}: '
                    f'{self.scenarios[num].name}')

            self.load_scenario(num)
        
        return ret

    def load_scenario(self, num: int):
        previous_scn = self.current
        self.current_num = num
        next_scn = self.current
        default_scn = self.scenarios[0]
        
        _logger.info(f'switch scenario from {previous_scn} to {next_scn}')

        if self.patcher.switching_scenario is True:
            connections = self.ex_connections
        else:
            connections = (self.patcher.connections
                           | self.patcher.conns_rm_by_port)
            self.ex_connections = connections

        all_conns = set[ConnectionStr]()
        
        # remove from previous_scn saved conns not connected anymore
        if not isinstance(previous_scn, Scenario):
            # previous_scn is default_scn
            for svd_conn in list(default_scn.saved_conns):
                if (svd_conn not in connections
                        and svd_conn in self.recent_connections):
                    default_scn.saved_conns.discard(svd_conn)
        else:
            for svd_conn in list(previous_scn.saved_conns):
                if (svd_conn not in connections
                        and svd_conn in self.recent_connections):
                    previous_scn.saved_conns.discard(svd_conn)

            match previous_scn.mode:
                case ScenarioMode.REDIRECTIONS:
                    # remove from default_scn saved conns without projection
                    # connected anymore.
                    # (except if projections are forbidden
                    #  in the previous_scn).
                    for svd_conn in list(default_scn.saved_conns):
                        for proj_conn in previous_scn.projections(svd_conn):
                            if (proj_conn in connections
                                or proj_conn not in self.recent_connections
                                or proj_conn in previous_scn.forbidden_conns):
                                break
                        else:
                            default_scn.saved_conns.discard(svd_conn)
                            
                case ScenarioMode.CONNECT_DOMAIN:
                    # remove from default_scn saved conns not present
                    # and not in connect_domain if previous_scn
                    for svd_conn in list(default_scn.saved_conns):
                        if (not previous_scn._belongs_to_domain(svd_conn)
                                and svd_conn not in connections
                                and svd_conn in self.recent_connections):
                            default_scn.saved_conns.discard(svd_conn)

        # stock all possible connections we want to treat
        all_conns = (connections
                     | default_scn.saved_conns
                     | default_scn.forbidden_conns)
        if isinstance(previous_scn, Scenario):
            all_conns |= (previous_scn.saved_conns
                          | previous_scn.forbidden_conns)
        if isinstance(next_scn, Scenario):
            all_conns |= (next_scn.saved_conns
                          | next_scn.forbidden_conns)

        projection_conns = set[ConnectionStr]()

        if isinstance(previous_scn, Scenario):
            match previous_scn.mode:
                case ScenarioMode.REDIRECTIONS:
                    for conn in connections:
                        if previous_scn.must_stock_conn(conn):
                            # save unprojectable conns in previous_scn
                            previous_scn.saved_conns.add(conn)
                            continue
                        
                        # save projections of previous_scn in default_scn
                        for df_proj in previous_scn.projections(
                                conn, restored=True):
                            default_scn.saved_conns.add(df_proj)
                            
                case ScenarioMode.CONNECT_DOMAIN:
                    for conn in connections:
                        if previous_scn._belongs_to_domain(conn):
                            previous_scn.saved_conns.add(conn)
                        else:
                            default_scn.saved_conns.add(conn)
        else:
            for conn in connections:
                default_scn.saved_conns.add(conn)

        # set projection connections
        if isinstance(next_scn, Scenario):
            match next_scn.mode:
                case ScenarioMode.REDIRECTIONS:
                    for conn in default_scn.saved_conns:
                        if conn in next_scn.saved_conns:
                            continue
                        
                        for proj_conn in next_scn.projections(conn):
                            projection_conns.add(proj_conn)
                
                case ScenarioMode.CONNECT_DOMAIN:
                    for conn in default_scn.saved_conns:
                        if not next_scn._belongs_to_domain(conn):
                            projection_conns.add(conn)
        else:
            for conn in default_scn.saved_conns:
                projection_conns.add(conn)
        
        all_conns |= projection_conns
        
        conns_to_connect = self.patcher.conns_to_connect
        conns_to_disconnect = self.patcher.conns_to_disconnect
        conns_to_connect.clear()
        conns_to_disconnect.clear()
        
        for conn in all_conns:
            if conn in next_scn.forbidden_conns:
                conns_to_disconnect.add(conn)
                continue
            
            if conn in next_scn.saved_conns:
                conns_to_connect.add(conn)
                continue
            
            if conn in default_scn.forbidden_conns:
                conns_to_disconnect.add(conn)
                continue
            
            if conn in projection_conns:
                conns_to_connect.add(conn)
                continue            
            
            conns_to_disconnect.add(conn)

        self.recent_connections.clear()
        self.patcher.conns_rm_by_port.clear()
        self.patcher.set_all_ports_new()
        self.patcher.switching_scenario = True
