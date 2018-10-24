# -*- coding: utf-8 -*-

import sys, os
import pathlib
from PyQt5.QtCore import QSettings, QDataStream, QIODevice, QUrl, QByteArray
from PyQt5.QtXml  import QDomDocument, QDomText
from shared import *

QFileDialogMagic = 190

class PickerType(object):
    def __init__(self, config_path):
        self.config_path = config_path
        self.written     = False
        
    def makeBookmark(self, spath):
        pass
    
    def removeBookmark(self, spath):
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
        
        self.printContents(contents)
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
                
            if line or not fav0_found:
                contents+= "%s\n" % line
        
        if not empty_fav:
            num+=1
            contents += "favorite%.2d:%s" % (num, spath)
            
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
                    
        self.printContents(contents)
        self.written = False

class PickerTypeQt4(PickerType):
    def makeBookmark(self, spath):
        if self.written:
            return
        
        if not os.path.exists(self.config_path):
            #do not write shortcuts if file was not created by Qt4 himself
            return
        
        url = pathlib.Path(spath).as_uri()
        
        settings = QSettings(self.config_path, QSettings.IniFormat)
        if not settings.isWritable():
            return
        
        data = settings.value('Qt/filedialog')
        stream = QDataStream(data, QIODevice.ReadOnly)
        
        magic   = stream.readUInt32()
        version = stream.readUInt32()
        if not (magic == QFileDialogMagic and version == 3):
            return
        
        split_states = stream.readBytes()
        
        bookmarks_len = stream.readUInt32()
        bookmarks = []
        for bm in range(bookmarks_len):
            qUrl = QUrl()
            stream >> qUrl
            
            if qUrl.isLocalFile() and qUrl.toLocalFile() == spath:
                #spath already in qt4 bookmarks
                return
            
            bookmarks.append(qUrl)
            
            
        history_len = stream.readUInt32()
        history = []
        for h in range(history_len):
            his = stream.readQString()
            history.append(his)
            
        current_dir = stream.readQString()
        header_data = stream.readBytes()
        view_mode   = stream.readUInt32()
        
        
        #now rewrite bytes
        
        new_data = QByteArray()
        new_stream = QDataStream(new_data, QIODevice.WriteOnly)
        
        new_stream.writeUInt32(magic)
        new_stream.writeUInt32(3)
        new_stream.writeBytes(split_states)
        new_stream.writeUInt32(bookmarks_len+1)
        for bm in bookmarks:
            new_stream << bm
            
        qUrl = QUrl(url)
        new_stream << qUrl
        
        new_stream.writeQStringList(history)
        new_stream.writeQString(current_dir)
        new_stream.writeBytes(header_data)
        new_stream.writeUInt32(view_mode)
        
        settings.setValue('Qt/filedialog', new_data)
        settings.sync()
        
        self.written = True
    
    def removeBookmark(self, spath):
        if not self.written:
            return
        
        if not os.path.exists(self.config_path):
            self.written = False
            return
        
        url = pathlib.Path(spath).as_uri()
        
        settings = QSettings(self.config_path, QSettings.IniFormat)
        if not settings.isWritable():
            self.written = False
            return
        
        data = settings.value('Qt/filedialog')
        stream = QDataStream(data, QIODevice.ReadOnly)
        
        magic   = stream.readUInt32()
        version = stream.readUInt32()
        if not (magic == QFileDialogMagic and version == 3):
            self.written = False
            return
        
        split_states = stream.readBytes()
        
        bookmark_found = False
        bookmarks_len = stream.readUInt32()
        bookmarks = []
        for bm in range(bookmarks_len):
            qUrl = QUrl()
            stream >> qUrl
            
            if qUrl.isLocalFile() and qUrl.toLocalFile() == spath:
                bookmark_found = True
            else:
                bookmarks.append(qUrl)
                
        if not bookmark_found:
            self.written = False
            return
        
        history_len = stream.readUInt32()
        history = []
        for h in range(history_len):
            his = stream.readQString()
            history.append(his)
            
        current_dir = stream.readQString()
        header_data = stream.readBytes()
        view_mode   = stream.readUInt32()
        
        #now rewrite bytes
        
        new_data = QByteArray()
        new_stream = QDataStream(new_data, QIODevice.WriteOnly)
        
        new_stream.writeUInt32(magic)
        new_stream.writeUInt32(3)
        new_stream.writeBytes(split_states)
        new_stream.writeUInt32(bookmarks_len-1)
        for bm in bookmarks:
            new_stream << bm
            
        qUrl = QUrl(url)
        new_stream << qUrl
        
        new_stream.writeQStringList(history)
        new_stream.writeQString(current_dir)
        new_stream.writeBytes(header_data)
        new_stream.writeUInt32(view_mode)
        
        settings.setValue('Qt/filedialog', new_data)
        settings.sync()
        
        self.written = False

