
import liblo
import os
import sys
import time

# !!! we don't load ray.py to win import duration
# if change in ray.Err numbers, this has to be changed too !!!
ERR_UNKNOWN_MESSAGE = -18

def areTheyAllString(args):
    for arg in args:
        if type(arg) != str:
            return False
    return True

def highlightText(string):
    if "'" in string:
        return '"%s"' % string
    else:
        return "'%s'" % string

class OscServer(liblo.Server):
    def __init__(self):
        liblo.Server.__init__(self)
        self.m_daemon_address = None
        self.add_method('/reply', None, self.replyMessage)
        self.add_method('/error', 'sis', self.errorMessage)
        self.add_method('/minor_error', 'sis', self.minorErrorMessage)
        self.add_method('/ray/control/message', 's', self.rayControlMessage)
        self.add_method('/ray/control/server/announce', 'siisi',
                        self.rayControlServerAnnounce)
        self._final_err = -1
        self._wait_for_announce = False
        self._wait_for_start = False
        self._wait_for_start_only = False
        self._started_time = 0
        self._stop_port_list = []

    def replyMessage(self, path, args, types, src_addr):
        if not areTheyAllString(args):
            return
        
        if len(args) >= 1:
            reply_path = args[0]
        else:
            return
        
        if reply_path == '/ray/server/controller_announce':
            self._wait_for_announce = False
            return
        
        elif reply_path == '/ray/server/quit':
            sys.stderr.write('--- Daemon at port %i stopped. ---\n'
                             % src_addr.port)
            if self._stop_port_list:
                if src_addr.port == self._stop_port_list[0]:
                    stopped_port = self._stop_port_list.pop(0)
                    
                    if self._stop_port_list:
                        self.stopDaemon(self._stop_port_list[0])
                    else:
                        self._final_err = 0
                    return
        
        if reply_path != self._osc_order_path:
            sys.stdout.write('bug: reply for a wrong path:%s instead of %s\n'
                             % (highlightText(reply_path), 
                                highlightText(self._osc_order_path)))
            return
        
        if reply_path in ('/ray/server/list_factory_client_templates',
                            '/ray/server/list_user_client_templates'):
            if len(args) >= 2:
                templates = args[1:]
                out_message = ""
                for template_and_icon in templates:
                    template, slash, icon = template_and_icon.partition('/')
                    out_message += "%s\n" % template
                sys.stdout.write(out_message)
                return
            else:
                self._final_err = 0
                
        elif reply_path == '/ray/session/list_snapshots':
            if len(args) >= 2:
                snapshots = args[1:]
                out_message = ""
                for snapshot_and_info in snapshots:
                    snapshot, slash, info = snapshot_and_info.partition(':')
                    out_message += "%s\n" % snapshot
                sys.stdout.write(out_message)
                return
            else:
                self._final_err = 0
        
        elif os.path.basename(reply_path).startswith(('list_', 'get_')):
            if len(args) >= 2:
                sessions = args[1:]
                out_message = ""
                for session in sessions:
                    out_message += "%s\n" % session
                sys.stdout.write(out_message)
                return
            else:
                self._final_err = 0
        
        elif len(args) == 2:
            reply_path, message = args
            if os.path.basename(reply_path).startswith('add_'):
                sys.stdout.write("%s\n" % message)
            self._final_err = 0
    
    def errorMessage(self, path, args, types, src_addr):
        error_path, err, message = args
        
        if error_path != self._osc_order_path:
            sys.stdout.write('bug: error for a wrong path:%s instead of %s\n'
                             % (highlightText(error_path), 
                                highlightText(self._osc_order_path)))
            return
        
        sys.stderr.write('%s\n' % message)
        self._final_err = - err
        print('kofrko', self._final_err)
        
    def minorErrorMessage(self, path, args, types, src_addr):
        error_path, err, message = args
        sys.stdout.write('\033[31m%s\033[0m\n' % message)
        if err == ERR_UNKNOWN_MESSAGE:
            self._final_err = -err
    
    def rayControlMessage(self, path, args, types, src_addr):
        message = args[0]
        sys.stdout.write("%s\n" % message)
        
    def rayControlServerAnnounce(self, path, args, types, src_addr):
        sys.stderr.write('--- Daemon started at port %i ---\n'
                         % src_addr.port)
        
        self._wait_for_start = False
        
        if self._wait_for_start_only:
            self._final_err = 0
            return
        
        self.m_daemon_address = src_addr
        self.sendOrderMessage()
    
    def setDaemonAddress(self, daemon_port):
        self.m_daemon_address = liblo.Address(daemon_port)
        self._wait_for_announce = True
        self._announce_time = time.time()
        self.toDaemon('/ray/server/controller_announce')
    
    def toDaemon(self, *args):
        self.send(self.m_daemon_address, *args)
    
    def setOrderPathArgs(self, path, args):
        self._osc_order_path = path
        self._osc_order_args = args
    
    def sendOrderMessage(self):
        if not self._osc_order_path:
            sys.stderr.write('error: order path was not set\n')
            sys.exit(101)
            
        self.toDaemon(self._osc_order_path, *self._osc_order_args)
    
    def finalError(self):
        return self._final_err
    
    def waitForStart(self):
        self._wait_for_start = True
        self._started_time = time.time()
    
    def waitForStartOnly(self):
        self._wait_for_start_only = True
        
    def setStartedTime(self, started_time):
        self._started_time = started_time
        
    def isWaitingStartForALong(self):
        if not (self._wait_for_start or self._wait_for_announce):
            return False
        
        if self._wait_for_start:
            if time.time() - self._started_time > 3.00:
                sys.stderr.write("server didn't announce, sorry !\n")
                return True
        elif self._wait_for_announce:
            if time.time() - self._announce_time > 1:
                sys.stderr.write(
                    'Error: server did not reply, it may be busy !\n')
                return True
        
        return False
    
    def stopDaemon(self, port):
        sys.stderr.write('--- Stopping daemon at port %i ---\n' % port)
        self.setDaemonAddress(port)
        self.toDaemon('/ray/server/quit')
    
    def stopDaemons(self, stop_port_list):
        self._stop_port_list = stop_port_list
        if self._stop_port_list:
            self.stopDaemon(self._stop_port_list[0])
        
