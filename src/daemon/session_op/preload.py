from io import TextIOWrapper
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING
import xml.etree.ElementTree as ET

from qtpy.QtCore import QCoreApplication

import osc_paths.ray.gui as rg
import ray
from xml_tools import XmlElement

from client import Client
from daemon_tools import Terminal
import multi_daemon_file

from .session_op import SessionOp

if TYPE_CHECKING:
    from session_operating import OperatingSession


_logger = logging.getLogger(__name__)
_translate = QCoreApplication.translate


class Preload(SessionOp):
    def __init__(self, session: 'OperatingSession',
                 session_name: str, auto_create=True):
        super().__init__(session)
        self.session_name = session_name
        self.auto_create = auto_create
        self.routine = [self.preload]

    def preload(self):
        '''load session data in self.future*
        (clients, trashed_clients, session_path, session_name)'''
        session = self.session
        session_short_path = Path(self.session_name)
        if session_short_path.is_absolute():
            spath = session_short_path
        else:
            spath = session.root / session_short_path

        if spath == session.path:
            session.load_error(ray.Err.SESSION_LOCKED)
            return

        session_ray_file = spath / 'raysession.xml'
        session_nsm_file = spath / 'session.nsm'

        if spath.exists():
            # session directory exists
            for sess_file in session_ray_file, session_nsm_file:
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
                        if file_ in ('raysession.xml', 'session.nsm'):
                            # dir contains a session inside,
                            # do not try to load it
                            session.load_error(ray.Err.SESSION_IN_SESSION_DIR)
                            return
        else:
            if not self.auto_create:
                session.load_error(ray.Err.NO_SUCH_FILE)
                return
            
            # session directory doesn't exists,
            # create this session.            
            
            if session._is_path_in_a_session_dir(spath):
                # prevent to create a session in a session directory
                # for better user organization
                session.load_error(ray.Err.SESSION_IN_SESSION_DIR)
                return

            try:
                spath.mkdir(parents=True)
            except:
                session.load_error(ray.Err.CREATE_FAILED)
                return

        if not multi_daemon_file.is_free_for_session(spath):
            Terminal.warning(f"Session {spath} is used by another daemon")
            session.load_error(ray.Err.SESSION_LOCKED)
            return

        session.message("Attempting to open %s" % spath)

        # change session file only for raysession launched with NSM_URL env
        # Not sure that this feature is really useful.
        # Any cases, It's important to rename it
        # because we want to prevent session creation in a session folder
        if session.is_nsm_locked() and os.getenv('NSM_URL'):
            session_ray_file = spath / 'raysubsession.xml'

        nsm_file: TextIOWrapper | None = None
        is_ray_file = True
        
        try:
            tree = ET.parse(session_ray_file)
        except BaseException as e:
            _logger.info(str(e))
            is_ray_file = False

        if not is_ray_file:
            try:
                nsm_file = open(session_nsm_file, 'r')
            except BaseException as e:
                _logger.info(str(e))

                root = ET.Element('RAYSESSION')
                root.attrib['VERSION'] = ray.VERSION
                if session.is_nsm_locked():
                    root.attrib['name'] = spath.name.rpartition('.')[0]
                    
                tree = ET.ElementTree(root)

                try:
                    tree.write(session_ray_file)                    
                except BaseException as e:
                    _logger.error(str(e))
                    session.load_error(ray.Err.CREATE_FAILED)
                    return
                else:
                    is_ray_file = True

        session._no_future()
        sess_name = ""

        if is_ray_file:
            try:
                tree = ET.parse(session_ray_file)
            except BaseException as e:
                _logger.error(str(e))
                session.load_error(ray.Err.BAD_PROJECT)
                return
            
            root = tree.getroot()
            if root.tag != 'RAYSESSION':
                session.load_error(ray.Err.BAD_PROJECT)
                return

            xroot = XmlElement(root)
            sess_name = xroot.string('name')
            
            if xroot.bool('notes_shown'):
                session.future_notes_shown = True

            client_ids = set[str]()
            
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

        else:
            # prevent to load a locked NSM session
            lock_file = spath / '.lock'
            if lock_file.is_file():
                Terminal.warning("Session %s is locked by another process")
                session.load_error(ray.Err.SESSION_LOCKED)
                return

            if nsm_file is not None:
                for line in nsm_file.read().splitlines():
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

                nsm_file.close()
            session.send_gui(rg.session.IS_NSM)

        if not session.is_dummy:
            session.canvas_saver.load_json_session_canvas(spath)

        full_notes_path = spath / ray.NOTES_PATH

        if (full_notes_path.is_file()
                and os.access(full_notes_path, os.R_OK)): 
            notes_file = open(full_notes_path)
            # limit notes characters to 65000 to prevent OSC message accidents
            session.future_notes = notes_file.read(65000)
            notes_file.close()

        session.future_session_path = spath
        session.future_session_name = sess_name
        session.switching_session = bool(session.path is not None)

        session.next_function()
