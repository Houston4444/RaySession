#!/usr/bin/python3 -u

import os
import subprocess
import sys

from PyQt5.QtCore import QProcess

import ray


class WindowProperties(object):
    id      = ""
    desktop = 0
    pid     = 0
    wclass  = ""
    name    = ""

def moveWin(win_id, desktop_from, desktop_to):
    if desktop_from == desktop_to:
        return
    
    if desktop_to == -1:
        subprocess.run(['wmctrl', 'i', '-r', win_id, '-b', 'add,sticky'])
        return
    
    if desktop_from == -1:
        subprocess.run(['wmctrl', 'i', '-r', win_id, '-b', 'remove,sticky'])
        
    subprocess.run(['wmctrl', '-i', '-r', win_id, '-t', str(desktop_to)])
    
class DesktopsMemory(object):
    def __init__(self, session):
        self.session = session
        self.saved_windows      = []
        self.active_window_list = []
        self.daemon_pids     = []
        self.non_daemon_pids = []
    
    def isChildOfDaemon(self, pid):
        if pid in self.daemon_pids:
            return True
        
        if pid in self.non_daemon_pids:
            return False
        
        daemon_pid = os.getpid()
        
        if pid < daemon_pid:
            self.non_daemon_pids.append(pid)
            return False
        
        ppid = pid
        
        if ray.isPidChildOf(pid, daemon_pid):
            self.daemon_pids.append(pid)
            return True
        
        #while ppid > daemon_pid and ppid > 1:
            #try:
                #ppid = int(subprocess.check_output(['ps', '-o', 'ppid=',
                                                    #'-p', str(ppid)]))
            #except:
                #self.non_daemon_pids.append(pid)
                #return False
            
        #if ppid == daemon_pid:
            #self.daemon_pids.append(pid)
            #return True
        
        self.non_daemon_pids.append(pid)
        return False
        
    def isNameInSession(self, name):
        for client in self.session.clients:
            if client.name == name and client.active:
                return True
                
        return False
        
    def setActiveWindowList(self):
        try:
            wmctrl_all = subprocess.check_output(['wmctrl', '-l',
                                                  '-p', '-x']).decode()
        except:
            sys.stderr.write('unable to use wmctrl')
            return
        
        self.active_window_list.clear()
        
        all_lines = wmctrl_all.split('\n')
        
        for line in all_lines:
            if not line:
                continue
            
            line_sep = line.split(' ')
            properties = []
            for el in line_sep:
                if el:
                    properties.append(el)
                    
            if (len(properties) >= 6
                    and properties[1].lstrip('-').isdigit()
                    and properties[2].isdigit()):
                wid     = properties[0]
                desktop = int(properties[1])
                pid     = int(properties[2])
                wclass  = properties[3]
                
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
                        if self.isNameInSession(exceptions[class_name]):
                            ignore_pid = True
                
                if not (ignore_pid or self.isChildOfDaemon(pid)):
                    continue
                
                name = ""
                for prop in properties[5:]:
                    name+=prop
                    name+=" "
                name = name[:-1] #remove last space
                
                awin = WindowProperties()
                awin.id      = wid
                awin.pid     = pid
                awin.desktop = desktop
                awin.wclass  = wclass
                awin.name    = name
                
                self.active_window_list.append(awin)
    
    def save(self):
        self.setActiveWindowList()
        if not self.active_window_list:
            return
        
        for awin in self.active_window_list:
            for win in self.saved_windows:
                if win.wclass == awin.wclass and win.name == awin.name:
                    win.desktop = awin.desktop
                    break
            else:
                win = WindowProperties()
                win.id      = awin.id
                win.desktop = awin.desktop
                win.wclass  = awin.wclass
                win.name    = awin.name
                
                self.saved_windows.append(win)
        
    def replace(self):
        if not self.saved_windows:
            return
        
        self.setActiveWindowList()
        if not self.active_window_list:
            return
        
        for awin in self.active_window_list:
            for win in self.saved_windows:
                if win.wclass == awin.wclass and win.name == awin.name:
                    win.id = awin.id
                    moveWin(awin.id, awin.desktop, win.desktop)
                    break
                    
                elif win.wclass == awin.wclass:
                    if self.session.name:
                        win_name_sps = win.name.split(self.session.name, 1)
                        
                        if (len(win_name_sps) == 2
                                and awin.name.startswith(win_name_sps[0])
                                and awin.name.endswith(win_name_sps[1])):
                            moveWin(awin.id, awin.desktop, win.desktop)
                            break
                                
    def readXml(self, xml_element):
        self.saved_windows.clear()
        
        nodes = xml_element.childNodes()
        
        for i in range(nodes.count()):
            node = nodes.at(i)
            el = node.toElement()
            if el.tagName() != "window":
                continue
            
            win = WindowProperties()
            
            win.wclass  = el.attribute('class')
            win.name    = el.attribute('name')
            
            desktop = el.attribute('desktop')
            if desktop.lstrip('-').isdigit():
                win.desktop = int(desktop)
            
            self.saved_windows.append(win)
            
    def findAndClose(self, pid):
        for awin in self.active_window_list:
            if ray.isPidChildOf(awin.pid, pid):
                QProcess.startDetached('wmctrl', ['-i', '-c', awin.id])
