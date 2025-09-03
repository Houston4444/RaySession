import logging
from typing import TYPE_CHECKING, Literal

from patshared import PortMode

from .bases import ConnectionPattern, ConnectionStr, PortData
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
    def __init__(self):
        self.name = 'Default'
        self.forbidden_connections = set[ConnectionStr]()
        self.forbidden_patterns = list[ConnectionPattern]()
        self.all_forbidden_conns = set[ConnectionStr]()
        
        self.saved_connections = set[ConnectionStr]()
        self.saved_patterns = list[ConnectionPattern]()
        self.all_saved_conns = set[ConnectionStr]()
        
    def __repr__(self) -> str:
        return 'DefaultScenario'

    def must_stock_conn(self, conn: ConnectionStr) -> Literal[False]:
        return False
    
    def redirected(self, conn: ConnectionStr,
                   restored=False) -> list[ConnectionStr]:
        return []
    
    def to_yaml_dict(self) -> dict:
        out_d = {}
        forbidden_conns = (
            yaml_tools.patterns_to_dict(self.forbidden_patterns)
            +  [{'from': c[0], 'to': c[1]}
                for c in sorted(self.forbidden_connections)])
        if forbidden_conns:
            out_d['forbidden_connections'] = forbidden_conns
        
        saved_conns = (
            yaml_tools.patterns_to_dict(self.saved_patterns)
            +  [{'from': c[0], 'to': c[1]}
                for c in sorted(self.saved_connections)])
        if saved_conns:
            out_d['connections'] = saved_conns
        
        return out_d
    
    def save_tmp_connections(self):
        ...
    
    def startup_depattern(self, ports: dict[PortMode, list[PortData]]):
        for conn in self.saved_connections:
            self.all_saved_conns.add(conn)
        for conn in self.forbidden_connections:
            self.all_forbidden_conns.add(conn)
        depattern.startup(
            ports, self.all_saved_conns, self.saved_patterns)
        depattern.startup(
            ports, self.all_forbidden_conns, self.forbidden_patterns)
        
    def port_depattern(
            self, ports: dict[PortMode, list[PortData]], port: PortData):
        depattern.add_port(
            ports, self.all_saved_conns, self.saved_patterns, port)
        depattern.add_port(
            ports, self.all_forbidden_conns, self.forbidden_patterns, port)
        

class Scenario(BaseScenario):
    def __init__(self, rules: ScenarioRules):
        super().__init__()
        self.name = ''
        self.rules = rules
        self.playback_redirections = list[ConnectionStr]()
        self.capture_redirections = list[ConnectionStr]()
        self.tmp_connections = set[ConnectionStr]()

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

    def redirected(self, conn: ConnectionStr,
                   restored=False) -> list[ConnectionStr]:
        '''return all connections that could be a redirection of conn.'''
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
    
    def to_yaml_dict(self) -> dict:
        out_d = {}
        out_d['name'] = self.name
        out_d['rules'] = self.rules.to_yaml_dict()
        
        forbidden_conns = (
            yaml_tools.patterns_to_dict(self.forbidden_patterns)
            +  [{'from': c[0], 'to': c[1]}
                for c in sorted(self.forbidden_connections)])
        if forbidden_conns:
            out_d['forbidden_connections'] = forbidden_conns
        
        saved_conns = (
            yaml_tools.patterns_to_dict(self.saved_patterns)
            +  [{'from': c[0], 'to': c[1]}
                for c in sorted(self.saved_connections)])
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
    
    def save_tmp_connections(self):
        for conn in self.tmp_connections:
            self.saved_connections.add(conn)
        self.tmp_connections.clear()


