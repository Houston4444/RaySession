
import sys

from sip import voidptr
from struct import pack
import time

from PyQt5.QtCore import qCritical, Qt, QPoint, QPointF, QRectF, QTimer
from PyQt5.QtGui import (QCursor, QFont, QFontMetrics, QImage,
                         QLinearGradient, QPainter, QPen, QPolygonF,
                         QColor, QIcon, QPixmap, QPainterPath)
from PyQt5.QtWidgets import QGraphicsItem, QMenu, QApplication

# ------------------------------------------------------------------------------------------------------------
# Imports (Custom)

from . import (
    canvas,
    features,
    options,
    CanvasBoxType,
    ACTION_PLUGIN_EDIT,
    ACTION_PLUGIN_SHOW_UI,
    ACTION_PLUGIN_CLONE,
    ACTION_PLUGIN_REMOVE,
    ACTION_PLUGIN_RENAME,
    ACTION_PLUGIN_REPLACE,
    ACTION_GROUP_INFO,
    ACTION_GROUP_JOIN,
    ACTION_GROUP_SPLIT,
    ACTION_GROUP_RENAME,
    ACTION_GROUP_MOVE,
    ACTION_GROUP_WRAP,
    ACTION_PORTS_DISCONNECT,
    ACTION_INLINE_DISPLAY,
    ACTION_CLIENT_SHOW_GUI,
    PORT_MODE_NULL,
    PORT_MODE_INPUT,
    PORT_MODE_OUTPUT,
    PORT_TYPE_NULL,
    PORT_TYPE_AUDIO_JACK,
    PORT_TYPE_MIDI_ALSA,
    PORT_TYPE_MIDI_JACK,
    PORT_TYPE_PARAMETER,
    MAX_PLUGIN_ID_ALLOWED,
    ICON_HARDWARE,
    ICON_INTERNAL,
    ICON_CLIENT,
    DIRECTION_DOWN
)
import patchcanvas.utils as utils
from .canvasboxshadow import CanvasBoxShadow
from .canvasicon import CanvasSvgIcon, CanvasIconPixmap
from .canvasport import CanvasPort
from .canvasportgroup import CanvasPortGroup
from .theme import Theme

from .canvasbox_abstract import (
    CanvasBoxAbstract,
    UNWRAP_BUTTON_NONE,
    UNWRAP_BUTTON_LEFT,
    UNWRAP_BUTTON_CENTER,
    UNWRAP_BUTTON_RIGHT,
    LAYOUT_AUTO,
    LAYOUT_HIGH,
    LAYOUT_LARGE)

_translate = QApplication.translate

TITLE_ON_TOP = 0
TITLE_ON_SIDE = 1
TITLE_ON_SIDE_UNDER_ICON = 2


class TitleLine:
    text = ''
    size = 0
    x = 0
    y = 0
    is_little = False

    def __init__(self, text: str, theme, little=False):
        self.theme = theme
        self.text = text
        self.is_little = little
        self.x = 0
        self.y = 0

        self.font = None
        self.size = theme.get_text_width(text)

    def get_font(self):
        return self.theme.font()


class BoxArea:
    width = 0
    heigth = 0
    header_width = 0
    header_height = 0
    column_mode = LAYOUT_AUTO
    ports_in_width = 0
    ports_out_width = 0
    ports_margin = 30
    height_for_ports = 0
    height_for_ports_one = 0
    title_on_side = False
    
    def __init__(self):
        pass
    
    def area(self) -> float:
        return float(self.width * self.height)
    
    def __lt__(self, other):
        return self.area() < other.area()


