
import os
import shutil
import sys

from PyQt5.QtWidgets import (QApplication, QFileDialog, QMessageBox,
                             QPushButton, QDialogButtonBox)
from PyQt5.QtGui import QIcon
from PyQt5.QtCore import QProcess, QProcessEnvironment, Qt


import ray
from gui_tools import CommandLineArgs
from child_dialogs import ChildDialog, OpenSessionDialog
import ui.hydro_rh_nsm
import ui.ray_to_nsm

_translate = QApplication.translate



UTIL_SCRIPT_NONE = 0
UTIL_SCRIPT_CONVERT_ARDOUR_TO_SESSION = 1

class HydrogenRhNsmDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui.hydro_rh_nsm.Ui_Dialog()
        self.ui.setupUi(self)
        self.ui.checkBoxCurrentSession.stateChanged.connect(
            self._current_session_check)
        self._check_boxes = (self.ui.checkBoxAllSessions,
                             self.ui.checkBoxClientTemplates,
                             self.ui.checkBoxSessionTemplates)

        for check_box in self._check_boxes:
            check_box.stateChanged.connect(self._one_state_changed)

        if self.session.server_status != ray.ServerStatus.READY:
            self.ui.checkBoxCurrentSession.setEnabled(False)

    def _current_session_check(self, state:bool):
        for check_box in self._check_boxes:
            check_box.setEnabled(not state)

    def _one_state_changed(self):
        for check_box in self._check_boxes:
            if check_box.isChecked():
                break
        else:
            for check_box in self._check_boxes:
                check_box.setChecked(True)

    def get_check_arguments(self)->list:
        args = []
        if self.ui.checkBoxCurrentSession.isChecked():
            return args

        if self.ui.checkBoxAllSessions.isChecked():
            args.append('sessions')
        if self.ui.checkBoxClientTemplates.isChecked():
            args.append('client_templates')
        if self.ui.checkBoxSessionTemplates.isChecked():
            args.append('session_templates')
        return args

    def rename_for_other_app(self, name:str):
        self.ui.label.setText(self.ui.label.text().replace('Hydrogen', name))


class RayToNsmDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui.ray_to_nsm.Ui_Dialog()
        self.ui.setupUi(self)
        
        self.choose_current_session = False
        #self.choose_session
        choose_button = self.ui.buttonBox.addButton(
            _translate('utilities', 'Choose a session'),
            QDialogButtonBox.AcceptRole)
        choose_button.setIcon(QIcon.fromTheme('folder-open'))

        this_session_button = self.ui.buttonBox.addButton(
            _translate('utilities', 'Convert the current session'),
            QDialogButtonBox.AcceptRole)
        
        if not self.session.path:
            this_session_button.setVisible(False)
            
        this_session_button.clicked.connect(
            self._set_on_choose_current_session)
    
    def _set_on_choose_current_session(self):
        self.choose_current_session = True
    
    def get_check_arguments(self)->list:
        if self.ui.checkBoxJackPatch.isChecked():
            return ['--replace-jackpatch']
        
        return ['']


