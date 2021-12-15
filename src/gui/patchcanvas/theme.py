#!/usr/bin/python3

import sys

from PyQt5.QtGui import QColor, QPen, QFont, QBrush
from PyQt5.QtCore import Qt

def print_error(string: str):
    sys.stderr.write("patchcanvas.theme::%s\n" % string)

def _to_qcolor(color):
    ''' convert a color given with a string, a list or a tuple (of ints)
    to a QColor.
    returns None if color has a incorrect value.'''
    if isinstance(color, str):
        qcolor = QColor(color)
        
        if (qcolor.getRgb() == (0, 0, 0, 255)
                and color.lower() not in ('black', "#000000", '#ff000000')):
            return None
        return qcolor
    
    if isinstance(color, (tuple, list)):
        if not 3 <= len(color) <= 4:
            return None

        for col in color:
            if not isinstance(col, int):
                return None
            
            if not 0 <= col <= 255:
                return None

        return QColor(*color)
    
    return None


class StyleAttributer:
    def __init__(self, path, parent=None):
        self.subs = []

        self._border_color = None
        self._border_width = None
        self._border_style = None
        self._background_color = None
        self._background2_color = None
        self._text_color = None
        self._font_name = None
        self._font_size = None
        self._font_width = None

        self._path = path
        self._parent = parent
    
    def set_attribute(self, attribute: str, value):
        err = False
        
        if attribute == 'border-color':
            self._border_color = _to_qcolor(value)
            if self._border_color is None:
                err = True
                
        elif attribute == 'border-width':
            if isinstance(value, (int, float)):
                self._border_width = float(value)
            else:
                err = True
                
        elif attribute == 'border-style':
            if isinstance(value, str):
                value = value.lower()
                if value == 'solid':
                    self._border_style = Qt.SolidLine
                elif value == 'nopen':
                    self._border_style = Qt.NoPen
                elif value == 'dash':
                    self._border_style = Qt.DashLine
                elif value == 'dashdot':
                    self._border_style = Qt.DashDotLine
                elif value == 'dashdotdot':
                    self._border_style = Qt.DashDotDotLine
                else:
                    err = True
            else:
                err = True

        elif attribute == 'background':
            self._background_color = _to_qcolor(value)
            if self._background_color is None:
                err = True
                
        elif attribute == 'background2':
            self._background2_color = _to_qcolor(value)
            if self._background2_color is None:
                err = True
                
        elif attribute == 'text-color':
            self._text_color = _to_qcolor(value)
            if self._text_color is None:
                err = True
                
        elif attribute == 'font-name':
            if isinstance(value, str):
                self._font_name = value
            else:
                err = True
                
        elif attribute == 'font-size':
            if isinstance(value, int):
                self._font_size = value
            else:
                err = True
                
        elif attribute == 'font-width':
            if isinstance(value, int):
                value = min(value, 99)
                value = max(value, 0)
                self._font_width = value
            elif isinstance(value, str):
                value = value.lower()
                if value == 'normal':
                    self._font_state = QFont.Normal
                elif value == 'bold':
                    self._font_state = QFont.Bold
                else:
                    err = True
            else:
                err = True
        else:
            print_error("%s:unknown key: %s" % (self._path, attribute))

        if err:
            print_error("%s:invalid value for %s: %s"
                        % (self._path, attribute, str(value)))
    
    def set_style_dict(self, context: str, style_dict: dict):
        if context:
            begin, point, end = context.partition('.')
            
            if begin not in self.subs:
                print_error("%s:invalid ignored key: %s" % (self._path, begin))
                return
            self.__getattribute__(begin).set_style_dict(end, style_dict)
            return
        
        for key, value in style_dict.items():
            self.set_attribute(key, value)
    
    def get_value_of(self, attribute, orig_path=''):
        if attribute not in self.__dir__():
            print_error("get_value_of, invalide attribute: %s" % attribute)
            return None
        
        if not orig_path:
            orig_path = self._path

        for path_end in ('selected', 'disconnecting'):
            if (orig_path.endswith('.' + path_end)
                    and path_end in self.subs
                    and self._path + '.' + path_end != orig_path):
                return self.selected.get_value_of(attribute, self._path)

        if self.__getattribute__(attribute) is None:
            if self._parent is None:
                print_error("get_value_of: %s None value and no parent"
                            % self._path)
                return None
            return self._parent.get_value_of(attribute, orig_path)

        return self.__getattribute__(attribute)
    
    def fill_pen(self):
        return QPen(QBrush(self.get_value_of('_border_color')),
                    self.get_value_of('_border_width'),
                    self.get_value_of('_border_style'))
    
    def background_color(self):
        return self.get_value_of('_background_color')
    
    def background2_color(self):
        return self.get_value_of('_background2_color')
    
    def text_color(self):
        return self.get_value_of('_text_color')
    
    def font(self):
        rfont = QFont()
        rfont.setFamily(self.get_value_of('_font_name'))
        rfont.setPixelSize(self.get_value_of('_font_size'))
        rfont.setWeight(self.get_value_of('_font_width'))
        return rfont


class UnselectedStyleAttributer(StyleAttributer):
    def __init__(self, path, parent=None):
        StyleAttributer.__init__(self, path, parent=parent)
        self.selected = StyleAttributer(path + '.selected', self)
        self.subs.append('selected')


class BoxStyleAttributer(UnselectedStyleAttributer):
    def __init__(self, path, parent):
        UnselectedStyleAttributer.__init__(self, path, parent)
        self.hardware = UnselectedStyleAttributer(path + '.hardware', self)
        self.client = UnselectedStyleAttributer(path + '.client', self)
        self.monitor = UnselectedStyleAttributer(path + '.monitor', self)
        self.subs += ['hardware', 'client', 'monitor']


