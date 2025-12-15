import logging
import os
from pathlib import Path
import shutil
from typing import TYPE_CHECKING

from qtpy.QtCore import QCoreApplication
from osclib.bases import OscPack

import ray

from client import Client
from daemon_tools import NoSessionPath

from .session_op import SessionOp

if TYPE_CHECKING:
    from session_operating import OperatingSession


_logger = logging.getLogger(__name__)
_translate = QCoreApplication.translate


class AddOtherSessionClient(SessionOp):
    def __init__(self, session: 'OperatingSession', client: Client,
                 osp: OscPack | None =None):
        super().__init__(session, osp)
        self.client = client
        self.new_client: Client | None = None
        self.tmp_work_dir: Path | None = None
        self.routine = [self.copy_other_client,
                        self.rename_files]

    def copy_other_client(self):
        session = self.session
        client = self.client

        # eat attributes but keep client_id
        new_client = Client(session)
        new_client.client_id = session.generate_client_id(
            Client.short_client_id(client.client_id))
        
        ok = session._add_client(new_client)
        if not ok:
            self.error(ray.Err.NOT_NOW, 'session is busy')
            return

        if session.path is None:
            raise NoSessionPath

        new_client.eat_attributes(client)
        new_client.send_gui_client_properties()
        
        tmp_basedir = ".tmp_ray_workdir"
        
        while Path(session.path / tmp_basedir).exists():
            tmp_basedir += 'X'
        tmp_work_dir = session.path / tmp_basedir
        
        try:
            tmp_work_dir.mkdir(parents=True)
        except:
            session._remove_client(new_client)
            self.error(
                ray.Err.CREATE_FAILED,
                f"impossible to make a tmp workdir at {tmp_work_dir}. Abort.")
            return

        new_client.set_status(ray.ClientStatus.PRECOPY)
        err = session.file_copier.start_client_copy(
            new_client.client_id, client.project_files, tmp_work_dir)
        if err is not ray.Err.OK:
            self.error(
                err,
                _translate(
                    'error', "Impossible to copy client files"))
            return
        
        self.new_client = new_client
        self.tmp_work_dir = tmp_work_dir
        
        self.next(-1, ray.WaitFor.FILE_COPY)

    def rename_files(
            self):
        session = self.session
        client = self.client
        if self.new_client is None or self.tmp_work_dir is None:
            raise AttributeError
         
        if session.file_copier.aborted:
            shutil.rmtree(self.tmp_work_dir)
            session._remove_client(self.new_client)
            self.error(ray.Err.COPY_ABORTED, 'Copy was aborted by user')
            return
         
        self.new_client._rename_files(
            self.tmp_work_dir, client.session.name, session.name,
            client.prefix, self.new_client.prefix,
            client.client_id, self.new_client.client_id,
            client.links_dirname, self.new_client.links_dirname)

        has_move_errors = False

        for file_path in os.listdir(self.tmp_work_dir):
            try:
                os.rename(f'{self.tmp_work_dir}/{file_path}',
                          f'{session.path}/{file_path}')
            except:
                session.message(
                    _translate(
                        'client',
                        'failed to move %s/%s to %s/%s, sorry.')
                        % (self.tmp_work_dir, file_path,
                           session.path, file_path))
                has_move_errors = True
        
        if not has_move_errors:
            try:
                shutil.rmtree(self.tmp_work_dir)
            except:
                session.message(
                    f'failed to remove temp client directory '
                    f'{self.tmp_work_dir}. sorry.')

        self.reply('Client copied from another session')

        if self.new_client.auto_start:
            self.new_client.start()
        else:
            self.new_client.set_status(ray.ClientStatus.STOPPED)
            
        session.steps_osp = None
