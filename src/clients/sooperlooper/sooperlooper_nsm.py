#!/usr/bin/python3 -u


import os
import signal
import sys

try:
    from liblo import Address, make_method
except ImportError:
    from pyliblo3 import Address, make_method

from qtpy import QT5
from qtpy.QtCore import (QCoreApplication, Signal, QObject, QTimer,
                          QProcess)
from qtpy.QtXml import QDomDocument

import ray
from nsm_client_qt import NSMThread, NSMSignaler
import jacklib

def signalHandler(sig, frame):
    if sig in (signal.SIGINT, signal.SIGTERM):
        general_object.leave()


class SlOSCThread(NSMThread):
    def __init__(self, name, signaler, daemon_address, debug):
        NSMThread.__init__(self, name, signaler,
                                      daemon_address, debug)
        self.sl_is_ready = False
        self.number_of_loops = 0

    @make_method('/pongSL', 'ssi')
    def pong(self, path, args):
        self.sl_is_ready = True
        self.number_of_loops = args[2]

        if general_object.wait_for_load:
            general_object.sl_ready.emit()


class GeneralObject(QObject):
    sl_ready = Signal()

    def __init__(self, sl_port=None):
        QObject.__init__(self)

        self.sl_process = QProcess()
        self.sl_process.setProcessChannelMode(QProcess.ForwardedChannels)
        self.sl_process.finished.connect(self.slProcessFinished)

        if sl_port is not None:
            self.sl_port = sl_port
        else:
            self.sl_port = ray.get_free_osc_port(9951)

        self.sl_url = Address(self.sl_port)

        self.gui_process = QProcess()
        self.gui_process.setProcessChannelMode(QProcess.ForwardedChannels)
        self.gui_process.started.connect(self.guiProcessStarted)
        self.gui_process.finished.connect(self.guiProcessFinished)

        self.project_path = ''
        self.session_path = ''
        self.session_name = ''
        self.full_client_id = ''
        self.session_file = ''
        self.session_bak = ''
        self.midi_bindings_file = ''

        self.file_timer = QTimer()
        self.file_timer.setInterval(100)
        self.file_timer.timeout.connect(self.checkFile)
        self.n_file_timer = 0

        signaler.server_sends_open.connect(self.initialize)
        signaler.server_sends_save.connect(self.saveSlSession)
        signaler.show_optional_gui.connect(self.showOptionalGui)
        signaler.hide_optional_gui.connect(self.hideOptionalGui)

        self.sl_ready.connect(self.loadSession)

        self._switching = False
        self.leaving = False
        self.wait_for_load = False

        self.ping_timer = QTimer()
        self.ping_timer.setInterval(100)
        self.ping_timer.timeout.connect(self.pingSL)
        self.ping_timer.start()

        self.transport_timer = QTimer()
        self.transport_timer.setInterval(2)
        self.transport_timer.timeout.connect(self.checkTransport)

        self.transport_playing = False
        self.will_trig = False
        
        self.jack_follow_naming = False

    def JackShutdownCallback(self, arg=None):
        self.transport_timer.stop()
        return 0

    def checkTransport(self):
        pos = jacklib.jack_position_t()
        pos.valid = 0

        state = jacklib.transport_query(jack_client, jacklib.pointer(pos))

        if self.will_trig:
            if pos.beat == pos.beats_per_bar:
                if (pos.ticks_per_beat - pos.tick) <= 4:
                    # we are at 4 ticks or less from next bar (arbitrary)
                    # so we send a trig message to sooperlooper.
                    server.send(self.sl_url, '/sl/-1/hit', 'trigger')
                    self.will_trig = False
                    return

        if (self.transport_playing
                and state == jacklib.JackTransportStopped):
            if self.will_trig:
                self.will_trig = False
            else:
                server.send(self.sl_url, '/sl/-1/hit', 'pause_on')

            self.transport_playing = False

        elif (not self.transport_playing
              and state == jacklib.JackTransportRolling):
            if pos.beat == 1 and pos.tick == 0:
                server.send(self.sl_url, '/sl/-1/hit', 'trigger')

            else:
                self.will_trig = True

            self.transport_playing = True

    def pingSL(self):
        if server.sl_is_ready:
            self.ping_timer.stop()
        else:
            server.send(self.sl_url, '/ping', server.url, '/pongSL')

    def leave(self):
        self.leaving = True
        
        if QT5:
            if self.gui_process.state():
                self.gui_process.terminate()
            else:
                if self.sl_process.state():
                    server.send(self.sl_url, '/quit')
                else:
                    app.quit()
            return

        if self.gui_process.state() is QProcess.ProcessState.NotRunning:
            if self.sl_process.state() is QProcess.ProcessState.NotRunning:
                app.quit()
            else:
                server.send(self.sl_url, '/quit')
        else:
            self.gui_process.terminate()

    def isGuiShown(self):
        return bool(self.sl_process.state() == QProcess.ProcessState.Running)

    def slProcessFinished(self, exit_code):
        if not self._switching:
            app.quit()

    def guiProcessStarted(self):
        server.sendGuiState(True)

    def guiProcessFinished(self, exit_code):
        if self.leaving:
            if self.sl_process.state():
                server.send(self.sl_url, '/quit')
            else:
                app.quit()

        server.sendGuiState(False)

    def startFileChecker(self):
        self.n_file_timer = 0

        if os.path.exists(self.session_file):
            self.stopFileChecker()
            return

        self.file_timer.start()

    def stopFileChecker(self):
        self.n_file_timer = 0
        self.file_timer.stop()

        self.xmlCorrection()

        server.saveReply()

    def checkFile(self):
        if self.n_file_timer > 200: #more than 20 second
            self.stopFileChecker()
            return

        if os.path.exists(self.session_file):
            self.stopFileChecker()
            return

        self.n_file_timer += 1

    def xmlCorrection(self):
        try:
            sl_file = open(self.session_file)
            xml = QDomDocument()
            xml.setContent(sl_file.read())
            sl_file.close()
        except:
            return

        content = xml.documentElement()

        if content.tagName() != 'SLSession':
            return

        nodes = content.childNodes()

        for i in range(nodes.count()):
            node = nodes.at(i)

            if node.toElement().tagName() != 'Loopers':
                continue

            sub_nodes = node.childNodes()

            for j in range(sub_nodes.count()):
                sub_node = sub_nodes.at(j)
                element = sub_node.toElement()

                if element.tagName() != 'Looper':
                    continue

                audio_file_name = str(element.attribute('loop_audio'))

                if audio_file_name.startswith("%s/" % self.project_path):
                    element.setAttribute('loop_audio',
                                         os.path.relpath(audio_file_name))

        try:
            sl_file = open(self.session_file, 'w')
        except:
            return

        sl_file.write(xml.toString())
        sl_file.close()


    def initialize(self, project_path, session_name, full_client_id):
        self.project_path = project_path
        self.session_name = session_name
        self.session_file = "%s/session.slsess" % self.project_path
        self.session_bak = "%s/session.slsess.bak" % self.project_path
        self.midi_bindings_file = "%s/session.slb" % self.project_path
        #self.midi_bindings_bak = "%s/session.slb.bak" % self.project_path

        if not self.jack_follow_naming:
            full_client_id = 'sooperlooper'

        if full_client_id != self.full_client_id:
            self.full_client_id = full_client_id

            if self.gui_process.state():
                self.gui_process.terminate()
                self.gui_process.waitForFinished(500)
            else:
                server.sendGuiState(False)
            
            self._switching = True
            
            if self.sl_process.state():
                self.sl_process.terminate()
                self.sl_process.waitForFinished(500)
            
            self._switching = False
            
            self.sl_process.start(
                'sooperlooper',
                ['-p', str(self.sl_port), '-j', self.full_client_id])

        if not os.path.exists(self.project_path):
            os.makedirs(self.project_path)

        os.chdir(self.project_path)

        if server.sl_is_ready:
            self.loadSession()
            
        else:
            self.wait_for_load = True

        if jack_client:
            self.transport_timer.start()

    def loadSession(self):
        #self.sl_process.start('sooperlooper', ['-p', str(self.sl_port)])
        self.wait_for_load = False
        server.send(self.sl_url, '/load_session', self.session_file,
                    server.url, '/re-load')
        server.send(self.sl_url, '/load_midi_bindings',
                    self.midi_bindings_file, '')

        if jack_client is not None:
            server.send(self.sl_url, '/set', 'sync_source', -1.0)
            server.send(self.sl_url, '/set', 'eighth_per_cycle', 8.0)
            server.send(self.sl_url, '/sl/0/set,' 'quantize', 1.0)
        server.openReply()

    def saveSlSession(self):
        if os.path.exists(self.session_bak):
            os.remove(self.session_bak)

        if os.path.exists(self.session_file):
            os.rename(self.session_file, self.session_bak)

        server.send(self.sl_url, '/save_session', self.session_file,
                    server.url, '/re-save', 1)

        server.send(self.sl_url, '/save_midi_bindings',
                    self.midi_bindings_file, '')

        self.startFileChecker()

    def showOptionalGui(self):
        if QT5:
            if not self.gui_process.state():
                self.gui_process.start('slgui', ['-P', str(self.sl_port)])
        else:
            if self.gui_process.state() is QProcess.ProcessState.NotRunning:
                self.gui_process.start('slgui', ['-P', str(self.sl_port)]) 

    def hideOptionalGui(self):
        if QT5:
            if self.gui_process.state():
                self.gui_process.terminate()
        else:
            if (self.gui_process.state()
                    is not QProcess.ProcessState.NotRunning):
                self.gui_process.terminate()