class PickerTypeQt5(PickerType):
    def makeBookmark(self, spath):
        if self.written:
            return
        
        if not os.path.exists(self.config_path):
            #do not write shortcuts if file was not created by Qt5 himself
            return
        
        url = pathlib.Path(spath).as_uri()
        
        settings = QSettings(self.config_path, QSettings.IniFormat)
        if not settings.isWritable():
            return
        
        shortcuts = getListInSettings(settings, 'FileDialog/shortcuts')
        
        if url in shortcuts:
            return
        
        shortcuts.append(url)
        
        settings.setValue('FileDialog/shortcuts', shortcuts)
        settings.sync()
        self.written = True
            
    def removeBookmark(self, spath):
        if not self.written:
            return
        
        if not os.path.exists(self.config_path):
            self.written = False
            return
        
        url = pathlib.Path(spath).as_uri()
        
        settings = QSettings(self.config_path, QSettings.IniFormat)
        shortcuts = settings.value('FileDialog/shortcuts', type=list)
        
        if not url in shortcuts:
            self.written = False
            return
        
        shortcuts.remove(url)
        
        settings.setValue('FileDialog/shortcuts', shortcuts)
        settings.sync()
        self.written = False

class PickerTypeKde5(PickerType):
    def makeBookmark(self, spath):
        if self.written:
            return
        
        contents = self.getContents()
        if not contents:
            #we won't write a file for kde5 if file doesn't already exists
            return
        
        url = pathlib.Path(spath).as_uri()
        
        xml = QDomDocument()
        xml.setContent(contents)
        content = xml.documentElement()
        if content.tagName() != 'xbel':
            return
        
        node = content.firstChild()
        while not node.isNull():
            el = node.toElement()
            if el.tagName() == 'bookmark':
                if el.attribute('href') == url:
                    #bookmark already exists
                    return
            
            node = node.nextSibling()
        
        bk = xml.createElement('bookmark')
        bk.setAttribute('href', url)
        title = xml.createElement('title')
        title_text = xml.createTextNode(os.path.basename(spath))
        title.appendChild(title_text)
        bk.appendChild(title)
        content.appendChild(bk)
        
        if self.printContents(xml.toString()):
            self.written = True
            
            
    def removeBookmark(self, spath):
        if not self.written:
            return
        
        contents = self.getContents()
        if not contents:
            self.written = False
            return
        
        url = pathlib.Path(spath).as_uri()
        
        xml = QDomDocument()
        xml.setContent(contents)
        content = xml.documentElement()
        if content.tagName() != 'xbel':
            self.written = False
            return
        
        node = content.firstChild()
        while not node.isNull():
            el = node.toElement()
            if el.tagName() == 'bookmark':
                if el.attribute('href') == url:
                    content.removeChild(node)
                    break
            
            node = node.nextSibling()
        else:
            self.written = False
            return
        
        self.printContents(xml.toString())
        self.written = False
        
        
