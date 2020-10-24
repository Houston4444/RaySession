
import os
import socket
import sys
from liblo import Address
from PyQt5.QtCore import QObject, QProcess, QTimer
from PyQt5.QtWidgets import QApplication

import ray
from gui_server_thread import GUIServerThread
from gui_tools import CommandLineArgs, ErrDaemon, _translate

class DaemonManager(QObject):
    def __init__(self, session):
        QObject.__init__(self)
        self._session = session
        self._signaler = self._session._signaler

        self.executable = 'ray-daemon'
        self.process = QProcess()

        if ray.QT_VERSION >= (5, 6):
            self.process.errorOccurred.connect(self.errorInProcess)
        self.process.setProcessChannelMode(QProcess.ForwardedChannels)

        self.announce_timer = QTimer()
        self.announce_timer.setInterval(2000)
        self.announce_timer.setSingleShot(True)
        self.announce_timer.timeout.connect(self.announceTimerOut)

        self.stopped_yet = False
        self.is_local = True
        self.launched_before = False
        self.address = None
        self.port = None
        self.url = ''

        self.is_announced = False
        self.is_nsm_locked = False

        self.session_root = ""

        self._signaler.daemon_announce.connect(self.receiveAnnounce)
        self._signaler.daemon_url_changed.connect(self.changeUrl)

    def finishInit(self):
        self._main_win = self._session._main_win

    def errorInProcess(self, error):
        self._main_win.daemonCrash()

    def changeUrl(self, new_url):
        try:
            self.setOscAddress(ray.getLibloAddress(new_url))
        except BaseException:
            return

        self.callDaemon()

    def callDaemon(self):
        if not self.address:
            # I don't know really why, but it works only with a timer
            QTimer.singleShot(5, self.showDaemonUrlWindow)
            return

        self.announce_timer.start()

        server = GUIServerThread.instance()
        if not server:
            sys.stderr.write(
                'GUI can not call daemon, GUI OSC server is missing.\n')
            return

        server.announce()

    def showDaemonUrlWindow(self):
        self._signaler.daemon_url_request.emit(ErrDaemon.NO_ERROR, self.url)

    def announceTimerOut(self):
        if self.launched_before:
            self._signaler.daemon_url_request.emit(
                ErrDaemon.NO_ANNOUNCE, self.url)
        else:
            sys.stderr.write(
                _translate(
                    'error',
                    "No announce from ray-daemon. RaySession can't works. Sorry.\n"))
            QApplication.quit()

    def receiveAnnounce(
            self,
            src_addr,
            version,
            server_status,
            options,
            session_root,
            is_net_free):
        self.announce_timer.stop()

        if version.split('.')[:1] != ray.VERSION.split('.')[:1]:
            # works only if the two firsts digits are the same (ex: 0.6)
            self._signaler.daemon_url_request.emit(
                ErrDaemon.WRONG_VERSION, self.url)
            self.disannounce(src_addr)
            return

        if (CommandLineArgs.net_session_root
                and session_root != CommandLineArgs.net_session_root):
            self._signaler.daemon_url_request.emit(
                ErrDaemon.WRONG_ROOT, self.url)
            self.disannounce(src_addr)
            return

        if not is_net_free:
            self._signaler.daemon_url_request.emit(
                ErrDaemon.FORBIDDEN_ROOT, self.url)
            self.disannounce(src_addr)
            return

        if (CommandLineArgs.out_daemon
                and server_status != ray.ServerStatus.OFF):
            self._signaler.daemon_url_request.emit(ErrDaemon.NOT_OFF, self.url)
            self.disannounce(src_addr)
            return

        self.is_announced = True
        self.address = src_addr
        self.port = src_addr.port
        self.url = src_addr.url
        self.session_root = session_root
        CommandLineArgs.changeSessionRoot(self.session_root)

        self.is_nsm_locked = options & ray.Option.NSM_LOCKED

        if self.is_nsm_locked:
            #self._signaler.daemon_nsm_locked.emit(True)
            self._session._main_win.setNsmLocked(True)
        elif CommandLineArgs.under_nsm:
            server = GUIServerThread.instance()
            server.toDaemon('/ray/server/set_nsm_locked')

        self._signaler.daemon_announce_ok.emit()
        self._session.setDaemonOptions(options)

    def disannounce(self, address=None):
        if not address:
            address = self.address

        if address:
            server = GUIServerThread.instance()
            server.disannounce(address)

        self.port = None
        self.url = ''
        del self.address
        self.address = None
        self.is_announced = False

    def setExternal(self):
        self.launched_before = True

    def setOscAddress(self, address):
        self.address = address
        self.launched_before = True
        self.port = self.address.port
        self.url = self.address.url

        self.is_local = bool(self.address.hostname == socket.gethostname())

    def setOscAddressViaUrl(self, url):
        self.setOscAddress(ray.getLibloAddress(url))

    def start(self):
        if self.launched_before:
            self.callDaemon()
            return

        ray_control_process = QProcess()
        ray_control_process.start("ray_control",
                                  ['get_port_gui_free',
                                   CommandLineArgs.session_root])
        ray_control_process.waitForFinished(2000)

        if ray_control_process.exitCode() == 0:
            port_str_lines = ray_control_process.readAllStandardOutput().data().decode('utf-8')
            port_str = port_str_lines.partition('\n')[0]

            if port_str and port_str.isdigit():
                self.address = Address(int(port_str))
                self.port = self.address.port
                self.url = self.address.url
                self.launched_before = True
                self.is_local = True
                self.callDaemon()
                sys.stderr.write(
                    "\033[92m%s\033[0m\n" %  (_translate('GUI_daemon',
                                          "Connecting GUI to existing ray-daemon port %i")
                                % self.port))

                if CommandLineArgs.start_session:
                    server = GUIServerThread.instance()
                    if server:
                        server.send(self.address, '/ray/server/open_session',
                                    CommandLineArgs.start_session)
                return

        server = GUIServerThread.instance()
        if not server:
            sys.stderr.write(
                "impossible for GUI to launch daemon. server missing.\n")

        # start process
        arguments = ['--gui-url', str(server.url),
                     '--gui-pid', str(os.getpid()),
                     '--osc-port', str(self.port),
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

        self.process.startDetached('ray-daemon', arguments)
        #self.process.start('konsole', ['-e', 'ray-daemon'] + arguments)

    def stop(self):
        if self.launched_before:
            self.disannounce()
            QTimer.singleShot(10, QApplication.quit)
            return

        server = GUIServerThread.instance()
        server.toDaemon('/ray/server/quit')
        QTimer.singleShot(10, QApplication.quit)

    def notEndedAfterWait(self):
        sys.stderr.write('ray-daemon is still running, sorry !\n')
        QApplication.quit()

    def setNewOscAddress(self):
        if not (self.address or self.port):
            self.port = ray.getFreeOscPort()
            self.address = Address(self.port)

    def setNsmLocked(self):
        self.is_nsm_locked = True

    def isAnnounced(self):
        return self.is_announced

    def setDisannounced(self):
        server = GUIServerThread.instance()
        server.disannounce()

        self.port = None
        self.url = ''
        del self.address
        self.address = None
        self.is_announced = False

    def getUrl(self):
        if self.address:
            return self.address.url

        return ''