if __name__ == '__main__':
    NSM_URL = os.getenv('NSM_URL')
    if not NSM_URL:
        sys.stderr.write('Could not register as NSM client.\n')
        sys.exit()

    daemon_address = ray.get_liblo_address(NSM_URL)

    signal.signal(signal.SIGINT, signalHandler)
    signal.signal(signal.SIGTERM, signalHandler)

    app = QCoreApplication(sys.argv)
    app.setApplicationName("SooperLooperNSM")
    app.setOrganizationName("SooperLooperNSM")

    timer = QTimer()
    timer.setInterval(200)
    timer.timeout.connect(lambda: None)
    timer.start()

    signaler = NSMSignaler()

    server = SlOSCThread('sooperlooper_nsm', signaler, daemon_address, False)

    if len(sys.argv) > 1 and '--transport_workaround' in sys.argv[1:]:
        jack_client = jacklib.client_open(
            "sooper_ray_wk",
            jacklib.JackNoStartServer | jacklib.JackSessionID,
            None)
    else:
        jack_client = None

    sl_port = None
    if len(sys.argv) > 1 and '--osc-port' in sys.argv[1:]:
        port_index = sys.argv.index('--osc-port')
        if len(sys.argv) > port_index + 1 and sys.argv[port_index + 1].isdigit():
            sl_port = int(sys.argv[port_index + 1])

    general_object = GeneralObject(sl_port=sl_port)
    if "--follow-jack-naming" in sys.argv[1:]:
        general_object.jack_follow_naming = True

    server.start()
    
    capabilities = ':optional-gui:switch:'
    server.announce('SooperLooper', capabilities, 'sooperlooper_nsm')

    app.exec()

    server.stop()

    del server
    del app
