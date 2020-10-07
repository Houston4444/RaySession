import functools
import math
import os
import random
import shutil
import string
import subprocess
import sys
from liblo import Address
from PyQt5.QtCore import QCoreApplication, QTimer, QProcess
from PyQt5.QtXml  import QDomDocument

import ray

from bookmarker        import BookMarker
from desktops_memory   import DesktopsMemory
from snapshoter        import Snapshoter
from multi_daemon_file import MultiDaemonFile
from signaler          import Signaler
from server_sender     import ServerSender
from file_copier       import FileCopier
from client            import Client
from scripter          import StepScripter
from daemon_tools import (TemplateRoots, RS, Terminal,
                          getGitDefaultUnAndIgnored)

_translate = QCoreApplication.translate
signaler = Signaler.instance()

def dirname(*args):
    return os.path.dirname(*args)

def basename(*args):
    return os.path.basename(*args)


class Session(ServerSender):
    def __init__(self, root):
        ServerSender.__init__(self)
        self.root = root
        self.is_dummy = False

        self.clients = []
        self.future_clients = []
        self.trashed_clients = []
        self.future_trashed_clients = []
        self.new_client_exec_args = []
        self.favorites = []
        self.name = ""
        self.path = ""
        self.future_session_path = ""
        self.future_session_name = ""
        self.notes = ""
        self.future_notes = ""
        self.load_locked = False

        self.is_renameable = True
        self.forbidden_ids_list = []

        self.file_copier = FileCopier(self)
        self.bookmarker = BookMarker()
        self.desktops_memory = DesktopsMemory(self)
        self.snapshoter = Snapshoter(self)
        self.step_scripter = StepScripter(self)

    #############
    def oscReply(self, *args):
        if not self.osc_src_addr:
            return

        self.send(self.osc_src_addr, *args)

    def setRenameable(self, renameable):
        if not renameable:
            if self.is_renameable:
                self.is_renameable = False
                if self.hasServer():
                    self.getServer().sendRenameable(False)
            return

        for client in self.clients:
            if client.isRunning():
                return

        self.is_renameable = True
        if self.hasServer():
            self.getServer().sendRenameable(True)

    def message(self, string, even_dummy=False):
        if self.is_dummy and not even_dummy:
            return

        Terminal.message(string)

    def setRoot(self, session_root):
        if self.path:
            raise NameError("impossible to change root. session %s is loaded"
                                % self.path)
            return

        self.root = session_root

        multi_daemon_file = MultiDaemonFile.getInstance()
        if multi_daemon_file:
            multi_daemon_file.update()

    def setName(self, session_name):
        self.name = session_name

    def setPath(self, session_path, session_name=''):
        if not self.is_dummy:
            if self.path:
                self.bookmarker.removeAll(self.path)

        self.path = session_path

        if session_name:
            self.setName(session_name)
        else:
            self.setName(session_path.rpartition('/')[2])

        if self.is_dummy:
            return

        multi_daemon_file = MultiDaemonFile.getInstance()
        if multi_daemon_file:
            multi_daemon_file.update()

        if self.path:
            server = self.getServer()
            if server and server.option_bookmark_session:
                self.bookmarker.setDaemonPort(server.port)
                self.bookmarker.makeAll(self.path)

    def noFuture(self):
        self.future_clients.clear()
        self.future_session_path = ''
        self.future_session_name = ''
        self.future_trashed_clients.clear()
        self.future_notes = ""

    def getShortPath(self):
        if self.path.startswith("%s/" % self.root):
            return self.path.replace("%s/" % self.root, '', 1)

        return self.name

    def getFullPath(self, session_name: str)->str:
        spath = "%s%s%s" % (self.root, os.sep, session_name)

        if session_name.startswith(os.sep):
            spath = session_name

        if spath.endswith(os.sep):
            spath = spath[:-1]

        return spath

    def getClient(self, client_id):
        for client in self.clients:
            if client.client_id == client_id:
                return client

        sys.stderr.write("client_id %s is not in ray-daemon session\n")

    def getClientByAddress(self, addr):
        if not addr:
            return None

        for client in self.clients:
            if client.addr and client.addr.url == addr.url:
                return client

    def newClient(self, executable, client_id=None):
        client = Client(self)
        client.executable_path = executable
        client.name = basename(executable)
        client.client_id = client_id
        if not client_id:
            client.client_id = self.generateClientId(executable)

        self.clients.append(client)
        return client

    def trashClient(self, client):
        if not client in self.clients:
            raise NameError("No client to trash: %s" % client.client_id)
            return

        client.setStatus(ray.ClientStatus.REMOVED)

        ## Theses lines are commented because finally choice is to
        ## always send client to trash
        ## comment self.trashed_client.append(client) if choice is reversed !!!
        #if client.isRayHack():
            #client_dir = client.getProjectPath()
            #if os.path.isdir(client_dir):
                #if os.listdir(client_dir):
                    #self.trashed_clients.append(client)
                    #client.sendGuiClientProperties(removed=True)
                #else:
                    #try:
                        #os.removedirs(client_dir)
                    #except:
                        #self.trashed_clients.append(client)
                        #client.sendGuiClientProperties(removed=True)

        #elif client.getProjectFiles() or client.net_daemon_url:
            #self.trashed_clients.append(client)
            #client.sendGuiClientProperties(removed=True)

        self.trashed_clients.append(client)
        client.sendGuiClientProperties(removed=True)
        self.clients.remove(client)

    def removeClient(self, client):
        client.terminateScripts()
        client.terminate()

        if not client in self.clients:
            raise NameError("No client to remove: %s" % client.client_id)
            return

        client.setStatus(ray.ClientStatus.REMOVED)

        self.clients.remove(client)

    def restoreClient(self, client)->bool:
        client.sent_to_gui = False

        if not self.addClient(client):
            return False

        self.sendGui('/ray/gui/trash/remove', client.client_id)
        self.trashed_clients.remove(client)
        return True

    def tellAllClientsSessionIsLoaded(self):
        self.message("Telling all clients that session is loaded...")
        for client in self.clients:
            client.tellClientSessionIsLoaded()

    def clientsHaveErrors(self):
        for client in self.clients:
            if client.active and client.hasError():
                return True
        return False

    def updateForbiddenIdsList(self):
        if not self.path:
            return

        self.forbidden_ids_list.clear()

        for file in os.listdir(self.path):
            if os.path.isdir("%s/%s" % (self.path, file)) and '.' in file:
                client_id = file.rpartition('.')[2]
                if not client_id in self.forbidden_ids_list:
                    self.forbidden_ids_list.append(client_id)

            elif os.path.isfile("%s/%s" % (self.path, file)) and '.' in file:
                for string in file.split('.')[1:]:
                    if not string in self.forbidden_ids_list:
                        self.forbidden_ids_list.append(string)

        for client in self.clients + self.trashed_clients:
            if not client.client_id in self.forbidden_ids_list:
                self.forbidden_ids_list.append(client.client_id)

    def getSearchTemplateDirs(self, factory)->list:
        if factory:
            # search templates in /etc/xdg (RaySession installed)
            templates_root = TemplateRoots.factory_clients_xdg

            # search templates in source code
            if not os.path.isdir(templates_root):
                templates_root = TemplateRoots.factory_clients

            if (os.path.isdir(templates_root)
                    and os.access(templates_root, os.R_OK)):
                return ["%s/%s" % (templates_root, f)
                        for f in sorted(os.listdir(templates_root))]

            return []

        return [TemplateRoots.user_clients]

    def generateClientIdAsNsm(self):
        client_id = 'n'
        for i in range(4):
            client_id += random.choice(string.ascii_uppercase)

        return client_id

    def generateClientId(self, wanted_id=""):
        self.updateForbiddenIdsList()
        wanted_id = basename(wanted_id)

        if wanted_id:
            for to_rm in ('ray-', 'non-', 'carla-'):
                if wanted_id.startswith(to_rm):
                    wanted_id = wanted_id.replace(to_rm, '', 1)
                    break

            wanted_id = wanted_id.replace('jack', '')

            #reduce string if contains '-'
            if '-' in wanted_id:
                new_wanted_id = ''
                seplist = wanted_id.split('-')
                for sep in seplist[:-1]:
                    if len(sep) > 0:
                        new_wanted_id += (sep[0] + '_')
                new_wanted_id += seplist[-1]
                wanted_id = new_wanted_id


            #prevent non alpha numeric characters
            new_wanted_id = ''
            last_is_ = False
            for char in wanted_id:
                if char.isalnum():
                    new_wanted_id += char
                else:
                    if not last_is_:
                        new_wanted_id += '_'
                        last_is_ = True

            wanted_id = new_wanted_id

            while wanted_id and wanted_id.startswith('_'):
                wanted_id = wanted_id[1:]

            while wanted_id and wanted_id.endswith('_'):
                wanted_id = wanted_id[:-1]

            if not wanted_id:
                wanted_id = self.generateClientIdAsNsm()
                while wanted_id in self.forbidden_ids_list:
                    wanted_id = self.generateClientIdAsNsm()

            #limit string to 10 characters
            if len(wanted_id) >= 11:
                wanted_id = wanted_id[:10]

            if not wanted_id in self.forbidden_ids_list:
                self.forbidden_ids_list.append(wanted_id)
                return wanted_id

            n = 2
            while "%s_%i" % (wanted_id, n) in self.forbidden_ids_list:
                n += 1

            self.forbidden_ids_list.append(wanted_id)
            return "%s_%i" % (wanted_id, n)

        client_id = 'n'
        for l in range(4):
            client_id += random.choice(string.ascii_uppercase)

        while client_id in self.forbidden_ids_list:
            client_id = 'n'
            for l in range(4):
                client_id += random.choice(string.ascii_uppercase)

        self.forbidden_ids_list.append(client_id)
        return client_id

    def getListOfExistingClientIds(self):
        if not self.path:
            return []

        client_ids_list = []

        for file in os.listdir(self.path):
            if os.path.isdir(file) and file.contains('.'):
                client_ids_list.append(file.rpartition('.')[2])
            elif os.path.isfile(file) and file.contains('.'):
                file_without_extension = file.rpartition('.')[0]

    def addClient(self, client)->bool:
        if self.load_locked or not self.path:
            return False

        if client.isRayHack():
            project_path = client.getProjectPath()
            if not os.path.isdir(project_path):
                try:
                    os.makedirs(project_path)
                except:
                    return False

        client.updateInfosFromDesktopFile()
        self.clients.append(client)
        client.sendGuiClientProperties()

        return True

    def reOrderClients(self, client_ids_list, src_addr=None, src_path=''):
        client_newlist = []

        for client_id in client_ids_list:
            for client in self.clients:
                if client.client_id == client_id:
                    client_newlist.append(client)
                    break

        if len(client_ids_list) != len(self.clients):
            if src_addr:
                self.send(src_addr, '/error', src_path, ray.Err.GENERAL_ERROR,
                          "%s clients are missing or incorrect" \
                            % (len(self.clients) - len(client_ids_list)))
            return

        self.clients.clear()
        for client in client_newlist:
            self.clients.append(client)

        if src_addr:
            self.answer(src_addr, src_path, "clients reordered")

    def isPathInASessionDir(self, spath):
        if self.isNsmLocked() and os.getenv('NSM_URL'):
            return False

        base_path = spath
        while not base_path in ('/', ''):
            base_path = os.path.dirname(base_path)
            if os.path.isfile("%s/raysession.xml" % base_path):
                return True

        return False

    def rewriteUserTemplatesFile(self, content, templates_file)->bool:
        if not os.access(templates_file, os.W_OK):
            return False

        file_version = content.attribute('VERSION')

        if ray.versionToTuple(file_version) >= ray.versionToTuple(ray.VERSION):
            return False

        content.setAttribute('VERSION', ray.VERSION)
        if ray.versionToTuple(file_version) >= (0, 8, 0):
            return True

        nodes = content.childNodes()

        for i in range(nodes.count()):
            node = nodes.at(i)
            ct = node.toElement()
            tag_name = ct.tagName()
            if tag_name != 'Client-Template':
                continue

            executable = ct.attribute('executable')
            if not executable:
                continue

            ign_list, unign_list = getGitDefaultUnAndIgnored(executable)
            if ign_list:
                ct.setAttribute('ignored_extensions', " ".join(ign_list))
            if unign_list:
                ct.setAttribute('unignored_extensions', " ".join(unign_list))

        return True


