import logging
from typing import TYPE_CHECKING

from ruamel.yaml.comments import CommentedMap, CommentedSeq

from patshared import PortMode

from jack_renaming_tools import Renamer, one_port_belongs_to_client

from .bases import (ConnectionStr, JackClientBaseName,
                    NsmClientName, PortData)
from . import yaml_tools
from .scenario import ScenarioMode, ScenarioRules, BaseScenario, Scenario
from .equivalences import Equivalences

if TYPE_CHECKING:
    from .patcher import Patcher


_logger = logging.getLogger(__name__)


class ScenariosManager:
    def __init__(self, patcher: 'Patcher'):
        self.scenarios = list[BaseScenario]()
        self.scenarios.append(BaseScenario(self))
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
        
        self.capture_eqvs = Equivalences()
        self.playback_eqvs = Equivalences()

    @property
    def current(self) -> BaseScenario:
        return self.scenarios[self.current_num]

    def replace_aliases(
            self, conns: set[ConnectionStr]) -> set[ConnectionStr]:
        '''replace in `conns` all aliases (equivalences)
        with their first present port.
        If no port exists, keep the alias'''
        out_conns = set[ConnectionStr]()
        
        out_port_names = set(
            [p.name for p in self.patcher.ports[PortMode.OUTPUT]])
        in_port_names = set(
            [p.name for p in self.patcher.ports[PortMode.INPUT]])
        
        for conn in conns:
            out_conns.add(
                (self.capture_eqvs.first(conn[0], out_port_names),
                 self.playback_eqvs.first(conn[1], in_port_names)))
        
        return out_conns

    def replace_aliases_on_place(self, conns: set[ConnectionStr]):
        '''replace in `conns` all aliases (equivalences)
        with their first present port.
        If no port exists, keep the alias'''
        out_port_names = set(
            [p.name for p in self.patcher.ports[PortMode.OUTPUT]])
        in_port_names = set(
            [p.name for p in self.patcher.ports[PortMode.INPUT]])
        
        out_conns = set[ConnectionStr]()
        for conn in conns:
            out_conns.add(
                (self.capture_eqvs.first(conn[0], out_port_names),
                    self.playback_eqvs.first(conn[1], in_port_names)))
        
        conns.clear()
        conns |= out_conns
        
    def replace_ports_with_aliases(
            self, conns: set[ConnectionStr]) -> set[ConnectionStr]:
        '''replace in `conns` port names with their alias if it exists'''
        out_conns = set[ConnectionStr]()
        
        for conn in conns:
            out_conns.add(
                (self.capture_eqvs.alias(conn[0]),
                 self.playback_eqvs.alias(conn[1])))
        
        return out_conns

    def load_aliases(self, conns: set[ConnectionStr]):
        '''replace in `conns` all port names with their alias,
        and then all aliases with their first present port name'''
        aliconns = self.replace_ports_with_aliases(conns)
        self.replace_aliases_on_place(aliconns)
        conns.clear()
        conns |= aliconns

    def replace_port_name(
            self, conns: set[ConnectionStr], alias: str, new: str,
            port_mode: PortMode):
        if port_mode not in (PortMode.OUTPUT, PortMode.INPUT):
            return
        
        out_conns = set[ConnectionStr]()
        process = False
        
        if port_mode is PortMode.OUTPUT:
            for conn in conns:
                if self.capture_eqvs.alias(conn[0]) == alias:
                    process = True
                    out_conns.add((new, conn[1]))
                else:
                    out_conns.add(conn)
        else:
            for conn in conns:
                if self.playback_eqvs.alias(conn[1]) == alias:
                    process = True
                    out_conns.add((conn[0], new))
                else:
                    out_conns.add(conn)

        if process:
            conns.clear()
            conns |= out_conns

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
            
            scenario = Scenario(self, sc_rules, el)
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

        all_equiv_ports = set[str]()
        for eqv_key in ('capture_equivalences', 'playback_equivalences'):
            equivalences = yaml_tools.item_at(yaml_dict, eqv_key, dict)
            if isinstance(equivalences, CommentedMap):
                for alias, port_names in equivalences.items():
                    if not isinstance(alias, str):
                        yaml_tools._err_reading_yaml(
                            equivalences, alias, f'{alias} is not a string, '
                            f'ignored !')
                        continue
                    
                    if not isinstance(port_names, CommentedSeq):
                        yaml_tools.log_wrong_type_in_map(
                            equivalences, alias, list)
                    
                    equiv = list[str]()
                    
                    for i, port_name in enumerate(port_names):
                        if not isinstance(port_name, str):
                            yaml_tools.log_wrong_type_in_seq(
                                port_names, i, 'port name', str)
                            continue
                        
                        if port_name in all_equiv_ports:
                            yaml_tools._err_reading_yaml(
                                port_names, i,
                                f'{port_name} is already used '
                                f'in a previous equivalence. Ignored')
                            continue

                        all_equiv_ports.add(port_name)
                        equiv.append(port_name)
                    
                    if equiv:
                        if eqv_key == 'capture_equivalences':
                            self.capture_eqvs[alias] = equiv
                        else:
                            self.playback_eqvs[alias] = equiv
        
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

        self.replace_aliases_on_place(default.saved_conns)
        self.replace_aliases_on_place(default.forbidden_conns)

        scenars = yaml_tools.item_at(yaml_dict, 'scenarios', list)
        if isinstance(scenars, CommentedSeq):
            self._load_yaml_scenarios(scenars)
        
        out_port_names = set(
            [p.name for p in self.patcher.ports[PortMode.OUTPUT]])
        in_port_names = set(
            [p.name for p in self.patcher.ports[PortMode.INPUT]])
        
        for scenario in self.scenarios:
            scenario.startup_depattern(self.patcher.ports)
            self.replace_aliases_on_place(scenario.saved_conns)
            self.replace_aliases_on_place(scenario.forbidden_conns)

            if isinstance(scenario, Scenario):
                for i, cp_red in enumerate(scenario.capture_redirections):
                    scenario.capture_redirections[i] = tuple(
                        [self.capture_eqvs.corrected(cp, out_port_names)
                         for cp in cp_red])
                
                for i, pb_red in enumerate(scenario.playback_redirections):
                    scenario.playback_redirections[i] = tuple(
                        [self.playback_eqvs.corrected(pb, in_port_names)
                         for pb in pb_red])

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
                            self.replace_ports_with_aliases(
                                scenario.saved_conns))
                        yaml_tools.save_connections(
                            scenar_map, 'forbidden_connections',
                            scenario.forbidden_patterns,
                            self.replace_ports_with_aliases(
                                scenario.forbidden_conns))
                        break
        
        default = self.scenarios[0]

        yaml_tools.save_connections(
            yaml_dict, 'connections',
            default.saved_patterns,
            self.replace_ports_with_aliases(default.saved_conns))
        
        yaml_tools.save_connections(
            yaml_dict, 'forbidden_connections',
            default.forbidden_patterns,
            self.replace_ports_with_aliases(default.forbidden_conns))

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
        # self.patcher.switching_scenario = True

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

        out_port_names = set(
            [p.name for p in self.patcher.ports[PortMode.OUTPUT]])
        in_port_names = set(
            [p.name for p in self.patcher.ports[PortMode.INPUT]])

        # manage aliases
        if port.mode is PortMode.INPUT:
            alias = self.playback_eqvs.alias(port.name)
            if alias == port.name:
                return

            if self.playback_eqvs.first(alias, in_port_names) != port.name:
                # new port does not becomes the first item of alias
                return
        
        elif port.mode is PortMode.OUTPUT:
            alias = self.capture_eqvs.alias(port.name)
            if alias == port.name:
                return

            if self.capture_eqvs.first(alias, out_port_names) != port.name:
                # new port does not becomes the first item of alias
                return

        else:
            return

        # replace in all connections sets the alias or the old port name
        # with the new port name        
        for scenario in self.scenarios:
            for conns in scenario.saved_conns, scenario.forbidden_conns:
                self.replace_port_name(
                    conns, alias, port.name, port.mode)
            
            if isinstance(scenario, Scenario):
                if port.mode is PortMode.OUTPUT:
                    for i, cp_red in enumerate(scenario.capture_redirections):
                        scenario.capture_redirections[i] = tuple(
                            [self.capture_eqvs.corrected(cp, out_port_names)
                             for cp in cp_red])
                        
                else:
                    for i, pb_red in enumerate(scenario.playback_redirections):
                        scenario.playback_redirections[i] = tuple(
                            [self.playback_eqvs.corrected(pb, in_port_names)
                             for pb in pb_red])
        
        if port.mode is PortMode.INPUT:
            for conn in self.patcher.connections:
                if not (self.playback_eqvs.alias(conn[1]) == alias
                        and conn[1] != port.name):
                    continue

                for in_port in self.patcher.ports[PortMode.INPUT]:
                    if in_port.name == conn[1]:
                        in_port.is_new = True
                        break

                self.patcher.conns_to_connect.discard(conn)
                self.patcher.conns_to_disconnect.add(conn)
                self.patcher.conns_to_connect.add((conn[0], port.name))
                self.patcher.conns_to_disconnect.discard((conn[0], port.name))

        elif port.mode is PortMode.OUTPUT:
            for conn in self.patcher.connections:
                if not (self.capture_eqvs.alias(conn[0]) == alias
                        and conn[0] != port.name):
                    continue

                for out_port in self.patcher.ports[PortMode.OUTPUT]:
                    if out_port.name == conn[0]:
                        out_port.is_new = True
                        break

                self.patcher.conns_to_connect.discard(conn)
                self.patcher.conns_to_disconnect.add(conn)
                self.patcher.conns_to_connect.add((port.name, conn[1]))
                self.patcher.conns_to_connect.discard((port.name, conn[1]))

    def check_removed_nsm_brothers(
            self, ex_brothers: dict[NsmClientName, JackClientBaseName]):
        '''At file open, in all connections lists,
        remove connections with a port that should not exist anymore
        because its NSM client has been removed.
        
        `brothers` is the dict in file'''
        rm_jack_clients = [ex_brothers[ex_b] for ex_b in ex_brothers
                           if ex_b not in self.patcher.brothers_dict]
        if not rm_jack_clients:
            return

        for scenario in self.scenarios:
            for svd_conn in list(scenario.saved_conns):
                for rm_jack in rm_jack_clients:
                    if one_port_belongs_to_client(svd_conn, rm_jack):
                        _logger.info(
                            f'remove saved connection {svd_conn}'
                            f'in {scenario} '
                            f'because NSM client has been removed')
                        scenario.saved_conns.discard(svd_conn)
                        break
            
            for fbd_conn in list(scenario.forbidden_conns):
                for rm_jack in rm_jack_clients:
                    if one_port_belongs_to_client(fbd_conn, rm_jack):
                        _logger.info(
                            f'remove forbidden connection {fbd_conn} '
                            f'in {scenario} '
                            f'because NSM client has been removed')
                        scenario.forbidden_conns.discard(fbd_conn)
                        break

    def nsm_brother_removed(
            self, nsm_client_id: NsmClientName,
            jack_name: JackClientBaseName):
        for scenario in self.scenarios:
            for svd_conn in list(scenario.saved_conns):
                if one_port_belongs_to_client(svd_conn, jack_name):
                    scenario.saved_conns.discard(svd_conn)
                    
            for fbd_conn in list(scenario.saved_conns):
                if one_port_belongs_to_client(fbd_conn, jack_name):
                    scenario.forbidden_conns.discard(fbd_conn)
        
        self.reload_scenario()

    def nsm_brother_id_changed(
            self,
            ex_client_id: NsmClientName, ex_jack_name: JackClientBaseName,
            new_client_id: NsmClientName, new_jack_name: JackClientBaseName):
        renamer = Renamer(ex_client_id, new_client_id,
                          ex_jack_name, new_jack_name)
        
        for scenario in self.scenarios:
            for svd_conn in list(scenario.saved_conns):
                if renamer.one_port_belongs(svd_conn):
                    scenario.saved_conns.discard(svd_conn)
                    scenario.saved_conns.add(renamer.ports_renamed(svd_conn))
                    
            for fbd_conn in list(scenario.forbidden_conns):
                if renamer.one_port_belongs(fbd_conn):
                    scenario.forbidden_conns.discard(fbd_conn)
                    scenario.forbidden_conns.add(
                        renamer.ports_renamed(fbd_conn))
            
            if not isinstance(scenario, Scenario):
                continue
            
            for i, client_name in enumerate(scenario.rules.present_clients):
                scenario.rules.present_clients[i] = \
                    renamer.group_renamed(client_name)
                scenario.base_map['rules']['present_clients'][i] = \
                    scenario.rules.present_clients[i]
            
            for i, client_name in enumerate(scenario.rules.absent_clients):
                scenario.rules.absent_clients[i] = \
                    renamer.group_renamed(client_name)
                scenario.base_map['rules']['absent_clients'][i] = \
                    scenario.rules.absent_clients[i]
                    
            for i, pb_red in enumerate(scenario.playback_redirections):
                if renamer.one_port_belongs(pb_red):
                    new_red = renamer.ports_renamed(pb_red)
                    scenario.playback_redirections[i] = new_red
                    red_map = scenario.base_map['playback_redirections'][i]
                    red_map['origin'], red_map['destination'] = new_red
            
            for i, ct_red in enumerate(scenario.capture_redirections):
                if renamer.one_port_belongs(ct_red):
                    new_red = renamer.ports_renamed(ct_red)
                    scenario.capture_redirections[i] = new_red                    
                    cap_map = scenario.base_map['capture_redirections'][i]
                    cap_map['origin'], cap_map['destination'] = new_red
            
            for i, cdomain in enumerate(scenario.connect_domain):
                from_, to_ = cdomain
                new_from_, new_to_ = cdomain
                if isinstance(from_, str):
                    new_from_ = renamer.port_renamed(from_)
                if isinstance(to_, str):
                    new_to_ = renamer.port_renamed(to_)
                    
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
                    new_from_ = renamer.port_renamed(from_)
                if isinstance(to_, str):
                    new_to_ = renamer.port_renamed(to_)
                    
                if new_from_ == from_ and new_to_ == to_:
                    continue

                scenario.no_connect_domain[i] = (new_from_, new_to_)
                dom_map = scenario.base_map['no_connect_domain'][i]
                if isinstance(new_from_, str):
                    dom_map['from'] = new_from_
                if isinstance(new_to_, str):
                    dom_map['to'] = new_to_

        self.reload_scenario()

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

        self.reload_scenario()

    def choose(self, present_clients: set[str]) -> str:
        '''choose the scenario because somes elements relative
        to scenarios rules may have change (present clients)'''
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

    def reload_scenario(self):
        '''rewrite patcher.conns_to_connect and patcher.conns_to_disconnect
        without checking scenario change.'''
        self.load_scenario(self.current_num)

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

        projection_conns = set[ConnectionStr]()

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
