# Imports from standard library
from typing import TYPE_CHECKING

# third party imports
from qtpy.QtCore import QCoreApplication

# Imports from src/shared
import ray

# Local imports
from daemon_tools import TemplateRoots

from .session_op import SessionOp

if TYPE_CHECKING:
    from session import Session


_translate = QCoreApplication.translate


class PrepareTemplate(SessionOp):
    def __init__(self, session: 'Session',
                 new_session_name: str, template_name: str, net=False):
        super().__init__(session)
        self.new_session_name = new_session_name
        self.template_name = template_name
        self.net = net
        self.routine = [self.copy_template, self.adjust_files]

    def copy_template(self):
        session = self.session
        template_root = TemplateRoots.user_sessions
        if self.net:
            template_root = session.root / TemplateRoots.net_session_name

        template_path = template_root / self.template_name
        is_factory = self.template_name.startswith('///')

        template_name = self.template_name
        if is_factory:
            template_name = self.template_name.replace('///', '')
            template_path = TemplateRoots.factory_sessions / template_name

        if not template_path.is_dir():
            self.minor_error(
                ray.Err.GENERAL_ERROR,
                _translate("error", "No template named %s")
                    % template_name)
            session.next_session_op()
            return

        spath = session.root / self.new_session_name

        if spath.exists():
            self.error(
                ray.Err.CREATE_FAILED,
                _translate("error", "Folder\n%s\nalready exists") % spath)
            return

        if session._is_path_in_a_session_dir(spath):
            self.error(
                ray.Err.SESSION_IN_SESSION_DIR,
                _translate(
                    "error",
                    "Can't create session in a dir containing a session\n"
                    "for better organization."))
            return

        if session.path is None:
            session.set_server_status(ray.ServerStatus.PRECOPY)
        else:
            session.set_server_status(ray.ServerStatus.COPY)

        session.send_gui_message(
            _translate('GUIMSG',
                       'start copy from template to session folder'))

        err = session.file_copier.start_session_copy(
            template_path, spath, src_is_factory=True)
        if err is not ray.Err.OK:
            self.error(
                err,
                _translate(
                    'error',
                    "Failed to copy session dir %s from template dir %s")
                        % (spath, template_path))
            return
        
        self.next(ray.WaitFor.FILE_COPY)

    def adjust_files(self):
        session = self.session
        if session.file_copier.aborted:
            self.error(ray.Err.ABORT_ORDERED, "Prepare template aborted")
            return
        
        err, err_msg = session.adjust_files_after_copy(
            self.new_session_name, ray.Template.SESSION_LOAD)
        
        if err is not ray.Err.OK:
            self.error(err, err_msg)
            return
        self.next()

        