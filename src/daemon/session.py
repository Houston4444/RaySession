
# Imports from standard library
import logging
import os
import random
import string
from typing import TYPE_CHECKING, Optional
from pathlib import Path
import xml.etree.ElementTree as ET
from io import BytesIO

# third-party imports
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

# Imports from src/shared
from osclib import Address, are_same_osc_port, OscPack
import ray
from xml_tools import XmlElement
import osc_paths.ray as r
import osc_paths.ray.gui as rg
import osc_paths.nsm as nsm

# Local imports
from bookmarker import BookMarker
from desktops_memory import DesktopsMemory
from snapshoter import Snapshoter
import multi_daemon_file
from signaler import Signaler
from server_sender import ServerSender
from client import Client
from daemon_tools import Terminal
import templates_database

if TYPE_CHECKING:
    from session_operating import OperatingSession


_logger = logging.getLogger(__name__)
signaler = Signaler.instance()


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
        self.snapshoter = Snapshoter(self)
        
        self._time_at_open = 0

    def set_renameable(self, renameable:bool):
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

    def _set_path(self, session_path: Optional[Path], session_name=''):
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

    def _no_future(self):
        self.future_clients.clear()
        self.future_session_path = Path()
        self.future_session_name = ''
        self.future_trashed_clients.clear()
        self.future_notes = ""
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

    def get_client(self, client_id: str) -> Optional[Client]:
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

    def _save_session_file(self) -> ray.Err:
        if self.path is None:
            return ray.Err.NO_SESSION_OPEN

        session_path = self.path
        session_file = session_path / 'raysession.xml'

        if self.is_nsm_locked() and os.getenv('NSM_URL'):
            session_file = session_path / 'raysubsession.xml'

        if session_file.is_file() and not os.access(session_file, os.W_OK):
            return ray.Err.CREATE_FAILED
        
        session_file_yaml = session_path / 'raysession.yaml'
        if self.is_nsm_locked() and os.getenv('NSM_URL'):
            session_file_yaml = session_path / 'raysubsession.yaml'
        
        # if (session_file_yaml.is_file()
        #         and not os.access(session_file_yaml, os.W_OK)):
        #     return ray.Err.CREATE_FAILED

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
        yaml.dump(main_map, session_file_yaml)

        root = ET.Element('RAYSESSION')
        xroot = XmlElement(root)
        xroot.set_str('VERSION', ray.VERSION)
        xroot.set_str('name', self.name)
        if self.notes_shown:
            xroot.set_bool('notes_shown', True)
        
        cs = xroot.new_child('Clients')
        rcs = xroot.new_child('RemovedClients')
        ws = xroot.new_child('Windows')
        
        # save clients attributes
        for client in self.clients:
            c = cs.new_child('client')
            c.set_str('id', client.client_id)
            
            launched = bool(
                client.is_running
                or (client.auto_start
                    and not client.has_been_started))
            c.set_bool('launched', launched)            
            client.write_xml_properties(c)
        
        # save trashed clients attributes
        for client in self.trashed_clients:
            c = rcs.new_child('client')
            c.set_str('id', client.client_id)
            client.write_xml_properties(c)
            
        # save desktop memory of windows if needed
        if self.has_server_option(ray.Option.DESKTOPS_MEMORY):
            self.desktops_memory.save()
            
        for win in self.desktops_memory.saved_windows:
            w = ws.new_child('window')
            w.set_str('class', win.wclass)
            w.set_str('name', win.name)
            w.set_int('desktop', win.desktop)

        tree = ET.ElementTree(root)
        ET.indent(tree, level=0)

        try:
            f = BytesIO()
            tree.write(f)
            header = ("<?xml version='1.0' encoding='UTF-8'?>\n"
                      "<!DOCTYPE RAYSESSION>\n")
            text = header + f.getvalue().decode()
            
            with open(session_file, 'w') as f:
                f.write(text)

        except BaseException as e:
            _logger.error(str(e))
            return ray.Err.CREATE_FAILED
        
        return ray.Err.OK

    def generate_abstract_client_id(self, wanted_id:str) -> str:
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

    def generate_client_id(self, wanted_id="", abstract=False) -> str:
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
            while "%s_%i" % (wanted_id, n) in self.forbidden_ids_set:
                n += 1

            self.forbidden_ids_set.add(wanted_id)
            return "%s_%i" % (wanted_id, n)

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

    def _is_path_in_a_session_dir(self, spath: Path):
        if self.is_nsm_locked() and os.getenv('NSM_URL'):
            return False

        base_path = spath
        
        while base_path.parent != base_path:
            base_path = base_path.parent
            if Path(base_path / 'raysession.xml').is_file():
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
        if TYPE_CHECKING and not isinstance(self, OperatingSession):
            return

        templates_database.rebuild_templates_database(self, base)
