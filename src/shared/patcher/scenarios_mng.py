import logging
from typing import TYPE_CHECKING

from ruamel.yaml.comments import CommentedMap, CommentedSeq
from jack_renaming_tools import (
    group_belongs_to_client,
    group_name_client_replaced,
    port_belongs_to_client,
    port_name_client_replaced)

from patshared import PortMode

from .bases import (ConnectionStr, JackClientBaseName,
                    NsmClientName, PortData)
from . import yaml_tools
from .scenario import ScenarioMode, ScenarioRules, BaseScenario, Scenario

if TYPE_CHECKING:
    from .patcher import Patcher


_logger = logging.getLogger(__name__)


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

        for i, el in enumerate(yaml_list):
            if not isinstance(el, CommentedMap):
                yaml_tools.log_wrong_type_in_seq(
                    yaml_list, i, 'scenario', dict)
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
                yaml_tools.log_wrong_type_in_map(
                    rules, 'present_clients', (list, str))
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
                yaml_tools.log_wrong_type_in_map(
                    rules, 'absent_clients', (list, str))
                continue
            
            scenario = Scenario(sc_rules, el)
            scenario.yaml_map = el
            
            name = el.get('name')
            if isinstance(name, str):
                scenario.name = name
            
            conns = yaml_tools.item_at(el, 'connections', list)
            if isinstance(conns, CommentedSeq):
                yaml_tools.load_conns_from_yaml(
                    conns, scenario.saved_conns,
                    scenario.saved_patterns)

            fbd_conns = yaml_tools.item_at(el, 'forbidden_connections', list)
            if isinstance(fbd_conns, CommentedSeq):
                yaml_tools.load_conns_from_yaml(
                    fbd_conns, scenario.forbidden_conns,
                    scenario.forbidden_patterns)

            pb_redirections = yaml_tools.item_at(
                el, 'playback_redirections', list)
            if isinstance(pb_redirections, CommentedSeq):
                for j, pb_red in enumerate(pb_redirections):
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
            
            ct_redirections = yaml_tools.item_at(
                el, 'capture_redirections', list)
            if isinstance(ct_redirections, CommentedSeq):
                for j, ct_red in enumerate(ct_redirections):
                    if not isinstance(ct_red, CommentedMap):
                        yaml_tools.log_wrong_type_in_seq(
                            ct_redirections, j, 'capture_redirection', dict)
                        continue
                    
                    origin = ct_red.get('origin')
                    destination = ct_red.get('destination')
                    
                    if not (isinstance(origin, str)
                            and isinstance(destination, str)):
                        yaml_tools._err_reading_yaml(
                            ct_redirections, j, 'incomplete redirection')
                        continue
                    
                    scenario.capture_redirections.append(
                        (origin, destination))
            
            domain = yaml_tools.item_at(el, 'connect_domain', list)
            if isinstance(domain, CommentedSeq):
                yaml_tools.load_connect_domain(
                    domain, scenario.connect_domain)
                
            no_domain = yaml_tools.item_at(el, 'no_connect_domain', list)
            if isinstance(no_domain, CommentedSeq):
                yaml_tools.load_connect_domain(
                    no_domain, scenario.no_connect_domain)

            scenario.mode = scenario.get_final_mode(
                ScenarioMode.from_input(el.get('mode')))

            valid_keys = {
                'name', 'rules',
                'connections', 'forbidden_connections',
                'playback_redirections', 'capture_redirections',
                'connect_domain', 'no_connect_domain'}

            for key in el.keys():
                if key not in valid_keys:
                    yaml_tools._err_reading_yaml(
                        el, key, f'{key} is unknown and will be ignored.')
                
                elif (key in ('connect_domain', 'no_connect_domain')
                        and scenario.mode is ScenarioMode.REDIRECTIONS):
                    yaml_tools._err_reading_yaml(
                        el, key, 
                        f'{key} will be ignored because '
                        'scenario contains redirections')
            
            self.scenarios.append(scenario)

    def load_yaml(self, yaml_dict: CommentedMap):        
        default = self.scenarios[0]

        conns = yaml_tools.item_at(yaml_dict, 'connections', list)
        if isinstance(conns, CommentedSeq):
            yaml_tools.load_conns_from_yaml(
                conns, default.saved_conns, default.saved_patterns)
        
        forbidden_conns = yaml_tools.item_at(
            yaml_dict, 'forbidden_connections', list)
        if isinstance(forbidden_conns, CommentedSeq):
            yaml_tools.load_conns_from_yaml(
                forbidden_conns, default.forbidden_conns,
                default.forbidden_patterns)

        scenars = yaml_tools.item_at(yaml_dict, 'scenarios', list)
        if isinstance(scenars, CommentedSeq):
            self._load_yaml_scenarios(scenars)
            
        for scenario in self.scenarios:
            scenario.startup_depattern(self.patcher.ports)

    def fill_yaml(self, yaml_dict: CommentedMap):
        scenars_seq = yaml_dict.get('scenarios')
        if isinstance(scenars_seq, CommentedSeq):
            for scenar_map in scenars_seq:
                if not isinstance(scenar_map, CommentedMap):
                    continue

                for scenario in self.scenarios[1:]:
                    if (isinstance(scenario, Scenario)
                            and scenario.base_map is scenar_map):
                        yaml_tools.save_connections(
                            scenar_map, 'connections',
                            scenario.saved_patterns,
                            scenario.saved_conns)
                        yaml_tools.save_connections(
                            scenar_map, 'forbidden_connections',
                            scenario.forbidden_patterns,
                            scenario.forbidden_conns)
                        scenar_map['rules'] = scenario.rules.to_yaml_dict()
                        break
        
        default = self.scenarios[0]

        yaml_tools.save_connections(
            yaml_dict, 'connections',
            default.saved_patterns, default.saved_conns)
        
        yaml_tools.save_connections(
            yaml_dict, 'forbidden_connections',
            default.forbidden_patterns, default.forbidden_conns)

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

    def check_nsm_brothers(
            self, ex_brothers: dict[NsmClientName, JackClientBaseName]):
        '''In all connections lists, remove connections with a port that
        should not exist anymore because its NSM client has been removed.
        
        `brothers` is the dict in file'''
        rm_jack_clients = [ex_brothers[ex_b] for ex_b in ex_brothers
                           if ex_b not in self.patcher.brothers_dict]
        if not rm_jack_clients:
            return

        for scenario in self.scenarios:
            for port_from, port_to in list(scenario.saved_conns):
                for rm_jack in rm_jack_clients:
                    if (port_belongs_to_client(port_from, rm_jack)
                            or port_belongs_to_client(port_to, rm_jack)):
                        _logger.info(
                            f'remove saved connection ({port_from}, {port_to}) '
                            f'in {scenario} '
                            f'because NSM client has been removed')
                        scenario.saved_conns.discard((port_from, port_to))
                        break
            
            for port_from, port_to in list(scenario.forbidden_conns):
                for rm_jack in rm_jack_clients:
                    if (port_belongs_to_client(port_from, rm_jack)
                            or port_belongs_to_client(port_to, rm_jack)):
                        _logger.info(
                            f'remove forbidden connection ({port_from}, {port_to}) '
                            f'in {scenario} '
                            f'because NSM client has been removed')
                        scenario.forbidden_conns.discard((port_from, port_to))
                        break

    def nsm_brother_id_changed(
            self,
            ex_client_id: NsmClientName, ex_jack_name: JackClientBaseName,
            new_client_id: NsmClientName, new_jack_name: JackClientBaseName):
        for scenario in self.scenarios:
            print('NSMBrotherID Cange', scenario)
            for port_from, port_to in list(scenario.saved_conns):
                if (port_belongs_to_client(port_from, ex_jack_name)
                        or port_belongs_to_client(port_to, ex_jack_name)):
                    scenario.saved_conns.discard((port_from, port_to))
                    print('aho', scenario, (port_from, port_to))
                    scenario.saved_conns.add(
                        (port_name_client_replaced(
                            port_from, ex_jack_name, new_jack_name),
                         port_name_client_replaced(
                            port_to, ex_jack_name, new_jack_name)))
                    
            for port_from, port_to in list(scenario.forbidden_conns):
                if (port_belongs_to_client(port_from, ex_jack_name)
                        or port_belongs_to_client(port_to, ex_jack_name)):
                    scenario.forbidden_conns.discard((port_from, port_to))
                    scenario.forbidden_conns.add(
                        (port_name_client_replaced(
                            port_from, ex_jack_name, new_jack_name),
                         port_name_client_replaced(
                            port_to, ex_jack_name, new_jack_name)))
            
            if not isinstance(scenario, Scenario):
                continue
            
            for i, client_name in enumerate(scenario.rules.present_clients):
                scenario.rules.present_clients[i] = \
                    group_name_client_replaced(
                        client_name, ex_jack_name, new_jack_name)
                scenario.base_map['rules']['present_clients'][i] = \
                    scenario.rules.present_clients[i]
            
            for i, client_name in enumerate(scenario.rules.absent_clients):
                scenario.rules.absent_clients[i] = \
                    group_name_client_replaced(
                        client_name, ex_jack_name, new_jack_name)
                scenario.base_map['rules']['absent_clients'][i] = \
                    scenario.rules.absent_clients[i]
                    
            for i, pb_red in enumerate(scenario.playback_redirections):
                orig, dest = pb_red
                if (port_belongs_to_client(orig, ex_jack_name)
                        or port_belongs_to_client(dest, ex_jack_name)):
                    scenario.playback_redirections[i] = (
                        port_name_client_replaced(
                            orig, ex_jack_name, new_jack_name),
                        port_name_client_replaced(
                            dest, ex_jack_name, new_jack_name)
                    )

                    red_map = scenario.base_map['playback_redirections'][i]
                    red_map['origin'] = scenario.playback_redirections[i][0]
                    red_map['destination'] = scenario.playback_redirections[i][1]                        
            
            for i, ct_red in enumerate(scenario.capture_redirections):
                orig, dest = ct_red
                if (port_belongs_to_client(orig, ex_jack_name)
                        or port_belongs_to_client(dest, ex_jack_name)):
                    scenario.capture_redirections[i] = (
                        port_name_client_replaced(
                            orig, ex_jack_name, new_jack_name),
                        port_name_client_replaced(
                            dest, ex_jack_name, new_jack_name)
                    )
                    
                    cap_map = scenario.base_map['capture_redirections'][i]
                    cap_map['origin'] = scenario.capture_redirections[i][0]
                    cap_map['destination'] = scenario.capture_redirections[i][1]  
            
            for i, cdomain in enumerate(scenario.connect_domain):
                from_, to_ = cdomain
                new_from_, new_to_ = cdomain
                if isinstance(from_, str):
                    new_from_ = port_name_client_replaced(
                        from_, ex_jack_name, new_jack_name)
                if isinstance(to_, str):
                    new_to_ = port_name_client_replaced(
                        to_, ex_jack_name, new_jack_name)
                    
                if new_from_ == from_ and new_to_ == to_:
                    continue

                scenario.connect_domain[i] = (new_from_, new_to_)
                dom_map = scenario.base_map['connect_domain'][i]
                if isinstance(new_from_, str):
                    dom_map['from'] = new_from_
                if isinstance(new_to_, str):
                    dom_map['to'] = new_to_
                
            for i, cdomain in enumerate(scenario.no_connect_domain):
                from_, to_ = cdomain
                new_from_, new_to_ = cdomain
                if isinstance(from_, str):
                    new_from_ = port_name_client_replaced(
                        from_, ex_jack_name, new_jack_name)
                if isinstance(to_, str):
                    new_to_ = port_name_client_replaced(
                        to_, ex_jack_name, new_jack_name)
                    
                if new_from_ == from_ and new_to_ == to_:
                    continue

                scenario.no_connect_domain[i] = (new_from_, new_to_)
                dom_map = scenario.base_map['no_connect_domain'][i]
                if isinstance(new_from_, str):
                    dom_map['from'] = new_from_
                if isinstance(new_to_, str):
                    dom_map['to'] = new_to_
                    
            
            # import re
            
            # for i, patt in enumerate(scenario.saved_patterns.copy()):
            #     from_, to_ = patt
            #     new_from_, new_to_ = patt

            #     if isinstance(from_, re.Pattern):
            #         from_str = from_.pattern.replace('\\.', '.')
            #         if port_belongs_to_client(from_str, ex_jack_name):
            #             new_str = port_name_client_replaced(
            #                 from_str, ex_jack_name, new_jack_name)
            #             new_from_ = re.compile(new_str.replace('.', '\\.'))
            #     else:
            #         if port_belongs_to_client(from_, ex_jack_name):
            #             new_from_ = port_name_client_replaced(
            #                 from_, ex_jack_name, new_jack_name)
                            
            #     if isinstance(to_, re.Pattern):
            #         to_str = to_.pattern.replace('\\.', '.')
            #         if port_belongs_to_client(to_str, ex_jack_name):
            #             new_str = port_name_client_replaced(
            #                 to_str, ex_jack_name, new_jack_name)
            #             new_to_ = re.compile(new_str.replace('.', '\\.'))
            #     else:
            #         if port_belongs_to_client(to_, ex_jack_name):
            #             new_to_ = port_name_client_replaced(
            #                 to_, ex_jack_name, new_jack_name)
                
            #     if from_ == new_from_ and to_ == new_to_:
            #         continue
                
            #     scenario.saved_patterns[i] = (new_from_, new_to_)

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

        self.load_scenario(self.current_num)

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
        '''Load a scenario written in the patch file, or default if num == 0.
        It sets patcher.conns_to_connect and patcher.conns_to_disconnect.'''
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