class BookMarker(object):
    def __init__(self, config_path):
        self.bookmarks_memory = "%s/bookmarks.xml" % config_path
        self.daemon_port      = 0
        
        if not os.path.exists(config_path):
            try:
                os.makedirs(config_path)
            except:
                pass
        
        HOME = os.getenv('HOME')
        
        self.gtk2 = PickerTypeGtk("%s/.gtk-bookmarks" % HOME)
        self.gtk3 = PickerTypeGtk("%s/.config/gtk-3.0/bookmarks" % HOME)
        self.fltk = PickerTypeFltk("%s/.fltk/fltk.org/filechooser.prefs" % HOME)
        self.kde5 = PickerTypeKde5("%s/.local/share/user-places.xbel" % HOME)
        self.qt4  = PickerTypeQt4("%s/.config/Trolltech.conf" % HOME)
        self.qt5  = PickerTypeQt5("%s/.config/QtProject.conf" % HOME)
        
    def setDaemonPort(self, port):
        self.daemon_port = port
    
    def getXml(self):
        xml = QDomDocument()
        file_exists = False
        
        if os.path.exists(self.bookmarks_memory):
            try:
                file = open(self.bookmarks_memory, 'r')
                xml.setContent(file.read())
                file_exists = True
            except:
                try:
                    os.path.remove(self.bookmarks_memory)
                except:
                    return None
        
        if not file_exists:
            bms_xml = xml.createElement('Bookmarks')
            xml.appendChild(bms_xml)
            
        return xml
    
    def writeXmlFile(self, xml):
        try:
            file = open(self.bookmarks_memory, 'w')
            file.write(xml.toString())
        except:
            return
    
    def getPickersForXml(self):
        string = ":"
        if self.gtk2.written:
            string += "gtk2:"
        if self.gtk3.written:
            string += "gtk3:"
        if self.fltk.written:
            string += "fltk:"
        if self.kde5.written:
            string += "kde5:"
        if self.qt4.written:
            string += "qt4:"
        if self.qt5.written:
            string += "qt5:"
        
        return string
    
    def makeAll(self, spath):
        for picker in (self.gtk2, self.gtk3, self.fltk, self.kde5, self.qt4, self.qt5):
            picker.makeBookmark(spath)
        
        xml = self.getXml()
        if not xml:
            return
            
        xml_content = xml.documentElement()
        node = xml_content.firstChild()
        
        bke = xml.createElement('bookmarker')
        bke.setAttribute('port', self.daemon_port)
        bke.setAttribute('session_path', spath)
        bke.setAttribute('pickers', self.getPickersForXml())
        node = xml_content.firstChild()
        xml_content.appendChild(bke)
        
        self.writeXmlFile(xml)
        
    def removeAll(self, spath):
        for picker in (self.gtk2, self.gtk3, self.fltk, self.kde5, self.qt4, self.qt5):
            picker.removeBookmark(spath)
            
        xml = self.getXml()
        if not xml:
            return
            
        xml_content = xml.documentElement()
        nodes = xml_content.childNodes()
        for i in range(nodes.count()):
            node = nodes.at(i)
            
            bke = node.toElement()
            port = bke.attribute('port')
            session_path = bke.attribute('session_path')
            
            if port.isdigit() and int(port) == self.daemon_port and session_path == spath:
                xml_content.removeChild(node)
                break
            
        self.writeXmlFile(xml)
            
    
    def clean(self, all_session_paths):
        xml = self.getXml()
        if not xml:
            return
        
        xml_content = xml.documentElement()
        nodes = xml_content.childNodes()
        nodes_to_remove = []
        
        for i in range(nodes.count()):
            node = nodes.at(i)
            bke = node.toElement()
            spath   = bke.attribute('session_path')
            pickers = bke.attribute('pickers')
            
            if not spath:
                nodes_to_remove.append(node)
                continue
            
            if not spath in all_session_paths:
                if ":gtk2:" in pickers:
                    self.gtk2.written = True
                    self.gtk2.removeBookmark(spath)
                if ":gtk3:" in pickers:
                    self.gtk3.written = True
                    self.gtk3.removeBookmark(spath)
                if ":fltk:" in pickers:
                    self.fltk.written = True
                    self.fltk.removeBookmark(spath)
                if ":kde5:" in pickers:
                    self.kde5.written = True
                    self.kde5.removeBookmark(spath)
                if ":qt4:" in pickers:
                    self.qt4.written = True
                    self.qt4.removeBookmark(spath)
                if ":qt5:" in pickers:
                    self.qt5.written = True
                    self.qt5.removeBookmark(spath)
            
                nodes_to_remove.append(node)
            
        for node in nodes_to_remove:
            xml_content.removeChild(node)
            
        self.writeXmlFile(xml)
    
if __name__ == '__main__':
    bm_maker = BookMarker()
    bm_maker.makeAll(sys.argv[1])
    
        
        
