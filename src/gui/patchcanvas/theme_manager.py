
import configparser
import json
import os
import sys

from PyQt5.QtCore import QTimer

from .theme import print_error, Theme
from .theme_default import default_theme
from . import canvas, ACTION_THEME_UPDATED

class ThemeManager:
    def __init__(self, theme_paths: tuple) -> None:
        self.current_theme = None
        self.current_theme_file = ''
        self.theme_paths = theme_paths

        self._last_modified = 0

        self._theme_file_timer = QTimer()
        self._theme_file_timer.setInterval(400)
        self._theme_file_timer.timeout.connect(self._check_theme_file_modified)

    def _check_theme_file_modified(self):
        if not self.current_theme_file:
            self._theme_file_timer.stop()
            return
        
        last_modified = os.path.getmtime(self.current_theme_file)
        if last_modified == self._last_modified:
            return
        
        if not self._update_theme():
            self._last_modified = last_modified

    def _update_theme(self) -> bool:
        conf = configparser.ConfigParser()
        try:
            # we don't need the file_list
            # it is just a convenience to mute conf.read
            file_list = conf.read(self.current_theme_file)
        except:
            sys.stderr.write('patchcanvas::theme:failed to open %s\n'
                                 % self.current_theme_file)
            return False
        
        theme_dict = self._convert_configparser_object_to_dict(conf)
        self._last_modified = os.path.getmtime(self.current_theme_file)
        
        del canvas.theme
        canvas.theme = Theme()
        canvas.theme.read_theme(theme_dict)

        canvas.scene.update_theme()
        canvas.callback(ACTION_THEME_UPDATED, 0, 0, '')
        return True
    
    @staticmethod
    def _convert_configparser_object_to_dict(conf) -> dict:
        def type_convert(value):
            ''' returns an int, a float, or the unchanged given value '''
            try:
                value = int(value)
            except:
                try:
                    value = float(value)
                except:
                    return value
            return value

        return_dict = {}
        for key, value in conf.items():
            if key == 'DEFAULT':
                continue

            new_dict = {}
            for skey, svalue in value.items():
                if svalue.startswith('(') and svalue.endswith(')'):
                    new_value = svalue[1:-1].split(', ')
                    new_value = tuple([type_convert(v) for v in new_value])
                elif svalue.startswith('[') and svalue.endswith(']'):
                    new_value = svalue[1:-1].split(', ')
                    new_value = [type_convert(v) for v in new_value]
                else:
                    new_value = type_convert(svalue)
                new_dict[skey] = new_value
            return_dict[key] = new_dict
        
        return return_dict
    
    def set_theme(self, theme_name: str) -> bool:
        self.current_theme = theme_name
        
        for theme_path in self.theme_paths:
            theme_file_path = "%s/%s/theme.conf" % (theme_path, theme_name)
            if os.path.exists(theme_file_path):
                self.current_theme_file = theme_file_path
                break
        else:
            print_error("Unable to find theme %s" % theme_name)
            return False

        theme_is_valid = self._update_theme()
        if not theme_is_valid:
            canvas.theme = Theme()
            canvas.theme.read_theme(default_theme)
            canvas.scene.update_theme()
            return False
        
        self.activate_watcher(os.access(self.current_theme_file, os.R_OK))
    
    def list_themes(self) -> set:
        conf = configparser.ConfigParser()
        themes_dicts = []
        lang = os.getenv('LANG')
        lang_short = ''
        if len(lang) >= 2:
            lang_short = lang[:2]
        
        for search_path in self.theme_paths:
            if not os.path.isdir(search_path):
                continue
            
            editable = bool(os.access(search_path, os.W_OK))
            
            for file_path in os.listdir(search_path):
                full_path = os.path.join(search_path, file_path, 'theme.conf')
                if not os.path.isfile(full_path):
                    continue

                try:
                    conf.read(full_path)
                except:
                    # TODO
                    continue
                
                name = file_path

                if 'Theme' in conf.keys():
                    conf_theme = conf['Theme']
                    if 'Name' in conf_theme.keys():
                        name = conf_theme['Name']
                    
                    name_lang_key = 'Name[%s]' % lang_short
                    
                    if name_lang_key in conf_theme.keys():
                        name = conf_theme[name_lang_key]
                    
                themes_dicts.append(
                    {'ref_id': file_path, 'name': name, 'editable': editable})

        return themes_dicts
    
    def activate_watcher(self, yesno: bool):
        if yesno:
            self._theme_file_timer.start()
        else:
            self._theme_file_timer.stop()
