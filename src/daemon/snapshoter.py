import locale
import os
import shutil
import subprocess
import sys
from PyQt5.QtCore import (QProcess, QProcessEnvironment, QTimer,
                          QObject, pyqtSignal, QDateTime)
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

def fullRefForGui(ref, name, rw_ref, rw_name='', ss_name=''):
    if ss_name:
        return "%s:%s\n%s:%s\n%s" % (ref, name, rw_ref, rw_name, ss_name) 
    return "%s:%s\n%s:%s" % (ref, name, rw_ref, rw_name) 

class Snapshoter(QObject):
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
        
        self._adder_aborted = False
        
        self._n_file_changed = 0
        self._n_file_treated = 0
        
        self.next_function = None
    
    def adderStandardOutput(self):
        standard_output = self.adder_process.readAllStandardOutput().data()
        
        if not self._n_file_changed:
            return
        
        self._n_file_treated += len(standard_output.decode().split('\n')) -1
        
        self.session.sendGui('/ray/gui/server_progress',
                             self._n_file_treated / self._n_file_changed)
    
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
    
    def getHistoryXmlDocumentElement(self):
        if not self.isInit():
            return None
        
        file_path = "%s/%s/%s" % (
                        self.session.path, self.gitname, self.history_path)
        
        xml = QDomDocument()
            
        try:
            history_file = open(file_path, 'r')
            xml.setContent(history_file.read())
            history_file.close()
        except BaseException:
            return None
        
        SNS_xml = xml.documentElement()
        if SNS_xml.tagName() != 'SNAPSHOTS':
            return None
        
        return SNS_xml
        
    def list(self, client_id=""):
        SNS_xml = self.getHistoryXmlDocumentElement()
        if not SNS_xml:
            return []
        
        nodes = SNS_xml.childNodes()
        
        all_tags = []
        all_snaps = []
        prv_session_name = self.session.name
        
        for i in range(nodes.count()):
            node = nodes.at(i)
            el = node.toElement()
            
            if client_id:
                client_nodes = node.childNodes()
                for j in range(client_nodes.count()):
                    client_node = client_nodes.at(j)
                    client_el = client_node.toElement()
                    if client_el.attribute('client_id') == client_id:
                        break
                else:
                    continue
            
            ref   = el.attribute('ref')
            name  = el.attribute('name')
            rw_sn = el.attribute('rewind_snapshot')
            rw_name = ""
            session_name = el.attribute('session_name')
            
            # don't list snapshot from client before session renamed
            if client_id and session_name != self.session.name:
                client = self.session.getClient(client_id)
                if (client
                    and client.prefix_mode == ray.PrefixMode.SESSION_NAME):
                        continue
            
            ss_name = ""
            if session_name != prv_session_name:
                ss_name = session_name
            
            prv_session_name = session_name
            
            if not ref.replace('_', '').isdigit():
                continue
                
            if '\n' in name:
                name = ""
            
            if not rw_sn.replace('_', '').isdigit():
                rw_sn = ""
            
            if rw_sn:
                for snap in all_snaps:
                    if snap[0] == rw_sn and not '\n' in snap[1]:
                        rw_name = snap[1]
                        break
            
            all_snaps.append((ref, name))
            all_tags.append(fullRefForGui(ref, name, rw_sn, rw_name, ss_name))
            
        return all_tags.__reversed__()
    
    def getTagDate(self):
        date_time = QDateTime.currentDateTimeUtc()
        date = date_time.date()
        time = date_time.time()
        
        tagdate = "%s_%s_%s_%s_%s_%s" % (
                    date.year(), date.month(), date.day(),
                    time.hour(), time.minute(), time.second())
        
        return tagdate
    
    def writeHistoryFile(self, date_str, snapshot_name='', rewind_snapshot=''):
        if not self.session.path:
            return
        
        file_path = "%s/%s/%s" % (
                        self.session.path, self.gitname, self.history_path)
        
        xml = QDomDocument()
            
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
            client_el.setAttribute('client_id', client.client_id)
            
            for client_file_path in client.getProjectFiles():
                base_path = client_file_path.replace(
                    "%s/" % self.session.path, '', 1)
                file_xml = xml.createElement('file')
                file_xml.setAttribute('path', base_path)
                client_el.appendChild(file_xml)
            
            snapshot_el.appendChild(client_el)
            
        SNS_xml.appendChild(snapshot_el)
        
        # let python print exception if any
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
                cext_list = client.ignored_extensions.split(' ')
                
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
            cext_list = client.ignored_extensions.split(' ')
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
                    if os.path.islink(filename):
                        short_folder = foldername.replace(
                                        self.session.path + '/', '', 1)
                        line = gitStringer("%s/%s" % (short_folder, filename))
                        contents += '!%s\n' % line
                    # file with extension globally ignored but
                    # unignored by its client will not be ignored
                    # and that is well as this.
                    continue
                        
                if os.path.islink(filename):
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
            command = self.getGitCommandList('ls-files',
                                             '--exclude-standard',
                                             '--others',
                                             '--modified')
            output = subprocess.check_output(command)
        except:
            return False
        
        self._n_file_treated = 0
        self._n_file_changed = len(output.decode().split('\n')) -1
        
        return bool(output)
    
    def canSave(self):
        if not self.session.path:
            return False
            
        if not self.isInit():
            self.runGit('init')
            
        if not self.isInit():
            return False
        
        return True
    
    def save(self, name='', rewind_snapshot='', next_function=None):
        self.next_snapshot_name  = name
        self._rw_snapshot = rewind_snapshot
        self.next_function = next_function
        
        if not self.canSave():
            Terminal.message("can't snapshot")
            return
        
        self.writeExcludeFile()
        
        all_args = self.getGitCommandList('add', '-A', '-v')
        
        self._adder_aborted = False
        self.adder_process.start(all_args.pop(0), all_args)
        # self.adder_process.finished is connected to self.save_step_1
        
    def save_step_1(self):
        if self._adder_aborted:
            self.setAutoSnapshot(False)
            return
        
        Terminal.beforeSnapshotMessage()
        self.runGit('commit', '-m', 'ray')
                
        ref = self.getTagDate()
            
        self.runGit('tag', '-a', ref, '-m', 'ray')
        self.writeHistoryFile(ref, self.next_snapshot_name, self._rw_snapshot)
        
        if self.session.hasServer():
            self.session.sendGui('/reply_snapshots_list',
                                 fullRefForGui(ref, self.next_snapshot_name, 
                                               self._rw_snapshot))
        if self.next_function:
            self.next_function()
        
    def load(self, spath, snapshot):
        snapshot_ref = snapshot.partition('\n')[0].partition(':')[0]
        
        self.runGitAt(spath, 'reset', '--hard')
        self.runGitAt(spath, 'checkout', snapshot_ref)
    
    def loadClientExclusive(self, client_id, snapshot):
        SNS_xml = self.getHistoryXmlDocumentElement()
        if not SNS_xml:
            # TODO send error
            return 
        
        nodes = SNS_xml.childNodes()
        
        client_path_list = []
        
        for i in range(nodes.count()):
            node = nodes.at(i)
            el = node.toElement()
            
            if el.attribute('ref') != snapshot:
                continue
            
            client_nodes = node.childNodes()
            
            for j in range(client_nodes.count()):
                client_node = client_nodes.at(j)
                client_el = client_node.toElement()
                
                if client_el.attribute('client_id') != client_id:
                    continue
                
                file_nodes = client_node.childNodes()
                
                for k in range(file_nodes.count()):
                    file_node = file_nodes.at(k)
                    file_el = file_node.toElement()
                    file_path = file_el.attribute('path')
                    if file_path:
                        client_path_list.append(file_path)
        
        self.runGitAt(self.session.path, 'reset', '--hard')
        Terminal.beforeSnapshotMessage()
        self.runGitAt(self.session.path, 'checkout', snapshot, '--',
                      *client_path_list)
        
    def abort(self):
        if not self.adder_process.state():
            return 
        
        self.setAutoSnapshot(False)
        
        self._adder_aborted = True
        self.adder_process.terminate()
    
    def setAutoSnapshot(self, bool_snapshot):
        auto_snap_file = "%s/%s/prevent_auto_snapshot" % (self.session.path,
                                                          self.gitname)
        file_exists = bool(os.path.exists(auto_snap_file))
        
        if bool_snapshot:
            if file_exists:
                try:
                    os.remove(auto_snap_file)
                except PermissionError:
                    return
        else:
            if not file_exists:
                contents = "# This file prevent auto snapshots for this session (RaySession)\n"
                contents += "# remove it if you want auto snapshots back"
                
                try:
                    file = open(auto_snap_file, 'w')
                    file.write(contents)
                    file.close()
                except PermissionError:
                    return
                
    def isAutoSnapshotPrevented(self):
        auto_snap_file = "%s/%s/prevent_auto_snapshot" % (self.session.path, self.gitname)
        
        return bool(os.path.exists(auto_snap_file))
