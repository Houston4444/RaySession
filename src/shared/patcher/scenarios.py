import logging
from typing import TYPE_CHECKING

from patshared import PortMode

from .bases import ConnectionPattern, ConnectionStr,  PortData
from . import depattern
from . import yaml_tools

if TYPE_CHECKING:
    from .patcher import Patcher


_logger = logging.getLogger(__name__)


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
    
    def to_yaml_dict(self) -> dict:
        out_d = {}
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
        self.playback_redirections = list[ConnectionStr]()
        self.capture_redirections = list[ConnectionStr]()

    def __repr__(self) -> str:
        return f'Scenario({self.name})'

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

    def to_yaml_dict(self) -> dict:
        out_d = {}
        out_d['name'] = self.name
        out_d['rules'] = self.rules.to_yaml_dict()
        
        forbidden_conns = depattern.to_yaml_list(
            self.forbidden_patterns, self.forbidden_conns)
        if forbidden_conns:
            out_d['forbidden_connections'] = forbidden_conns

        saved_conns = depattern.to_yaml_list(
            self.saved_patterns, self.saved_conns)        
        if saved_conns:
            out_d['connections'] = saved_conns
        
        if self.playback_redirections:
            out_d['playback_redirections'] = [
                {'origin': pb[0], 'destination': pb[1]}
                for pb in self.playback_redirections]
        
        if self.capture_redirections:
            out_d['capture_redirections'] = [
                {'origin': ct[0], 'destination': ct[1]}
                for ct in self.capture_redirections]
        
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

    @property
    def current(self) -> BaseScenario:
        return self.scenarios[self.current_num]

    def _load_yaml_scenarios(self, yaml_list: list):
        if not isinstance(yaml_list, list):
            return
        
        for el in yaml_list:
            m = f'Scenario {el} ignored.'
            
            if not isinstance(el, dict):
                _logger.warning(f'{m} not a dict')
                continue
            
            rules = el.get('rules')
            if not isinstance(rules, dict):
                _logger.warning(f'{m} It must have "rules" dict.')
                continue
            
            sc_rules = ScenarioRules()
            present_clients = rules.get('present_clients')

            valid = True
            if isinstance(present_clients, str):
                sc_rules.present_clients.append(present_clients)
            elif isinstance(present_clients, list):
                for present_client in present_clients:
                    if not isinstance(present_client, str):
                        valid = False
                        break
                    sc_rules.present_clients.append(present_client)
            elif present_clients is not None:
                valid = False
            
            if not valid:
                _logger.warning(f'{m} Invalid present client in rules')
                continue
            
            absent_clients = rules.get('absent_clients')
            valid = True
            if isinstance(absent_clients, str):
                sc_rules.absent_clients.append(absent_clients)
            elif isinstance(absent_clients, list):
                for absent_client in absent_clients:
                    if not isinstance(absent_client, str):
                        valid = False
                        break
                    sc_rules.absent_clients.append(absent_client)
            elif absent_clients is not None:
                valid = False

            if not valid:
                _logger.warning(f'{m} Invalid absent client in rules')
                continue
            
            scenario = Scenario(sc_rules)
            
            name = el.get('name')
            if isinstance(name, str):
                scenario.name = name
                
            conns = el.get('connections')
            if isinstance(conns, list):
                yaml_tools.load_conns_from_yaml(
                    conns, scenario.saved_conns,
                    scenario.saved_patterns)

            fbd_conns = el.get('forbidden_connections')
            if isinstance(fbd_conns, list):
                yaml_tools.load_conns_from_yaml(
                    fbd_conns, scenario.forbidden_conns,
                    scenario.forbidden_patterns)
            
            pb_redirections = el.get('playback_redirections')
            if isinstance(pb_redirections, list):
                for pb_red in pb_redirections:
                    if not isinstance(pb_red, dict):
                        continue
                    
                    origin = pb_red.get('origin')
                    destination = pb_red.get('destination')
                    
                    if not (isinstance(origin, str)
                            and isinstance(destination, str)):
                        continue
                    
                    scenario.playback_redirections.append(
                        (origin, destination))
            
            ct_redirections = el.get('capture_redirections')
            if isinstance(ct_redirections, list):
                for ct_red in ct_redirections:
                    if not isinstance(ct_red, dict):
                        continue
                    
                    origin = ct_red.get('origin')
                    destination = ct_red.get('destination')
                    
                    if not (isinstance(origin, str)
                            and isinstance(destination, str)):
                        continue
                    
                    scenario.capture_redirections.append(
                        (origin, destination))
            
            self.scenarios.append(scenario)

    def load_yaml(self, yaml_dict: dict):
        conns = yaml_dict.get('connections')
        default = self.scenarios[0]
        if isinstance(conns, list):
            yaml_tools.load_conns_from_yaml(
                conns, default.saved_conns, default.saved_patterns)
        
        forbidden_conns = yaml_dict.get('forbidden_connections')
        if isinstance(forbidden_conns, list):
            yaml_tools.load_conns_from_yaml(
                forbidden_conns, default.forbidden_conns,
                default.forbidden_patterns)
        
        scenars = yaml_dict.get('scenarios')
        if isinstance(scenars, list):
            self._load_yaml_scenarios(scenars)
            
        for scenario in self.scenarios:
            scenario.startup_depattern(self.patcher.ports)

    def fill_yaml(self, yaml_dict: dict):
        yaml_dict['scenarios'] = [
            sc.to_yaml_dict() for sc in self.scenarios[1:]]
        for key, value in self.scenarios[0].to_yaml_dict().items():
            yaml_dict[key] = value

    def load_xml_connections(self, conns: set[ConnectionStr]):
        default = self.scenarios[0]
        default.saved_conns = conns
        default.startup_depattern(self.patcher.ports)

    def open_default(self):
        default = self.scenarios[0]
        self.patcher.conns_to_connect.clear()
        self.patcher.conns_to_disconnect.clear()
        for conn in default.saved_conns:
            self.patcher.conns_to_connect.add(conn)
        for fbd_conn in default.forbidden_conns:
            self.patcher.conns_to_disconnect.add(fbd_conn)
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
        
        if scenario is default:
            for conn in self.patcher.connections:
                default.saved_conns.add(conn)
            
            rm_conns = list[ConnectionStr]()
            for svd_conn in default.saved_conns:
                if (svd_conn not in self.patcher.connections
                        and svd_conn[0] in output_ports
                        and svd_conn[1] in input_ports):
                    rm_conns.append(svd_conn)
            
            for rm_conn in rm_conns:
                default.saved_conns.discard(rm_conn)
        else:
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

            rm_conns = list[ConnectionStr]()
            for svd_conn in scenario.saved_conns:
                if (svd_conn not in self.patcher.connections
                        and svd_conn[0] in output_ports
                        and svd_conn[1] in input_ports):
                    rm_conns.append(svd_conn)
            for rm_conn in rm_conns:
                scenario.saved_conns.discard(rm_conn)

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
        if previous_scn is default_scn:
            for svd_conn in list(default_scn.saved_conns):
                if (svd_conn not in connections
                        and svd_conn in self.recent_connections):
                    default_scn.saved_conns.discard(svd_conn)
        else:
            for svd_conn in list(previous_scn.saved_conns):
                if (svd_conn not in connections
                        and svd_conn in self.recent_connections):
                    previous_scn.saved_conns.discard(svd_conn)

            # remove from default_scn saved conns without projection
            # connected anymore.
            # (except if projections are forbidden in the previous_scn).
            for svd_conn in list(default_scn.saved_conns):
                for proj_conn in previous_scn.projections(svd_conn):
                    if (proj_conn in connections
                        or proj_conn not in self.recent_connections
                        or proj_conn in previous_scn.forbidden_conns):
                        break
                else:
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
        
        # save projections of previous_scn in default_scn
        # and unprojectable conns in previous_scn
        projection_conns = set[ConnectionStr]()

        if isinstance(previous_scn, Scenario):
            for conn in connections:
                if previous_scn.must_stock_conn(conn):
                    previous_scn.saved_conns.add(conn)
                    continue
                
                for df_proj in previous_scn.projections(conn, restored=True):
                    default_scn.saved_conns.add(df_proj)
        else:
            for conn in connections:
                default_scn.saved_conns.add(conn)

        # set projection connections
        if isinstance(next_scn, Scenario):
            for conn in default_scn.saved_conns:
                if conn in next_scn.saved_conns:
                    continue
                
                for proj_conn in next_scn.projections(conn):
                    projection_conns.add(proj_conn)
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
