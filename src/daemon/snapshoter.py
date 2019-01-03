import locale
import os
import shutil
import subprocess
import sys
import time
from PyQt5.QtCore import QProcess, QProcessEnvironment

class Snapshoter:
    def __init__(self, session):
        self.session = session
        self.gitname = '.git'
        #process_env = QProcessEnvironment.systemEnvironment()
        #process_env.insert('NSM_URL', self.getServerUrl())
        
        #self.process = QProcess()
        #self.process.setProcessEnvironment(process_env)
        
    def getGitDir(self):
        if not self.session.path:
            raise NameError("attempting to save with no session path !!!")
        
        return "%s/%s" % (self.session.path, self.gitname)
    
    def runGit(self, *args):
        gitdir = self.getGitDir()
        if not gitdir:
            return 
        
        subprocess.run(self.getGitCommandList(*args))
    
    def getGitCommandList(self, *args):
        gitdir = self.getGitDir()
        if not gitdir:
            return []
        
        return ['git', '-C' , self.session.path] + list(args)
    
    def list(self):
        gitdir = self.getGitDir()
        if not gitdir:
            return []
        
        all_list = subprocess.check_output(self.getGitCommandList('tag'))
        all_list_utf = all_list.decode()
        all_tags = all_list_utf.split('\n')
        
        return all_tags
    
    def initSession(self):
        gitdir = self.getGitDir()
        if not gitdir:
            return
        
        print('gitdir', gitdir)
        
        if os.path.exists(gitdir):
            return
        
        print('gitdir2')
        
        self.runGit('init')
        
    def excludeUndesired(self):
        if not self.session.path:
            return
        
        exclude_path = "%s/.git/info/exclude" % self.session.path
        exclude_file = open(exclude_path, 'w')
        
        contents = ""
        for extension in ('wav', 'peak', 'flac', 'ogg', 'mp3', 'midi', 'mid'
                          'avi', 'mp4'):
            contents += "*.%s\n" % extension
        
        contents += '\n'
        
        big_files_all = subprocess.check_output(['find', self.session.path,
                                                 '-size', '+50M'])
        big_files_utf = big_files_all.decode()
        contents += big_files_utf
        
        exclude_file.write(contents)
        exclude_file.close()
    
    def save(self):
        #self.initSession()
        #self.excludeUndesired()
        
        date = time.localtime()
        tagdate = "%s_%s_%s_%s_%s_%s" % (
                    date.tm_year, date.tm_mon, date.tm_mday,
                    date.tm_hour, date.tm_min, date.tm_sec)
        
        subprocess.run(['ray-snapshot', self.session.path, tagdate])
        
        #self.runGit('add', '-A')
        #self.runGit('commit', '-m', tagdate)
        #self.runGit('tag', '-a', tagdate, '-m', 'ray')
        
    
