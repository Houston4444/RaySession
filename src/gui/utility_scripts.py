
import os
import shutil
import sys

from PyQt5.QtWidgets import QApplication, QFileDialog
from PyQt5.QtCore import QProcess, QProcessEnvironment

_translate = QApplication.translate

UTIL_SCRIPT_NONE = 0
UTIL_SCRIPT_CONVERT_ARDOUR_TO_SESSION = 1

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



