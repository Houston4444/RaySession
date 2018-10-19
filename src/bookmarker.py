# -*- coding: utf-8 -*-

import sys, os
import pathlib

STATE_OFF       = 0
STATE_WRITTEN   = 1
STATE_NO_CONFIG = 2
STATE_PERMANENT = 3
STATE_ERROR     = 4

class PickerType(object):
    def __init__(self, config_path):
        self.config_path = config_path
        self.written     = False
        
    def makeBookmark(self, url):
        pass
    
    def removeBookmark(self, url):
        pass
    
    def getContents(self):
        if os.path.exists(self.config_path):
            try:
                file = open(self.config_path, 'r')
                contents = file.read()
                file.close()
                return contents
            except:
                return None
        else:
            print('no cffu', self.config_path)
            return ""
        
    def printContents(self, contents):
        try:
            file = open(self.config_path, 'w')
        except:
            return False
        
        file.write(contents)
        file.close()
        
        return True
    
class PickerTypeGtk(PickerType):
    def makeBookmark(self, spath):
        if self.written:
            return
        
        url = pathlib.Path(spath).as_uri()
        
        config_dir = os.path.dirname(self.config_path)
        
        if not os.path.exists(config_dir):
            try:
                os.makedirs(config_dir)
            except:
                return
        
        contents = self.getContents()
        if contents == None:
            return
        
        bookmarks = contents.split('\n')
        
        if url in bookmarks:
            return
            
        contents += "%s\n" % url
        
        if self.printContents(contents):
            self.written = True
        
    def removeBookmark(self, spath):
        if not self.written:
            return
        
        url = pathlib.Path(spath).as_uri()
        
        contents = self.getContents()        
        if not contents:
            self.written = False
            return
        
        bookmarks = contents.split('\n')
        
        if url in bookmarks:
            bookmarks.remove(url)
        else:
            self.written = False
            return
            
        contents = ''
        for url in bookmarks:
            if url:
                contents += "%s\n" % url
        
        if self.printContents(contents):
            self.written = False
        
class PickerTypeFltk(PickerType):
    def makeBookmark(self, spath):
        if self.written:
            return
        
        contents = self.getContents()
        if not contents:
            #we won't write a file for fltk if file doesn't already exists
            return
        
        lines = contents.split('\n')
        contents = ""
        num = -1
        empty_fav = False
        fav0_found = False
        
        for line in lines:
            if line.startswith('favorite') and ':' in line:
                fav0_found = True
                
                if line.partition(':')[2]:
                    if line.partition(':')[2] == spath:
                        #bookmark already written, do nothing
                        return
                    
                    num_s = line.partition(':')[0].replace('favorite', '', 1)
                    if num_s.isdigit():
                        num = int(num_s)
                else:
                    if not empty_fav:
                        line += spath
                        empty_fav = True
                
            #else:
            if line or not fav0_found:
                contents+= "%s\n" % line
        
        if not empty_fav:
            num+=1
            contents+="favorite%.2d:%s" % (num, spath)
            
        if self.printContents(contents):
            self.written = True
            
    def removeBookmark(self, spath):
        if not self.written:
            return
           
        contents = self.getContents()
        if not contents:
            self.written = False
            return
        
        lines = contents.split('\n')
        favorites = []
        
        for line in lines:
            if line.startswith('favorite') and ':' in line:
                fav = line.partition(':')[2]
                favorites.append(fav)
        
        if not spath in favorites:
            self.written = False
            return
        
        favorites.remove(spath)
        contents = ""
        num = 0
        
        for line in lines:
            if line.startswith('favorite') and ':' in line:
                fav = ''
                if num < len(favorites):
                    fav = favorites[num]
                
                contents+= "favorite%.2d:%s\n" % (num, fav)
                num+=1
            else:
                contents+= "%s\n" % line
                    
        if self.printContents(contents):
            self.written = False

class BookmarkMaker(object):
    def __init__(self):
        HOME = os.getenv('HOME')
        self.gtk2 = PickerTypeGtk("%s/.gtk-bookmarks" % HOME)
        self.gtk3 = PickerTypeGtk("%s/.config/gtk-3.0/bookmarks" % HOME)
        self.fltk = PickerTypeFltk("%s/.fltk/fltk.org/filechooser.prefs" % HOME)
        self.kde5 = PickerType("%s/.local/share/user-places.xbel" % HOME)
        self.qt4  = PickerType("%s/.config/Trolltech.conf" % HOME) #but seems impossible
        self.qt5  = PickerType("%s/.config/QtProject.conf" % HOME)
        
    def makeAll(self, spath):
        for picker in (self.gtk2, self.gtk3, self.fltk):
            picker.makeBookmark(spath)
        
    def removeAll(self, spath):
        for picker in (self.gtk2, self.gtk3, self.fltk):
            picker.written = True
            picker.removeBookmark(spath)
        
if __name__ == '__main__':
    bm_maker = BookmarkMaker()
    bm_maker.removeAll(sys.argv[1])
    
        
        
