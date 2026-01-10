
# Imports from standard library
import os
import logging
from pathlib import Path
from typing import TYPE_CHECKING

# third party imports
from qtpy.QtWidgets import QDialog, QMessageBox, QFileDialog

# Imports from src/shared
import ray
import osc_paths.ray as r

# Local imports
from gui_server_thread import GuiServerThread
from gui_tools import _translate, CommandLineArgs, RS

if TYPE_CHECKING:
    from main_window import MainWindow


_logger = logging.getLogger(__name__)

class ChildDialog(QDialog):
    def __init__(self, parent: 'MainWindow'):
        QDialog.__init__(self, parent)
        self.session = parent.session
        self.signaler = self.session.signaler
        self.daemon_manager = self.session.daemon_manager

        self.signaler.server_status_changed.connect(
            self._server_status_changed)
        self.signaler.server_copying.connect(self._server_copying)

        self._root_folder_file_dialog: QFileDialog | None = None
        self._root_folder_message_box: QMessageBox | None = None

        self.server_copying = parent.server_copying

    @classmethod
    def to_daemon(cls, *args):
        server = GuiServerThread.instance()
        if server is not None:
            server.to_daemon(*args)
        else:
            _logger.error(f'No GUI OSC Server, can not send {args}.')

    def _server_status_changed(self, server_status: ray.ServerStatus):
        ...

    def _server_copying(self, copying: bool):
        self.server_copying = copying
        self._server_status_changed(self.session.server_status)

    def _change_root_folder(self):
        # construct this here only because it can be quite long
        if self._root_folder_file_dialog is None:
            self._root_folder_file_dialog = QFileDialog(
                self,
                _translate("root_folder_dialogs",
                        "Choose root folder for sessions"),
                CommandLineArgs.session_root)
            self._root_folder_file_dialog.setFileMode(
                QFileDialog.FileMode.Directory)
            self._root_folder_file_dialog.setOption(
                QFileDialog.Option.ShowDirsOnly)
        else:
            self._root_folder_file_dialog.setDirectory(
                CommandLineArgs.session_root)

        self._root_folder_file_dialog.exec()
        if not self._root_folder_file_dialog.result():
            return

        selected_files = self._root_folder_file_dialog.selectedFiles()
        if not selected_files:
            return

        root_folder = Path(selected_files[0])

        # Security, kde dialogs sends $HOME if user type a folder path
        # that doesn't already exists.
        if root_folder == Path.home():
            return

        self._root_folder_message_box = QMessageBox(
            QMessageBox.Icon.Critical,
            _translate(
                'root_folder_dialogs',
                "<p>You have no permissions for %s,"
                "<br>choose another directory !</p>")
                    % root_folder,
            '', QMessageBox.StandardButton.NoButton, self)

        if not root_folder.exists():
            try:
                root_folder.mkdir(parents=True)
            except:
                self._root_folder_message_box.exec()
                self._root_folder_message_box = None
                return

        if not os.access(root_folder, os.W_OK):
            self._root_folder_message_box.exec()
            self._root_folder_message_box = None
            return

        RS.settings.setValue('default_session_root', root_folder)
        self.to_daemon(r.server.CHANGE_ROOT, root_folder)

    def parent(self) -> 'MainWindow':
        return super().parent() # type:ignore

    def leaveEvent(self, event):
        parent = self.parent()
        
        if parent is not None and self.isActiveWindow():
            parent.mouse_is_inside = False
        super().leaveEvent(event)

    def enterEvent(self, event):
        parent = self.parent()
        if parent is not None:
            parent.mouse_is_inside = True
        super().enterEvent(event)
