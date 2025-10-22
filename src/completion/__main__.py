from enum import Enum
from pathlib import Path
import subprocess
import sys

from arg_lines import (
    CLIENT_PROPS, HELP_ARGS, FIRST_ARG, SERVER_OPTIONS, YESNO,
    ADD_EXEC_OPS, LIST_CLIENTS_FILTERS,
    CLIENT_ARG, TRASHED_CLIENT_ARG)

MULTI_DAEMON_FILE = Path('/tmp/RaySession/multi-daemon.json')
CONFIG_FILE = Path.home() / '.config' / 'RaySession' / 'RaySession.conf'


class ControlState(Enum):
    NOT_CHECKED = 0
    STARTED = 1
    HIDDEN_STARTED = 2


class RControl:
    def __init__(self) -> None:
        self.state = ControlState.NOT_CHECKED
        self.port = '0'
        'used only in case we need a hidden daemon'
        
    def command(self, *args) -> str:
        if self.state is ControlState.NOT_CHECKED:
            port = ray_control('get_port')
            if port:
                self.state = ControlState.STARTED
            else:
                json_list = None
                import os
                if os.path.exists(MULTI_DAEMON_FILE):
                    import json
                    try:
                        with open(MULTI_DAEMON_FILE, 'r') as f:
                            json_list = json.load(f)
                    except:
                        pass

                if isinstance(json_list, list):
                    def_root = get_default_root()
                    
                    for daemon_d in json_list:
                        if not isinstance(daemon_d, dict):
                            continue
                        
                        if daemon_d.get('root') == def_root:
                            port = daemon_d.get('port')
                            if isinstance(port, int):
                                self.port = str(port)
                                break
                
                if self.port == '0':
                    self.port = ray_control(
                        'start_new_hidden').partition('\n')[0]
                crade_log('le port hidden', self.port)
                self.state = ControlState.HIDDEN_STARTED
                
        if self.state is ControlState.STARTED:
            return ray_control(*args)
        
        return ray_control('--port', self.port, *args)
    
    def bs_comm(self, *args):
        ret = self.command(*args)
        out_ret = ''
        for c in ret:
            if c in ' $`"\'|&;<>()[]{}^*?~=,%!':
                out_ret += '\\\\'
            out_ret += c
        crade_log(out_ret.splitlines())
        return out_ret
    
    def clear(self):
        if self.state is ControlState.HIDDEN_STARTED:
            ray_control('--port', self.port, 'quit')


r_control = RControl()

def crade_log(*args):
    with open('ray_comp_log', 'a') as f:
        f.write(f"{args}")

def ray_control(*args: str) -> str:
    ctrls = ['ray_control'] + [a for a in args]
    try:
        ret = subprocess.check_output(
            ctrls, stderr=subprocess.DEVNULL).decode()
    except subprocess.CalledProcessError as e:
        return ''
    
    return ret

def get_default_root() -> str:
    if not CONFIG_FILE.exists():
        return str(Path.home() / 'Ray Sessions')
    
    try:
        with open(CONFIG_FILE, 'r') as f:
            contents = f.read()
    except:
        return ''
    
    read_general = False
    for line in contents.splitlines():
        line_strip = line.strip()
        if line_strip == '[General]':
            read_general = True
            continue
        elif line_strip.startswith('['):
            read_general = False
            continue
        
        if read_general and line_strip.startswith('default_session_root='):
            return line_strip.partition('=')[2]
    
    return str(Path.home() / 'Ray Sessions')

def complete_control(comp_words: list[str]) -> str:
    if len(comp_words) == 1:
        return HELP_ARGS + FIRST_ARG
    
    if comp_words[0] == '--detach':
        comp_words = comp_words[1:]
        
    if comp_words[0] == '--port':
        if len(comp_words) == 2:
            return ray_control('list_daemons')
        comp_words = comp_words[2:]
        
        if comp_words[0] == '--detach':
            comp_words = comp_words[1:]
    
    if len(comp_words) == 1:
        return FIRST_ARG

    match comp_words[0]:
        case 'open_session'|'open_session_off':
            if len(comp_words) == 2:
                return r_control.bs_comm('list_sessions')
            if len(comp_words) == 3:
                return r_control.bs_comm('list_session_templates')
        
        case 'new_session':
            if len(comp_words) == 3:
                return r_control.bs_comm('list_session_templates')
            
        case 'remove_client_template':
            if len(comp_words) == 2:
                return r_control.bs_comm('list_user_client_templates')
        
        case 'has_option':
            if len(comp_words) == 2:
                return SERVER_OPTIONS
        
        case 'auto_export_custom_names':
            if len(comp_words) == 2:
                return YESNO
        
        case 'save_as_template':
            if len(comp_words) == 2:
                return r_control.bs_comm('list_session_templates')
        
        case 'open_snapshot':
            if len(comp_words) == 2:
                return r_control.bs_comm('list_snapshots')
            
        case 'add_exec':
            if len(comp_words) > 2:
                return ADD_EXEC_OPS
        
        case 'add_factory_client_template':
            if len(comp_words) == 2:
                return r_control.bs_comm('list_factory_client_templates')
            if len(comp_words) == 3:
                return 'not_start'
        
        case 'add_user_client_template':
            if len(comp_words) == 2:
                return r_control.bs_comm('list_user_client_templates')
            if len(comp_words) == 3:
                return 'not_start'
            
        case 'list_clients':
            return LIST_CLIENTS_FILTERS
        
        case 'client':
            if len(comp_words) == 2:
                return r_control.bs_comm('list_clients')
            
            if len(comp_words) == 3:
                return CLIENT_ARG
            
            match comp_words[2]:
                case 'open_snapshot':
                    if len(comp_words) == 4:
                        return r_control.bs_comm(
                            'client', comp_words[1], 'list_snapshots')
                        
                case 'set_properties':
                    return CLIENT_PROPS
                
        case 'trashed_client':
            if len(comp_words) == 2:
                return r_control.bs_comm('list_trashed_clients')
            
            if len(comp_words) == 3:
                return TRASHED_CLIENT_ARG

    return ''

if __name__ == '__main__':
    with open('ray_comp_log', 'w') as f:
        f.write('')
    
    app, *args = sys.argv[1:]
    crade_log(args)
    
    if app == 'ray_control':
        print(complete_control(args))