class ScenariosManager:
    def __init__(self, patcher: 'Patcher'):
        self.scenarios = list[BaseScenario]()
        self.scenarios.append(BaseScenario())
        self.current_num = 0
        self.patcher = patcher
        self.conns_to_connect = patcher.conns_to_connect
        self.conns_to_disconnect = patcher.conns_to_disconnect

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
                    conns, scenario.saved_connections,
                    scenario.saved_patterns)

            fbd_conns = el.get('forbidden_connections')
            if isinstance(fbd_conns, list):
                yaml_tools.load_conns_from_yaml(
                    fbd_conns, scenario.forbidden_connections,
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
                conns, default.saved_connections, default.saved_patterns)
        
        forbidden_conns = yaml_dict.get('forbidden_connections')
        if isinstance(forbidden_conns, list):
            yaml_tools.load_conns_from_yaml(
                forbidden_conns, default.forbidden_connections,
                default.forbidden_patterns)
        
        scenars = yaml_dict.get('scenarios')
        if isinstance(scenars, list):
            self._load_yaml_scenarios(scenars)
            
        for scenario in self.scenarios:
            scenario.startup_depattern(self.patcher.ports)

    def to_yaml(self) -> list[dict]:
        out_list = list[dict]()
        for scenario in self.scenarios[1:]:
            out_list.append(scenario.to_yaml_dict())
        return out_list

    def load_xml_connections(self, conns: set[ConnectionStr]):
        default = self.scenarios[0]
        default.saved_connections = conns
        default.startup_depattern(self.patcher.ports)

    def open_default(self):
        default = self.scenarios[0]
        self.patcher.conns_to_connect.clear()
        self.patcher.conns_to_disconnect.clear()
        for conn in default.all_saved_conns:
            self.patcher.conns_to_connect.add(conn)
        for fbd_conn in default.all_forbidden_conns:
            self.patcher.conns_to_disconnect.add(fbd_conn)

    def port_depattern(self, port: PortData):
        for scenario in self.scenarios:
            scenario.port_depattern(self.patcher.ports, port)

    def save(self):
        current = self.current
        for scenario in self.scenarios:
            if scenario is current:
                input_ports = set([
                    p.name for p in self.patcher.ports[PortMode.INPUT]])
                output_ports = set([
                    p.name for p in self.patcher.ports[PortMode.OUTPUT]])
                
                rm_conns = list[ConnectionStr]()
                for svd_conn in scenario.saved_connections:
                    if (svd_conn not in self.patcher.connections
                            and svd_conn[0] in output_ports
                            and svd_conn[1] in input_ports):
                        rm_conns.append(svd_conn)
                
                for rm_conn in rm_conns:
                    scenario.saved_connections.remove(rm_conn)
                
                for conn in self.patcher.connections:
                    if scenario.must_stock_conn(conn):
                        scenario.saved_connections.add(conn)
            else:
                scenario.save_tmp_connections()

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
                    f'{self.scenarios[num - 1].name}')
            elif self.current_num:
                ret = (f'Close scenario {num}: '
                    f'{self.scenarios[num - 1].name}')
            # self.current_scenario = scen_num
            self.load_scenario(num)
        
        return ret

    def _load(self, scenario: Scenario, unload=False):
        # self.patcher.connections_in_redirection.clear()
        added_conns = list[ConnectionStr]()
        rm_conns = list[ConnectionStr]()
        
        for conn in (self.patcher.conns_rm_by_port
                     | self.patcher.connections):
            if conn in self.conns_to_connect:
                continue

            if unload:
                if scenario.must_stock_conn(conn):
                    scenario.tmp_connections.add(conn)
                    continue
            else:
                if conn in scenario.tmp_connections:
                    # self.patcher.connections_in_redirection.add(conn)
                    # self.patcher.saved_conn_cache.add(conn)
                    continue

            redirected = scenario.redirected(conn, restored=unload)
            if redirected:
                rm_conns.append(conn)
                for red_conn in redirected:
                    # self.patcher.connections_in_redirection.add(red_conn)
                    added_conns.append(red_conn)
        
        for conn in self.conns_to_connect:
            if unload:
                if scenario.must_stock_conn(conn):
                    scenario.saved_connections.add(conn)
                    continue
            else:
                if conn in scenario.saved_connections:
                    continue
            
            redirected = scenario.redirected(conn, restored=unload)
            if not redirected:
                continue
            
            rm_conns.append(conn)
            for rescon in redirected:
                added_conns.append(rescon)
                
        if not unload:
            for conn in scenario.tmp_connections | scenario.saved_connections:
                added_conns.append(conn)
            scenario.tmp_connections.clear()

        for conn in rm_conns:
            self.conns_to_connect.discard(conn)
            self.conns_to_disconnect.add(conn)
        for conn in added_conns:
            self.conns_to_connect.add(conn)
            self.conns_to_disconnect.discard(conn)

    def load_scenario(self, num: int):
        scenario = self.current
        # self.patcher.allow_disconnections = True
        
        print('descenarizon', scenario)
        if isinstance(scenario, Scenario):
            self._load(scenario, unload=True)
        
        self.current_num = num
        scenario = self.current

        print('scenarizon', scenario)
        if isinstance(scenario, Scenario):
            self._load(scenario)
        print('scenar loaded', scenario)
        
        self.patcher.set_all_ports_new()
