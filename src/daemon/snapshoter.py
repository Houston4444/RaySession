import locale
import os
import shutil
import subprocess
import sys
import time
from PyQt5.QtCore import (QProcess, QProcessEnvironment, QTimer,
                          QObject, pyqtSignal)
from PyQt5.QtXml import QDomDocument
import ray
from daemon_tools import Terminal

def gitStringer(string):
    for char in (' ', '*', '?', '[', ']', '(', ')'):
        string = string.replace(char, "\\" + char)
      
    for char in ('#', '!'):
        if string.startswith(char):
            string = "\\" + string

    return string
    
    
class Snapshoter(QObject):
    saved = pyqtSignal()
    
    def __init__(self, session):
        QObject.__init__(self)
        self.session = session
        self.gitname = '.ray-snapshots'
        self.exclude_path = 'info/exclude'
        self.history_path = "session_history.xml"
        self.max_file_size = 50 #in Mb
        
        self.next_snapshot_name  = ''
        self.next_rw_snapshot = ''
        
        self.adder_process = QProcess()
        self.adder_process.finished.connect(self.save_step_1)
        self.adder_process.readyReadStandardOutput.connect(self.adderStandardOutput)
        
        self.adder_timer = QTimer()
        self.adder_timer.setSingleShot(True)
        self.adder_timer.setInterval(2000)
        self.adder_timer.timeout.connect(self.gitAdderTooLong)
    
    def adderStandardOutput(self):
        print('moerko')
        standard_output = self.adder_process.readAllStandardOutput().data()
        print('adddd', standard_output.decode())
    
    def getGitDir(self):
        if not self.session.path:
            raise NameError("attempting to save with no session path !!!")
        
        return "%s/%s" % (self.session.path, self.gitname)
    
    def runGit(self, *args):
        subprocess.run(self.getGitCommandList(*args))
    
    def runGitAt(self, spath, *args):
        first_args = ['git', '--work-tree', spath, '--git-dir',
                      "%s/%s" % (spath, self.gitname)]
        
        subprocess.run(first_args + list(args))
    
    def getGitCommandList(self, *args):
        first_args = ['git', '--work-tree', self.session.path, '--git-dir',
                      "%s/%s" % (self.session.path, self.gitname)]
        
        return first_args + list(args)
    
    def list(self):
        gitdir = self.getGitDir()
        if not gitdir:
            return []
        
        if not self.isInit():
            return []
        
        all_list = subprocess.check_output(self.getGitCommandList('tag'))
        all_list_utf = all_list.decode()
        all_tags = all_list_utf.split('\n')
        
        if len(all_tags) >= 1:
            if not all_tags[-1]:
                all_tags = all_tags[:-1]
        
        if len(all_tags) >= 1:
            if all_tags[-1] == 'list':
                all_tags = all_tags[:-1]
        
        return all_tags.__reversed__()
    
    def getTagDate(self):
        date = time.localtime()
        tagdate = "%s_%s_%s_%s_%s_%s" % (
                    date.tm_year, date.tm_mon, date.tm_mday,
                    date.tm_hour, date.tm_min, date.tm_sec)
        
        return tagdate
    
    def writeHistoryFile(self, date_str, snapshot_name='', rewind_snapshot=''):
        file_path = "%s/%s/%s" % (
                        self.session.path, self.gitname, self.history_path)
        
        #history_contents = ""
        xml = QDomDocument()
        
        if not os.path.exists(file_path):
            #history_contents = ""
            pass
            
        try:
            history_file = open(file_path, 'r')
            xml.setContent(history_file.read())
            history_file.close()
        except:
            pass
        
        if xml.firstChild().isNull():
            SNS_xml = xml.createElement('SNAPSHOTS')
            xml.appendChild(SNS_xml)
        else:
            SNS_xml = xml.firstChild()
        
        
        
        snapshot_el = xml.createElement('Snapshot')
        snapshot_el.setAttribute('ref', date_str)
        snapshot_el.setAttribute('name', snapshot_name)
        snapshot_el.setAttribute('rewind_snapshot', rewind_snapshot)
        snapshot_el.setAttribute('session_name', self.session.name)
        snapshot_el.setAttribute('VERSION', ray.VERSION)
        
        for client in self.session.clients + self.session.removed_clients:
            client_el = xml.createElement('client')
            client.writeXmlProperties(client_el)
            
            for client_file_path in client.getProjectFiles():
                base_path = client_file_path.replace(
                    "%s/" % self.session.path, '', 1)
                file_xml = xml.createElement('file')
                file_xml.setAttribute('path', base_path)
                client_el.appendChild(file_xml)
            
            snapshot_el.appendChild(client_el)
            
            
        
        #session_xml = QDomDocument()
        #session_xml_path = "%s/raysession.xml" % self.session.path
        
        #try:
            #session_file = open(session_xml_path, 'r')
            #session_xml.setContent(session_file.read())
        #except:
            #return
        
        ##session_el = session_xml.firstChild()
        
        #for i in range(session_xml.childNodes().count()):
            #node = session_xml.childNodes().at(i)
            #if node.toElement().tagName() == 'RAYSESSION':
                #snapshot_el.appendChild(node)
                #break
            
        #print(session_el.toElement().attribute('VERSION'))
        print('zifj')
        #snapshot_el.appendChild(session_el)
        print('evrf')
        SNS_xml.appendChild(snapshot_el)
        print('eirji)')
        print(xml.toString())
        history_file = open(file_path, 'w')
        history_file.write(xml.toString())
        history_file.close()
    
    def writeExcludeFile(self):
        file_path = "%s/%s/%s" % (
                        self.session.path, self.gitname, self.exclude_path)
        
        try:
            exclude_file = open(file_path, 'w')
        except:
            sys.stderr.write(
                "impossible to open %s for writing.\n" % file_path)
            raise
        
        contents = ""
        contents += "# This file is generated by ray-daemon at each snapshot\n"
        contents += "# Don't edit this file.\n"
        contents += "# If you want to add/remove files managed by git\n"
        contents += "# Create/Edit .gitignore in the session folder\n"
        contents += "\n"
        contents += "%s\n" % self.gitname
        contents += "\n"
        contents += "# Globally ignored extensions\n"
        
        session_ignored_extensions = ray.getGitIgnoredExtensions()
        session_ign_list = session_ignored_extensions.split(' ')
        session_ign_list = tuple(filter(bool, session_ign_list))
        
        # write global ignored extensions
        for extension in session_ign_list:
            contents+= "*%s\n" % extension 
            
            for client in self.session.clients:
                cext_list = client.git_ignored_extensions.split(' ')
                if not extension in cext_list:
                    contents += "!%s.%s/**/*%s\n" % (
                        gitStringer(client.getPrefixString()),
                        gitStringer(client.client_id),
                        extension)
                    contents += "!%s.%s.**/*%s\n" % (
                        gitStringer(client.getPrefixString()),
                        gitStringer(client.client_id),
                        extension)
                    
        contents += '\n'
        contents += "# Extensions ignored by clients\n"
        
        # write client specific ignored extension
        for client in self.session.clients:
            cext_list = client.git_ignored_extensions.split(' ')
            for extension in cext_list:
                if not extension:
                    continue
                
                if extension in session_ignored_extensions:
                    continue
                
                contents += "%s.%s/**/*%s\n" % (
                    gitStringer(client.getPrefixString()), 
                    gitStringer(client.client_id),
                    extension)
                
                contents += "%s.%s.**/*%s\n" % (
                    gitStringer(client.getPrefixString()), 
                    gitStringer(client.client_id),
                    extension)
        
        contents += '\n'
        contents += "# Too big Files\n"
        
        no_check_list = (self.gitname)
        # check too big files
        for foldername, subfolders, filenames in os.walk(self.session.path):
            subfolders[:] = [d for d in subfolders if d not in no_check_list]
            
            if foldername == "%s/%s" % (self.session.path, self.gitname):
                continue
            
            
            for filename in filenames:
                if filename.endswith(session_ign_list):
                    # file with extension globally ignored but
                    # unignored by its client will not be ignored
                    # and that is well as this.
                    continue
                        
                try:
                    file_size = os.path.getsize(os.path.join(foldername,
                                                             filename))
                except:
                    continue
                
                if file_size > self.max_file_size*1024**2:
                    if foldername == self.session.path:
                        line = gitStringer(filename)
                    else:
                        short_folder = foldername.replace(
                                        self.session.path + '/', '', 1)
                        line = gitStringer("%s/%s" % (short_folder, filename))
                        
                    contents += "%s\n" % line
        
        exclude_file.write(contents)
        exclude_file.close()
    
    def isInit(self):
        if not self.session.path:
            return False
        
        return os.path.isfile("%s/%s/%s" % (
                self.session.path, self.gitname, self.exclude_path))
        
    def hasChanges(self):
        if not self.session.path:
            return False
        
        if not self.isInit():
            return True
        
        try:
            process = subprocess.run(
                self.getGitCommandList('diff', '--exit-code', '--quiet'))
        except:
            return False
        
        if process.returncode:
            return True
        
        try:
            command = self.getGitCommandList('ls-files',
                                             '--exclude-standard',
                                             '--others')
            output = subprocess.check_output(command)
        except:
            return False
        
        return bool(output)
    
    def gitAdderTooLong(self):
        print("c'est trop long")
    
    def canSave(self):
        if not self.session.path:
            return False
            
        if not self.isInit():
            self.runGit('init')
            
        if not self.isInit():
            return False
        
        return True
    
    def save(self, name='', rewind_snapshot=''):
        self.next_snapshot_name  = name
        self._rw_snapshot = rewind_snapshot
        
        if not self.canSave():
            Terminal.message("can't snapshot")
            self.saved.emit()
            return
        
        self.writeHistoryFile(self.getTagDate())
        self.writeExcludeFile()
        
        all_args = self.getGitCommandList('add', '-A', '-v')
        
        self.adder_timer.start()
        self.adder_process.start(all_args.pop(0), all_args)
        # self.adder_process.finished is connected to self.save_step_1
        
    def save_step_1(self):
        self.adder_timer.stop()
        self.runGit('commit', '-m', 'ray')
                
        snapshot_name = self.getTagDate()
        
        if self.next_snapshot_name:
            snapshot_name = "%s_%s" % (snapshot_name, self.next_snapshot_name)
        elif self._rw_snapshot:
            snapshot_name = "%s,%s" % (snapshot_name, self._rw_snapshot)
            
        print('ukulélé')
        print(snapshot_name)
            
        self.runGit('tag', '-a', snapshot_name, '-m', 'ray')
        
        if self.session.hasServer():
            self.session.sendGui('/reply_snapshots_list', snapshot_name)
            
        self.saved.emit()
        
    def load(self, spath, snapshot):
        #tag_for_last = "%s,%s" % (self.getTagDate(), snapshot)
        print('load bien executé')
        self.runGitAt(spath, 'reset', '--hard')
        print('tadididia')
        #self.runGitAt(spath, 'tag', '-a', tag_for_last, '-m', 'ray')
        self.runGitAt(spath, 'checkout', snapshot)
        
