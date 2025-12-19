# Imports from standard library
from enum import Enum, auto
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING
import xml.etree.ElementTree as ET

# third party imports
from qtpy.QtCore import QCoreApplication
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

# Imports from src/shared
import osc_paths.ray.gui as rg
import ray
from xml_tools import XmlElement

# Local imports
from client import Client
from daemon_tools import Terminal
import multi_daemon_file

from .session_op import SessionOp

if TYPE_CHECKING:
    from session import Session


_YAML_FILE = 'raysession.yaml'
_XML_FILE = 'raysession.xml'
_NSM_FILE = 'session.nsm'
_YAML_SUB_FILE = 'raysubsession.yaml'
_XML_SUB_FILE = 'raysubsession.xml'

_logger = logging.getLogger(__name__)
_translate = QCoreApplication.translate


class _FileType(Enum):
    NONE = auto()
    YAML = auto()
    XML = auto()
    NSM = auto()


class Preload(SessionOp):
    def __init__(self, session: 'Session',
                 session_name: str, auto_create=True):
        super().__init__(session)
        self.session_name = session_name
        self.auto_create = auto_create
        self.routine = [self.preload]

    def load_error(self, err_loading: ray.Err):
        self.session.message("Load session failed")
        m = _translate('Load Error', "Unknown error")
        match err_loading:
            case ray.Err.CREATE_FAILED:
                m = _translate('Load Error', "Could not create session file!")
            case ray.Err.SESSION_LOCKED:
                m = _translate(
                    'Load Error', "Session is locked by another process!")
            case ray.Err.NO_SUCH_FILE:
                m = _translate(
                    'Load Error', "The named session does not exist.")
            case ray.Err.BAD_PROJECT:
                m = _translate('Load Error', "Could not load session file.")
            case ray.Err.SESSION_IN_SESSION_DIR:
                m = _translate(
                    'Load Error',
                    "Can't create session in a dir containing a session\n"
                    + "for better organization.")

        self.error(err_loading, m)
    
    def preload(self):
        '''load session data in self.future*
        (clients, trashed_clients, session_path, session_name).
        
        This future session can be loaded later and safely in load.Load,
        after take_place.TakePlace.'''
        session = self.session
        session_short_path = Path(self.session_name)
        if session_short_path.is_absolute():
            spath = session_short_path
        else:
            spath = session.root / session_short_path

        if spath == session.path:
            self.load_error(ray.Err.SESSION_LOCKED)
            return

        sess_yaml_file = spath / _YAML_FILE
        sess_xml_file = spath / _XML_FILE
        sess_nsm_file = spath / _NSM_FILE

        if spath.exists():
            # session directory exists
            for sess_file in sess_yaml_file, sess_xml_file, sess_nsm_file:
                if sess_file.exists():
                    break
            else:
                # session directory doesn't contains session file.
                # Check if it contains another session file in a subfolder
                # and in this case, prevent to create this session
                for root, dirs, files in os.walk(spath):
                    #exclude hidden files and dirs
                    files = [f for f in files if not f.startswith('.')]
                    dirs[:] = [d for d in dirs  if not d.startswith('.')]

                    if root == str(spath):
                        continue

                    for file_ in files:
                        if file_ in (_YAML_FILE, _XML_FILE, _NSM_FILE):
                            # dir contains a session inside,
                            # do not try to load it
                            self.load_error(ray.Err.SESSION_IN_SESSION_DIR)
                            return
        else:
            if not self.auto_create:
                self.load_error(ray.Err.NO_SUCH_FILE)
                return
            
            # session directory doesn't exists,
            # create this session.            
            
            if session.is_path_in_a_session_dir(spath):
                # prevent to create a session in a session directory
                # for better user organization
                self.load_error(ray.Err.SESSION_IN_SESSION_DIR)
                return

            try:
                spath.mkdir(parents=True)
            except:
                self.load_error(ray.Err.CREATE_FAILED)
                return

        if not multi_daemon_file.is_free_for_session(spath):
            Terminal.warning(f"Session {spath} is used by another daemon")
            self.load_error(ray.Err.SESSION_LOCKED)
            return

        session.message(f'Attempting to open {spath}')

        # change session file only for raysession launched with NSM_URL env
        # Not sure that this feature is really useful.
        # Any cases, It's important to rename it
        # because we want to prevent session creation in a session folder
        if session.is_nsm_locked() and os.getenv('NSM_URL'):
            sess_yaml_file = spath / _YAML_SUB_FILE
            sess_xml_file = spath / _XML_SUB_FILE

        nsm_contents = ''
        file_type = _FileType.NONE
        yaml = YAML()
        
        if sess_yaml_file.exists():
            file_type = _FileType.YAML
        elif sess_xml_file.exists():
            file_type = _FileType.XML
        elif sess_nsm_file.exists():
            file_type = _FileType.NSM
        
        if file_type is _FileType.NONE:
            yaml_dict = {'app': ray.APP_TITLE.upper(),
                         'version': ray.VERSION}
            
            if session.is_nsm_locked():
                yaml_dict['name'] = spath.name.rpartition('.')[0]
            
            try:
                with open(sess_yaml_file, 'w') as f:
                    yaml.dump(yaml_dict, f)
            except BaseException as e:
                _logger.error(str(e))
                self.load_error(ray.Err.CREATE_FAILED)
                return
            else:
                file_type = _FileType.YAML

        session.no_future()
        sess_name = ""
        client_ids = set[str]()

        if file_type is _FileType.YAML:
            try:
                with open(sess_yaml_file, 'r') as f:
                    sess_dict = yaml.load(f)
            except BaseException as e:
                _logger.error(
                    f'Failed to load {sess_yaml_file} as a yaml file')
                self.load_error(ray.Err.BAD_PROJECT)
                return
            
            if not isinstance(sess_dict, CommentedMap):
                _logger.error(f'{sess_yaml_file} should be a map')
                self.load_error(ray.Err.BAD_PROJECT)
                return
            
            if sess_dict.get('app') != ray.APP_TITLE.upper():
                _logger.error(f'{sess_yaml_file} is not for {ray.APP_TITLE}')
                self.load_error(ray.Err.BAD_PROJECT)
                return
            
            sess_name = sess_dict.get('name', '')
            if sess_dict.get('notes_shown') is True:
                session.future_notes_shown = True
            
            for section in 'clients', 'trashed_clients':
                clients_map = sess_dict.get(section)
                if isinstance(clients_map, CommentedMap):
                    for client_id, client_map in clients_map.items():
                        if not (isinstance(client_id, str)
                                and isinstance(client_map, CommentedMap)):
                            continue
                        
                        client = Client(session)
                        client.read_yaml_properties(client_map)
                        if not client.executable:
                            continue
                        if client.client_id in client_ids:
                            continue
                        client.client_id = client_id
                        
                        if section == 'clients':
                            session.future_clients.append(client)
                        else:
                            session.future_trashed_clients.append(client)
             
            windows_seq = sess_dict.get('windows')
            if isinstance(windows_seq, CommentedSeq):
                session.desktops_memory.read_yaml(windows_seq)
                    
        elif file_type is _FileType.XML:
            try:
                tree = ET.parse(sess_xml_file)
            except BaseException as e:
                _logger.error(str(e))
                self.load_error(ray.Err.BAD_PROJECT)
                return
            
            root = tree.getroot()
            if root.tag != 'RAYSESSION':
                self.load_error(ray.Err.BAD_PROJECT)
                return

            xroot = XmlElement(root)
            sess_name = xroot.string('name')
            
            if xroot.bool('notes_shown'):
                session.future_notes_shown = True
            
            for child in root:
                if child.tag in ('Clients', 'RemovedClients'):
                    for cchild in child:
                        c = XmlElement(cchild)
                        client = Client(session)
                        client.read_xml_properties(c)
                        
                        if not client.executable:
                            continue

                        if client.executable == 'ray-proxy':
                            client.transform_from_proxy_to_hack(
                                spath, sess_name)

                        if client.client_id in client_ids:
                            # prevent double same id
                            continue
                            
                        if child.tag == 'Clients':
                            session.future_clients.append(client)
                        elif child.tag == 'RemovedClients':
                            session.future_trashed_clients.append(client)
                        else:
                            continue
                        
                        client_ids.add(client.client_id)

                elif child.tag == 'Windows':
                    if session.has_server_option(ray.Option.DESKTOPS_MEMORY):
                        session.desktops_memory.read_xml(XmlElement(child))

        elif file_type is _FileType.NSM:
            # prevent to load a locked NSM session
            lock_file = spath / '.lock'
            if lock_file.is_file():
                Terminal.warning(
                    f'Session {self.session_name} is locked '
                    'by another process')
                self.load_error(ray.Err.SESSION_LOCKED)
                return

            try:
                with open(sess_nsm_file, 'r') as f:
                    nsm_contents = f.read()
            except:
                self.load_error(ray.Err.BAD_PROJECT)
                return

            for line in nsm_contents.splitlines():
                elements = line.split(':')
                if len(elements) >= 3:
                    client = Client(session)
                    client.name = elements[0]
                    client.executable = elements[1]
                    client.client_id = elements[2]
                    client.prefix_mode = ray.PrefixMode.CLIENT_NAME
                    client.auto_start = True
                    client.jack_naming = ray.JackNaming.LONG

                    session.future_clients.append(client)

            session.send_gui(rg.session.IS_NSM)

        if not session.is_dummy:
            session.canvas_saver.load_json_session_canvas(spath)

        full_notes_path = spath / ray.NOTES_PATH

        if (full_notes_path.is_file()
                and os.access(full_notes_path, os.R_OK)):
            try:
                with open(full_notes_path) as notes_file:
                    # limit notes characters to 65000 
                    # to prevent OSC message accidents
                    session.future_notes = notes_file.read(65000)
            except BaseException as e:
                _logger.warning(
                    f'Failed to load session notes in {full_notes_path}\n'
                    f'{str(e)}')
                session.future_notes = ''

        session.future_session_path = spath
        session.future_session_name = sess_name
        session.switching_session = bool(session.path is not None)

        self.next()