from enum import Enum, auto
import re

from ruamel.yaml.comments import CommentedMap

from patshared import PortMode

from . import depattern
from .bases import ConnectionStr, ConnectionPattern, PortData


class ScenarioMode(Enum):
    '''Defines the scenario connections behavior.'''

    AUTO = auto()
    '''Scenario mode will be REDIRECTIONS if there are redirections and
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
        forbidden_conns = depattern.to_yaml_connection_dicts(
            self.forbidden_patterns, self.forbidden_conns)
        if forbidden_conns:
            out_d['forbidden_connections'] = forbidden_conns
        saved_conns = depattern.to_yaml_connection_dicts(
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
    def __init__(self, rules: ScenarioRules, base_map: CommentedMap):
        super().__init__()
        self.name = ''
        self.rules = rules
        self.base_map = base_map
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
        
        out_d['rules'] = self.rules.to_yaml_dict()
        
        if self.capture_redirections:
            out_d['capture_redirections'] = [
                {'origin': cr[0], 'destination': cr[1]}
                for cr in self.capture_redirections]
        if self.playback_redirections:
            out_d['playback_redirections'] = [
                {'origin': pr[0], 'destination': pr[1]}
                for pr in self.playback_redirections]
        
        if self.connect_domain:
            cd_dicts = list[dict]()
            for cd in self.connect_domain:
                cd_dict = {}
                if isinstance(cd[0], re.Pattern):
                    if cd[0].pattern != '.*':
                        cd_dict['from_pattern'] = cd[0].pattern
                else:
                    cd_dict['from'] = cd[0]
                    
                if isinstance(cd[1], re.Pattern):
                    if cd[1].pattern != '.*':
                        cd_dict['to_pattern'] = cd[1].pattern
                else:
                    cd_dict['to'] = cd[1]
                cd_dicts.append(cd_dict)
            
            out_d['connect_domain'] = cd_dicts
            
        if self.no_connect_domain:
            ncd_dicts = list[dict]()
            for ncd in self.no_connect_domain:
                ncd_dict = {}
                if isinstance(ncd[0], re.Pattern):
                    if ncd[0].pattern != '.*':
                        ncd_dict['from_pattern'] = ncd[0].pattern
                else:
                    ncd_dict['from'] = ncd[0]
                    
                if isinstance(ncd[1], re.Pattern):
                    if ncd[1].pattern != '.*':
                        ncd_dict['to_pattern'] = ncd[1].pattern
                else:
                    ncd_dict['to'] = ncd[1]
                ncd_dicts.append(ncd_dict)
            
            out_d['no_connect_domain'] = ncd_dicts
        
        forbidden_conns = depattern.to_yaml_connection_dicts(
            self.forbidden_patterns, self.forbidden_conns)
        if forbidden_conns:
            out_d['forbidden_connections'] = forbidden_conns

        saved_conns = depattern.to_yaml_connection_dicts(
            self.saved_patterns, self.saved_conns)        
        if saved_conns:
            out_d['connections'] = saved_conns
                
        return out_d