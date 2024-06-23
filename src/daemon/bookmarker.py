# -*- coding: utf-8 -*-

import os
from pathlib import Path
import sys
from typing import Optional

from PyQt5.QtCore import QSettings, QDataStream, QIODevice, QUrl, QByteArray
from PyQt5.QtXml  import QDomDocument

import ray
from daemon_tools import get_app_config_path, dirname

QFILEDIALOG_MAGIC = 190


class PickerType:
    def __init__(self, config_path):
        self.config_path = config_path
        self.written = False

    def _get_contents(self):
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

    def _print_contents(self, contents):
        try:
            file = open(self.config_path, 'w')
        except:
            return False

        file.write(contents)
        file.close()

        return True

    def make_bookmark(self, spath):
        pass

    def remove_bookmark(self, spath):
        pass

class PickerTypeGtk(PickerType):
    def make_bookmark(self, spath: Path):
        if self.written:
            return

        url = spath.as_uri()

        config_dir = dirname(self.config_path)

        if not os.path.exists(config_dir):
            try:
                os.makedirs(config_dir)
            except:
                return

        contents = self._get_contents()
        if contents is None:
            return

        bookmarks = contents.split('\n')

        if url in bookmarks:
            return

        contents += "%s\n" % url

        if self._print_contents(contents):
            self.written = True

    def remove_bookmark(self, spath: Path):
        if not self.written:
            return

        url = spath.as_uri()

        contents = self._get_contents()
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

        self._print_contents(contents)
        self.written = False

class PickerTypeFltk(PickerType):
    def make_bookmark(self, spath: Path):
        if self.written:
            return

        contents = self._get_contents()
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
                    if line.partition(':')[2] == str(spath):
                        #bookmark already written, do nothing
                        return

                    num_s = line.partition(':')[0].replace('favorite', '', 1)
                    if num_s.isdigit():
                        num = int(num_s)
                else:
                    if not empty_fav:
                        line += str(spath)
                        empty_fav = True

            if line or not fav0_found:
                contents += "%s\n" % line

        if not empty_fav:
            num += 1
            contents += "favorite%.2d:%s" % (num, spath)

        if self._print_contents(contents):
            self.written = True

    def remove_bookmark(self, spath: Path):
        if not self.written:
            return

        contents = self._get_contents()
        if not contents:
            self.written = False
            return

        lines = contents.split('\n')
        favorites = list[str]()

        for line in lines:
            if line.startswith('favorite') and ':' in line:
                fav = line.partition(':')[2]
                favorites.append(fav)

        if not str(spath) in favorites:
            self.written = False
            return

        favorites.remove(str(spath))
        contents = ""
        num = 0

        for line in lines:
            if line.startswith('favorite') and ':' in line:
                fav = ''
                if num < len(favorites):
                    fav = favorites[num]

                contents += "favorite%.2d:%s\n" % (num, fav)
                num += 1
            else:
                contents += "%s\n" % line

        self._print_contents(contents)
        self.written = False

