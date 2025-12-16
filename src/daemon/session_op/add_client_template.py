import logging
from pathlib import Path
from typing import TYPE_CHECKING

from qtpy.QtCore import QCoreApplication
from osclib.bases import OscPack

import ray
import osc_paths.ray.gui as rg

import ardour_templates
from client import Client
from daemon_tools import NoSessionPath, RS, highlight_text

from .session_op import SessionOp

if TYPE_CHECKING:
    from session_operating import OperatingSession


_logger = logging.getLogger(__name__)
_translate = QCoreApplication.translate


class AddClientTemplate(SessionOp):
    def __init__(
            self, session: 'OperatingSession', template_name: str,
            factory: bool, auto_start=True, unique_id='',
            osp: OscPack | None =None):
        super().__init__(session, osp)
        self.template_name = template_name
        self.factory = factory
        self.auto_start = auto_start
        self.unique_id = unique_id
        self.client: Client | None = None
        
        self.routine = [self.copy_template, self.adjust_files]

    def copy_template(self):
        session = self.session
        if session.path is None:
            raise NoSessionPath
        
        base = 'factory' if self.factory else 'user'
        templates_database = session.get_client_templates_database(base)

        # if this client template is not present in the database
        # first, rebuild the database
        if self.template_name not in [
                t.template_name for t in templates_database]:
            session._rebuild_templates_database(base)

        for t in templates_database:
            if t.template_name == self.template_name:
                break
        else:
            # no template found with that name
            for favorite in RS.favorites:
                if (favorite.name == self.template_name
                        and favorite.factory is self.factory):
                    session.send_gui(
                        rg.favorites.REMOVED,
                        favorite.name, int(favorite.factory))
                    RS.favorites.remove(favorite)
                    break

            self.error(
                ray.Err.NO_SUCH_FILE,
                _translate('GUIMSG', "%s is not an existing template !")
                    % highlight_text(self.template_name))
            return
    
        file_paths = list[Path]()
        template_path = t.templates_root / self.template_name

        if t.templates_root.name and template_path.is_dir():
            for file_path in template_path.iterdir():
                file_paths.append(file_path)

        template_client = t.template_client
        client = Client(session)
        client.protocol = template_client.protocol
        client.ray_hack = template_client.ray_hack
        client.ray_net = template_client.ray_net
        client.template_origin = self.template_name
        if t.display_name:
            client.template_origin = t.display_name
        client.eat_attributes(template_client)
        client.auto_start = self.auto_start

        if self.unique_id:
            client.client_id = self.unique_id
            client.label = self.unique_id.replace('_', ' ')
            client.jack_naming = ray.JackNaming.LONG
        else:
            client.client_id = session.generate_client_id(
                template_client.client_id)
        
        # If It is an Ardour template
        if t.template_name.startswith('/ardour_tp/'):
            ard_tp_name = t.template_name.rpartition('/')[2]
            ard_tp_path = ardour_templates.get_template_path_from_name(
                ard_tp_name, client.executable)
            if ard_tp_path is None:
                self.error(ray.Err.BAD_PROJECT,
                            'Failed to copy Ardour template')
                return
            
            ard_tp_copyed = ardour_templates.copy_template_to_session(
                ard_tp_path,
                session.path,
                client.prefix,
                client.client_id
            )
            if not ard_tp_copyed:
                self.error(ray.Err.BAD_PROJECT,
                            'Failed to copy Ardour template')
                return
        
        if not session._add_client(client):
            self.error(ray.Err.NOT_NOW,
                        'Session does not accept any new client now')
            return
        
        if file_paths:
            client.set_status(ray.ClientStatus.PRECOPY)
            err = session.file_copier.start_client_copy(
                client.client_id, file_paths, session.path,
                src_is_factory=self.factory)
            if err is not ray.Err.OK:
                self.error(
                    err,
                    _translate('error',
                                'Failed to copy files for new client '
                                'from template'))
                return
        
        self.client = client
        self.next(ray.WaitFor.FILE_COPY)

    def adjust_files(self):
        session = self.session
        client = self.client
        if client is None:
            raise AttributeError
        
        if session.file_copier.aborted:
            session._remove_client(client)
            self.error(ray.Err.COPY_ABORTED,
                       _translate('GUIMSG', 'Copy has been aborted !'))
            return
        
        client.adjust_files_after_copy(session.name, ray.Template.CLIENT_LOAD)

        if client.auto_start:
            client.start()
        else:
            client.set_status(ray.ClientStatus.STOPPED)

        self.reply(client.client_id)
