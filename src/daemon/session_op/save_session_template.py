# Imports from standard library
import os
from typing import TYPE_CHECKING

# third party imports
from qtpy.QtCore import QCoreApplication

# Imports from src/shared
import ray
from osclib import Address
import osc_paths.ray as r

# Local imports
from daemon_tools import highlight_text, NoSessionPath, TemplateRoots

from .session_op import SessionOp

if TYPE_CHECKING:
    from session_operating import OperatingSession


_translate = QCoreApplication.translate


class SaveSessionTemplate(SessionOp):
    def __init__(self, session: 'OperatingSession',
                 template_name: str, net=False):
        super().__init__(session)
        self.template_name = template_name
        self.net = net
        self.routine = [self.copy_session_folder,
                        self.adjust_files]

    def copy_session_folder(self):
        session = self.session
        if session.path is None:
            raise NoSessionPath

        template_root = TemplateRoots.user_sessions

        if self.net:
            template_root = session.root / TemplateRoots.net_session_name

        spath = template_root / self.template_name

        #overwrite existing template
        if spath.is_dir():            
            if not os.access(spath, os.W_OK):
                self.error(
                    ray.Err.GENERAL_ERROR,
                    _translate(
                        "error",
                        "Impossible to save template, unwriteable file !"))
                return

            spath.rmdir()

        if not template_root.exists():
            template_root.mkdir(parents=True)

        # For network sessions,
        # save as template the network session only
        # if there is no other server on this same machine.
        # Else, one could erase template just created by another one.
        # To prevent all confusion,
        # all seen machines are sent to prevent an erase by looping
        # (a network session can contains another network session
        # on the machine where is the master daemon, for example).

        for client in session.clients:
            if (client.is_ray_net
                    and client.ray_net.daemon_url):
                session.send(
                    Address(client.ray_net.daemon_url),
                    r.server.SAVE_SESSION_TEMPLATE,
                    session.short_path_name,
                    self.template_name,
                    client.ray_net.session_root)

        session.set_server_status(ray.ServerStatus.COPY)

        session.send_gui_message(
            _translate('GUIMSG', 'start session copy to template...'))
        
        err = session.file_copier.start_session_copy(session.path, spath)
        if err is not ray.Err.OK:
            self.error(
                err, 
                _translate(
                    'Session Copy',
                    'Failed to start copy for template from %s to %s') % (
                        session.path, spath))
            return
        
        self.next(ray.WaitFor.FILE_COPY)

    def adjust_files(self):
        session = self.session
        if session.file_copier.aborted:
            self.error(ray.Err.ABORT_ORDERED, "Session template aborted")
            return
        
        tp_mode = ray.Template.SESSION_SAVE
        if self.net:
            tp_mode = ray.Template.SESSION_SAVE_NET

        for client in session.clients + session.trashed_clients:
            client.adjust_files_after_copy(self.template_name, tp_mode)

        session.message("Done")
        session.send_gui_message(
            _translate('GUIMSG', "...session saved as template named %s")
            % highlight_text(self.template_name))

        self.reply('Saved as template.')
