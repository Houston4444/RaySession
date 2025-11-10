from enum import Enum, auto
import logging
from typing import TYPE_CHECKING

from ruamel.yaml.comments import CommentedMap, CommentedSeq

from patshared import PortMode

from . import depattern
from .bases import ConnectionStr, ConnectionPattern, PortData

if TYPE_CHECKING:
    from .scenarios_mng import ScenariosManager

_logger = logging.getLogger(__name__)


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

    def update_yaml_map(self, yaml_map: CommentedMap):
        if self.present_clients:
            pres = yaml_map.get('present_clients')
            if isinstance(pres, CommentedSeq):
                if len(pres) != len(self.present_clients):
                    _logger.warning(
                        'Difference between number of present clients '
                        f'in data ({len(self.present_clients)}) '
                        f'and in yaml map ({len(pres)}) !!!')
                    return

                for i, present_client in enumerate(self.present_clients):
                    pres[i] = present_client
                    
            elif isinstance(pres, str):
                if len(self.present_clients) != 1:
                    _logger.warning(
                        f'yaml present_clients is a str but there is not '
                        f'just 1 present client in data '
                        f'({len(self.present_clients)}) !')
                    return
                
                yaml_map['present_clients'] = self.present_clients[0]
        
        if self.absent_clients:
            abst = yaml_map.get('absent_clients')
            if isinstance(abst, CommentedSeq):
                if len(abst) != len(self.absent_clients):
                    _logger.warning(
                        'Difference between number of absent clients '
                        f'in data ({len(self.absent_clients)}) '
                        f'and in yaml map ({len(abst)}) !!!')
                    return

                for i, absent_client in enumerate(self.absent_clients):
                    abst[i] = absent_client
                    
            elif isinstance(abst, str):
                if len(self.absent_clients) != 1:
                    _logger.warning(
                        f'yaml present_clients is a str but there is not '
                        f'just 1 present client in data '
                        f'({len(self.absent_clients)}) !')
                    return
                
                yaml_map['absent_clients'] = self.absent_clients[0]


class BaseScenario:
    '''Mother Class of Scenario. Is used by the default scenario.
    Does not contains rules and redirections'''
    def __init__(self, mng: 'ScenariosManager'):
        self.mng = mng
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
    
    def startup_depattern(self, ports: dict[PortMode, list[PortData]]):
        depattern.startup(
            ports, self.mng,
            self.saved_conns, self.saved_patterns)
        depattern.startup(
            ports, self.mng, 
            self.forbidden_conns, self.forbidden_patterns)

    def port_depattern(
            self, ports: dict[PortMode, list[PortData]], port: PortData):
        depattern.add_port(
            ports, self.saved_conns, self.saved_patterns, port)
        depattern.add_port(
            ports, self.forbidden_conns, self.forbidden_patterns, port)


class Scenario(BaseScenario):
    def __init__(
            self, mng: 'ScenariosManager',
            rules: ScenarioRules, base_map: CommentedMap):
        super().__init__(mng)
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
            if self.mng.capture_eqvs.alias(port_from) == cp_red[0]:
                return True
        
        for cp_red in self.playback_redirections:
            if self.mng.playback_eqvs.alias(port_to) == cp_red[0]:
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
                  if self.mng.capture_equivalence(ct[orig]) == port_from]
        r_ins = [ct[dest] for ct in self.playback_redirections
                 if self.mng.playback_equivalence(ct[orig]) == port_to]

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