class UtilityScriptLauncher:
    def __init__(self, main_win, session):
        self.daemon_manager = session.daemon_manager
        self.main_win = main_win
        self._process = QProcess()

    def _which_terminal(self, title='')->list:
        """ returns the most appropriate terminal executable
            with its arguments """
        terminals = ['gnome-terminal', 'mate-terminal', 'xfce4-terminal',
                     'xterm', 'konsole', 'lxterminal', 'rxvt']
        current_desktop = os.getenv('XDG_CURRENT_DESKTOP')
        terminal = ''

        # make prior most appropriate terminal
        if current_desktop == 'GNOME':
            pass

        elif current_desktop == 'KDE':
            terminals.remove('konsole')
            terminals.insert(0, 'konsole')

        elif current_desktop == 'MATE':
            terminals.remove('mate-terminal')
            terminals.insert(0, 'mate-terminal')

        elif current_desktop == 'XFCE':
            terminals.remove('xfce4-terminal')
            terminals.insert(0, 'xfce4-terminal')
            terminals.insert(0, 'xfce-terminal')

        elif current_desktop == 'LXDE':
            terminals.remove('lxterminal')
            terminals.insert(0, 'lxterminal')

        # search executable for terminals
        for term in terminals:
            if shutil.which(term):
                terminal = term
                break
        else:
            return []

        if terminal == 'gnome-terminal':
            return [terminal, '--hide-menubar', '--']

        if terminal == 'konsole':
            if title:
                return [terminal, '--hide-tabbar', '--hide-menubar', '-p',
                        "tabtitle=%s" % title, '-e']

            return [terminal, '--hide-tabbar', '--hide-menubar', '-e']

        if terminal == 'mate-terminal':
            if title:
                return [terminal, '--hide-menubar', '--title', title, '--']

            return [terminal, '--hide-menubar', '--']

        if terminal == 'xfce4-terminal':
            if title:
                return [terminal, '--hide-menubar', '--hide-toolbar',
                        '-T', title, '-e']

            return [terminal, '--hide-menubar', '--hide-toolbar', '-e']

        return [terminal, '-e']

    def _get_scripts_path(self)->str:
        code_root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
        return os.path.join(code_root, 'utility-scripts')

    def _start_process(self, script_name, terminal_title, *args):
        if not self.daemon_manager.is_local or CommandLineArgs.under_nsm:
            # utility scripts are not available if daemon is not
            # on the same machine, or if current session is a subsession
            return

        if self._process.state():
            QMessageBox.critical(
                self.main_win,
                _translate('utilities', 'Other script running'),
                _translate('utilities',
                           "An utility script is already running,\n"
                           "please close its terminal and start again !"))
            return

        process_env = QProcessEnvironment.systemEnvironment()
        process_env.insert(
            'RAY_CONTROL_PORT', str(self.daemon_manager.get_port()))
        self._process.setProcessEnvironment(process_env)

        terminal_args = self._which_terminal(terminal_title)
        if not terminal_args:
            return

        full_script_path = os.path.join(self._get_scripts_path(), script_name)
        terminal = terminal_args.pop(0)
        self._process.setProgram(terminal)

        self._process.setArguments(
            terminal_args
            + ["utility_script_keeper.sh", full_script_path]
            + list(args))
        self._process.start()

    def convert_ardour_to_session(self):
        script_name = 'ardour_from_external_to_session.sh'
        terminal_title = _translate('utilities', 'Convert Ardour session to Ray')

        ardour_session , filter = QFileDialog.getOpenFileName(
            self.main_win,
            _translate('utilities', "Choose an Ardour session to convert..."),
            os.getenv('HOME'),
            _translate('utilities', "Ardour sessions (*.ardour)"))

        if not ardour_session:
            return

        executable = "ardour"
        if not shutil.which(executable):
            for i in range(9, 5, -1):
                if shutil.which("ardour%i" % i):
                    executable = "ardour%i" % i
                    break
                if shutil.which("Ardour%i" % i):
                    executable = "Ardour%i" % i
                    break

        args = ["--executable", executable, ardour_session]

        self._start_process(script_name, terminal_title, *args)

    def convert_ray_hack_to_nsm_hydrogen(self):
        script_name = 'all_ray_hack_to_nsm_hydrogen.sh'
        terminal_title = _translate('utilities', 'Hydrogen Ray-Hack->NSM')

        dialog = HydrogenRhNsmDialog(self.main_win)
        dialog.exec()
        if not dialog.result():
            return

        args = dialog.get_check_arguments()
        self._start_process(script_name, terminal_title, *args)

    def convert_ray_hack_to_nsm_jack_mixer(self):
        script_name = 'all_ray_hack_to_nsm_jack_mixer.sh'
        terminal_title = _translate('utilities', 'Jack Mixer Ray-Hack->NSM')

        dialog = HydrogenRhNsmDialog(self.main_win)
        dialog.rename_for_other_app('Jack Mixer')
        dialog.exec()
        if not dialog.result():
            return

        args = dialog.get_check_arguments()
        self._start_process(script_name, terminal_title, *args)
        
    def convert_to_nsm_file_format(self):
        script_name = 'session_ray_to_nsm.sh'
        terminal_title = _translate('utilities', 'Session to NSM file format')
        
        dialog = RayToNsmDialog(self.main_win)

        dialog.exec()
        if not dialog.result():
            return

        args = dialog.get_check_arguments()
        
        if not dialog.choose_current_session:
            open_dialog = OpenSessionDialog(self.main_win)
            open_dialog.setWindowTitle(
                _translate('utilities', 'Choose a session to convert to NSM'))
            open_dialog.exec()
            if not open_dialog.result():
                return

            session_path = open_dialog.get_selected_session()
            print('shoulbi', session_path)
            args.append(session_path)

        self._start_process(script_name, terminal_title, *args)
