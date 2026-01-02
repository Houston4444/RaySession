
# Imports from standard library
import logging
import os
import random
import string
from typing import Optional, TYPE_CHECKING
from pathlib import Path
import xml.etree.ElementTree as ET

# third party imports
from qtpy.QtCore import QCoreApplication, QTimer
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

# Imports from src/shared
from osclib import OscPack, Address, are_same_osc_port
import ray
from xml_tools import XmlElement
import osc_paths.nsm as nsm
import osc_paths.ray as r
import osc_paths.ray.gui as rg

# Local imports
from bookmarker import BookMarker
from client import Client
from daemon_tools import Terminal
from desktops_memory import DesktopsMemory
import multi_daemon_file
import patchbay_dmn_mng
from server_sender import ServerSender
import session_op as sop
from snapshoter import Snapshoter
from file_copier import FileCopier
from scripter import StepScripter
from canvas_saver import CanvasSaver
import templates_database


_logger = logging.getLogger(__name__)
_translate = QCoreApplication.translate


class Session(ServerSender):
    def __init__(self, root: Path, session_id=0):
        ServerSender.__init__(self)
        self.root = root
        self.is_dummy = False
        self.session_id = session_id

        self.clients = list[Client]()
        self.future_clients = list[Client]()
        self.trashed_clients = list[Client]()
        self.future_trashed_clients = list[Client]()
        self.recent_sessions = dict[Path, list[str]]()

        self.name = ''
        self.path: Optional[Path] = None
        self.future_session_path = Path()
        self.future_session_name = ''
        self.notes = ''
        self.future_notes = ''
        self.notes_shown = False
        self.future_notes_shown = False
        self.load_locked = False

        self.is_renameable = True
        self.forbidden_ids_set = set[str]()

        self.bookmarker = BookMarker()
        self.desktops_memory = DesktopsMemory(self)
        
        self._time_at_open = 0.0

        self.wait_for = ray.WaitFor.NONE

        self.file_copier = FileCopier(self)
        self.step_scripter = StepScripter(self)
        self.canvas_saver = CanvasSaver(self)
        self.snapshoter = Snapshoter(self)

        self.timer = QTimer()
        self.timer_redondant = False
        self.expected_clients = list[Client]()

        self.timer_launch = QTimer()
        self.timer_launch.setInterval(100)
        self.timer_launch.timeout.connect(self._timer_launch_timeout)
        self.clients_to_launch = list[Client]()

        self.timer_quit = QTimer()
        self.timer_quit.setInterval(100)
        self.timer_quit.timeout.connect(self._timer_quit_timeout)
        self.clients_to_quit = list[Client]()

        self.timer_waituser_progress = QTimer()
        self.timer_waituser_progress.setInterval(500)
        self.timer_waituser_progress.timeout.connect(
            self._timer_wait_user_progress_timeout)
        self.timer_wu_progress_n = 0

        self.steps_osp: Optional[OscPack] = None
        'Stock the OscPack of the long operation running (if any).'

        self.cur_session_op: sop.SessionOp | None = None
        '''Is only used to prevent destruction of the current session_op
        when the timer waits for some client or session actions.'''
        self.session_ops = list[sop.SessionOp]()
        '''Contains the SessionOp list to run once self.cur_session_op
        is finished.'''

        self.alternative_groups = list[set[str]]()

        self.terminated_yet = False

        # externals are clients not launched from the daemon
        # but with NSM_URL=...
        self.externals_timer = QTimer()
        self.externals_timer.setInterval(100)
        self.externals_timer.timeout.connect(self._check_externals_states)

        self.window_waiter = QTimer()
        self.window_waiter.setInterval(200)
        self.window_waiter.timeout.connect(self._check_windows_appears)

        self.script_osp: OscPack | None = None

        self.switching_session = False

    def set_renameable(self, renameable: bool):
        server = self.get_server()
        if server is None:
            return

        if not renameable:
            if self.is_renameable:
                self.is_renameable = False
                if server:
                    server.send_renameable(False)
            return

        for client in self.clients:
            if client.is_running:
                return

        self.is_renameable = True
        server.send_renameable(True)

    def message(self, string: str, even_dummy=False):
        '''write in the prompt, with the following syntax:
        
        `[ray-daemon] message`
        
        Also write in log files'''
        
        if self.is_dummy and not even_dummy:
            return

        server = self.get_server()
        if server is not None:
            Terminal.message(string, server.port) #type:ignore
        else:
            Terminal.message(string)

    def set_path(self, session_path: Path | None, session_name=''):
        if not self.is_dummy:
            if self.path:
                self.bookmarker.remove_all(self.path)

        if session_path is None:
            self.path = None
            self.name = ''
        else:
            self.path = session_path
            if session_name:
                self.name = session_name
            else:
                self.name = session_path.name

        if self.is_dummy:
            return

        multi_daemon_file.update()

        if self.path:
            if self.has_server_option(ray.Option.BOOKMARK_SESSION):
                self.bookmarker.set_daemon_port(self.get_server_port())
                self.bookmarker.make_all(self.path)

    def no_future(self):
        'reset all attributes related to the future session (self.future_*)'
        self.future_clients.clear()
        self.future_session_path = Path()
        self.future_session_name = ''
        self.future_trashed_clients.clear()
        self.future_notes = ''
        self.future_notes_shown = False

    @property
    def short_path_name(self) -> str:
        '''The session path relative to sessions root, as str.
        Empty if no session is open,
        Session name if session is not in session root.'''
        if self.path is None:
            return ''
        
        if self.path.is_relative_to(self.root):
            return str(self.path.relative_to(self.root))
        
        return self.name

    def remember_as_recent(self):
        'put loaded session (if exists) in recent sessions'
        if self.path is None:
            return
        
        if self.name and not self.is_dummy:
            long_name = str(self.path.relative_to(self.root))

            if not self.root in self.recent_sessions.keys():
                self.recent_sessions[self.root] = []
            if long_name in self.recent_sessions[self.root]:
                self.recent_sessions[self.root].remove(long_name)
            self.recent_sessions[self.root].insert(0, long_name)
            if len(self.recent_sessions[self.root]) > 7:
                self.recent_sessions[self.root] = \
                    self.recent_sessions[self.root][:7]
            self.send_gui(rg.server.RECENT_SESSIONS,
                          *self.recent_sessions[self.root])

    def get_client(self, client_id: str) -> Client | None:
        for client in self.clients:
            if client.client_id == client_id:
                return client

        _logger.error(f'client_id {client_id} is not in ray-daemon session')

    def get_client_by_address(self, addr: Address) -> Optional[Client]:
        if not addr:
            return None

        for client in self.clients:
            if client.addr and client.addr.url == addr.url:
                return client

    def _trash_client(self, client:Client):
        if not client in self.clients:
            raise NameError("No client to trash: %s" % client.client_id)
            return

        client.set_status(ray.ClientStatus.REMOVED)

        ## Theses lines are commented because finally choice is to
        ## always send client to trash
        ## comment self.trashed_client.append(client) if choice is reversed !!!
        #if client.is_ray_hack():
            #client_dir = client.get_project_path()
            #if os.path.isdir(client_dir):
                #if os.listdir(client_dir):
                    #self.trashed_clients.append(client)
                    #client.send_gui_client_properties(removed=True)
                #else:
                    #try:
                        #os.removedirs(client_dir)
                    #except:
                        #self.trashed_clients.append(client)
                        #client.send_gui_client_properties(removed=True)

        #elif client.getProjectFiles() or client.net_daemon_url:
            #self.trashed_clients.append(client)
            #client.send_gui_client_properties(removed=True)

        self.trashed_clients.append(client)
        client.send_gui_client_properties(removed=True)
        self.clients.remove(client)

    def _remove_client(self, client:Client):
        client.terminate_scripts()
        client.terminate()

        if client not in self.clients:
            raise NameError("No client to remove: %s" % client.client_id)

        client.set_status(ray.ClientStatus.REMOVED)

        self.clients.remove(client)

    def _restore_client(self, client: Client) -> bool:
        client.sent_to_gui = False

        if not self._add_client(client):
            return False

        self.send_gui(rg.trash.REMOVE, client.client_id)
        self.trashed_clients.remove(client)
        return True

    def _clients_have_errors(self):
        for client in self.clients:
            if client.nsm_active and client.has_error():
                return True
        return False

    def _update_forbidden_ids_set(self):
        if self.path is None:
            return

        self.forbidden_ids_set.clear()

        for file in self.path.iterdir():
            if file.is_dir() and '.' in file.name:
                client_id = file.name.rpartition('.')[2]
                self.forbidden_ids_set.add(client_id)
                
            elif file.is_file() and '.' in file.name:
                for string in file.name.split('.')[1:]:
                    self.forbidden_ids_set.add(string)

        for client in self.clients + self.trashed_clients:
            self.forbidden_ids_set.add(client.client_id)

    def _generate_client_id_as_nsm(self) -> str:
        client_id = 'n'
        for i in range(4):
            client_id += random.choice(string.ascii_uppercase)

        return client_id

    def save_session_file(self) -> ray.Err:
        if self.path is None:
            return ray.Err.NO_SESSION_OPEN

        session_path = self.path
        
        session_file = session_path / 'raysession.yaml'
        if self.is_nsm_locked() and os.getenv('NSM_URL'):
            session_file = session_path / 'raysubsession.yaml'

        main_map = CommentedMap()
        main_map['app'] = 'RAYSESSION'
        main_map['version'] = ray.VERSION
        main_map['name'] = self.name
        if self.notes_shown:
            main_map['notes_shown'] = True
            
        clients_map = CommentedMap()
        for client in self.clients:
            client_map = CommentedMap()
            client.write_yaml_properties(client_map)
            
            launched = bool(
                client.is_running
                or (client.auto_start
                    and not client.has_been_started))
            if not launched:
                client_map['launched'] = False
            
            clients_map[client.client_id] = client_map
        
        main_map['clients'] = clients_map
        
        trashed_clients_map = CommentedMap()
        if self.trashed_clients:
            for client in self.trashed_clients:
                client_map = CommentedMap()
                client.write_yaml_properties(client_map)
                trashed_clients_map[client.client_id] = client_map
            
            main_map['trashed_clients'] = trashed_clients_map
        
        alter_groups_seq = [sorted(ag) for ag in self.alternative_groups]
        if alter_groups_seq:
            main_map['alternative_groups'] = alter_groups_seq
        
        # save desktop memory of windows if needed
        if self.has_server_option(ray.Option.DESKTOPS_MEMORY):
            self.desktops_memory.save()
        
        if self.desktops_memory.saved_windows:
            main_map['windows'] = CommentedSeq()
            for win in self.desktops_memory.saved_windows:
                wmap = CommentedMap()
                wmap['class'] = win.wclass
                wmap['name'] = win.name
                wmap['desktop'] = win.desktop
        
        yaml = YAML()
        try:
            yaml.dump(main_map, session_file)
        except BaseException as e:
            _logger.error(f'Failed to save session file {session_file}')
            _logger.error(f'{str(e)}')
            return ray.Err.CREATE_FAILED

        # root = ET.Element('RAYSESSION')
        # xroot = XmlElement(root)
        # xroot.set_str('VERSION', ray.VERSION)
        # xroot.set_str('name', self.name)
        # if self.notes_shown:
        #     xroot.set_bool('notes_shown', True)
        
        # cs = xroot.new_child('Clients')
        # rcs = xroot.new_child('RemovedClients')
        # ws = xroot.new_child('Windows')
        
        # # save clients attributes
        # for client in self.clients:
        #     c = cs.new_child('client')
        #     c.set_str('id', client.client_id)
            
        #     launched = bool(
        #         client.is_running
        #         or (client.auto_start
        #             and not client.has_been_started))
        #     c.set_bool('launched', launched)            
        #     client.write_xml_properties(c)
        
        # # save trashed clients attributes
        # for client in self.trashed_clients:
        #     c = rcs.new_child('client')
        #     c.set_str('id', client.client_id)
        #     client.write_xml_properties(c)
            
        # # save desktop memory of windows if needed
        # if self.has_server_option(ray.Option.DESKTOPS_MEMORY):
        #     self.desktops_memory.save()
            
        # for win in self.desktops_memory.saved_windows:
        #     w = ws.new_child('window')
        #     w.set_str('class', win.wclass)
        #     w.set_str('name', win.name)
        #     w.set_int('desktop', win.desktop)

        # tree = ET.ElementTree(root)
        # ET.indent(tree, level=0)

        # try:
        #     f = BytesIO()
        #     tree.write(f)
        #     header = ("<?xml version='1.0' encoding='UTF-8'?>\n"
        #               "<!DOCTYPE RAYSESSION>\n")
        #     text = header + f.getvalue().decode()
            
        #     with open(session_file, 'w') as f:
        #         f.write(text)

        # except BaseException as e:
        #     _logger.error(str(e))
        #     return ray.Err.CREATE_FAILED
        
        return ray.Err.OK

    def generate_abstract_client_id(self, wanted_id: str) -> str:
        '''generates a client_id from wanted_id
        not regarding the existing ids in the session
        or session directory. Useful for templates'''
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
                if sep:
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

        #limit string to 10 characters
        if len(wanted_id) >= 11:
            wanted_id = wanted_id[:10]
            
        return wanted_id

    def generate_client_id(self, wanted_id='') -> str:
        self._update_forbidden_ids_set()
        wanted_id = Path(wanted_id).name

        if wanted_id:
            wanted_id = self.generate_abstract_client_id(wanted_id)

            if not wanted_id:
                wanted_id = self._generate_client_id_as_nsm()
                while wanted_id in self.forbidden_ids_set:
                    wanted_id = self._generate_client_id_as_nsm()

            if not wanted_id in self.forbidden_ids_set:
                self.forbidden_ids_set.add(wanted_id)
                return wanted_id

            n = 2
            while f'{wanted_id}_{n}' in self.forbidden_ids_set:
                n += 1

            self.forbidden_ids_set.add(wanted_id)
            return f'{wanted_id}_{n}'

        client_id = 'n'
        for l in range(4):
            client_id += random.choice(string.ascii_uppercase)

        while client_id in self.forbidden_ids_set:
            client_id = 'n'
            for l in range(4):
                client_id += random.choice(string.ascii_uppercase)

        self.forbidden_ids_set.add(client_id)
        return client_id

    def _add_client(self, client: Client) -> bool:
        if self.load_locked or self.path is None:
            return False

        if client.is_ray_hack:
            project_path = client.project_path
            if not project_path.is_dir():
                try:
                    project_path.mkdir(parents=True)
                except:
                    return False

        client.update_infos_from_desktop_file()
        self.clients.append(client)
        client.send_gui_client_properties()
        self.send_monitor_client_update(client)
        self._update_forbidden_ids_set()
        
        return True

    def _re_order_clients(
            self, client_ids_list: list[str], osp: Optional[OscPack]=None):
        client_newlist = list[Client]()

        for client_id in client_ids_list:
            for client in self.clients:
                if client.client_id == client_id:
                    client_newlist.append(client)
                    break

        if len(client_newlist) != len(self.clients):
            if osp is not None:
                self.send(
                    *osp.error(),
                    ray.Err.GENERAL_ERROR,
                    "%s clients are missing or incorrect" \
                        % (len(self.clients) - len(client_ids_list)))
            return

        self.clients.clear()
        for client in client_newlist:
            self.clients.append(client)

        if osp is not None:
            self.send(*osp.reply(), "clients reordered")

        self.send_gui(rg.session.SORT_CLIENTS,
                      *[c.client_id for c in self.clients])

    def is_path_in_a_session_dir(self, spath: Path):
        if self.is_nsm_locked() and os.getenv('NSM_URL'):
            return False

        base_path = spath
        
        while base_path.parent != base_path:
            base_path = base_path.parent
            for filename in 'raysession.yaml', 'raysession.xml':
                if Path(base_path / filename).is_file():
                    return True
            
        return False
        
    def send_initial_monitor(
            self, monitor_addr: Address, monitor_is_client=True):
        '''send clients states to a new monitor'''

        mon = nsm.client.monitor
        if not monitor_is_client:
            mon = r.monitor

        n_clients = 0

        for client in self.clients:
            if (monitor_is_client
                    and client.addr is not None
                    and are_same_osc_port(client.addr.url, monitor_addr.url)):
                continue

            self.send(
                monitor_addr,
                mon.CLIENT_STATE,
                client.client_id,
                client.jack_client_name,
                int(client.is_running))
            n_clients += 1

        for client in self.trashed_clients:
            self.send(
                monitor_addr,
                mon.CLIENT_STATE,
                client.client_id,
                client.jack_client_name,
                0)            
            n_clients += 1

        self.send(monitor_addr, mon.CLIENT_STATE, '', '', n_clients)

    def send_monitor_client_update(self, client: Client):
        '''send an event message to clients capable of ":monitor:"'''
        for other_client in self.clients:
            if (other_client is not client
                    and other_client.can_monitor):
                other_client.send_to_self_address(
                    nsm.client.monitor.CLIENT_UPDATED,
                    client.client_id,
                    client.jack_client_name,
                    int(client.is_running))
        
        server = self.get_server()
        if server is not None:
            for monitor_addr in server.monitor_list:
                self.send(
                    monitor_addr,
                    r.monitor.CLIENT_UPDATED,
                    client.client_id,
                    client.jack_client_name,
                    int(client.is_running))

    def send_monitor_event(self, event: str, client_id=''):
        '''send an event message to clients capable of ":monitor:"'''
        for client in self.clients:
            if (client.client_id != client_id
                    and client.can_monitor):
                client.send_to_self_address(
                    nsm.client.monitor.CLIENT_EVENT, client_id, event)
        
        server = self.get_server()
        if server is not None:
            for monitor_addr in server.monitor_list:
                self.send(monitor_addr, r.monitor.CLIENT_EVENT,
                          client_id, event)
    
    def _rebuild_templates_database(self, base: str):
        if TYPE_CHECKING and not isinstance(self, Session):
            return

        templates_database.rebuild_templates_database(self, base)


    def wait_and_go_to(
            self, session_op: sop.SessionOp, wait_for: ray.WaitFor,
            timeout: int | None =None, redondant=False):
        self.timer.stop()

        # we need to delete timer to change the timeout connect
        del self.timer
        self.timer = QTimer()

        if wait_for in (ray.WaitFor.SCRIPT_QUIT,
                        ray.WaitFor.PATCHBAY_QUIT,
                        ray.WaitFor.SNAPSHOT_ADD,
                        ray.WaitFor.FILE_COPY):
            match wait_for:
                case ray.WaitFor.SCRIPT_QUIT:
                    if not self.step_scripter.is_running():
                        session_op.run_next()
                        return
                case ray.WaitFor.PATCHBAY_QUIT:
                    if not patchbay_dmn_mng.is_running():
                        session_op.run_next()
                        return
                case ray.WaitFor.SNAPSHOT_ADD:
                    if not self.snapshoter.adder_running:
                        session_op.run_next()
                        return
                case ray.WaitFor.FILE_COPY:
                    if not self.file_copier.is_active():
                        session_op.run_next()
                        return

            self.wait_for = wait_for
            self.timer.setSingleShot(True)
            self.timer.timeout.connect(session_op.run_next)
            if timeout is not None:
                self.timer.start(timeout)
            return

        if self.expected_clients:
            n_expected = len(self.expected_clients)

            if wait_for is ray.WaitFor.ANNOUNCE:
                if n_expected == 1:
                    message = _translate(
                        'GUIMSG',
                        'waiting announce from %s...'
                            % self.expected_clients[0].gui_msg_style)
                else:
                    message = _translate(
                        'GUIMSG',
                        'waiting announce from %i clients...' % n_expected)
                self.send_gui_message(message)
            elif wait_for is ray.WaitFor.QUIT:
                if n_expected == 1:
                    message = _translate(
                        'GUIMSG',
                        'waiting for %s to stop...'
                            % self.expected_clients[0].gui_msg_style)
                else:
                    message = _translate(
                        'GUIMSG',
                        'waiting for %i clients to stop...' % n_expected)
                self.send_gui_message(message)

            self.timer_redondant = redondant

            self.wait_for = wait_for
            self.timer.setSingleShot(True)
            self.timer.timeout.connect(session_op.run_next)
            if timeout is not None:
                self.timer.start(timeout)
        else:
            session_op.run_next()

    def _forget_timer(self):
        self.timer.setSingleShot(True)
        self.timer.stop()
        self.timer.start(0)

    def end_timer_if_last_expected(self, client: Client):
        if self.wait_for is ray.WaitFor.QUIT and client in self.clients:
            self._remove_client(client)

        if client in self.expected_clients:
            self.expected_clients.remove(client)

            if self.timer_redondant:
                self.timer.start()
                if self.timer_waituser_progress.isActive():
                    self.timer_wu_progress_n = 0
                    self.timer_waituser_progress.start()

        if not self.expected_clients:
            self._forget_timer()
            self.timer_waituser_progress.stop()

    def clean_expected(self):
        if self.expected_clients:
            client_names = [c.gui_msg_style for c in self.expected_clients]

            match self.wait_for:
                case ray.WaitFor.ANNOUNCE:
                    self.send_gui_message(
                        _translate('GUIMSG', "%s didn't announce.")
                        % ', '.join(client_names))

                case ray.WaitFor.QUIT:
                    self.send_gui_message(
                        _translate('GUIMSG', "%s still alive !")
                        % ', '.join(client_names))

            self.expected_clients.clear()

        self.wait_for = ray.WaitFor.NONE

    def next_session_op(self, script_osp: OscPack | None =None,
                        script_forbidden=False):
        if self.script_osp is not None and script_osp is None:
            self.set_server_status(ray.ServerStatus.SCRIPT)
            self.send(*self.script_osp.reply(), 'step done')
            self.script_osp = None
            return

        if script_osp is not None:
            self.script_osp = script_osp

        if not self.session_ops:
            return

        next_sop = self.session_ops[0]
        if script_osp is not None:
            self.script_osp = script_osp
                
        if (self.has_server_option(ray.Option.SESSION_SCRIPTS)
                and not script_forbidden
                and not self.step_scripter.is_running()
                and self.path is not None
                and script_osp is None
                and not (isinstance(next_sop, sop.Load)
                         and next_sop.open_off)
                and next_sop.script_step
                and self.steps_osp is not None
                and self.step_scripter.start(next_sop.script_step)):
            self.set_server_status(ray.ServerStatus.SCRIPT)
            return

        self.cur_session_op = next_sop
        self.session_ops.__delitem__(0)

        if (script_osp is not None
                and self.step_scripter.is_running()
                and next_sop.script_step == self.step_scripter.step):
            self.step_scripter.called_run_step = True
            next_sop.start_from_script(script_osp)
            return

        _logger.debug(
            f'next session operation: {next_sop.__class__.__name__}')
        next_sop.start()

    def _timer_launch_timeout(self):
        if self.clients_to_launch:
            self.clients_to_launch[0].start()
            self.clients_to_launch.__delitem__(0)

        if not self.clients_to_launch:
            self.timer_launch.stop()

    def _timer_quit_timeout(self):
        if self.clients_to_quit:
            client_quitting = self.clients_to_quit.pop(0)
            client_quitting.stop()

        if not self.clients_to_quit:
            self.timer_quit.stop()

    def _timer_wait_user_progress_timeout(self):
        if not self.expected_clients:
            self.timer_waituser_progress.stop()

        self.timer_wu_progress_n += 1

        ratio = float(self.timer_wu_progress_n / 240)
        self.send_gui(rg.server.PROGRESS, ratio)

    def _check_externals_states(self):
        '''check if clients started from external are still alive
        or if clients launched in terminal have still their process active'''
        has_alives = False

        # execute client.external_finished will remove the client
        # from self.clients, so we need to collect them first
        # and execute this after to avoid item remove during iteration
        clients_to_finish = list[Client]()

        for client in self.clients:
            if client.is_external:
                has_alives = True
                if not os.path.exists('/proc/%i' % client.pid):
                    clients_to_finish.append(client)
            
            elif client._internal is not None:
                if client._internal.running:
                    has_alives = True
                elif client.status is not ray.ClientStatus.STOPPED:
                    clients_to_finish.append(client)

            elif (client.is_running
                    and client.launched_in_terminal
                    and client.status is not ray.ClientStatus.LOSE):
                has_alives = True
                if (client.nsm_active
                        and not os.path.exists('/proc/%i' % client.pid_from_nsm)):
                    client.nsm_finished_terminal_alive()

        for client in clients_to_finish:
            client.external_finished()

        if not has_alives:
            self.externals_timer.stop()

    def _check_windows_appears(self):
        for client in self.clients:
            if client.is_running and client.ray_hack_waiting_win:
                break
        else:
            self.window_waiter.stop()
            return

        if self.has_server_option(ray.Option.HAS_WMCTRL):
            self.desktops_memory.set_active_window_list()
            for client in self.clients:
                if client.ray_hack_waiting_win:
                    if self.desktops_memory.has_window(client.pid):
                        client.ray_hack_waiting_win = False
                        client.ray_hack_ready()

    def patchbay_process_finished(self):
        if self.wait_for is ray.WaitFor.PATCHBAY_QUIT:
            self._forget_timer()

    def snapshoter_add_finished(self):
        '`git add .` snapshoter command is finished'
        if self.wait_for is not ray.WaitFor.SNAPSHOT_ADD:
            _logger.warning(
                'git add command ended while nothing is waiting for it')
            return
        
        self.wait_for = ray.WaitFor.NONE
        self._forget_timer()        

    def files_copy_finished(self):
        if self.wait_for is ray.WaitFor.FILE_COPY:
            self.wait_for = ray.WaitFor.NONE
            self._forget_timer()

    def _send_reply(self, *args: str):
        if self.steps_osp is None:
            return
        
        self.send_even_dummy(*self.steps_osp.reply(), *args)
        
    def _send_error(self, err: ray.Err, error_message: str):
        # clear process order to allow other new operations
        self.session_ops.clear()

        if self.script_osp is not None:
            if err is ray.Err.OK:
                self.send(*self.script_osp.reply(), error_message)
            else:
                self.send(*self.script_osp.error(), err, error_message)
            
        if self.steps_osp is None:
            return
        
        self.send_even_dummy(*self.steps_osp.error(), err, error_message)

    def step_scripter_finished(self):
        if self.wait_for is ray.WaitFor.SCRIPT_QUIT:
            self.wait_for = ray.WaitFor.NONE
            self._forget_timer()
            return

        if not self.step_scripter.called_run_step:
            # script has not call run_step
            if self.step_scripter.step in ('load', 'close'):
                self.session_ops.clear()
                self.session_ops = [
                    sop.Close(self, clear_all_clients=True),
                    sop.Success(self, msg='Aborted')]

                self.next_session_op(script_forbidden=True)
                return

            if self.session_ops:
                self.session_ops.__delitem__(0)

        self.next_session_op()

    def adjust_files_after_copy(
            self, new_session_name: str,
            template_mode: ray.Template) -> tuple[ray.Err, str]:
        new_session_short_path = Path(new_session_name)
        
        if new_session_short_path.is_absolute():
            spath = new_session_short_path
        else:
            spath = self.root / new_session_short_path

        # create tmp clients from raysession.xml to adjust files after copy
        yaml_session_file = spath / 'raysession.yaml'
        xml_session_file = spath / 'raysession.xml'

        yaml = YAML()
        tmp_clients = list[Client]()

        if yaml_session_file.is_file():
            try:
                with open(yaml_session_file, 'r') as f:
                    session_map = yaml.load(f)
                assert isinstance(session_map, CommentedMap)
            except BaseException as e:
                _logger.error(str(e))
                return (
                    ray.Err.BAD_PROJECT,
                    _translate("error",
                               "impossible to read %s as a YAML session file")
                    % xml_session_file)
            
            if session_map.get('app') != 'RAYSESSION':
                return (
                    ray.Err.BAD_PROJECT,
                    _translate(
                        "error", "wrong YAML format, not a RAYSESSION app"))
                
            session_map['name'] = spath.name

            for clients_key in 'clients', 'trashed_clients':
                clients_map = session_map.get(clients_key)
                if not isinstance(clients_map, CommentedMap):
                    continue
                for client_id, cmap in clients_map.items():
                    if not (isinstance(client_id, str)
                            and isinstance(cmap, CommentedMap)):
                        continue
                    client = Client(self)
                    client.read_yaml_properties(cmap)
                    if not client.executable:
                        continue
                    client.client_id = client_id
                    tmp_clients.append(client)
            
            try:
                with open(yaml_session_file, 'w') as f:
                    yaml.dump(session_map, f)
            except BaseException as e:
                return (
                    ray.Err.CREATE_FAILED,
                    _translate("error", "impossible to write YAML file %s")
                        % xml_session_file)
                
        elif xml_session_file.is_file():
            try:
                tree = ET.parse(xml_session_file)
            except Exception as e:
                _logger.error(str(e))
                return (
                    ray.Err.BAD_PROJECT,
                    _translate("error", "impossible to read %s as a XML file")
                        % xml_session_file)
            
            root = tree.getroot()
            if root.tag != 'RAYSESSION':
                return (
                    ray.Err.BAD_PROJECT,
                    _translate("error",
                               "wrong XML format, no 'RAYSESSION' tag"))
            
            root.attrib['name'] = spath.name

            for child in root:
                if not child.tag in ('Clients', 'RemovedClients'):
                    continue

                for client_xml in child:
                    client = Client(self)
                    client.read_xml_properties(XmlElement(client_xml))
                    if not client.executable:
                        continue
                
                    tmp_clients.append(client)

            try:
                tree.write(xml_session_file)
            except BaseException as e:
                _logger.error(str(e))
                return (ray.Err.CREATE_FAILED,
                        _translate("error", "impossible to write XML file %s")
                            % xml_session_file)

        for client in tmp_clients:
            client.adjust_files_after_copy(new_session_name, template_mode)
        
        return ray.Err.OK, ''

    def get_client_from_id(self, client_id: str) -> Client | None:
        '''if it exists, return the client in self.clients
        with this `client_id`. If `client_id` is in trash, and is
        an alternative to a client in self.clients, return this matching
        client in self.clients'''
        for client in self.clients:
            if client.client_id == client_id:
                return client
        
        client_ids = set([c.client_id for c in self.clients])
        
        for alter_group in self.alternative_groups:
            if client_id in alter_group:
                for alt_client_id in alter_group:
                    if alt_client_id in client_ids:
                        for client in self.clients:
                            if client.client_id == alt_client_id:
                                return client