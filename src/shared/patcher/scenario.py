from enum import Enum, auto
import logging
from typing import TYPE_CHECKING

from ruamel.yaml.comments import CommentedMap, CommentedSeq

from patshared import PortMode

from . import depattern
from .bases import ConnectionStr, ConnectionPattern, PortData
from . import yaml_tools

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
        self.started_nsm_clients = list[str]()
        self.stopped_nsm_clients = list[str]()
        
    def fill(self, map: CommentedMap) -> bool:
        '''fill the rules with yaml contents.
        Return `False` if rules are not valid'''
        lists_ = {'present_clients': self.present_clients,
                  'absent_clients': self.absent_clients,
                  'present_nsm_clients': self.started_nsm_clients,
                  'absent_nsm_clients': self.stopped_nsm_clients}
        
        for key, list_ in lists_.items():
            seq = map.get(key)    
            valid = True

            if isinstance(seq, str):
                list_.append(seq)
            elif isinstance(seq, CommentedSeq):
                for item in seq:
                    if not isinstance(item, str):
                        valid = False
                        break
                    list_.append(item)
            elif seq is not None:
                valid = False
            
            if not valid:
                yaml_tools.log_wrong_type_in_map(
                    map, key, (list, str))
                return False
        
        return True
        
    def match(self, mng: 'ScenariosManager') -> bool:
        for client_name in self.present_clients:
            if client_name not in mng.patcher.present_clients:
                return False
        
        for client_name in self.absent_clients:
            if client_name in mng.patcher.present_clients:
                return False
            
        for nsm_client_id in self.started_nsm_clients:
            if nsm_client_id not in mng.patcher.started_brothers:
                return False
            
        for nsm_client_id in self.stopped_nsm_clients:
            if nsm_client_id in mng.patcher.started_brothers:
                return False
        
        return True


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