class PortStyleAttributer(UnselectedStyleAttributer):
    def __init__(self, path, parent):
        UnselectedStyleAttributer.__init__(self, path, parent)
        self.audio = UnselectedStyleAttributer(path + '.audio', self)
        self.midi = UnselectedStyleAttributer(path + '.midi', self)
        self.cv = UnselectedStyleAttributer(path + '.cv', self)
        self.subs += ['audio', 'midi', 'cv']


class LineStyleAttributer(UnselectedStyleAttributer):
    def __init__(self, path, parent):
        UnselectedStyleAttributer.__init__(self, path, parent)
        self.audio = UnselectedStyleAttributer(path + '.audio', self)
        self.midi = UnselectedStyleAttributer(path + '.midi', self)
        self.disconnecting = StyleAttributer(path + '.disconnecting', self)
        self.subs += ['audio', 'midi', 'disconnecting']


class GuiButtonStyleAttributer(StyleAttributer):
    def __init__(self, path, parent):
        StyleAttributer.__init__(self, path, parent)
        self.gui_visible = StyleAttributer('.gui_visible', self)
        self.gui_hidden = StyleAttributer('.gui_hidden', self)
        self.subs += ['gui_visible', 'gui_hidden']


class Theme(StyleAttributer):
    def __init__(self):
        StyleAttributer.__init__(self, '')

        # fallbacks values for all (ugly style, but better than nothing)
        self._border_color = QColor('white')
        self._border_width = 1
        self._border_style = Qt.SolidLine
        self._background_color = QColor('black')
        self._background2_color = QColor('black')
        self._text_color = QColor('white')
        self._font_name = "Deja Vu Sans"
        self._font_size = 11
        self._font_width = QFont.Normal # QFont.Normal is 50

        self.background_color = QColor('black')
        self.box_shadow_color = QColor('gray')
        self.monitor_color = QColor(190, 158, 0)
        self.port_height = 16
        self.port_spacing = 2
        self.port_type_spacing = 2
        self.port_offset = 0
        self.port_grouped_width = 19
        self.box_spacing = 4
        self.box_spacing_horizontal = 24
        self.magnet = 12
        self.hardware_rack_width = 5

        self.aliases = {}

        self.box = BoxStyleAttributer('.box', self)
        self.portgroup = PortStyleAttributer('.portgroup', self)
        self.port = PortStyleAttributer('.port', self)
        self.line = LineStyleAttributer('.line', self)
        self.wrapper = UnselectedStyleAttributer('.wrapper', self)
        self.rubberband = StyleAttributer('.rubberband', self)
        self.hardware_rack = UnselectedStyleAttributer('.hardware_rack', self)
        self.header_line = UnselectedStyleAttributer('.header_line', self)
        self.monitor_decoration = UnselectedStyleAttributer('.monitor_decoration', self)
        self.gui_button = GuiButtonStyleAttributer('.gui_button', self)
        
        self.subs += ['box', 'portgroup', 'port', 'line', 'wrapper',
                      'rubberband', 'hardware_rack', 'header_line',
                      'monitor_decoration', 'gui_button']
        
    def read_theme(self, theme_dict: dict):
        if not isinstance(theme_dict, dict):
            print_error("invalid dict read error")
            return
        
        self.aliases.clear()
        
        # first read if there are any aliases
        for key, value in theme_dict.items():
            if key != 'aliases':
                continue
            
            if not isinstance(value, dict):
                print_error("'%s' must contains a dictionnary, ignored" % key)
                continue
            
            for alias_key, alias_value in value.items():
                if not isinstance(alias_key, str):
                    print_error("alias key must be a string. Ignore: %s"
                                % str(alias_key))
                    continue
                
                self.aliases[alias_key] = alias_value
            
            break
        
        # read and parse the dict
        for key, value in theme_dict.items():
            if key == 'aliases':
                continue
            
            begin, point, end = key.partition('.')
            
            if not isinstance(value, dict):
                print_error("'%s' must contains a dictionnary, ignored" % key)
                continue
            
            if key == 'body':
                for body_key, body_value in value.items():
                    if body_key in (
                            'port-height', 'port-spacing', 'port-type-spacing',
                            'box-spacing', 'box-spacing-horizontal', 'magnet',
                            'hardware-rack-width', 'port-offset'):
                        if not isinstance(body_value, int):
                            continue
                        self.__setattr__(body_key.replace('-', '_'), body_value)
                    elif body_key == 'background':
                        self.background_color = _to_qcolor(body_value)
                        if self.background_color is None:
                            self.background_color = QColor('black')
                    elif body_key == 'box-shadow-color':
                        self.box_shadow_color = _to_qcolor(body_value)
                        if self.box_shadow_color is None:
                            self.box_shadow_color = QColor('black')
                    elif body_key == 'monitor-color':
                        self.monitor_color = _to_qcolor(body_value)
                        if self.monitor_color is None:
                            self.monitor_color = QColor(190, 158, 0)
                continue
            
            if begin not in self.subs:
                print_error("invalid ignored key: %s" % key)
                continue

            for sub_key, sub_value in value.items():
                for alias_key, alias_value in self.aliases.items():
                    if sub_value == alias_key:
                        value[sub_key] = alias_value
                        break

            sub_attributer = self.__getattribute__(begin)
            sub_attributer.set_style_dict(end, value)


if __name__ == '__main__':
    theme = Theme()
    from .theme_default import default_theme
    theme.read_theme(default_theme)
    print(theme.port.audio.font())
