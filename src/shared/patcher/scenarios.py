import logging
from typing import TYPE_CHECKING, Optional

from .bases import ConnectionPattern, ConnectionStr, FullPortName
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


class Scenario:
    def __init__(self, rules: ScenarioRules):
        self.name = ''
        self.rules = rules
        self.forbidden_connections = set[ConnectionStr]()
        self.forbidden_patterns = list[ConnectionPattern]()
        self.saved_connections = set[ConnectionStr]()
        self.saved_patterns = list[ConnectionPattern]()
        self.playback_redirections = list[ConnectionStr]()
        self.capture_redirections = list[ConnectionStr]()
        
    def __repr__(self) -> str:
        return f'Scenario({self.name})'

    def in_redirect(self, port_name: FullPortName) -> FullPortName:
        for orig, dest in self.playback_redirections:
            if orig == port_name:
                return dest
        return port_name
    
    def out_redirect(self, port_name: FullPortName) -> FullPortName:
        for orig, dest in self.capture_redirections:
            if orig == port_name:
                return dest
        return port_name
    
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


class ScenariosManager:
    def __init__(self, patcher: 'Patcher'):
        self.scenarios = list[Scenario]()
        self.current_scenario = 0
        self.patcher = patcher
        self.saved_conn_cache = patcher.saved_conn_cache
        self.to_disc_conns = patcher.to_disc_connections

    @property
    def current(self) -> Optional[Scenario]:
        if self.current_scenario == 0:
            return None
        return self.scenarios[self.current_scenario - 1]

    def load_yaml(self, yaml_list: list):
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
                    conns, scenario.saved_connections, scenario.saved_patterns)
            
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
                    
                    scenario.playback_redirections.append((origin, destination))
            
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
                    
                    scenario.capture_redirections.append((origin, destination))
            
            self.scenarios.append(scenario)

    def in_redirect(self, port_name: FullPortName):
        scenario = self.current
        if scenario is None:
            return port_name
        return scenario.in_redirect(port_name)

    def out_redirect(self, port_name: FullPortName):
        scenario = self.current
        if scenario is None:
            return port_name
        return scenario.out_redirect(port_name)

    def choose(self, present_clients: set[str]) -> str:
        scen_num = 0
        for scenario in self.scenarios:
            scen_num += 1
            if scenario.rules.match(present_clients):
                break
        else:
            scen_num = 0

        ret = ''
        if scen_num != self.current_scenario:
            if scen_num:
                ret = (f'Switch to scenario {scen_num}: '
                    f'{self.scenarios[scen_num - 1].name}')
            elif self.current_scenario:
                ret = (f'Close scenario {scen_num}: '
                    f'{self.scenarios[scen_num - 1].name}')
            # self.current_scenario = scen_num
            self.load_scenario(scen_num)
        
        return ret

    def _load_current(self, scenario: Scenario, unload=False):
        self.patcher.connections_in_redirection.clear()
        added_conns = list[ConnectionStr]()
        rm_conns = list[ConnectionStr]()
        
        i = 0
        for lis in self.patcher.disco_unregister, self.patcher.connections, self.patcher.saved_conn_cache:
            if 'jack_mixer.Jackouillasikus:Monitor L' in [l[0] for l in lis]:
                print(f'il est lallla unload={unload} {i}', lis)
            i += 1
        
        for conn in (self.patcher.disco_unregister
                     | self.patcher.connections):
            if conn in self.saved_conn_cache:
                continue

            redirected = scenario.redirected(conn, restored=unload)
            if redirected:
                rm_conns.append(conn)
                for red_conn in redirected:
                    self.patcher.connections_in_redirection.add(red_conn)
        
        for conn in self.saved_conn_cache:
            redirected = scenario.redirected(conn, restored=unload)
            if not redirected:
                continue
            
            rm_conns.append(conn)
            for rescon in redirected:
                added_conns.append(rescon)
                
        for conn in rm_conns:
            self.saved_conn_cache.discard(conn)
            self.to_disc_conns.add(conn)
        for conn in added_conns:
            self.saved_conn_cache.add(conn)
            self.to_disc_conns.discard(conn)

    def load_scenario(self, num: int):
        scenario = self.current
        self.patcher.glob.allow_disconnections = True
        
        print('descenarizon', scenario)
        if scenario is not None:
            self._load_current(scenario, unload=True)
        
        self.current_scenario = num
        scenario = self.current

        print('scenarizon', scenario)
        if scenario is not None:
            self._load_current(scenario)
        print('scenar loaded', scenario)