class PickerTypeQt4(PickerType):
    def make_bookmark(self, spath: Path):
        if self.written:
            return

        if not os.path.exists(self.config_path):
            #do not write shortcuts if file was not created by Qt4 himself
            return

        url = spath.as_uri()

        settings_qt4 = QSettings(self.config_path, QSettings.IniFormat)
        if not settings_qt4.isWritable():
            return

        data = settings_qt4.value('Qt/filedialog')
        stream = QDataStream(data, QIODevice.ReadOnly)

        magic = stream.readUInt32()
        version = stream.readUInt32()
        if not (magic == QFILEDIALOG_MAGIC and version == 3):
            return

        split_states = stream.readBytes()

        bookmarks_len = stream.readUInt32()
        bookmarks = []
        for bm in range(bookmarks_len):
            qUrl = QUrl()
            stream >> qUrl

            if qUrl.isLocalFile() and qUrl.toLocalFile() == str(spath):
                #spath already in qt4 bookmarks
                return

            bookmarks.append(qUrl)

        history_len = stream.readUInt32()
        history = [stream.readQString() for h in range(history_len)]
        current_dir = stream.readQString()
        header_data = stream.readBytes()
        view_mode = stream.readUInt32()

        #now rewrite bytes

        new_data = QByteArray()
        new_stream = QDataStream(new_data, QIODevice.WriteOnly)

        new_stream.writeUInt32(magic)
        new_stream.writeUInt32(3)
        new_stream.writeBytes(split_states)
        new_stream.writeUInt32(bookmarks_len + 1)
        for bm in bookmarks:
            new_stream << bm

        qUrl = QUrl(url)
        new_stream << qUrl

        new_stream.writeQStringList(history)
        new_stream.writeQString(current_dir)
        new_stream.writeBytes(header_data)
        new_stream.writeUInt32(view_mode)

        settings_qt4.setValue('Qt/filedialog', new_data)
        settings_qt4.sync()

        self.written = True

    def remove_bookmark(self, spath: Path):
        if not self.written:
            return

        if not os.path.exists(self.config_path):
            self.written = False
            return

        url = spath.as_uri()

        settings_qt4 = QSettings(self.config_path, QSettings.IniFormat)
        if not settings_qt4.isWritable():
            self.written = False
            return

        data = settings_qt4.value('Qt/filedialog')
        stream = QDataStream(data, QIODevice.ReadOnly)

        magic = stream.readUInt32()
        version = stream.readUInt32()
        if not (magic == QFILEDIALOG_MAGIC and version == 3):
            self.written = False
            return

        split_states = stream.readBytes()

        bookmark_found = False
        bookmarks_len = stream.readUInt32()
        bookmarks = []
        for bm in range(bookmarks_len):
            qUrl = QUrl()
            stream >> qUrl

            if qUrl.isLocalFile() and qUrl.toLocalFile() == str(spath):
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
        view_mode = stream.readUInt32()

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

        settings_qt4.setValue('Qt/filedialog', new_data)
        settings_qt4.sync()

        self.written = False

class PickerTypeQt5(PickerType):
    def make_bookmark(self, spath: Path):
        if self.written:
            return

        if not os.path.exists(self.config_path):
            #do not write shortcuts if file was not created by Qt5 himself
            return

        url = spath.as_uri()

        settings_qt5 = QSettings(self.config_path, QSettings.IniFormat)
        if not settings_qt5.isWritable():
            return

        shortcuts = ray.get_list_in_settings(settings_qt5,
                                             'FileDialog/shortcuts')

        for sc in shortcuts:
            sc_url = QUrl(sc)
            if sc_url.isLocalFile() and sc_url.toLocalFile() == str(spath):
                return

        shortcuts.append(url)

        settings_qt5.setValue('FileDialog/shortcuts', shortcuts)
        settings_qt5.sync()
        self.written = True

    def remove_bookmark(self, spath: Path):
        if not self.written:
            return

        if not os.path.exists(self.config_path):
            self.written = False
            return

        settings_qt5 = QSettings(self.config_path, QSettings.IniFormat)
        shortcuts = ray.get_list_in_settings(settings_qt5,
                                             'FileDialog/shortcuts')

        for sc in shortcuts:
            sc_url = QUrl(sc)
            if sc_url.isLocalFile() and sc_url.toLocalFile() == str(spath):
                shortcuts.remove(sc)
                break
        else:
            self.written = False
            return

        settings_qt5.setValue('FileDialog/shortcuts', shortcuts)
        settings_qt5.sync()
        self.written = False

class PickerTypeKde5(PickerType):
    def make_bookmark(self, spath: Path):
        if self.written:
            return

        contents = self._get_contents()
        if not contents:
            # we won't write a file for kde5 if file doesn't already exists
            return

        url = spath.as_uri()

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
        title_text = xml.createTextNode(spath.name)
        title.appendChild(title_text)
        bk.appendChild(title)
        content.appendChild(bk)

        if self._print_contents(xml.toString()):
            self.written = True


    def remove_bookmark(self, spath: Path):
        if not self.written:
            return

        contents = self._get_contents()
        if not contents:
            self.written = False
            return

        url = spath.as_uri()

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

        self._print_contents(xml.toString())
        self.written = False


