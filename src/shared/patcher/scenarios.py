import logging

from .bases import ConnectionPattern, ConnectionStr
from . import yaml_tools

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


scenarios = list[Scenario]()
current_scenario = 0


def write_scenarios_from_yaml(yaml_list: list):
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
        
        scenarios.append(scenario)

def choose(present_clients: set[str]) -> str:
    global current_scenario
    scen_num = 0
    for scenario in scenarios:
        scen_num += 1
        if scenario.rules.match(present_clients):
            break
    else:
        scen_num = 0

    ret = ''
    if scen_num != current_scenario:
        if scen_num:
            ret = (f'Switch to scenario {scen_num}: '
                   f'{scenarios[scen_num - 1].name}')
        elif current_scenario:
            ret = (f'Close scenario {scen_num}: '
                   f'{scenarios[scen_num - 1].name}')
        current_scenario = scen_num
    
    return ret