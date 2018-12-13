import sys
from daemon_tools import CommandLineArgs

debug_only = False
last_client_message = ''

class Terminal:
    _last_client_name = ''
    
    @classmethod
    def message(cls, string):
        if cls._last_client_name and cls._last_client_name != 'daemon':
            sys.stderr.write('\n')
        
        sys.stderr.write('[\033[90mray-daemon\033[0m]\033[92m%s\033[0m\n'
                            % string)
        
        cls._last_client_name = 'daemon'

    @classmethod
    def clientMessage(cls, byte_string, client_name, client_id):
        client_str = "%s.%s" % (client_name, client_id)
        
        if not CommandLineArgs.debug_only:
            if cls._last_client_name != client_str:
                sys.stderr.write('\n[\033[90m%s-%s\033[0m]\n'
                                    % (client_name, client_id))
            sys.stderr.buffer.write(byte_string)
            
        cls._last_client_name = client_str
        
    @classmethod
    def warning(cls, string):
        sys.stderr.write('[\033[90mray-daemon\033[0m]%s\033[0m\n' % string)
        cls._last_client_name = 'daemon'
    
def MESSAGE(string):
    global last_client_message
    
    if last_client_message and last_client_message != 'daemon':
        sys.stderr.write('\n')
        
    sys.stderr.write('[\033[90mray-daemon\033[0m]\033[92m%s\033[0m\n'
                        % string)
    
    last_client_message = 'daemon'

def CLIENT_MESSAGE(byte_string, client_name, client_id):
    global last_client_message
    
    client_str = "%s.%s" % (client_name, client_id)
    
    if not CommandLineArgs.debug_only:
        if last_client_message != client_str:
            sys.stderr.write('\n[\033[90m%s-%s\033[0m]\n'
                                % (client_name, client_id))
        sys.stderr.buffer.write(byte_string)
    
    last_client_message = client_str

def WARNING(string):
    sys.stderr.write('[\033[90mray-daemon\033[0m]%s\033[0m\n' % string)