class OperatingSession(Session):
    def __init__(self, root):
        Session.__init__(self, root)
        self.wait_for = ray.WaitFor.NONE

        self.timer = QTimer()
        self.timer_redondant = False
        self.expected_clients = []

        self.timer_launch = QTimer()
        self.timer_launch.setInterval(100)
        self.timer_launch.timeout.connect(self.timerLaunchTimeOut)
        self.clients_to_launch = []

        self.timer_quit = QTimer()
        self.timer_quit.setInterval(100)
        self.timer_quit.timeout.connect(self.timerQuitTimeOut)
        self.clients_to_quit = []

        self.timer_waituser_progress = QTimer()
        self.timer_waituser_progress.setInterval(500)
        self.timer_waituser_progress.timeout.connect(
            self.timerWaituserProgressTimeOut)
        self.timer_wu_progress_n = 0

        self.osc_src_addr = None
        self.osc_path = ''
        self.osc_args = []

        self.steps_order = []

        self.terminated_yet = False

        # externals are clients not launched from the daemon
        # but with NSM_URL=...
        self.externals_timer = QTimer()
        self.externals_timer.setInterval(100)
        self.externals_timer.timeout.connect(self.checkExternalsStates)

        self.window_waiter = QTimer()
        self.window_waiter.setInterval(200)
        self.window_waiter.timeout.connect(self.checkWindowsAppears)
        #self.window_waiter_clients = []

        self.run_step_addr = None

        self.switching_session = False

    def rememberOscArgs(self, path, args, src_addr):
        self.osc_src_addr = src_addr
        self.osc_path = path
        self.osc_args = args

    def forgetOscArgs(self):
        self.osc_src_addr = None
        self.osc_path = ''
        self.osc_args.clear()

    def waitAndGoTo(self, duration, follow, wait_for, redondant=False):
        self.timer.stop()

        # we need to delete timer to change the timeout connect
        del self.timer
        self.timer = QTimer()

        if type(follow) in (list, tuple):
            if len(follow) == 0:
                return
            elif len(follow) == 1:
                follow = follow[0]
            else:
                follow = functools.partial(follow[0], *follow[1:])

        if wait_for == ray.WaitFor.SCRIPT_QUIT:
            if self.step_scripter.isRunning():
                self.wait_for = wait_for
                self.timer.setSingleShot(True)
                self.timer.timeout.connect(follow)
                self.timer.start(duration)
            else:
                follow()
            return

        if self.expected_clients:
            n_expected = len(self.expected_clients)

            if wait_for == ray.WaitFor.ANNOUNCE:
                if n_expected == 1:
                    message = _translate('GUIMSG',
                        'waiting announce from %s...'
                            % self.expected_clients[0].guiMsgStyle())
                else:
                    message = _translate('GUIMSG',
                        'waiting announce from %i clients...' % n_expected)
                self.sendGuiMessage(message)
            elif wait_for == ray.WaitFor.QUIT:
                if n_expected == 1:
                    message = _translate('GUIMSG',
                        'waiting for %s to stop...'
                            % self.expected_clients[0].guiMsgStyle())
                else:
                    message = _translate('GUIMSG',
                        'waiting for %i clients to stop...' % n_expected)

            self.timer_redondant = redondant

            self.wait_for = wait_for
            self.timer.setSingleShot(True)
            self.timer.timeout.connect(follow)
            self.timer.start(duration)
        else:
            follow()

    def endTimerIfLastExpected(self, client):
        if self.wait_for == ray.WaitFor.QUIT and client in self.clients:
            self.removeClient(client)

        if client in self.expected_clients:
            self.expected_clients.remove(client)

            if self.timer_redondant:
                self.timer.start()
                if self.timer_waituser_progress.isActive():
                    self.timer_wu_progress_n = 0
                    self.timer_waituser_progress.start()

        if not self.expected_clients:
            self.timer.setSingleShot(True)
            self.timer.stop()
            self.timer.start(0)

            self.timer_waituser_progress.stop()

    def endTimerIfScriptFinished(self):
        if (self.wait_for == ray.WaitFor.SCRIPT_QUIT
                and not self.step_scripter.isRunning()):
            self.timer.setSingleShot(True)
            self.timer.stop()
            self.timer.start(0)

    def cleanExpected(self):
        if self.expected_clients:
            client_names = []

            for client in self.expected_clients:
                client_names.append(client.guiMsgStyle())

            if self.wait_for == ray.WaitFor.ANNOUNCE:
                self.sendGuiMessage(
                    _translate('GUIMSG', "%s didn't announce.")
                        % ', '.join(client_names))

            elif self.wait_for == ray.WaitFor.QUIT:
                self.sendGuiMessage(_translate('GUIMSG', "%s still alive !")
                                    % ', '.join(client_names))

            self.expected_clients.clear()

        self.wait_for = ray.WaitFor.NONE

    def nextFunction(self, from_run_step=False, run_step_args=[]):
        if self.run_step_addr and not from_run_step:
            self.answer(self.run_step_addr, '/ray/session/run_step',
                         'step done')
            self.run_step_addr = None
            return

        if len(self.steps_order) == 0:
            return

        next_item = self.steps_order[0]
        next_function = next_item
        arguments = []

        if isinstance(next_item, (tuple, list)):
            if not next_item:
                return

            next_function = next_item[0]
            if len(next_item) > 1:
                arguments = next_item[1:]

        server = self.getServer()
        if (server and server.option_session_scripts
                and not self.step_scripter.isRunning()
                and self.path and not from_run_step):
            for step_string in ('load', 'save', 'close'):
                if next_function == self.__getattribute__(step_string):
                    if (step_string == 'load'
                            and arguments
                            and arguments[0] == True):
                        # prevent use of load session script
                        # with open_session_off
                        break

                    if self.step_scripter.start(step_string, arguments,
                                    self.osc_src_addr, self.osc_path):
                        self.setServerStatus(ray.ServerStatus.SCRIPT)
                        return
                    break

        if (from_run_step and next_function
                and self.step_scripter.isRunning()):
            if (next_function
                    == self.__getattribute__(
                                self.step_scripter.getStep())):
                self.step_scripter.setStepperHasCall(True)

            if next_function == self.load:
                if 'open_off' in run_step_args:
                    arguments = [True]
            elif next_function == self.close:
                if 'close_all' in run_step_args:
                    arguments = [True]

        self.steps_order.__delitem__(0)
        next_function(*arguments)

    def timerLaunchTimeOut(self):
        if self.clients_to_launch:
            self.clients_to_launch[0].start()
            self.clients_to_launch.__delitem__(0)

        if not self.clients_to_launch:
            self.timer_launch.stop()

    def timerQuitTimeOut(self):
        if self.clients_to_quit:
            client = self.clients_to_quit.pop(0)
            client.stop()

        if not self.clients_to_quit:
            self.timer_quit.stop()

    def timerWaituserProgressTimeOut(self):
        if not self.expected_clients:
            self.timer_waituser_progress.stop()

        self.timer_wu_progress_n += 1

        ratio = float(self.timer_wu_progress_n / 240)
        self.sendGui('/ray/gui/server/progress', ratio)

    def checkExternalsStates(self):
        has_externals = False

        for client in self.clients:
            if client.is_external:
                has_externals = True
                if not os.path.exists('/proc/%i' % client.pid):
                    # Quite dirty, but works.
                    client.processFinished(0, 0)

        if not has_externals:
            self.externals_timer.stop()

    def checkWindowsAppears(self):
        for client in self.clients:
            if client.isRunning() and client.ray_hack_waiting_win:
                break
        else:
            self.window_waiter.stop()
            return

        server = self.getServer()
        if server and server.option_has_wmctrl:
            self.desktops_memory.setActiveWindowList()
            for client in self.clients:
                if client.ray_hack_waiting_win:
                    if self.desktops_memory.hasWindow(client.pid):
                        client.ray_hack_waiting_win = False
                        client.rayHackReady()

    def sendReply(self, *messages):
        if not (self.osc_src_addr and self.osc_path):
            return

        self.sendEvenDummy(self.osc_src_addr, '/reply',
                           self.osc_path, *messages)

    def sendError(self, err, error_message):
        #clear process order to allow other new operations
        self.steps_order.clear()

        if self.run_step_addr:
            self.answer(self.run_step_addr, '/ray/session/run_step',
                         error_message, err)

        if not (self.osc_src_addr and self.osc_path):
            return

        self.sendEvenDummy(self.osc_src_addr, "/error",
                           self.osc_path, err, error_message)

    def sendMinorError(self, err, error_message):
        if not (self.osc_src_addr and self.osc_path):
            return

        self.sendEvenDummy(self.osc_src_addr, "/minor_error",
                           self.osc_path, err, error_message)

    def stepScripterFinished(self):
        if self.wait_for == ray.WaitFor.SCRIPT_QUIT:
            self.timer.setSingleShot(True)
            self.timer.stop()
            self.timer.start(0)
            return

        if not self.step_scripter.stepperHasCalled():
            # script has not call
            # the next_function (save, close, load)
            if self.step_scripter.getStep() in ('load', 'close'):
                self.steps_order.clear()
                self.steps_order = [(self.close, True),
                                    self.abortDone]

                # Fake the nextFunction to come from run_step message
                # This way, we are sure the close step
                # is not runned with a script.
                self.nextFunction(True)
                return

            if self.steps_order:
                self.steps_order.__delitem__(0)

        self.nextFunction()

    def adjustFilesAfterCopy(self, new_session_full_name, template_mode):
        new_session_name = basename(new_session_full_name)

        spath = "%s/%s" % (self.root, new_session_full_name)
        if new_session_full_name.startswith('/'):
            spath = new_session_full_name

        # create tmp clients from raysession.xml to adjust Files after copy
        session_file = "%s/%s" % (spath, "raysession.xml")

        try:
            ray_file = open(session_file, 'r')
        except:
            self.sendError(ray.Err.BAD_PROJECT,
                           _translate("error", "impossible to read %s")
                           % session_file)
            return

        tmp_clients = []

        xml = QDomDocument()
        xml.setContent(ray_file.read())

        content = xml.documentElement()

        if content.tagName() != "RAYSESSION":
            ray_file.close()
            self.loadError(ray.Err.BAD_PROJECT)
            return

        content.setAttribute('name', new_session_name)

        nodes = content.childNodes()

        for i in range(nodes.count()):
            node = nodes.at(i)
            tag_name = node.toElement().tagName()
            if tag_name in ('Clients', 'RemovedClients'):
                clients_xml = node.toElement().childNodes()

                for j in range(clients_xml.count()):
                    client_xml = clients_xml.at(j)
                    client = Client(self)
                    cx = client_xml.toElement()
                    client.readXmlProperties(cx)

                    tmp_clients.append(client)

        ray_file.close()

        ray_file_w = open(session_file, 'w')
        ray_file_w.write(xml.toString())
        ray_file_w.close()


        for client in tmp_clients:
            client.adjustFilesAfterCopy(new_session_full_name, template_mode)


    ############################## COMPLEX OPERATIONS ###################
    # All functions are splitted when we need to wait clients
    # for something (announce, reply, quit).
    # For example, at the end of save(), timer is launched,
    # then, when timer is timeout or when all client replied,
    # save_substep1 is launched.

    def save(self, outing=False):
        if not self.path:
            self.nextFunction()
            return

        if outing:
            self.setServerStatus(ray.ServerStatus.OUT_SAVE)
        else:
            self.setServerStatus(ray.ServerStatus.SAVE)

        self.sendGuiMessage(_translate('GUIMSG', '-- Saving session %s --')
                                % ray.highlightText(self.getShortPath()))

        for client in self.clients:
            if client.canSaveNow():
                self.expected_clients.append(client)
            client.save()

        if self.expected_clients:
            if len(self.expected_clients) == 1:
                self.sendGuiMessage(
                    _translate('GUIMSG', 'waiting for %s to save...')
                        % self.expected_clients[0].guiMsgStyle())
            else:
                self.sendGuiMessage(
                    _translate('GUIMSG', 'waiting for %i clients to save...')
                        % len(self.expected_clients))

        self.waitAndGoTo(10000, (self.save_substep1, outing), ray.WaitFor.REPLY)

    def save_substep1(self, outing=False):
        self.cleanExpected()

        if outing:
            for client in self.clients:
                if client.hasError():
                    self.sendError(ray.Err.GENERAL_ERROR,
                                  "Some clients could not save")
                    break

        if not self.path:
            self.nextFunction()
            return

        session_file = self.path + '/raysession.xml'
        if self.isNsmLocked() and os.getenv('NSM_URL'):
            session_file = self.path + '/raysubsession.xml'

        if (os.path.isfile(session_file)
                and not os.access(session_file, os.W_OK)):
            self.saveError(ray.Err.CREATE_FAILED)
            return

        try:
            file = open(session_file, 'w')
        except:
            self.saveError(ray.Err.CREATE_FAILED)
            return

        xml = QDomDocument()
        p = xml.createElement('RAYSESSION')
        p.setAttribute('VERSION', ray.VERSION)
        p.setAttribute('name', self.name)

        xml_cls = xml.createElement('Clients')
        xml_rmcls = xml.createElement('RemovedClients')
        xml_wins = xml.createElement('Windows')
        for client in self.clients:
            cl = xml.createElement('client')
            cl.setAttribute('id', client.client_id)

            launched = int(bool(client.isRunning() or
                                (client.auto_start
                                 and not client.has_been_started)))

            cl.setAttribute('launched', launched)

            client.writeXmlProperties(cl)

            xml_cls.appendChild(cl)

        for client in self.trashed_clients:
            cl = xml.createElement('client')
            cl.setAttribute('id', client.client_id)

            client.writeXmlProperties(cl)

            xml_rmcls.appendChild(cl)

        if self.hasServer() and self.getServer().option_desktops_memory:
            self.desktops_memory.save()

        for win in self.desktops_memory.saved_windows:
            xml_win = xml.createElement('window')
            xml_win.setAttribute('class', win.wclass)
            xml_win.setAttribute('name', win.name)
            xml_win.setAttribute('desktop', win.desktop)
            xml_wins.appendChild(xml_win)

        p.appendChild(xml_cls)
        p.appendChild(xml_rmcls)
        p.appendChild(xml_wins)

        xml.appendChild(p)

        contents = ("<?xml version='1.0' encoding='UTF-8'?>\n"
                    "<!DOCTYPE RAYSESSION>\n")

        contents += xml.toString()

        try:
            file.write(contents)
        except:
            file.close()
            self.saveError(ray.Err.CREATE_FAILED)

        file.close()

        full_notes_path = "%s/%s" % (self.path, ray.NOTES_PATH)

        if self.notes:
            try:
                notes_file = open(full_notes_path, 'w')
                notes_file.write(self.notes)
                notes_file.close()
            except:
                Terminal.message("unable to save notes in %s"
                                 % full_notes_path)
        elif os.path.isfile(full_notes_path):
            try:
                os.remove(full_notes_path)
            except:
                Terminal.message("unable to remove %s" % full_notes_path)

        self.sendGuiMessage(_translate('GUIMSG', "Session '%s' saved.")
                                % self.getShortPath())
        self.message("Session %s saved." % self.getShortPath())

        self.nextFunction()

    def saveDone(self):
        self.message("Done.")
        self.sendReply("Saved.")
        self.setServerStatus(ray.ServerStatus.READY)

    def saveError(self, err_saving):
        self.message("Failed")
        m = _translate('Load Error', "Unknown error")

        if err_saving == ray.Err.CREATE_FAILED:
            m = _translate(
                'GUIMSG', "Can't save session, session file is unwriteable !")

        self.message(m)
        self.sendGuiMessage(m)
        self.sendError(ray.Err.CREATE_FAILED, m)

        self.setServerStatus(ray.ServerStatus.READY)
        self.steps_order.clear()
        self.forgetOscArgs()

    def snapshot(self, snapshot_name='', rewind_snapshot='',
                 force=False, outing=False):
        if not force:
            server = self.getServer()
            if not (server and server.option_snapshots
                    and not self.snapshoter.isAutoSnapshotPrevented()
                    and self.snapshoter.hasChanges()):
                self.nextFunction()
                return

        if outing:
            self.setServerStatus(ray.ServerStatus.OUT_SNAPSHOT)
        else:
            self.setServerStatus(ray.ServerStatus.SNAPSHOT)

        self.sendGuiMessage(_translate('GUIMSG', "snapshot started..."))
        self.snapshoter.save(snapshot_name, rewind_snapshot,
                             self.snapshot_substep1, self.snapshotError)

    def snapshot_substep1(self, aborted=False):
        if aborted:
            self.message('Snapshot aborted')
            self.sendGuiMessage(_translate('GUIMSG', 'Snapshot aborted!'))

        self.sendGuiMessage(_translate('GUIMSG', '...snapshot finished.'))
        self.nextFunction()

    def snapshotDone(self):
        self.setServerStatus(ray.ServerStatus.READY)
        self.sendReply("Snapshot taken.")

    def snapshotError(self, err_snapshot, info_str=''):
        m = _translate('Snapshot Error', "Unknown error")
        if err_snapshot == ray.Err.SUBPROCESS_UNTERMINATED:
            m = _translate('Snapshot Error',
                           "git didn't stop normally.\n%s") % info_str
        elif err_snapshot == ray.Err.SUBPROCESS_CRASH:
            m = _translate('Snapshot Error',
                           "git crashes.\n%s") % info_str
        elif err_snapshot == ray.Err.SUBPROCESS_EXITCODE:
            m = _translate('Snapshot Error',
                           "git exit with an error code.\n%s") % info_str
        self.message(m)
        self.sendGuiMessage(m)

        # quite dirty
        # minor error is not a fatal error
        # it's important for ray_control to not stop
        # if operation is not snapshot (ex: close or save)
        if self.nextFunction.__name__ == 'snapshotDone':
            self.sendError(err_snapshot, m)
            self.forgetOscArgs()
            return

        self.sendMinorError(err_snapshot, m)
        self.nextFunction()

    def closeNoSaveClients(self):
        self.cleanExpected()

        server = self.getServer()
        if server and server.option_has_wmctrl:
            has_nosave_clients = False
            for client in self.clients:
                if client.isRunning() and client.noSaveLevel() == 2:
                    has_nosave_clients = True
                    break

            if has_nosave_clients:
                self.desktops_memory.setActiveWindowList()
                for client in self.clients:
                    if client.isRunning() and client.noSaveLevel() == 2:
                        self.expected_clients.append(client)
                        self.desktops_memory.findAndClose(client.pid)

        if self.expected_clients:
            self.sendGuiMessage(
              _translate('GUIMSG',
                'waiting for no saveable clients to be closed gracefully...'))

        duration = int(1000 * math.sqrt(len(self.expected_clients)))
        self.waitAndGoTo(duration, self.closeNoSaveClients_substep1,
                         ray.WaitFor.QUIT)

    def closeNoSaveClients_substep1(self):
        self.cleanExpected()
        has_nosave_clients = False

        for client in self.clients:
            if (client.isRunning() and client.noSaveLevel()):
                self.expected_clients.append(client)
                has_nosave_clients = True

        if has_nosave_clients:
            self.setServerStatus(ray.ServerStatus.WAIT_USER)
            self.timer_wu_progress_n = 0
            self.timer_waituser_progress.start()
            self.sendGuiMessage(_translate('GUIMSG',
                'waiting you to close yourself unsaveable clients...'))

        # Timer (2mn) is restarted if an expected client has been closed
        self.waitAndGoTo(120000, self.nextFunction, ray.WaitFor.QUIT, True)

    def close(self, clear_all_clients=False):
        self.expected_clients.clear()

        if not self.path:
            self.nextFunction()
            return

        byebye_client_list = []
        future_clients_exec_args = []

        if not clear_all_clients:
            for future_client in self.future_clients:
                if future_client.auto_start:
                    future_clients_exec_args.append(
                     (future_client.executable_path, future_client.arguments))

        has_keep_alive = False

        for client in self.clients:
            if (not clear_all_clients
                and (client.active and client.isCapableOf(':switch:')
                     or (client.isDumbClient() and client.isRunning()))
                and ((client.running_executable, client.running_arguments)
                     in future_clients_exec_args)):
                # client will switch
                # or keep alive if non active and running
                has_keep_alive = True
                client.switch_state = ray.SwitchState.RESERVED
                future_clients_exec_args.remove(
                    (client.running_executable, client.running_arguments))
            else:
                # client is not capable of switch, or is not wanted
                # in the new session
                if client.isRunning():
                    self.expected_clients.append(client)
                else:
                    byebye_client_list.append(client)

        if has_keep_alive:
            self.setServerStatus(ray.ServerStatus.CLEAR)
        else:
            self.setServerStatus(ray.ServerStatus.CLOSE)

        for client in byebye_client_list:
            if client in self.clients:
                self.removeClient(client)
            else:
                raise NameError('no client %s to remove' % client.client_id)

        if self.expected_clients:
            if len(self.expected_clients) == 1:
                self.sendGuiMessage(
                    _translate('GUIMSG',
                            'waiting for %s to quit...')
                        % self.expected_clients[0].guiMsgStyle())
            else:
                self.sendGuiMessage(
                    _translate('GUIMSG',
                            'waiting for %i clients to quit...')
                        % len(self.expected_clients))

            for client in self.expected_clients.__reversed__():
                self.clients_to_quit.append(client)
            self.timer_quit.start()

        self.trashed_clients.clear()
        self.sendGui('/ray/gui/trash/clear')

        self.waitAndGoTo(30000, (self.close_substep1, clear_all_clients),
                         ray.WaitFor.QUIT)

    def close_substep1(self, clear_all_clients=False):
        for client in self.expected_clients:
            client.kill()

        self.waitAndGoTo(1000, (self.close_substep2, clear_all_clients),
                         ray.WaitFor.QUIT)

    def close_substep2(self, clear_all_clients=False):
        self.cleanExpected()
        if clear_all_clients:
            self.setPath('')
        self.nextFunction()

    def closeDone(self):
        self.cleanExpected()
        self.clients.clear()
        self.setPath('')
        self.sendGui("/ray/gui/session/name", "", "")
        self.noFuture()
        self.sendReply("Closed.")
        self.message("Done")
        self.setServerStatus(ray.ServerStatus.OFF)
        self.forgetOscArgs()

    def abortDone(self):
        self.cleanExpected()
        self.clients.clear()
        self.setPath('')
        self.sendGui("/ray/gui/session/name", "", "")
        self.noFuture()
        self.sendReply("Aborted.")
        self.message("Done")
        self.setServerStatus(ray.ServerStatus.OFF)
        self.forgetOscArgs()

    def new(self, new_session_name):
        self.sendGuiMessage(
            _translate('GUIMSG', "Creating new session \"%s\"")
            % new_session_name)
        spath = self.getFullPath(new_session_name)

        if self.isPathInASessionDir(spath):
            self.sendError(ray.Err.SESSION_IN_SESSION_DIR,
                           """Can't create session in a dir containing a session
for better organization.""")
            return

        try:
            os.makedirs(spath)
        except:
            self.sendError(ray.Err.CREATE_FAILED,
                           "Could not create the session directory")
            return

        self.setServerStatus(ray.ServerStatus.NEW)
        self.setPath(spath)
        self.sendGui("/ray/gui/session/name",
                     self.name, self.path)
        self.nextFunction()

    def newDone(self):
        self.sendGuiMessage(_translate('GUIMSG', 'Session is ready'))
        self.sendReply("Created.")
        self.setServerStatus(ray.ServerStatus.READY)
        self.forgetOscArgs()

    def initSnapshot(self, spath, snapshot):
        self.setServerStatus(ray.ServerStatus.REWIND)
        if self.snapshoter.load(spath, snapshot, self.initSnapshotError):
            self.nextFunction()

    def initSnapshotError(self, err, info_str=''):
        m = _translate('Snapshot Error', "Snapshot error")
        if err == ray.Err.SUBPROCESS_UNTERMINATED:
            m = _translate('Snapshot Error',
                           "command didn't stop normally:\n%s") % info_str
        elif err == ray.Err.SUBPROCESS_CRASH:
            m = _translate('Snapshot Error',
                           "command crashes:\n%s") % info_str
        elif err == ray.Err.SUBPROCESS_EXITCODE:
            m = _translate('Snapshot Error',
                           "command exit with an error code:\n%s") % info_str
        elif err == ray.Err.NO_SUCH_FILE:
            m = _translate('Snapshot Error',
                           "error reading file:\n%s") % info_str
        self.message(m)
        self.sendGuiMessage(m)
        self.sendError(err, m)

        self.setServerStatus(ray.ServerStatus.OFF)
        self.steps_order.clear()

    def duplicate(self, new_session_full_name):
        if self.clientsHaveErrors():
            self.sendError(ray.Err.GENERAL_ERROR,
                           _translate('error', "Some clients could not save"))
            return

        self.sendGui('/ray/gui/trash/clear')
        self.sendGuiMessage(
            _translate('GUIMSG', '-- Duplicating session %s to %s --')
                % (ray.highlightText(self.getShortPath()),
                   ray.highlightText(new_session_full_name)))

        for client in self.clients:
            if client.protocol == ray.Protocol.RAY_NET:
                client.ray_net.duplicate_state = -1
                if (client.ray_net.daemon_url
                        and ray.isValidOscUrl(client.ray_net.daemon_url)):
                    self.send(Address(client.ray_net.daemon_url),
                              '/ray/session/duplicate_only',
                              self.getShortPath(),
                              new_session_full_name,
                              client.ray_net.session_root)
            #client.net_duplicate_state = -1

            #if (client.net_daemon_url
                    #and ray.isValidOscUrl(client.net_daemon_url)):
                #self.send(Address(client.net_daemon_url),
                          #'/ray/session/duplicate_only',
                          #self.getShortPath(),
                          #new_session_full_name,
                          #client.net_session_root)

                self.expected_clients.append(client)

        if self.expected_clients:
            self.sendGuiMessage(
                _translate('GUIMSG',
                    'waiting for network daemons to start duplicate...'))

        self.waitAndGoTo(2000,
                         (self.duplicate_substep1, new_session_full_name),
                         ray.WaitFor.DUPLICATE_START)

    def duplicate_substep1(self, new_session_full_name):
        spath = "%s/%s" % (self.root, new_session_full_name)
        self.setServerStatus(ray.ServerStatus.COPY)

        self.sendGuiMessage(_translate('GUIMSG', 'start session copy...'))

        self.file_copier.startSessionCopy(self.path,
                                          spath,
                                          self.duplicate_substep2,
                                          self.duplicateAborted,
                                          [new_session_full_name])

    def duplicate_substep2(self, new_session_full_name):
        self.cleanExpected()

        self.sendGuiMessage(_translate('GUIMSG', '...session copy finished.'))
        for client in self.clients:
            if (client.protocol == ray.Protocol.RAY_NET
                    and 0 <= client.ray_net.duplicate_state < 1):
                self.expected_clients.append(client)

        if self.expected_clients:
            self.sendGuiMessage(
                _translate('GUIMSG',
                    'waiting for network daemons to finish duplicate'))

        self.waitAndGoTo(3600000,  #1Hour
                         (self.duplicate_substep3, new_session_full_name),
                         ray.WaitFor.DUPLICATE_FINISH)

    def duplicate_substep3(self, new_session_full_name):
        self.adjustFilesAfterCopy(new_session_full_name, ray.Template.NONE)
        self.nextFunction()

    def duplicateAborted(self, new_session_full_name):
        self.steps_order.clear()

        self.sendError(ray.Err.NO_SUCH_FILE, "No such file.")
        self.send(self.osc_src_addr, '/ray/net_daemon/duplicate_state', 1)

        self.setServerStatus(ray.ServerStatus.READY)
        self.forgetOscArgs()

    def saveSessionTemplate(self, template_name, net=False):
        template_root = TemplateRoots.user_sessions

        if net:
            template_root = "%s/%s" \
                            % (self.root, TemplateRoots.net_session_name)

        spath = "%s/%s" % (template_root, template_name)

        #overwrite existing template
        if os.path.isdir(spath):
            if not os.access(spath, os.W_OK):
                self.sendError(
                    ray.Err.GENERAL_ERROR,
                    _translate(
                        "error",
                        "Impossible to save template, unwriteable file !"))

                self.setServerStatus(ray.ServerStatus.READY)
                return

            shutil.rmtree(spath)

        if not os.path.exists(template_root):
            os.makedirs(template_root)

        # For network sessions,
        # save as template the network session only
        # if there is no other server on this same machine.
        # Else, one could erase template just created by another one.
        # To prevent all confusion,
        # all seen machines are sent to prevent an erase by looping
        # (a network session can contains another network session
        # on the machine where is the master daemon, for example).

        for client in self.clients:
            if (client.protocol == ray.Protocol.RAY_NET
                    and client.ray_net.daemon_url):
                self.send(Address(client.ray_net.daemon_url),
                          '/ray/server/save_session_template',
                          self.getShortPath(),
                          template_name,
                          client.ray_net.session_root)

        self.setServerStatus(ray.ServerStatus.COPY)

        self.sendGuiMessage(
            _translate('GUIMSG', 'start session copy to template...'))

        self.file_copier.startSessionCopy(self.path,
                                          spath,
                                          self.saveSessionTemplate_substep_1,
                                          self.saveSessionTemplateAborted,
                                          [template_name, net])

    def saveSessionTemplate_substep_1(self, template_name, net):
        tp_mode = ray.Template.SESSION_SAVE
        if net:
            tp_mode = ray.Template.SESSION_SAVE_NET

        for client in self.clients + self.trashed_clients:
            client.adjustFilesAfterCopy(template_name, tp_mode)

        self.message("Done")
        self.sendGuiMessage(
            _translate('GUIMSG', "...session saved as template named %s")
                % ray.highlightText(template_name))

        self.sendReply("Saved as template.")
        self.setServerStatus(ray.ServerStatus.READY)

    def saveSessionTemplateAborted(self, template_name):
        self.steps_order.clear()
        self.sendReply("Session template aborted")
        self.setServerStatus(ray.ServerStatus.READY)

    def prepareTemplate(self, new_session_full_name,
                        template_name, net=False):
        template_root = TemplateRoots.user_sessions

        if net:
            template_root = "%s/%s" \
                            % (self.root, TemplateRoots.net_session_name)

        template_path = "%s/%s" % (template_root, template_name)

        if template_name.startswith('///'):
            template_name = template_name.replace('///', '')
            template_path = "%s/%s" \
                            % (TemplateRoots.factory_sessions, template_name)

        if not os.path.isdir(template_path):
            self.sendMinorError(ray.Err.GENERAL_ERROR,
                           _translate("error", "No template named %s")
                           % template_name)
            self.nextFunction()
            return

        spath = self.getFullPath(new_session_full_name)

        if os.path.exists(spath):
            self.sendError(ray.Err.CREATE_FAILED,
                           _translate("error", "Folder\n%s\nalready exists")
                           % spath)
            return

        if self.isPathInASessionDir(spath):
            self.sendError(ray.Err.SESSION_IN_SESSION_DIR,
                           _translate("error",
                """Can't create session in a dir containing a session
for better organization."""))
            return

        if self.path:
            self.setServerStatus(ray.ServerStatus.COPY)
        else:
            self.setServerStatus(ray.ServerStatus.PRECOPY)

        self.sendGuiMessage(
            _translate('GUIMSG',
                       'start copy from template to session folder'))

        self.file_copier.startSessionCopy(template_path,
                                          spath,
                                          self.prepareTemplate_substep1,
                                          self.prepareTemplateAborted,
                                          [new_session_full_name])

    def prepareTemplate_substep1(self, new_session_full_name):
        self.adjustFilesAfterCopy(new_session_full_name,
                                  ray.Template.SESSION_LOAD)
        self.nextFunction()

    def prepareTemplateAborted(self, new_session_full_name):
        self.steps_order.clear()
        if self.path:
            self.setServerStatus(ray.ServerStatus.READY)
        else:
            self.setServerStatus(ray.ServerStatus.OFF)

            self.setPath('')
            self.sendGui('/ray/gui/session/name', '', '')

    def rename(self, new_session_name):
        for client in self.clients + self.trashed_clients:
            client.adjustFilesAfterCopy(new_session_name, ray.Template.RENAME)

        try:
            spath = "%s/%s" % (dirname(self.path), new_session_name)
            subprocess.run(['mv', self.path, spath])
            self.setPath(spath)

            self.sendGuiMessage(
                _translate('GUIMSG', 'Session directory is now: %s')
                % self.path)
        except:
            pass

        self.nextFunction()

    def renameDone(self, new_session_name):
        self.sendGuiMessage(
            _translate('GUIMSG', 'Session %s has been renamed to %s .')
            % (self.name, new_session_name))
        self.sendReply("Session '%s' has been renamed to '%s' ."
                        % (self.name, new_session_name))
        self.forgetOscArgs()

    def preload(self, session_full_name):
        # load session data in self.future* (clients, trashed_clients,
        #                                    session_path, session_name)

        spath = self.getFullPath(session_full_name)

        if spath == self.path:
            self.loadError(ray.Err.SESSION_LOCKED)
            return

        if not os.path.exists(spath):
            if self.isPathInASessionDir(spath):
                # prevent to create a session in a session directory
                # for better user organization
                self.loadError(ray.Err.SESSION_IN_SESSION_DIR)
                return

            try:
                os.makedirs(spath)
            except:
                self.loadError(ray.Err.CREATE_FAILED)
                return

        multi_daemon_file = MultiDaemonFile.getInstance()
        if (multi_daemon_file
                and not multi_daemon_file.isFreeForSession(spath)):
            Terminal.warning("Session %s is used by another daemon")
            self.loadError(ray.Err.SESSION_LOCKED)
            return

        self.message("Attempting to open %s" % spath)

        session_ray_file = "%s/raysession.xml" % spath
        session_nsm_file = "%s/session.nsm" % spath

        # change session file only for raysession launched with NSM_URL env
        # Not sure that this feature is really useful.
        # Any cases, It's important to rename it
        # because we want to prevent session creation in a session folder
        if self.isNsmLocked() and os.getenv('NSM_URL'):
            session_ray_file = "%s/raysubsession.xml" % spath

        is_ray_file = True

        try:
            ray_file = open(session_ray_file, 'r')
        except:
            is_ray_file = False

        if not is_ray_file:
            try:
                file = open(session_nsm_file, 'r')
            except:
                try:
                    ray_file = open(session_ray_file, 'w')
                    xml = QDomDocument()
                    p = xml.createElement('RAYSESSION')
                    p.setAttribute('VERSION', ray.VERSION)

                    if self.isNsmLocked():
                        name = basename(session_full_name).rpartition('.')[0]
                        p.setAttribute('name', name)

                    xml.appendChild(p)

                    ray_file.write(xml.toString())
                    ray_file.close()

                    ray_file = open(session_ray_file, 'r')

                    is_ray_file = True

                except:
                    self.loadError(ray.Err.CREATE_FAILED)
                    return

        self.noFuture()
        sess_name = ""

        if is_ray_file:
            xml = QDomDocument()
            try:
                xml.setContent(ray_file.read())
            except:
                self.loadError(ray.Err.BAD_PROJECT)
                return

            content = xml.documentElement()

            if content.tagName() != "RAYSESSION":
                ray_file.close()
                self.loadError(ray.Err.BAD_PROJECT)
                return

            sess_name = content.attribute('name')

            client_id_list = []

            nodes = content.childNodes()

            for i in range(nodes.count()):
                node = nodes.at(i)
                tag_name = node.toElement().tagName()
                if tag_name in ('Clients', 'RemovedClients'):
                    clients_xml = node.toElement().childNodes()

                    for j in range(clients_xml.count()):
                        client_xml = clients_xml.at(j)
                        client = Client(self)
                        cx = client_xml.toElement()
                        client.readXmlProperties(cx)

                        if client.client_id in client_id_list:
                            # prevent double same id
                            continue

                        if tag_name == 'Clients':
                            self.future_clients.append(client)

                        elif tag_name == 'RemovedClients':
                            self.future_trashed_clients.append(client)
                        else:
                            continue

                        client_id_list.append(client.client_id)

                elif tag_name == "Windows":
                    server = self.getServer()
                    if server and server.option_desktops_memory:
                        self.desktops_memory.readXml(node.toElement())

            ray_file.close()

        else:
            # prevent to load a locked NSM session
            if os.path.isfile(spath + '/.lock'):
                Terminal.warning("Session %s is locked by another process")
                self.loadError(ray.Err.SESSION_LOCKED)
                return

            for line in file.read().split('\n'):
                elements = line.split(':')
                if len(elements) >= 3:
                    client = Client(self)
                    client.name = elements[0]
                    client.executable_path = elements[1]
                    client.client_id = elements[2]
                    client.prefix_mode = ray.PrefixMode.CLIENT_NAME
                    client.auto_start = True
                    client._from_nsm_file = True
                    self.future_clients.append(client)

            file.close()
            self.sendGui('/ray/gui/session/is_nsm')

        full_notes_path = "%s/%s" % (spath, ray.NOTES_PATH)

        if (os.path.isfile(full_notes_path)
                and os.access(full_notes_path, os.R_OK)):
            notes_file = open(full_notes_path)
            # limit notes characters to 65000 to prevent OSC message accidents
            self.future_notes = notes_file.read(65000)
            notes_file.close()

        self.future_session_path = spath
        self.future_session_name = sess_name
        self.switching_session = bool(self.path)

        self.nextFunction()

    def takePlace(self):
        self.setPath(self.future_session_path, self.future_session_name)

        if (self.name and self.name != os.path.basename(self.path)):
            # session folder has been renamed
            # so rename session to it
            for client in self.future_clients + self.future_trashed_clients:
                client.adjustFilesAfterCopy(self.path, ray.Template.RENAME)
            self.setPath(self.future_session_path)

        self.sendGui("/ray/gui/session/name", self.name, self.path)
        self.trashed_clients.clear()

        self.notes = self.future_notes
        self.sendGui('/ray/gui/session/notes', self.notes)

        self.load_locked = True

        self.nextFunction()

    def load(self, open_off=False):
        self.cleanExpected()
        self.clients_to_quit.clear()

        # first quit unneeded clients
        # It has probably been done but we can't know if during the load script
        # some clients could have been stopped.
        # Because adding client is not allowed
        # during the load script before run_step,
        # we can assume all these clients are needed if they are running.
        # 'open_off' decided during the load script
        # is a good reason to stop all clients.

        for client in self.clients.__reversed__():
            if (open_off
                    or not client.isRunning()
                    or client.isReplyPending()
                    or client.switch_state != ray.SwitchState.RESERVED):
                self.clients_to_quit.append(client)
                self.expected_clients.append(client)
            else:
                client.switch_state = ray.SwitchState.NEEDED

        self.timer_quit.start()
        self.waitAndGoTo(5000, (self.load_substep2, open_off), ray.WaitFor.QUIT)

    def load_substep2(self, open_off):
        for client in self.expected_clients:
            client.kill()

        self.waitAndGoTo(1000, (self.load_substep3, open_off), ray.WaitFor.QUIT)

    def load_substep3(self, open_off):
        self.cleanExpected()

        self.load_locked = False
        self.sendGuiMessage(_translate('GUIMSG', "-- Opening session %s --")
                                % ray.highlightText(self.getShortPath()))

        for trashed_client in self.future_trashed_clients:
            self.trashed_clients.append(trashed_client)
            trashed_client.sendGuiClientProperties(removed=True)

        self.message("Commanding smart clients to switch")
        has_switch = False
        new_client_id_list = []

        # remove stopped clients
        rm_indexes = []
        for i in range(len(self.clients)):
            client = self.clients[i]
            if not client.isRunning():
                rm_indexes.append(i)

        rm_indexes.reverse()
        for i in rm_indexes:
            self.removeClient(self.clients[i])

        # Lie to the GUI saying all clients are removed.
        # Clients will reappear just in a few time
        # It prevents GUI to have 2 clients with the same client_id
        # in the same time
        for client in self.clients:
            client.setStatus(ray.ClientStatus.REMOVED)
            client.sent_to_gui = False

        for future_client in self.future_clients:
            client = None

            # This part needs care
            # we add future_clients to clients.
            # At this point,
            # running clients waiting for switch have SwitchState NEEDED
            # running clients already choosen for switch have SwitchState DONE
            # clients just added from future clients without switch
            #    have SwitchState NONE.

            if future_client.auto_start:
                for client in self.clients:
                    if (client.switch_state == ray.SwitchState.NEEDED
                            and client.client_id == future_client.client_id
                            and client.running_executable
                                    == future_client.executable_path
                            and client.running_arguments
                                    == future_client.arguments):
                        #we found the good existing client
                        break
                else:
                    for client in self.clients:
                        if (client.switch_state == ray.SwitchState.NEEDED
                                and client.running_executable
                                    == future_client.executable_path
                                and client.running_arguments
                                    == future_client.arguments):
                            # we found a switchable client
                            break
                    else:
                        client = None

            if client:
                client.switch_state = ray.SwitchState.DONE
                client.eatAttributes(future_client)
                has_switch = True
            else:
                if not self.addClient(future_client):
                    continue

                if future_client.auto_start and not (self.is_dummy or open_off):
                    self.clients_to_launch.append(future_client)

                    if (not future_client.executable_path
                            in RS.non_active_clients):
                        self.expected_clients.append(future_client)

            new_client_id_list.append(future_client.client_id)

        for client in self.clients:
            if client.switch_state == ray.SwitchState.DONE:
                client.switch()

        self.reOrderClients(new_client_id_list)
        self.sendGui('/ray/gui/session/sort_clients', *new_client_id_list)

        self.noFuture()

        if has_switch:
            self.setServerStatus(ray.ServerStatus.SWITCH)
        else:
            self.setServerStatus(ray.ServerStatus.LAUNCH)


        #* this part is a little tricky... the clients need some time to
        #* send their 'announce' messages before we can send them 'open'
        #* and know that a reply is pending and we should continue waiting
        #* until they finish.

        #* dumb clients will never send an 'announce message', so we need
        #* to give up waiting on them fairly soon. */

        self.timer_launch.start()

        wait_time = 4000 + len(self.expected_clients) * 1000

        self.waitAndGoTo(wait_time, self.load_substep4, ray.WaitFor.ANNOUNCE)

    def load_substep4(self):
        for client in self.expected_clients:
            if not client.executable_path in RS.non_active_clients:
                RS.non_active_clients.append(client.executable_path)

        RS.settings.setValue('daemon/non_active_list', RS.non_active_clients)

        self.cleanExpected()

        self.setServerStatus(ray.ServerStatus.OPEN)

        for client in self.clients:
            if client.active and client.isReplyPending():
                self.expected_clients.append(client)
            elif client.isRunning() and client.isDumbClient():
                client.setStatus(ray.ClientStatus.NOOP)

        if self.expected_clients:
            n_expected = len(self.expected_clients)
            if n_expected == 1:
                self.sendGuiMessage(
                    _translate('GUIMSG',
                            'waiting for %s to load its project...')
                        % self.expected_clients[0].guiMsgStyle())
            else:
                self.sendGuiMessage(
                    _translate('GUIMSG',
                            'waiting for %s clients to load their project...')
                        % n_expected)

        wait_time = 8000 + len(self.expected_clients) * 2000
        for client in self.expected_clients:
            wait_time = max(2 * 1000 * client.last_open_duration, wait_time)

        self.waitAndGoTo(wait_time, self.load_substep5, ray.WaitFor.REPLY)

    def load_substep5(self):
        self.cleanExpected()

        server = self.getServer()
        if server and server.option_desktops_memory:
            self.desktops_memory.replace()

        self.tellAllClientsSessionIsLoaded()
        self.message('Loaded')
        self.sendGuiMessage(
            _translate('GUIMSG', 'session %s is loaded.')
                % ray.highlightText(self.getShortPath()))
        self.sendGui("/ray/gui/session/name", self.name, self.path)

        self.switching_session = False

        self.nextFunction()

    def loadDone(self):
        self.sendReply("Loaded.")
        self.message("Done")
        self.setServerStatus(ray.ServerStatus.READY)
        self.forgetOscArgs()

    def loadError(self, err_loading):
        self.message("Failed")
        m = _translate('Load Error', "Unknown error")
        if err_loading == ray.Err.CREATE_FAILED:
            m = _translate('Load Error', "Could not create session file!")
        elif err_loading == ray.Err.SESSION_LOCKED:
            m = _translate('Load Error',
                           "Session is locked by another process!")
        elif err_loading == ray.Err.NO_SUCH_FILE:
            m = _translate('Load Error', "The named session does not exist.")
        elif err_loading == ray.Err.BAD_PROJECT:
            m = _translate('Load Error', "Could not load session file.")
        elif err_loading == ray.Err.SESSION_IN_SESSION_DIR:
            m = _translate('Load Error',
                """Can't create session in a dir containing a session
for better organization.""")

        self.sendError(err_loading, m)

        if self.path:
            self.setServerStatus(ray.ServerStatus.READY)
        else:
            self.setServerStatus(ray.ServerStatus.OFF)

        self.steps_order.clear()

    def duplicateOnlyDone(self):
        self.send(self.osc_src_addr, '/ray/net_daemon/duplicate_state', 1)
        self.forgetOscArgs()

    def duplicateDone(self):
        self.message("Done")
        self.sendReply("Duplicated.")
        self.setServerStatus(ray.ServerStatus.READY)
        self.forgetOscArgs()

    def exitNow(self):
        self.setServerStatus(ray.ServerStatus.OFF)
        self.setPath('')
        self.message("Bye Bye...")
        self.sendReply("Bye Bye...")
        self.sendGui('/ray/gui/server/disannounce')
        QCoreApplication.quit()

    def addClientTemplate(self, src_addr, src_path,
                          template_name, factory=False):
        search_paths = self.getSearchTemplateDirs(factory)

        for search_path in search_paths:
            xml_file = "%s/%s" % (search_path, 'client_templates.xml')

            try:
                file = open(xml_file, 'r')
                xml = QDomDocument()
                xml.setContent(file.read())
                file.close()
            except:
                self.answer(src_addr, src_path,
                            _translate('GUIMSG', '%s is missing or corrupted !')
                                % xml_file,
                            ray.Err.NO_SUCH_FILE)
                return

            if xml.documentElement().tagName() != 'RAY-CLIENT-TEMPLATES':
                self.answer(src_addr, src_path,
                            _translate('GUIMSG',
                                '%s has no RAY-CLIENT-TEMPLATES top element !')
                                    % xml_file,
                            ray.Err.BAD_PROJECT)
                return

            nodes = xml.documentElement().childNodes()

            for i in range(nodes.count()):
                node = nodes.at(i)
                ct = node.toElement()

                if ct.tagName() != 'Client-Template':
                    continue

                if ct.attribute('template-name') != template_name:
                    continue

                client = Client(self)
                client.readXmlProperties(ct)

                # search for '/nsm/server/announce' in executable binary
                # if it is asked by "check_nsm_bin" key
                if ct.attribute('check_nsm_bin') in  ("1", "true"):
                    if not client.executable_path:
                        continue

                    which_exec = shutil.which(client.executable_path)
                    if not which_exec:
                        continue

                    result = QProcess.execute(
                        'grep', ['-q', '/nsm/server/announce', which_exec])
                    if result:
                        continue

                needed_version = ct.attribute('needed-version')

                if (needed_version.startswith('.')
                        or needed_version.endswith('.')
                        or not needed_version.replace('.', '').isdigit()):
                    #needed-version not writed correctly, ignores it
                    needed_version = ''

                if factory and needed_version:
                    version_process = QProcess()
                    version_process.start(client.executable_path,
                                          ['--version'])
                    version_process.waitForFinished(500)

                    if version_process.state():
                        version_process.terminate()
                        version_process.waitForFinished(500)
                        continue

                    full_program_version = str(
                        version_process.readAllStandardOutput(),
                        encoding='utf-8')

                    previous_is_digit = False
                    program_version = ''

                    for character in full_program_version:
                        if character.isdigit():
                            program_version += character
                            previous_is_digit = True
                        elif character == '.':
                            if previous_is_digit:
                                program_version += character
                            previous_is_digit = False
                        else:
                            if program_version:
                                break

                    if not program_version:
                        continue


                    neededs = []
                    progvss = []

                    for n in needed_version.split('.'):
                        neededs.append(int(n))

                    for n in program_version.split('.'):
                        progvss.append(int(n))

                    if neededs > progvss:
                        node = node.nextSibling()
                        continue

                full_name_files = []

                if not needed_version:
                    # if there is a needed version,
                    # then files are ignored because factory templates with
                    # version must be NSM compatible
                    # and dont need files (factory)
                    template_path = "%s/%s" % (search_path, template_name)

                    if os.path.isdir(template_path):
                        for file in os.listdir(template_path):
                            full_name_files.append("%s/%s"
                                                    % (template_path, file))

                if not self.addClient(client):
                    self.answer(src_addr, src_path,
                                "Session does not accept any new client now",
                                ray.Err.NOT_NOW)
                    return

                client.template_origin = template_name

                if full_name_files:
                    client.setStatus(ray.ClientStatus.PRECOPY)
                    self.file_copier.startClientCopy(
                        client.client_id, full_name_files, self.path,
                        self.addClientTemplate_step_1,
                        self.addClientTemplateAborted,
                        [src_addr, src_path, client])
                else:
                    self.addClientTemplate_step_1(src_addr, src_path,
                                                    client)

                return

        # no template found with that name
        for favorite in RS.favorites:
            if (favorite.name == template_name
                    and favorite.factory == factory):
                self.sendGui('/ray/gui/favorites/removed',
                                favorite.name,
                                int(favorite.factory))
                RS.favorites.remove(favorite)
                break

        self.send(src_addr, '/error', src_path, ray.Err.NO_SUCH_FILE,
                    _translate('GUIMSG', "%s is not an existing template !")
                    % ray.highlightText(template_name))

    def addClientTemplate_step_1(self, src_addr, src_path, client):
        client.adjustFilesAfterCopy(self.name, ray.Template.CLIENT_LOAD)

        if client.auto_start:
            client.start()
        else:
            client.setStatus(ray.ClientStatus.STOPPED)

        self.answer(src_addr, src_path, client.client_id)

    def addClientTemplateAborted(self, src_addr, src_path, client):
        self.removeClient(client)
        self.send(src_addr, '/error', src_path, ray.Err.COPY_ABORTED,
                  _translate('GUIMSG', 'Copy has been aborted !'))

    def closeClient(self, client):
        self.setServerStatus(ray.ServerStatus.READY)

        self.expected_clients.append(client)
        client.stop()

        self.waitAndGoTo(30000, (self.closeClient_substep1, client),
                         ray.WaitFor.STOP_ONE)

    def closeClient_substep1(self, client):
        if client in self.expected_clients:
            client.kill()

        self.waitAndGoTo(1000, self.nextFunction, ray.WaitFor.STOP_ONE)

    def loadClientSnapshot(self, client_id, snapshot):
        self.setServerStatus(ray.ServerStatus.REWIND)
        if self.snapshoter.loadClientExclusive(client_id, snapshot,
                                               self.loadClientSnapshotError):
            self.setServerStatus(ray.ServerStatus.READY)
            self.nextFunction()

    def loadClientSnapshotError(self, err, info_str=''):
        m = _translate('Snapshot Error', "Snapshot error")
        if err == ray.Err.SUBPROCESS_UNTERMINATED:
            m = _translate('Snapshot Error',
                           "command didn't stop normally:\n%s") % info_str
        elif err == ray.Err.SUBPROCESS_CRASH:
            m = _translate('Snapshot Error',
                           "command crashes:\n%s") % info_str
        elif err == ray.Err.SUBPROCESS_EXITCODE:
            m = _translate('Snapshot Error',
                           "command exit with an error code:\n%s") % info_str
        elif err == ray.Err.NO_SUCH_FILE:
            m = _translate('Snapshot Error',
                           "error reading file:\n%s") % info_str
        self.message(m)
        self.sendGuiMessage(m)
        self.sendError(err, m)

        self.setServerStatus(ray.ServerStatus.OFF)
        self.steps_order.clear()

    def startClient(self, client):
        client.start()
        self.nextFunction()

    def loadClientSnapshotDone(self):
        self.send(self.osc_src_addr, '/reply', self.osc_path,
                  'Client snapshot loaded')
        
    def terminateStepScripter(self):
        if self.step_scripter.isRunning():
            self.step_scripter.terminate()

        self.waitAndGoTo(5000, self.terminateStepScripter_substep2,
                         ray.WaitFor.SCRIPT_QUIT)

    def terminateStepScripter_substep2(self):
        if self.step_scripter.isRunning():
            self.step_scripter.kill()

        self.waitAndGoTo(1000, self.terminateStepScripter_substep3,
                         ray.WaitFor.SCRIPT_QUIT)

    def terminateStepScripter_substep3(self):
        self.nextFunction()

    def clearClients(self, src_addr, src_path, *client_ids):
        self.clients_to_quit.clear()
        self.expected_clients.clear()

        for client in self.clients:
            if client.client_id in client_ids or not client_ids:
                self.clients_to_quit.append(client)
                self.expected_clients.append(client)

        self.timer_quit.start()

        self.waitAndGoTo(5000,
                         (self.clearClients_substep2, src_addr, src_path),
                         ray.WaitFor.QUIT)

    def clearClients_substep2(self, src_addr, src_path):
        for client in self.expected_clients:
            client.kill()

        self.waitAndGoTo(1000,
                         (self.clearClients_substep3, src_addr, src_path),
                         ray.WaitFor.QUIT)

    def clearClients_substep3(self, src_addr, src_path):
        self.answer(src_addr, src_path, 'Clients cleared')
