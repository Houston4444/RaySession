
import os
import sys
import time

# Imports from src/shared
from osclib import Server, Address
import osc_paths
import osc_paths.ray as r

# !!! we don't load ray.py to win import duration
# if change in ray.Err numbers, this has to be changed too !!!
ERR_UNKNOWN_MESSAGE = -18

def are_they_all_strings(args):
    for arg in args:
        if not isinstance(arg, str):
            return False
    return True

def highlight_text(string):
    if "'" in string:
        return '"%s"' % string
    return "'%s'" % string


class OscServer(Server):
    def __init__(self, detach=False):
        Server.__init__(self)
        self.m_daemon_address = None
        self.add_method(osc_paths.REPLY, None, self.reply_message)
        self.add_method(osc_paths.ERROR, 'sis', self.error_message)
        self.add_method(osc_paths.MINOR_ERROR, 'sis',
                        self.minor_error_message)
        self.add_method(r.control.MESSAGE, 's', self.ray_control_message)
        self.add_method(r.control.SERVER_ANNOUNCE, 'siisi',
                        self.ray_control_server_announce)
        self._final_err = -1
        self._wait_for_announce = False
        self._wait_for_start = False
        self._wait_for_start_only = False
        self._started_time = 0
        self._stop_port_list = list[int]()
        self._detach = detach
        self._announce_time = 0
        self._osc_order_path = ''
        self._osc_order_args = []

    def reply_message(
            self, path: str, args: list, types: str, src_addr: Address):
        if not are_they_all_strings(args):
            return

        if len(args) >= 1:
            reply_path: str = args[0]
        else:
            return

        if reply_path == r.server.CONTROLLER_ANNOUNCE:
            self._wait_for_announce = False
            return

        elif reply_path == r.server.QUIT:
            sys.stderr.write('--- Daemon at port %i stopped. ---\n'
                             % src_addr.port)
            if self._stop_port_list:
                if src_addr.port == self._stop_port_list[0]:
                    stopped_port = self._stop_port_list.pop(0)

                    if self._stop_port_list:
                        self.stop_daemon(self._stop_port_list[0])
                    else:
                        self._final_err = 0
                    return

        if reply_path != self._osc_order_path:
            sys.stdout.write('bug: reply for a wrong path:%s instead of %s\n'
                             % (highlight_text(reply_path),
                                highlight_text(self._osc_order_path)))
            return

        if reply_path.endswith('/list_snapshots'):
            if len(args) >= 2:
                snapshots: list[str] = args[1:] # type:ignore
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

    def error_message(self, path, args, types, src_addr):
        error_path, err, message = args

        if error_path != self._osc_order_path:
            sys.stdout.write('bug: error for a wrong path:%s instead of %s\n'
                             % (highlight_text(error_path),
                                highlight_text(self._osc_order_path)))
            return

        sys.stderr.write('%s\n' % message)
        self._final_err = - err

    def minor_error_message(self, path, args, types, src_addr):
        error_path, err, message = args
        sys.stdout.write('\033[31m%s\033[0m\n' % message)
        if err == ERR_UNKNOWN_MESSAGE:
            self._final_err = -err

    def ray_control_message(self, path, args, types, src_addr):
        message = args[0]
        sys.stdout.write("%s\n" % message)

    def ray_control_server_announce(self, path, args, types, src_addr):
        sys.stderr.write('--- Daemon started at port %i ---\n'
                         % src_addr.port)

        self._wait_for_start = False
        self.m_daemon_address = src_addr

        if self._wait_for_start_only:
            self._final_err = 0
            return

        self.send_order_message()

    def set_daemon_address(self, daemon_port):
        self.m_daemon_address = Address(daemon_port)
        self._wait_for_announce = True
        self._announce_time = time.time()
        self.to_daemon(r.server.CONTROLLER_ANNOUNCE, os.getpid())

    def get_daemon_port(self):
        if self.m_daemon_address:
            return self.m_daemon_address.port
        return None

    def to_daemon(self, *args):
        if self.m_daemon_address:
            self.send(self.m_daemon_address, *args)

    def set_order_path_args(self, path, args):
        self._osc_order_path = path
        self._osc_order_args = args

    def send_order_message(self):
        if not self._osc_order_path:
            sys.stderr.write('error: order path was not set\n')
            sys.exit(101)

        self.to_daemon(self._osc_order_path, *self._osc_order_args)

        if self._detach:
            self._final_err = 0

    def final_error(self):
        return self._final_err

    def wait_for_start(self):
        self._wait_for_start = True
        self._started_time = time.time()

    def wait_for_start_only(self):
        self._wait_for_start_only = True

    def set_started_time(self, started_time):
        self._started_time = started_time

    def is_waiting_start_for_a_long(self) -> bool:
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

    def stop_daemon(self, port):
        sys.stderr.write('--- Stopping daemon at port %i ---\n' % port)
        self.set_daemon_address(port)
        self.to_daemon(r.server.QUIT)

    def stop_daemons(self, stop_port_list: list[int]):
        self._stop_port_list = stop_port_list
        if self._stop_port_list:
            self.stop_daemon(self._stop_port_list[0])

    def disannounce_to_daemon(self):
        self.to_daemon(r.server.CONTROLLER_DISANNOUNCE)