class CanvasBox(CanvasBoxAbstract):
    def __init__(self, group_id: int, group_name: str, icon_type: int,
                 icon_name: str, parent=None):
        CanvasBoxAbstract.__init__(
            self, group_id, group_name, icon_type, icon_name, parent)
        self._tmp_port_list = []
        self._tmp_portgrp_list = []
    
    def _get_portgroup_position(self, port_id: int, portgrp_id: int)->tuple:
        if portgrp_id <= 0:
            return (0, 1)

        for portgrp in self._tmp_portgrp_list:
            if portgrp.portgrp_id == portgrp_id:
                for i in range(len(portgrp.port_id_list)):
                    if port_id == portgrp.port_id_list[i]:
                        return (i, len(portgrp.port_id_list))
        return (0, 1)

    def _get_portgroup_name(self, portgrp_id: int):
        return utils.get_portgroup_name_from_ports_names(
            [p.port_name for p in self._tmp_port_list
             if p.portgrp_id == portgrp_id])

    def _should_align_port_types(self, port_types: list) -> bool:
        ''' check if we can align port types
            eg, align first midi input to first midi output '''
        align_port_types = True
        port_types_aligner = []
            
        for port_type in port_types:
            aligner_item = []
            for alternate in (False, True):
                n_ins = 0
                n_outs = 0

                for port in self._tmp_port_list:
                    if (port.port_type == port_type
                            and port.is_alternate == alternate):
                        if port.port_mode == PORT_MODE_INPUT:
                            n_ins += 1
                        elif port.port_mode == PORT_MODE_OUTPUT:
                            n_outs += 1

                port_types_aligner.append((n_ins, n_outs))

        winner = PORT_MODE_NULL

        for n_ins, n_outs in port_types_aligner:
            if ((winner == PORT_MODE_INPUT and n_outs > n_ins)
                    or (winner == PORT_MODE_OUTPUT and n_ins > n_outs)):
                align_port_types = False
                break

            if n_ins > n_outs:
                winner = PORT_MODE_INPUT
            elif n_outs > n_ins:
                winner = PORT_MODE_OUTPUT
        
        return align_port_types
    
    def _get_geometry_dict(
            self, port_types: list, align_port_types: bool) -> dict:
        max_in_width = max_out_width = 0
        last_in_pos = last_out_pos = 0
        final_last_in_pos = final_last_out_pos = last_in_pos
        
        box_theme = self.get_theme()
        port_spacing = box_theme.port_spacing()
        port_offset = box_theme.port_offset()
        port_type_spacing = box_theme.port_type_spacing()
        last_in_type_alter = (PORT_TYPE_NULL, False)
        last_out_type_alter = (PORT_TYPE_NULL, False)
        last_port_mode = PORT_MODE_NULL
        
        for port_type in port_types:
            for alternate in (False, True):
                for port in self._tmp_port_list:
                    if (port.port_type != port_type
                            or port.is_alternate != alternate):
                        continue

                    port_pos, pg_len = self._get_portgroup_position(
                        port.port_id, port.portgrp_id)
                    first_of_portgrp = bool(port_pos == 0)
                    last_of_portgrp = bool(port_pos + 1 == pg_len)
                    size = 0
                    max_pwidth = options.max_port_width

                    if port.portgrp_id:
                        for portgrp in self._tmp_portgrp_list:
                            if not portgrp.portgrp_id == port.portgrp_id:
                                continue
                            
                            if port.port_id == portgrp.port_id_list[0]:
                                portgrp_name = self._get_portgroup_name(port.portgrp_id)

                                portgrp.widget.set_print_name(
                                    portgrp_name,
                                    max_pwidth - canvas.theme.port_grouped_width - 5)
                            
                            port.widget.set_print_name(
                                port.port_name.replace(
                                    self._get_portgroup_name(port.portgrp_id), '', 1),
                                int(max_pwidth/2))
                            
                            if (portgrp.widget.get_text_width() + 5
                                    > max_pwidth - port.widget.get_text_width()):
                                portgrp.widget.reduce_print_name(
                                    max_pwidth - port.widget.get_text_width() - 5)
                            
                            # the port_grouped_width is also used to define
                            # the portgroup minimum width
                            size = (max(portgrp.widget.get_text_width(),
                                        canvas.theme.port_grouped_width)
                                    + max(port.widget.get_text_width() + 6,
                                          canvas.theme.port_grouped_width)
                                    + port_offset)
                            break
                    else:
                        port.widget.set_print_name(port.port_name, max_pwidth)
                        size = max(port.widget.get_text_width() + port_offset, 20)
                    
                    type_alter = (port.port_type, port.is_alternate)
                    
                    if port.port_mode == PORT_MODE_INPUT:
                        max_in_width = max(max_in_width, size)
                        if type_alter != last_in_type_alter:
                            if last_in_type_alter != (PORT_TYPE_NULL, False):
                                last_in_pos += port_type_spacing
                            last_in_type_alter = type_alter

                        last_in_pos += canvas.theme.port_height
                        if last_of_portgrp:
                            last_in_pos += port_spacing

                    elif port.port_mode == PORT_MODE_OUTPUT:
                        max_out_width = max(max_out_width, size)
                        
                        if type_alter != last_out_type_alter:
                            if last_out_type_alter != (PORT_TYPE_NULL, False):
                                last_out_pos += port_type_spacing
                            last_out_type_alter = type_alter
                        
                        last_out_pos += canvas.theme.port_height
                        if last_of_portgrp:
                            last_out_pos += port_spacing
                    
                    final_last_in_pos = last_in_pos
                    final_last_out_pos = last_out_pos
                
                if align_port_types:
                    # align port types horizontally
                    if last_in_pos > last_out_pos:
                        last_out_type_alter = last_in_type_alter
                    else:
                        last_in_type_alter = last_out_type_alter
                    last_in_pos = last_out_pos = max(last_in_pos, last_out_pos)
        
        # calculates height in case of one column only
        last_inout_pos = 0
        last_type_alter = (PORT_TYPE_NULL, False)
        
        for port_type in port_types:
            for alternate in (False, True):
                for port in self._tmp_port_list:
                    if (port.port_type != port_type
                            or port.is_alternate != alternate):
                        continue
                    
                    if (port.port_type, port.is_alternate) != last_type_alter:
                        if last_type_alter != (PORT_TYPE_NULL, False):
                            last_inout_pos += port_type_spacing
                        last_type_alter = (port.port_type, port.is_alternate)
                    
                    port_pos, pg_len = self._get_portgroup_position(
                        port.port_id, port.portgrp_id)
                    if port_pos:
                        continue
                    last_inout_pos += pg_len * canvas.theme.port_height
                    last_inout_pos += port_spacing
                    
                    last_port_mode = port.port_mode
        
        return {'last_in_pos': final_last_in_pos,
                'last_out_pos': final_last_out_pos,
                'last_inout_pos': last_inout_pos,
                'max_in_width': max_in_width,
                'max_out_width': max_out_width,
                'last_port_mode': last_port_mode}

    def _set_ports_y_positions(
            self, port_types: list, align_port_types: bool, start_pos: int,
            one_column: bool) -> dict:
        def set_widget_pos(widget, pos):
            if self._wrapping:
                widget.setY(pos - ((pos - wrapped_port_pos)
                                   * self._wrapping_ratio))
            elif self._unwrapping:
                widget.setY(wrapped_port_pos + ((pos - wrapped_port_pos)
                                                * self._wrapping_ratio))
            elif self._wrapped:
                widget.setY(wrapped_port_pos)
            else:
                widget.setY(pos)
            
        ''' ports Y positioning, and get width informations '''
        max_in_width = max_out_width = 0
        last_in_pos = last_out_pos = start_pos
        final_last_in_pos = final_last_out_pos = last_in_pos
        wrapped_port_pos = start_pos
        
        box_theme = self.get_theme()
        port_spacing = box_theme.port_spacing()
        port_type_spacing = box_theme.port_type_spacing()
        last_in_type_alter = (PORT_TYPE_NULL, False)
        last_out_type_alter = (PORT_TYPE_NULL, False)
        last_type_alter = (PORT_TYPE_NULL, False)
        input_segments = []
        output_segments = []
        in_segment = [last_in_pos, last_in_pos]
        out_segment = [last_out_pos, last_out_pos]
        
        for port_type in port_types:
            for alternate in (False, True):
                for port in self._tmp_port_list:
                    if (port.port_type != port_type
                            or port.is_alternate != alternate):
                        continue
                    
                    if one_column:
                        last_in_pos = last_out_pos = max(last_in_pos, last_out_pos)
                    
                    port_pos, pg_len = self._get_portgroup_position(
                        port.port_id, port.portgrp_id)
                    first_of_portgrp = bool(port_pos == 0)
                    if port.portgrp_id and not first_of_portgrp:
                        continue
                    
                    type_alter = (port.port_type, port.is_alternate)
                    if one_column:
                        if type_alter != last_type_alter:
                            if last_type_alter != (PORT_TYPE_NULL, False):
                                last_in_pos += port_type_spacing
                                last_out_pos += port_type_spacing
                            last_type_alter = type_alter
                    
                    if port.port_mode == PORT_MODE_INPUT:
                        if not one_column and type_alter != last_in_type_alter:
                            if last_in_type_alter != (PORT_TYPE_NULL, False):
                                last_in_pos += port_type_spacing
                            last_in_type_alter = type_alter
                        
                        if last_in_pos >= in_segment[1] + port_spacing + port_type_spacing:
                            if in_segment[0] != in_segment[1]:
                                input_segments.append(in_segment)
                            in_segment = [last_in_pos, last_in_pos]
                        
                        if port.portgrp_id:
                            # we place the portgroup widget and all its ports now
                            # because in one column mode, we can't be sure
                            # that port consecutivity isn't break by a port with
                            # another mode:
                            # 
                            # input L
                            #     output L
                            # input R
                            #     output R
                            for portgrp in self._tmp_portgrp_list:
                                if portgrp.portgrp_id == port.portgrp_id:
                                    if portgrp.widget is not None:
                                        set_widget_pos(portgrp.widget, last_in_pos)
                                
                                    for port_id in portgrp.port_id_list:
                                        for gp_port in self._tmp_port_list:
                                            if gp_port.port_id == port_id:
                                                set_widget_pos(gp_port.widget, last_in_pos)
                                                last_in_pos += canvas.theme.port_height
                                                break
                                    break
                        else:
                            set_widget_pos(port.widget, last_in_pos)
                            last_in_pos += canvas.theme.port_height
                        in_segment[1] = last_in_pos
                        last_in_pos += port_spacing

                    elif port.port_mode == PORT_MODE_OUTPUT:
                        if not one_column and type_alter != last_out_type_alter:
                            if last_out_type_alter != (PORT_TYPE_NULL, False):
                                last_out_pos += port_type_spacing
                            last_out_type_alter = type_alter

                        if last_out_pos >= out_segment[1] + port_spacing + port_type_spacing:
                            if out_segment[0] != out_segment[1]:
                                output_segments.append(out_segment)
                            out_segment = [last_out_pos, last_out_pos]

                        if port.portgrp_id:
                            for portgrp in self._tmp_portgrp_list:
                                if portgrp.portgrp_id == port.portgrp_id:
                                    if portgrp.widget is not None:
                                        set_widget_pos(portgrp.widget, last_out_pos)
                                
                                    for port_id in portgrp.port_id_list:
                                        for gp_port in self._tmp_port_list:
                                            if gp_port.port_id == port_id:
                                                set_widget_pos(gp_port.widget, last_out_pos)
                                                last_out_pos += canvas.theme.port_height
                                                break
                                    break
                        else:
                            set_widget_pos(port.widget, last_out_pos)
                            last_out_pos += canvas.theme.port_height
                        
                        out_segment[1] = last_out_pos
                        last_out_pos += port_spacing
                
                if align_port_types:
                    # align port types horizontally
                    if last_in_pos > last_out_pos:
                        last_out_type_alter = last_in_type_alter
                    else:
                        last_in_type_alter = last_out_type_alter
                    last_in_pos = last_out_pos = max(last_in_pos, last_out_pos)
        
        if in_segment[0] != in_segment[1]:
            input_segments.append(in_segment)
        if out_segment[0] != out_segment[1]:
            output_segments.append(out_segment)
        
        return {'input_segments': input_segments,
                'output_segments': output_segments}
    
    @staticmethod
    def split_in_two(string: str, n_lines=2) -> tuple:
        if n_lines <= 1:
            return (string,)
        
        sep_indexes = []
        last_was_digit = False

        for sep in (' ', '-', '_', 'capital'):
            for i in range(len(string)):
                c = string[i]
                if sep == 'capital':
                    if c.upper() == c:
                        if not c.isdigit() or not last_was_digit:
                            sep_indexes.append(i)
                        last_was_digit = c.isdigit()

                elif c == sep:
                    sep_indexes.append(i)

            if sep_indexes:
                break

        if not sep_indexes:
            # no available separator in given text
            base_count = 6
            divisor = min(int(len(string) / base_count), n_lines)
            if divisor <= 1:
                return (string,)
            
            return_list = []
            c_count = int(len(string)/divisor)
            return tuple([string[start:start + c_count]
                          for start in range(0, len(string), c_count)])
            #return_list.append(string[:int(len(string)/divisor) - 1])
            #start = int(len(string)/divisor)
            
            #for i in range(divisor - 2):
                #return_list.append(string[start:start+len(string)/div
            
            #return (string,)

        if len(sep_indexes) + 1 <= n_lines:
            return_list = []
            last_index = 0

            for sep_index in sep_indexes:
                return_list.append(string[last_index:sep_index])
                last_index = sep_index
                if sep == ' ':
                    last_index += 1

            return_list.append(string[last_index:])

            return tuple(return_list)

        best_indexes = [0]
        string_rest = string
        string_list = []

        for i in range(n_lines, 1, -1):
            target = best_indexes[-1] + int(len(string_rest)/i)
            best_index = 0
            best_dif = len(string)

            for s in sep_indexes:
                if s <= best_indexes[-1]:
                    continue

                dif = abs(target - s)
                if dif < best_dif:
                    best_index = s
                    best_dif = dif
                else:
                    break

            if sep == ' ':
                string_rest = string[best_index+1:]
            else:
                string_rest = string[best_index:]

            best_indexes.append(best_index)

        best_indexes = best_indexes[1:]
        last_index = 0
        return_list = []

        for i in best_indexes:
            return_list.append(string[last_index:i])
            last_index = i
            if sep == ' ':
                last_index += 1

        return_list.append(string[last_index:])
        return tuple([rt for rt in return_list if rt])
    
    def _split_title(self, n_lines: int)->tuple:
        title, slash, subtitle = self._group_name.partition('/')

        if (not subtitle
                and self._icon_type == ICON_CLIENT
                and ' (' in self._group_name
                and self._group_name.endswith(')')):
            title, parenthese, subtitle = self._group_name.partition(' (')
            subtitle = subtitle[:-1]
        
        theme = self.get_theme()

        if self._icon_type == ICON_CLIENT and subtitle:
            # if there is a subtitle, title is not bold when subtitle is.
            # so title is 'little'
            client_line = TitleLine(title, theme, little=True)
            subclient_line = TitleLine(subtitle, theme)
            title_lines = []
            
            if n_lines <= 2:
                title_lines.append(client_line)
                title_lines.append(subclient_line)
            
            else:
                if client_line.size > subclient_line.size:
                    client_strs = self.split_in_two(title)
                    for client_str in client_strs:
                        title_lines.append(TitleLine(client_str, theme, little=True))
                    
                    for subclient_str in self.split_in_two(subtitle, n_lines - 2):
                        title_lines.append(TitleLine(subclient_str, theme))
                else:
                    two_lines_title = False
                    
                    if n_lines >= 4:
                        # Check if we need to split the client title
                        # it could be "Carla-Multi-Client.Carla".
                        subtitles = self.split_in_two(subtitle, n_lines - 2)

                        for subtt in subtitles:
                            subtt_line = TitleLine(subtt, theme)
                            if subtt_line.size > client_line.size:
                                break
                        else:
                            client_strs = self.split_in_two(title)
                            for client_str in client_strs:
                                title_lines.append(
                                    TitleLine(client_str, theme, little=True))
                            two_lines_title = True
                    
                    if not two_lines_title:
                        title_lines.append(client_line)
                    
                    subt_len = n_lines - 1
                    if two_lines_title:
                        subt_len -= 1
                        titles = self.split_in_two(subtitle, subt_len)
                        for title in titles:
                            title_lines.append(TitleLine(title, theme))
                    else:
                        titles = self.split_in_two('uuuu' + subtitle, subt_len)

                        for i in range(len(titles)):
                            title = titles[i]
                            if i == 0:
                                title = title[4:]
                            title_lines.append(TitleLine(title, theme))
        else:
            if n_lines >= 2:
                titles = self.split_in_two(self._group_name, n_lines)
                
                new_titles = list(titles)
                
                if len(titles) < n_lines:
                    biggest = ''
                    for title in titles:
                        if len(title) > len(biggest):
                            biggest = title
                
                    new_titles.clear()
                    for title in titles:
                        if title == biggest:
                            biggest = ''
                            new_titles += list(self.split_in_two(title, 2))
                        else:
                            new_titles.append(title)
                
                #new_titles = []
                #for title in titles:
                    #if new_titles and len(title) <= 2:
                        #new_titles[-1] += title
                    #else:
                        #new_titles.append(title)
                
                title_lines = [
                    TitleLine(tt, theme)
                    for tt in new_titles if tt]
            else:
                title_lines = [TitleLine(self._group_name, theme)]

        return tuple(title_lines)
    
    def _choose_title_disposition(
        self, height_for_ports: int, height_for_ports_one: int,
        ports_in_width: int, ports_out_width: int) -> dict:
        ''' choose in how many lines should be splitted the title
        returns needed more_height '''

        laout_times = {}
        laou_start = time.time()

        width_for_ports = 30 + ports_in_width + ports_out_width
        width_for_ports_one = 30 + max(ports_in_width, ports_out_width)

        ports_width = ports_in_width
        if self._current_port_mode == PORT_MODE_OUTPUT:
            ports_width = ports_out_width

        box_theme = self.get_theme()
        font_size = box_theme.font().pixelSize()

        # Check Text Name size
        all_title_templates = box_theme.get_title_templates(
            self._group_name, self._can_handle_gui)
        lines_choice_max = len(all_title_templates) - 1
        
        laout_times['bef parse templates'] = time.time() - laou_start
        
        if not all_title_templates:
            title_template = {
                "title_width": 0, "header_width": 0, "header_height": 0}
            all_title_templates = [title_template.copy() for i in range(8)]

            last_lines_count = 0

            for i in range(1, 8):
                max_title_size = 0
                max_header_width = 50
                if self._plugin_inline != self.INLINE_DISPLAY_DISABLED:
                    max_header_width = 200
                
                laout_times['beff splitti' + str(i)] = time.time() - laou_start
                title_lines = self._split_title(i)
                laout_times['aftt splitti' + str(i)] = time.time() - laou_start
                laout_times['tilles' + str(i)] = [tt.text for tt in title_lines]
                
                title_line_y_start = 2 + font_size
                gui_margin = 2

                for j in range(len(title_lines)):
                    title_line = title_lines[j]
                    title_line.y = title_line_y_start + j * int(font_size * 1.4)
                    max_title_size = max(max_title_size, title_line.size)
                    header_width = title_line.size + 12

                    if self.has_top_icon() and title_line.y <= 28 + font_size:
                        header_width += 28

                    max_header_width = max(max_header_width, header_width)
                
                header_height = 2 + font_size + 2
                if self.has_top_icon():
                    header_height = 4 + 24 + 4
                
                header_height = max(
                    header_height,
                    2 + font_size + int(font_size * 1.4) * (len(title_lines) - 1) + 2 + 5)
                
                if self._can_handle_gui:
                    max_header_width += 2 * gui_margin
                    header_height += 2 * gui_margin

                new_title_template = title_template.copy()
                new_title_template['title_width'] = max_title_size
                new_title_template['header_width'] = max_header_width
                new_title_template['header_height'] = header_height
                all_title_templates[i] = new_title_template

                if i > 2 and len(title_lines) <= last_lines_count:
                    break

                last_lines_count = len(title_lines)

            lines_choice_max = i
            box_theme.save_title_templates(
                self._group_name, self._can_handle_gui, all_title_templates[:lines_choice_max])

        laout_times['after parse tempts'] = time.time() - laou_start

        sizes_tuples = []
        
        layout_mode = self._get_layout_mode_for_this()
        
        if self._current_port_mode in (PORT_MODE_INPUT, PORT_MODE_OUTPUT):
            # splitted box
            
            if layout_mode in (LAYOUT_AUTO, LAYOUT_LARGE):
                ports_y_start_min = box_theme.port_spacing() + box_theme.port_type_spacing()
                
                # calculate area with title on side
                for i in range(1, lines_choice_max + 1):
                    sizes_tuples.append(
                        ((ports_width + all_title_templates[i]['header_width'])
                        * max(all_title_templates[i]['header_height'],
                            height_for_ports + ports_y_start_min),
                        i, False, TITLE_ON_SIDE))
                        
                # calculate area with title on side (title under the icon)
                for i in range(1, lines_choice_max + 1):
                    sizes_tuples.append(
                        ((ports_width + all_title_templates[i]['title_width'] + 16)
                        * max(all_title_templates[i]['header_height'] + 28,
                            height_for_ports + ports_y_start_min),
                        i, False, TITLE_ON_SIDE_UNDER_ICON))
            
            if layout_mode in (LAYOUT_AUTO, LAYOUT_HIGH):
                # calculate area with title on top
                for i in range(1, lines_choice_max + 1):
                    sizes_tuples.append(
                        (max(all_title_templates[i]['header_width'], width_for_ports)
                        * (all_title_templates[i]['header_height'] + height_for_ports),
                        i, False, TITLE_ON_TOP))
        else:
            # grouped box
            
            # calculate area with input and outputs ports descending
            if layout_mode in (LAYOUT_AUTO, LAYOUT_HIGH):
                for i in range(1, lines_choice_max + 1):
                    sizes_tuples.append(
                        (max(all_title_templates[i]['header_width'], width_for_ports_one)
                        * (all_title_templates[i]['header_height'] + height_for_ports_one),
                        i, True, TITLE_ON_TOP))

            # calculate area with input ports at left of output ports
            if layout_mode in (LAYOUT_AUTO, LAYOUT_LARGE):
                for i in range(1, lines_choice_max + 1):
                    sizes_tuples.append(
                        (max(all_title_templates[i]['header_width'], width_for_ports)
                        * (all_title_templates[i]['header_height'] + height_for_ports),
                        i, False, TITLE_ON_TOP))
        
        laout_times['after make size tuples'] = time.time() - laou_start
        
        # sort areas and choose the first one (the littlest area)
        #print('tt', self._group_name, self._current_port_mode, sizes_tuples)
        sizes_tuples.sort()
        area_size, lines_choice, one_column, title_on_side = sizes_tuples[0]
        
        self._title_lines = self._split_title(lines_choice)
        
        header_height = all_title_templates[lines_choice]['header_height']
        header_width = all_title_templates[lines_choice]['header_width']
        max_title_size = all_title_templates[lines_choice]['title_width']
        
        if self._current_port_mode == PORT_MODE_INPUT + PORT_MODE_OUTPUT:
            if one_column:
                self._current_layout_mode = LAYOUT_HIGH
            else:
                self._current_layout_mode = LAYOUT_LARGE
        else:
            if title_on_side:
                self._current_layout_mode = LAYOUT_LARGE
            else:
                self._current_layout_mode = LAYOUT_HIGH
        
        box_width = 0
        box_height = 0
        ports_y_start = header_height

        self._title_on_side = bool(title_on_side)
        self._title_under_icon = bool(title_on_side == TITLE_ON_SIDE_UNDER_ICON)

        if title_on_side:
            box_width = ports_width + 12 + header_width
            ports_y_start = box_theme.port_spacing() + box_theme.port_type_spacing()
            box_height = max(height_for_ports + ports_y_start, header_height)
            
            if title_on_side == TITLE_ON_SIDE_UNDER_ICON:
                header_width = max(38, max_title_size + 12)
                if self._can_handle_gui:
                    header_width += 4

                box_width = ports_width + header_width + 12
                header_height += 15 if len(self._title_lines) == 1 else 30
                box_height = max(height_for_ports + ports_y_start, header_height)

            ports_y_start = max(ports_y_start, header_height - height_for_ports)

        elif one_column:
            box_width = max(width_for_ports_one, header_width)
            box_height = header_height + height_for_ports_one
        else:
            box_width = max(width_for_ports, header_width)
            box_height = header_height + height_for_ports
        
        laout_times['ennkd'] = time.time() - laou_start
        
        #for key, value in laout_times.items():
            #print('    ', key, ':', value)
            
        
        return {'max_title_size': max_title_size,
                'box_height': box_height,
                'box_width': box_width,
                'header_width': header_width,
                'header_height': header_height,
                'ports_y_start': ports_y_start,
                'one_column': one_column}
    
    def _set_ports_x_positions(self, max_in_width: int, max_out_width: int):
        box_theme = self.get_theme()
        port_offset = box_theme.port_offset()
        
        # Horizontal ports re-positioning
        inX = port_offset
        outX = self._width - max_out_width - 12

        # Horizontal ports not in portgroup re-positioning
        for port in self._tmp_port_list:
            if port.portgrp_id:
                continue

            if port.port_mode == PORT_MODE_INPUT:
                port.widget.setX(inX)
                port.widget.set_port_width(max_in_width - port_offset)
            elif port.port_mode == PORT_MODE_OUTPUT:
                port.widget.setX(outX)
                port.widget.set_port_width(max_out_width - port_offset)

        # Horizontal portgroups and ports in portgroup re-positioning
        for portgrp in self._tmp_portgrp_list:
            if portgrp.widget is not None:
                if portgrp.port_mode == PORT_MODE_INPUT:
                    portgrp.widget.set_portgrp_width(max_in_width - port_offset)
                    portgrp.widget.setX(box_theme.port_offset() +1)
                elif portgrp.port_mode == PORT_MODE_OUTPUT:
                    portgrp.widget.set_portgrp_width(max_out_width - port_offset)
                    portgrp.widget.setX(outX)

            max_port_in_pg_width = canvas.theme.port_grouped_width

            for port in self._tmp_port_list:
                if (port.port_id in portgrp.port_id_list
                        and port.widget is not None):
                    port_print_width = port.widget.get_text_width()

                    # change port in portgroup width only if
                    # portgrp will have a name
                    # to ensure that portgroup widget is large enough
                    max_port_in_pg_width = max(max_port_in_pg_width,
                                               port_print_width + 4)

            out_in_portgrpX = (self._width - box_theme.port_offset() - 12
                               - max_port_in_pg_width)

            portgrp.widget.set_ports_width(max_port_in_pg_width)

            for port in self._tmp_port_list:
                if (port.port_id in portgrp.port_id_list
                        and port.widget is not None):
                    port.widget.set_port_width(max_port_in_pg_width)
                    if port.port_mode == PORT_MODE_INPUT:
                        port.widget.setX(inX)
                    elif port.port_mode == PORT_MODE_OUTPUT:
                        port.widget.setX(out_in_portgrpX)
    
    def _set_title_positions(self):
        ''' set title lines, header lines and icon positions '''
        self._header_line_left = None
        self._header_line_right = None

        box_theme = self.get_theme()
        font_size = box_theme.font().pixelSize()
        font_spacing = int(font_size * 1.4)
        # when client is client capable of gui state
        # header has margins
        gui_margin = 2 if self._can_handle_gui else 0
        
        # set title lines Y position
        title_y_start = font_size + 2 + gui_margin

        if self._title_under_icon:
            title_y_start = 4 + gui_margin + 24 + font_spacing
        
        for i in range(len(self._title_lines)):
            title_line = self._title_lines[i]
            title_line.y = title_y_start + i * font_spacing
        
        if not self._title_under_icon and len(self._title_lines) == 1:
            self._title_lines[0].y = int(
                (self._header_height - font_size) / 2 + font_size -2)
        
        if self._has_side_title():
            y_correction = 0

            # In case the title is near to be vertically centered in the box
            # It's prettier to center it correctly
            if (self._title_lines
                    and not self._title_under_icon
                    and not self._can_handle_gui
                    and self._title_lines[-1].y + int(font_size * 1.4) > self._height):
                y_correction = int((self._height - self._title_lines[-1].y - 2) / 2 - 2)
            
            # set title lines pos
            for title_line in self._title_lines:
                if self._current_port_mode == PORT_MODE_INPUT:
                    title_line.x = 4 + self._width - self._header_width + 2
                    if self._can_handle_gui:
                        title_line.x += 2
                    
                    if self.has_top_icon():
                        self.top_icon.set_pos(self._width - 28 - gui_margin,
                                              4 + gui_margin)
    
                elif self._current_port_mode == PORT_MODE_OUTPUT:
                    title_line.x = (self._header_width
                                    - title_line.size - 6)
                    
                    if self._can_handle_gui:
                        title_line.x -= 2
                    
                    if self.has_top_icon():
                        self.top_icon.set_pos(4 + gui_margin, 4 + gui_margin)
                
                title_line.y += y_correction
            return

        # Now we are sure title is on top

        # get title global sizes
        max_title_size = 0
        max_title_icon_size = 0

        for title_line in self._title_lines:
            title_size = title_line.size
            if self.has_top_icon() and title_line.y <= 28 + font_size:
                # title line is beside icon
                title_size += 28
                max_title_icon_size = max(max_title_icon_size, title_size)
            max_title_size = max(max_title_size, title_size)
        
        # set title lines X position
        for title_line in self._title_lines:
            if self.has_top_icon() and title_line.y <= 28 + font_size:
                # title line is beside the icon
                title_line.x = int((self._width - max_title_icon_size) / 2 + 28)
            else:
                title_line.x = int((self._width - title_line.size) / 2)
        
        # set icon position
        if self.has_top_icon():
            self.top_icon.set_pos(int((self._width - max_title_icon_size)/2),
                                  4 + gui_margin)
        
        # calculate header lines positions
        side_size = int((self._width - max(max_title_icon_size, max_title_size)) / 2)
        
        if side_size > 10:
            y = int(self._header_height / 2)
            
            self._header_line_left = (5, y, side_size - 5, y)
            self._header_line_right = (self._width - side_size + 5, y, self._width - 5, y)
    
    def build_painter_path(self, pos_dict):
        input_segments = pos_dict['input_segments']
        output_segments = pos_dict['output_segments']
        
        painter_path = QPainterPath()
        theme = self.get_theme()
        border_radius = theme.border_radius()
        port_offset = theme.port_offset()
        pen = theme.fill_pen()
        line_hinting = pen.widthF() / 2.0
        
        # theses values are needed to prevent some incorrect painter_path
        # united or subtracted results
        epsy = 0.001
        epsd = epsy * 2.0
        
        rect = QRectF(0.0, 0.0, self._width, self._height)
        rect.adjust(line_hinting, line_hinting, -line_hinting, -line_hinting)
        
        if border_radius == 0.0:
            painter_path.addRect(rect)
        else:
            painter_path.addRoundedRect(rect, border_radius, border_radius)
        
        if not (self._wrapping or self._unwrapping or self._wrapped):
            if port_offset != 0.0:
                # substract rects in the box shape in case of port_offset (even negativ)
                # logic would want to add rects if port_offset is negativ
                # But that also means that we should change the boudingRect,
                # So we won't.
                port_offset = abs(port_offset)
                for in_segment in input_segments:
                    moins_path = QPainterPath()
                    moins_path.addRect(QRectF(
                        0.0 - epsy,
                        in_segment[0] - line_hinting - epsy,
                        port_offset + line_hinting + epsd,
                        in_segment[1] - in_segment[0] + line_hinting * 2 + epsd))
                    painter_path = painter_path.subtracted(moins_path)
                    
                for out_segment in output_segments:
                    moins_path = QPainterPath()
                    moins_path.addRect(QRectF(
                        self._width - line_hinting - port_offset - epsy,
                        out_segment[0] - line_hinting - epsy,
                        port_offset + line_hinting + epsd,
                        out_segment[1] - out_segment[0] + line_hinting * 2 + epsd))
                    painter_path = painter_path.subtracted(moins_path)

            # No rounded corner if the last port is to close from the corner
            if (input_segments
                    and self._height - input_segments[-1][1] <= border_radius):
                left_path = QPainterPath()
                left_path.addRect(QRectF(
                    0.0 + line_hinting - epsy,
                    max(self._height - border_radius, input_segments[-1][1]) + line_hinting - epsy,
                    border_radius + epsd,
                    min(border_radius, self._height - input_segments[-1][1])
                    - 2 * line_hinting + epsd))
                painter_path = painter_path.united(left_path)

            if (input_segments
                    and input_segments[0][0] <= border_radius):
                top_left_path = QPainterPath()
                top_left_path.addRect(QRectF(
                    0.0 + line_hinting - epsy,
                    0.0 + line_hinting - epsy,
                    border_radius + epsd,
                    min(border_radius, input_segments[0][0])
                    - 2 * line_hinting + epsd))
                painter_path = painter_path.united(top_left_path)

            if (output_segments
                    and self._height - output_segments[-1][1] <= border_radius):
                right_path = QPainterPath()
                right_path.addRect(QRectF(
                    self._width - border_radius - line_hinting - epsy,
                    max(self._height - border_radius, output_segments[-1][1]) + line_hinting - epsy,
                    border_radius + epsd,
                    min(border_radius, self._height - output_segments[-1][1]) - 2 * line_hinting + epsd))
                painter_path = painter_path.united(right_path)
                
            if (output_segments
                    and output_segments[0][0] <= border_radius):
                top_right_path = QPainterPath()
                top_right_path.addRect(QRectF(
                    self._width - line_hinting + epsy - border_radius,
                    0.0 + line_hinting - epsy,
                    border_radius + epsd,
                    min(border_radius, output_segments[0][0])
                    - 2 * line_hinting + epsd))
                painter_path = painter_path.united(top_right_path)
            

        if self._group_name.endswith(' Monitor') and border_radius:
            left_path = QPainterPath()
            left_path.addRect(QRectF(
                0.0 + line_hinting - epsy,
                self._height - border_radius - epsy,
                border_radius + epsd, border_radius - line_hinting + epsd))
            painter_path = painter_path.united(left_path)

            top_left_path = QPainterPath()
            top_left_path.addRect(QRectF(
                0.0 + line_hinting - epsy, 0.0 + line_hinting - epsy,
                border_radius + epsd, border_radius - line_hinting + epsd))
            painter_path = painter_path.united(top_left_path)

        self._painter_path = painter_path
        
    def update_positions(self, even_animated=False, without_connections=False):
        if canvas.loading_items:
            return

        if (not even_animated
                and self in [b['widget'] for b in canvas.scene.move_boxes]):
            # do not change box disposition while box is moved by animation
            # update_positions will be called when animation is finished
            return

        self.prepareGeometryChange()
        
        self._current_port_mode = PORT_MODE_NULL
        self._tmp_port_list.clear()
        self._tmp_portgrp_list.clear()
        
        for port in canvas.port_list:
            if port.group_id == self._group_id and port.port_id in self._port_list_ids:
                # used to know present port modes (INPUT or OUTPUT or both)
                self._tmp_port_list.append(port)
                self._current_port_mode |= port.port_mode
                
        for portgrp in canvas.portgrp_list:
            if (portgrp.group_id == self._group_id
                    and self._current_port_mode & portgrp.port_mode):
                self._tmp_portgrp_list.append(portgrp)

        port_types = [PORT_TYPE_AUDIO_JACK, PORT_TYPE_MIDI_JACK,
                      PORT_TYPE_MIDI_ALSA, PORT_TYPE_PARAMETER]
    
        align_port_types = self._should_align_port_types(port_types)

        geo_dict = self._get_geometry_dict(port_types, align_port_types)
        last_in_pos = geo_dict['last_in_pos']
        last_out_pos = geo_dict['last_out_pos']
        last_inout_pos = geo_dict['last_inout_pos']
        max_in_width = geo_dict['max_in_width']
        max_out_width = geo_dict['max_out_width']
        last_port_mode = geo_dict['last_port_mode']
        
        box_theme = self.get_theme()
        down_height = box_theme.fill_pen().widthF()
        height_for_ports = max(last_in_pos, last_out_pos) + down_height
        height_for_ports_one = last_inout_pos + down_height
       
        self._width_in = max_in_width
        self._width_out = max_out_width

        if not (self._wrapping or self._unwrapping):
            titles_dict = self._choose_title_disposition(
                height_for_ports, height_for_ports_one,
                max_in_width, max_out_width)
            max_title_size = titles_dict['max_title_size']
            self._header_width = titles_dict['header_width']
            self._header_height = titles_dict['header_height']
            one_column = titles_dict['one_column']
            box_width = titles_dict['box_width']
            box_height = titles_dict['box_height']
            self._ports_y_start = titles_dict['ports_y_start']

            self._width = box_width
        
            # wrapped/unwrapped sizes
            normal_height = box_height
            normal_width = box_width
            wrapped_height = self._ports_y_start + canvas.theme.port_height
            wrapped_width = self._width
            
            if self._title_on_side:
                wrapped_height = self._header_height
                if self._current_port_mode == PORT_MODE_INPUT:
                    wrapped_width -= self._width_in
                elif self._current_port_mode == PORT_MODE_OUTPUT:
                    wrapped_width -= self._width_out
            
        else:
            normal_height = self._unwrapped_height
            normal_width = self._unwrapped_width
            wrapped_height = self._wrapped_height
            wrapped_width = self._wrapped_width
            
            one_column = bool(
                self._current_port_mode == PORT_MODE_OUTPUT + PORT_MODE_INPUT
                and self._current_layout_mode == LAYOUT_HIGH)
            
        last_in_pos += self._ports_y_start
        last_out_pos += self._ports_y_start

        if self._wrapping:
            self._height = (normal_height
                            - (normal_height - wrapped_height)
                              * self._wrapping_ratio)
            self._width = (normal_width
                           - (normal_width - wrapped_width)
                             * self._wrapping_ratio)

        elif self._unwrapping:
            self._height = (wrapped_height
                            + (normal_height - wrapped_height)
                              * self._wrapping_ratio)
            self._width = (wrapped_width
                           + (normal_width - wrapped_width)
                             * self._wrapping_ratio)

        elif self._wrapped:
            self._height = wrapped_height
            self._width = wrapped_width
        else:
            self._height = normal_height
            self._width = normal_width
            
            self._unwrap_triangle_pos = UNWRAP_BUTTON_NONE
            if self._height - self._header_height >= 64:
                y_side_space = last_in_pos - last_out_pos
                
                if one_column and last_port_mode == PORT_MODE_INPUT:
                    self._unwrap_triangle_pos = UNWRAP_BUTTON_RIGHT
                elif one_column and last_port_mode == PORT_MODE_OUTPUT:
                    self._unwrap_triangle_pos = UNWRAP_BUTTON_LEFT
                elif y_side_space < -10:
                    self._unwrap_triangle_pos = UNWRAP_BUTTON_LEFT
                elif y_side_space > 10:
                    self._unwrap_triangle_pos = UNWRAP_BUTTON_RIGHT
                else:
                    self._unwrap_triangle_pos = UNWRAP_BUTTON_CENTER

        self._wrapped_width = wrapped_width
        self._unwrapped_width = normal_width
        self._wrapped_height = wrapped_height
        self._unwrapped_height = normal_height

        # round self._height to the upper value
        self._height = float(int(self._height + 0.99))

        ports_y_segments_dict = self._set_ports_y_positions(
            port_types, align_port_types,
            self._ports_y_start,
            one_column)
        
        self._set_ports_x_positions(max_in_width, max_out_width)
        
        self._set_title_positions()
        if (self._width != self._ex_width
                or self._height != self._ex_height
                or ports_y_segments_dict != self._ex_ports_y_segments_dict):
            self.build_painter_path(ports_y_segments_dict)

        if (self._width != self._ex_width
                or self._height != self._ex_height
                or self.scenePos() != self._ex_scene_pos):
            canvas.scene.resize_the_scene()

        self._ex_width = self._width
        self._ex_height = self._height
        self._ex_ports_y_segments_dict = ports_y_segments_dict
        self._ex_scene_pos = self.scenePos()

        if not without_connections:
            self.repaint_lines(forced=True)

        if not (self._wrapping or self._unwrapping) and self.isVisible():
            canvas.scene.deplace_boxes_from_repulsers([self])

        self.update()
            
