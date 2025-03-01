
# Imports from standard library
import os
import socket
import sys
from typing import TYPE_CHECKING
import logging

# third party imports
from qtpy.QtCore import QObject, QProcess, QTimer
from qtpy.QtWidgets import QApplication

# Imports from src/shared
from osclib import (TCP, Address, get_free_osc_port,
                    verified_address)
import ray
import osc_paths.ray as R

# Local imports
from gui_server_thread import GuiServerThread
from gui_tools import CommandLineArgs, ErrDaemon, _translate

if TYPE_CHECKING:
    from .gui_session import SignaledSession


_logger = logging.getLogger(__name__)


class DaemonManager(QObject):
    def __init__(self, session: 'SignaledSession'):
        QObject.__init__(self)
        self.session = session
        self.signaler = self.session.signaler
        self.main_win = None

        self._process = QProcess()

        self._process.errorOccurred.connect(self._error_in_process)
        self._process.setProcessChannelMode(
            QProcess.ProcessChannelMode.ForwardedChannels)

        self._announce_timer = QTimer()
        self._announce_timer.setInterval(2000)
        self._announce_timer.setSingleShot(True)
        self._announce_timer.timeout.connect(self._announce_timer_out)

        self._port = None
        self._is_announced = False
        self._is_nsm_locked = False

        self.is_local = True
        self.launched_before = False
        self.address = None
        self.url = ''
        self.session_root = ""

        self.signaler.daemon_announce.connect(self._receive_announce)
        self.signaler.daemon_url_changed.connect(self._change_url)

    def _error_in_process(self, error):
        if self.main_win is None:
            return

        self.main_win.daemon_crash()

    def _change_url(self, new_url: str):
        addr = verified_address(new_url)
        if isinstance(addr, Address):
            self.set_osc_address(addr)
        else:
            return

        self._call_daemon()

    def _call_daemon(self):
        if not self.address:
            # I don't know really why, but it works only with a timer
            QTimer.singleShot(5, self._show_daemon_url_window)
            return

        self._announce_timer.start()

        server = GuiServerThread.instance()
        if not server:
            _logger.error(
                'GUI can not call daemon, GUI OSC server is missing.')
            return

        server.announce()

    def _show_daemon_url_window(self):
        self.signaler.daemon_url_request.emit(ErrDaemon.NO_ERROR, self.url)

    def _announce_timer_out(self):
        if self.launched_before:
            self.signaler.daemon_url_request.emit(
                ErrDaemon.NO_ANNOUNCE, self.url)
        else:
            sys.stderr.write(
                _translate(
                    'error',
                    "No announce from ray-daemon. RaySession can't works. Sorry.\n"))
            QApplication.quit()

    def _receive_announce(
            self, src_addr: Address, version: str, server_status: ray.ServerStatus,
            options: ray.Option, session_root: str, is_net_free: int):
        self._announce_timer.stop()

        if version.split('.')[:2] != ray.VERSION.split('.')[:2]:
            # works only if the two firsts digits are the same (ex: 0.6)
            self.signaler.daemon_url_request.emit(
                ErrDaemon.WRONG_VERSION, self.url)
            self.disannounce(src_addr)
            return

        if (CommandLineArgs.net_session_root
                and session_root != CommandLineArgs.net_session_root):
            self.signaler.daemon_url_request.emit(
                ErrDaemon.WRONG_ROOT, self.url)
            self.disannounce(src_addr)
            return

        if not is_net_free:
            self.signaler.daemon_url_request.emit(
                ErrDaemon.FORBIDDEN_ROOT, self.url)
            self.disannounce(src_addr)
            return

        if (CommandLineArgs.out_daemon
                and server_status is not ray.ServerStatus.OFF):
            self.signaler.daemon_url_request.emit(ErrDaemon.NOT_OFF, self.url)
            self.disannounce(src_addr)
            return

        self._is_announced = True
        self.address = src_addr
        self._port = src_addr.port
        self.url = src_addr.url
        self.session_root = session_root
        CommandLineArgs.change_session_root(self.session_root)

        self._is_nsm_locked = ray.Option.NSM_LOCKED in options

        if self._is_nsm_locked:
            if self.main_win is not None:
                self.main_win.set_nsm_locked(True)
        elif CommandLineArgs.under_nsm:
            server = GuiServerThread.instance()
            server.to_daemon(R.server.SET_NSM_LOCKED)

        if self.main_win is not None and self.main_win.waiting_for_patchbay:
            self.main_win.waiting_for_patchbay = False
            server = GuiServerThread.instance()
            server.to_daemon(R.server.ASK_FOR_PATCHBAY, '')

        self.signaler.daemon_announce_ok.emit()
        self.session.set_daemon_options(options)

    def finish_init(self):
        self.main_win = self.session.main_win

    def disannounce(self, address=None):
        if not address:
            address = self.address

        if address:
            server = GuiServerThread.instance()
            server.disannounce(address)

        self._port = None
        self.url = ''
        del self.address
        self.address = None
        self._is_announced = False

    def set_external(self):
        self.launched_before = True

    def set_osc_address(self, address: Address):
        self.address = address
        self.launched_before = True
        self._port = self.address.port
        self.url = self.address.url

        self.is_local = bool(self.address.hostname == socket.gethostname())

    def start(self):
        if self.launched_before:
            self._call_daemon()
            return

        if not CommandLineArgs.force_new_daemon:
            ray_control_process = QProcess()
            ray_control_process.start(
                "ray_control",
                ['get_port_gui_free', CommandLineArgs.session_root])
            ray_control_process.waitForFinished(2000)

            if ray_control_process.exitCode() == 0:
                port_str_lines = \
                    ray_control_process.readAllStandardOutput().\
                        data().decode('utf-8')
                port_str = port_str_lines.partition('\n')[0]

                if port_str and port_str.isdigit():
                    self.address = Address(int(port_str))
                    self._port = self.address.port
                    self.url = self.address.url
                    self.launched_before = True
                    self.is_local = True
                    self._call_daemon()
                    sys.stderr.write(
                        "\033[92m%s\033[0m\n" % (
                            _translate('GUI_daemon',
                                       "Connecting GUI to existing ray-daemon port %i")
                            % self._port))

                    if CommandLineArgs.start_session:
                        server = GuiServerThread.instance()
                        if server:
                            server.send(self.address, R.server.OPEN_SESSION,
                                        CommandLineArgs.start_session)
                    return

        server = GuiServerThread.instance()
        if not server:
            _logger.error(
                "impossible for GUI to launch daemon. server is missing.")

        # start process
        arguments = ['--gui-url', str(server.url),
                     '--gui-pid', str(os.getpid()),
                     '--osc-port', str(self._port),
                     '--session-root', CommandLineArgs.session_root]

        if CommandLineArgs.start_session:
            arguments.append('--session')
            arguments.append(CommandLineArgs.start_session)

        if CommandLineArgs.debug_only:
            arguments.append('--debug-only')
        elif CommandLineArgs.debug:
            arguments.append('--debug')
        elif CommandLineArgs.no_client_messages:
            arguments.append('--no-client-messages')

        if CommandLineArgs.config_dir:
            arguments.append('--config-dir')
            arguments.append(CommandLineArgs.config_dir)

        self._process.startDetached('ray-daemon', arguments)
        #self.process.start('konsole', ['-e', 'ray-daemon'] + arguments)

    def stop(self):
        if self.launched_before:
            self.disannounce()
            QTimer.singleShot(10, QApplication.quit)
            return

        server = GuiServerThread.instance()
        server.to_daemon(R.server.QUIT)
        QTimer.singleShot(50, QApplication.quit)

    def set_new_osc_address(self):
        if not (self.address or self._port):
            self._port = get_free_osc_port()
            self.address = Address(self._port)

    def is_announced(self):
        return self._is_announced

    def get_port(self):
        return self._port