class BookMarker:
    def __init__(self):
        self._bookmarks_memory = "%s/bookmarks.xml" % get_app_config_path()
        self._daemon_port = 0

        home = os.getenv('HOME')

        self._gtk2 = PickerTypeGtk("%s/.gtk-bookmarks" % home)
        self._gtk3 = PickerTypeGtk("%s/.config/gtk-3.0/bookmarks" % home)
        self._fltk = PickerTypeFltk(
            "%s/._fltk/fltk.org/filechooser.prefs" % home)
        self._kde5 = PickerTypeKde5("%s/.local/share/user-places.xbel" % home)
        self._qt4 = PickerTypeQt4("%s/.config/Trolltech.conf" % home)
        self._qt5 = PickerTypeQt5("%s/.config/QtProject.conf" % home)

    def _get_xml(self) -> Optional[QDomDocument]:
        xml = QDomDocument()
        file_exists = False

        if os.path.exists(self._bookmarks_memory):
            try:
                file = open(self._bookmarks_memory, 'r')
                xml.setContent(file.read())
                file_exists = True
            except:
                try:
                    os.remove(self._bookmarks_memory)
                except:
                    return None

        if not file_exists:
            bms_xml = xml.createElement('Bookmarks')
            xml.appendChild(bms_xml)

        return xml

    def _write_xml_file(self, xml: QDomDocument):
        try:
            file = open(self._bookmarks_memory, 'w')
            file.write(xml.toString())
        except:
            return

    def _get_pickers_for_xml(self):
        string = ":"
        if self._gtk2.written:
            string += "gtk2:"
        if self._gtk3.written:
            string += "gtk3:"
        if self._fltk.written:
            string += "fltk:"
        if self._kde5.written:
            string += "kde5:"
        if self._qt4.written:
            string += "qt4:"
        if self._qt5.written:
            string += "qt5:"

        return string

    def set_daemon_port(self, port):
        self._daemon_port = port

    def make_all(self, spath: Path):
        for picker in (self._gtk2, self._gtk3, self._fltk,
                       self._kde5, self._qt4, self._qt5):
            picker.make_bookmark(spath)

        xml = self._get_xml()
        if not xml:
            return

        xml_content = xml.documentElement()

        bke = xml.createElement('bookmarker')
        bke.setAttribute('port', self._daemon_port)
        bke.setAttribute('session_path', spath)
        bke.setAttribute('pickers', self._get_pickers_for_xml())

        xml_content.appendChild(bke)

        self._write_xml_file(xml)

    def remove_all(self, spath: Path):
        for picker in (self._gtk2, self._gtk3, self._fltk,
                       self._kde5, self._qt4, self._qt5):
            picker.remove_bookmark(spath)

        xml = self._get_xml()
        if not xml:
            return

        xml_content = xml.documentElement()
        nodes = xml_content.childNodes()
        for i in range(nodes.count()):
            node = nodes.at(i)

            bke = node.toElement()
            port = bke.attribute('port')
            session_path = bke.attribute('session_path')

            if (port.isdigit()
                    and int(port) == self._daemon_port
                    and session_path == str(spath)):
                xml_content.removeChild(node)
                break

        self._write_xml_file(xml)


    def clean(self, all_session_paths):
        xml = self._get_xml()
        if not xml:
            return

        xml_content = xml.documentElement()
        nodes = xml_content.childNodes()
        nodes_to_remove = []

        for i in range(nodes.count()):
            node = nodes.at(i)
            bke = node.toElement()
            spath = bke.attribute('session_path')
            pickers = bke.attribute('pickers')

            if not spath:
                nodes_to_remove.append(node)
                continue

            if not spath in all_session_paths:
                if ":gtk2:" in pickers:
                    self._gtk2.written = True
                    self._gtk2.remove_bookmark(spath)
                if ":gtk3:" in pickers:
                    self._gtk3.written = True
                    self._gtk3.remove_bookmark(spath)
                if ":fltk:" in pickers:
                    self._fltk.written = True
                    self._fltk.remove_bookmark(spath)
                if ":kde5:" in pickers:
                    self._kde5.written = True
                    self._kde5.remove_bookmark(spath)
                if ":qt4:" in pickers:
                    self._qt4.written = True
                    self._qt4.remove_bookmark(spath)
                if ":qt5:" in pickers:
                    self._qt5.written = True
                    self._qt5.remove_bookmark(spath)

                nodes_to_remove.append(node)

        for node in nodes_to_remove:
            xml_content.removeChild(node)

        self._write_xml_file(xml)


if __name__ == '__main__':
    bm_maker = BookMarker()
    bm_maker.make_all(Path(sys.argv[1]))
