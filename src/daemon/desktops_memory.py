#!/usr/bin/python3 -u

# Imports from standard library
import os
import subprocess
from typing import TYPE_CHECKING
import warnings

# third party imports
from qtpy.QtCore import QProcess
from ruamel.yaml.comments import CommentedSeq, CommentedMap

# Imports from src/shared
from xml_tools import XmlElement

# Local imports
from daemon_tools import is_pid_child_of

if TYPE_CHECKING:
    from session import Session


def move_win(win_id, desktop_from, desktop_to):
    if desktop_from == desktop_to:
        return

    if desktop_to == -1:
        subprocess.run(['wmctrl', 'i', '-r', win_id, '-b', 'add,sticky'])
        return

    if desktop_from == -1:
        subprocess.run(['wmctrl', 'i', '-r', win_id, '-b', 'remove,sticky'])

    subprocess.run(['wmctrl', '-i', '-r', win_id, '-t', str(desktop_to)])


class WindowProperties:
    id = ""
    desktop = 0
    pid = 0
    wclass = ""
    name = ""


class DesktopsMemory:
    def __init__(self, session: 'Session'):
        self.session = session

        self._active_window_list = list[WindowProperties]()
        self._daemon_pids = list[int]()
        self._non_daemon_pids = list[int]()

        self.saved_windows = list[WindowProperties]()

    def _is_child_of_daemon(self, pid: int) -> bool:
        if pid in self._daemon_pids:
            return True

        if pid in self._non_daemon_pids:
            return False

        daemon_pid = os.getpid()

        if pid < daemon_pid:
            self._non_daemon_pids.append(pid)
            return False

        if is_pid_child_of(pid, daemon_pid):
            self._daemon_pids.append(pid)
            return True

        self._non_daemon_pids.append(pid)
        return False

    def _is_name_in_session(self, name: str) -> bool:
        for client in self.session.clients:
            if client.name == name and client.nsm_active:
                return True

        return False

    def set_active_window_list(self):
        try:
            wmctrl_all = subprocess.check_output(['wmctrl', '-l',
                                                  '-p', '-x']).decode()
        except:
            warnings.warn('unable to use wmctrl')
            return

        self._active_window_list.clear()

        all_lines = wmctrl_all.split('\n')

        for line in all_lines:
            if not line:
                continue

            properties = [el for el in line.split(' ') if el]

            if (len(properties) >= 6
                    and properties[1].lstrip('-').isdigit()
                    and properties[2].isdigit()):
                wid = properties[0]
                desktop = int(properties[1])
                pid = int(properties[2])
                wclass = properties[3]

                ignore_pid = False

                # fltk based apps don't send their pids to wmctrl,
                # so if win seems to be one of these apps
                # and app is running in the session,
                # assume that this window is child of this ray-daemon
                if pid == 0 and '.' in wclass:
                    class_name = wclass.split('.')[0]

                    exceptions = {'luppp'        : 'Luppp',
                                  'Non-Mixer'    : 'Non-Mixer',
                                  'Non-Sequencer': 'Non-Sequencer',
                                  'Non-Timeline' : 'Non-Timeline'}

                    if class_name in exceptions:
                        if self._is_name_in_session(exceptions[class_name]):
                            ignore_pid = True

                if not (ignore_pid or self._is_child_of_daemon(pid)):
                    continue

                name = ""
                for prop in properties[5:]:
                    name += prop
                    name += " "
                name = name[:-1] #remove last space

                awin = WindowProperties()
                awin.id = wid
                awin.pid = pid
                awin.desktop = desktop
                awin.wclass = wclass
                awin.name = name

                self._active_window_list.append(awin)

    def save(self):
        self.set_active_window_list()
        if not self._active_window_list:
            return

        for awin in self._active_window_list:
            for win in self.saved_windows:
                if win.wclass == awin.wclass and win.name == awin.name:
                    win.desktop = awin.desktop
                    break
            else:
                win = WindowProperties()
                win.id = awin.id
                win.desktop = awin.desktop
                win.wclass = awin.wclass
                win.name = awin.name

                self.saved_windows.append(win)

    def replace(self):
        if not self.saved_windows:
            return

        self.set_active_window_list()
        if not self._active_window_list:
            return

        for awin in self._active_window_list:
            for win in self.saved_windows:
                if win.wclass == awin.wclass and win.name == awin.name:
                    win.id = awin.id
                    move_win(awin.id, awin.desktop, win.desktop)
                    break

                elif win.wclass == awin.wclass:
                    if self.session.name:
                        win_name_sps = win.name.split(self.session.name, 1)

                        if (len(win_name_sps) == 2
                                and awin.name.startswith(win_name_sps[0])
                                and awin.name.endswith(win_name_sps[1])):
                            move_win(awin.id, awin.desktop, win.desktop)
                            break
            
    def read_xml(self, xml_element: XmlElement):
        self.saved_windows.clear()

        for w in xml_element.iter():
            if w.el.tag != 'window':
                continue
            
            win = WindowProperties()
            win.wclass = w.string('class')
            win.name = w.string('name')
            desktop = w.string('desktop')
            if desktop.lstrip('-').isdigit():
                win.desktop = int(desktop)
            
            self.saved_windows.append(win)

    def read_yaml(self, seq: CommentedSeq):
        self.saved_windows.clear()
        
        for w in seq:
            if not isinstance(w, CommentedMap):
                continue
            
            win = WindowProperties()
            win.wclass = str(w.get('class', ''))
            win.name = str(w.get('name', ''))
            try:
                desktop = int(w.get('desktop', 0))
            except:
                desktop = 0 
            win.desktop = desktop
                
            self.saved_windows.append(win)

    def has_window(self, pid: int) -> bool:
        if not self._active_window_list:
            # here fo ray_hack check window
            # if window manager doesn't supports wmctrl
            # lie saying there is a window
            return True

        for awin in self._active_window_list:
            if is_pid_child_of(awin.pid, pid):
                return True
        return False

    def find_and_close(self, pid: int):
        for awin in self._active_window_list:
            if is_pid_child_of(awin.pid, pid):
                QProcess.startDetached('wmctrl', ['-i', '-c', awin.id])
