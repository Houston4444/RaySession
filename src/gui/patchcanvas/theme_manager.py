
import json
import os
import sys

from PyQt5.QtCore import QTimer

from .theme import print_error, Theme
from . import canvas, ACTION_THEME_UPDATE

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
        
        self._update_theme()

    def _update_theme(self) -> bool:
        with open(self.current_theme_file, 'r') as f:
            #try:
                theme_dict = self._convert_theme_file_contents_to_dict(f.read())
            #except:
                #sys.stderr.write('patchcanvas::theme:failed to open %s\n'
                                 #% self.current_theme_file)
                #return False
        
        self._last_modified = os.path.getmtime(self.current_theme_file)
        
        del canvas.theme
        canvas.theme = Theme()
        canvas.theme.read_theme(theme_dict)

        canvas.scene.update_theme()
        canvas.callback(ACTION_THEME_UPDATE, 0, 0, '')
        #for group in canvas.group_list:
            #for widget in group.widgets:
                #if widget is not None:
                    #widget.update_positions()
        
        canvas.scene.update()
        return True
    
    @staticmethod
    def _convert_theme_file_contents_to_dict(contents: str) -> dict:
        ''' converts theme file contents to a dict '''
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
        
        out_dict = {}
        dict_to_write = {}
        
        for line in contents.splitlines():
            if line.strip().startswith('#'):
                # ignore commented lines
                continue
            
            if (line.strip().startswith('[')
                    and line.strip().endswith(']')):
                key = line.strip()[1:-1]
                out_dict[key] = {}
                dict_to_write = out_dict[key]
                continue
            
            if not '=' in line:
                continue
            
            key, colon, value = line.partition('=')
            key = key.strip()
            value = value.strip()
            
            if value.startswith('(') and value.endswith(')'):
                value = value[1:-1].split(', ')
                value = tuple([type_convert(v) for v in value])
            elif value.startswith('[') and value.endswith(']'):
                value = value[1:-1].split(', ')
                value = [type_convert(v) for v in value]
            else:
                value = type_convert(value)
            dict_to_write[key] = value

        return out_dict
    
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

        valid_theme = self._update_theme()
        if not valid_theme:
            return False
        
        self.activate_watcher(os.access(self.current_theme_file, os.R_OK))
        
    def activate_watcher(self, yesno: bool):
        if yesno:
            self._theme_file_timer.start()
        else:
            self._theme_file_timer.stop()
