
import sys

from sip import voidptr
from struct import pack

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

from .canvasbox_abstract import CanvasBoxAbstract

_translate = QApplication.translate

UNWRAP_BUTTON_NONE = 0
UNWRAP_BUTTON_LEFT = 1
UNWRAP_BUTTON_CENTER = 2
UNWRAP_BUTTON_RIGHT = 3


class CanvasBox(CanvasBoxAbstract):
    def __init__(self, group_id: int, group_name: str, icon_type: int,
                 icon_name: str, parent=None):
        CanvasBoxAbstract.__init__(
            self, group_id, group_name, icon_type, icon_name, parent)
    
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

                for port in canvas.port_list:
                    if (port.group_id != self._group_id
                            or port.port_id not in self._port_list_ids):
                        continue

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
    
    def _set_ports_y_and_get_max_widths(
        self, port_types: list, align_port_types: bool) -> dict:
        ''' ports Y positioning, and get width informations '''
        max_in_width = max_out_width = 0
        last_in_pos = last_out_pos = self._default_header_height
        final_last_in_pos = final_last_out_pos = last_in_pos
        wrapped_port_pos = self._default_header_height
        
        box_theme = self.get_theme()
        port_spacing = canvas.theme.port_height + box_theme.port_spacing()
        last_in_type = last_out_type = PORT_TYPE_NULL
        last_in_alter = last_out_alter = False
        
        for port_type in port_types:
            for alternate in (False, True):
                for port in canvas.port_list:
                    if (port.group_id != self._group_id
                            or port.port_id not in self._port_list_ids
                            or port.port_type != port_type
                            or port.is_alternate != alternate):
                        continue
                    
                    ## uncomment this block to enable
                    ## inputs and outputs in down order
                    ## to win space in some cases
                    #last_in_pos = last_out_pos = max(last_in_pos, last_out_pos)
                    
                    port_pos, pg_len = utils.get_portgroup_position(
                        self._group_id, port.port_id, port.portgrp_id)
                    first_of_portgrp = bool(port_pos == 0)
                    last_of_portgrp = bool(port_pos + 1 == pg_len)
                    size = 0

                    max_pwidth = options.max_port_width

                    if port.portgrp_id:
                        for portgrp in canvas.portgrp_list:
                            if not (portgrp.group_id == self._group_id
                                    and portgrp.portgrp_id == port.portgrp_id):
                                continue
                            
                            if port.port_id == portgrp.port_id_list[0]:
                                portgrp_name = utils.get_portgroup_name(
                                    self._group_id, portgrp.port_id_list)

                                if portgrp_name:
                                    portgrp.widget.set_print_name(
                                        portgrp_name,
                                        max_pwidth - canvas.theme.port_grouped_width - 5)
                                else:
                                    portgrp.widget.set_print_name('', 0)
                            
                            port.widget.set_print_name(
                                utils.get_port_print_name(
                                    self._group_id, port.port_id, port.portgrp_id),
                                int(max_pwidth/2))

                            if (portgrp.widget.get_text_width() + 5
                                    > max_pwidth - port.widget.get_text_width()):
                                portgrp.widget.reduce_print_name(
                                    max_pwidth - port.widget.get_text_width() - 5)

                            size = portgrp.widget.get_text_width() \
                                   + max(port.widget.get_text_width() + 6,
                                         canvas.theme.port_grouped_width) \
                                   + box_theme.port_offset()
                            break
                    else:
                        port.widget.set_print_name(port.port_name, max_pwidth)
                        size = max(port.widget.get_text_width() + box_theme.port_offset(), 20)

                    if port.port_mode == PORT_MODE_INPUT:
                        max_in_width = max(max_in_width, size)
                        if (port.port_type != last_in_type
                                or port.is_alternate != last_in_alter):
                            if last_in_type != PORT_TYPE_NULL:
                                last_in_pos += box_theme.port_type_spacing()
                            last_in_type = port.port_type
                            last_in_alter = port.is_alternate

                        if self._wrapping:
                            port.widget.setY(last_in_pos
                                             - ((last_in_pos - wrapped_port_pos)
                                                * self._wrapping_ratio))
                        elif self._unwrapping:
                            port.widget.setY(wrapped_port_pos
                                             + ((last_in_pos - wrapped_port_pos)
                                                * self._wrapping_ratio))
                        elif self._wrapped:
                            port.widget.setY(wrapped_port_pos)
                        else:
                            port.widget.setY(last_in_pos)

                        if port.portgrp_id and first_of_portgrp:
                            for portgrp in canvas.portgrp_list:
                                if (portgrp.group_id == self._group_id
                                        and portgrp.portgrp_id == port.portgrp_id):
                                    if portgrp.widget is not None:
                                        if self._wrapped:
                                            portgrp.widget.setY(wrapped_port_pos)
                                        else:
                                            portgrp.widget.setY(last_in_pos)
                                    break

                        if last_of_portgrp:
                            last_in_pos += port_spacing
                        else:
                            last_in_pos += canvas.theme.port_height

                    elif port.port_mode == PORT_MODE_OUTPUT:
                        max_out_width = max(max_out_width, size)
                        if (port.port_type != last_out_type
                                or port.is_alternate != last_out_alter):
                            if last_out_type != PORT_TYPE_NULL:
                                last_out_pos += box_theme.port_type_spacing()
                            last_out_type = port.port_type
                            last_out_alter = port.is_alternate

                        if self._wrapping:
                            port.widget.setY(last_out_pos
                                             - ((last_out_pos - wrapped_port_pos)
                                                * self._wrapping_ratio))
                        elif self._unwrapping:
                            port.widget.setY(wrapped_port_pos
                                             + ((last_out_pos - wrapped_port_pos)
                                                * self._wrapping_ratio))
                        elif self._wrapped:
                            port.widget.setY(wrapped_port_pos)
                        else:
                            port.widget.setY(last_out_pos)

                        if port.portgrp_id and first_of_portgrp:
                            for portgrp in canvas.portgrp_list:
                                if (portgrp.group_id == self._group_id
                                        and portgrp.portgrp_id == port.portgrp_id):
                                    if portgrp.widget is not None:
                                        if self._wrapped:
                                            portgrp.widget.setY(wrapped_port_pos)
                                        else:
                                            portgrp.widget.setY(last_out_pos)
                                    break

                        if last_of_portgrp:
                            last_out_pos += port_spacing
                        else:
                            last_out_pos += canvas.theme.port_height
                
                    final_last_in_pos = last_in_pos
                    final_last_out_pos = last_out_pos
                
                if align_port_types:
                    # align port types horizontally
                    if last_in_pos > last_out_pos:
                        last_out_type = last_in_type
                        last_out_alter = last_in_alter
                    else:
                        last_in_type = last_out_type
                        last_in_alter = last_out_alter
                    last_in_pos = last_out_pos = max(last_in_pos, last_out_pos)
        
        return {'last_in_pos': final_last_in_pos,
                'last_out_pos': final_last_out_pos,
                'max_in_width': max_in_width,
                'max_out_width': max_out_width}
    
    def _choose_title_disposition(self, box_height: int, width_for_ports: int) -> dict:
        ''' choose in how many lines should be splitted the title
        returns needed more_height '''

        # Check Text Name size
        title_template = {"title_width": 0, "header_width": 0}
        all_title_templates = [title_template.copy() for i in range(5)]

        for i in range(1, 5):
            max_title_size = 0
            title_lines = self._split_title(i)

            for title_line in title_lines:
                max_title_size = max(max_title_size, title_line.size)

            all_title_templates[i]
            header_width = max_title_size

            if self.has_top_icon():
                header_width += 37
            else:
                header_width += 16

            header_width =  max(200 if self._plugin_inline != self.INLINE_DISPLAY_DISABLED else 50,
                                header_width)

            new_title_template = title_template.copy()
            new_title_template['title_width'] = max_title_size
            new_title_template['header_width'] = header_width
            all_title_templates[i] = new_title_template

            if header_width < width_for_ports:
                break

        more_height = 0
        lines_choice = 1

        if all_title_templates[1]['header_width'] <= width_for_ports:
            # One line title is shorter than the box, choose it
            lines_choice = 1
        elif all_title_templates[2]['header_width'] <= width_for_ports:
            # Two lines title is shorter than the box, choose it
            lines_choice = 2
        else:
            more_height = 14
            area_2 = all_title_templates[2]['header_width'] * box_height
            area_3 = (max(width_for_ports, all_title_templates[3]['header_width'])
                      * (box_height + more_height))

            if area_2 <= area_3:
                # Box area is smaller with 2 lines titles than with 3 lines title
                # choose 2 lines title
                lines_choice = 2
                more_height = 0

            elif all_title_templates[3]['header_width'] <= width_for_ports:
                # 3 lines title is shorter than the box, choose it
                lines_choice = 3
            else:
                area_4 = (max(width_for_ports, all_title_templates[4]['header_width'])
                          * (box_height + more_height))

                if area_3 - area_4 >= 5000:
                    lines_choice = 4
                else:
                    lines_choice = 3

        self._title_lines = self._split_title(lines_choice)
        
        header_width = all_title_templates[lines_choice]['header_width']
        max_title_size = all_title_templates[lines_choice]['title_width']
        return {'max_title_size': max_title_size,
                'header_width': header_width,
                'more_height': more_height}
    
    def _push_down_ports(self, down_height: int):
        # down ports
        for port in canvas.port_list:
            if (port.group_id == self._group_id
                    and port.port_id in self._port_list_ids):
                port.widget.setY(port.widget.y() + down_height)

        # down portgroups
        for portgrp in canvas.portgrp_list:
            if (portgrp.group_id == self._group_id
                    and self._current_port_mode & portgrp.port_mode):
                if portgrp.widget is not None:
                    portgrp.widget.setY(portgrp.widget.y() + down_height)
    
    def _set_ports_x_positions(self, max_in_width: int, max_out_width: int):
        box_theme = self.get_theme()
        port_offset = box_theme.port_offset()
        
        # Horizontal ports re-positioning
        inX = port_offset
        outX = self._width - max_out_width - 12

        # Horizontal ports not in portgroup re-positioning
        for port in canvas.port_list:
            if (port.group_id != self._group_id
                    or port.port_id not in self._port_list_ids
                    or port.portgrp_id):
                continue

            if port.port_mode == PORT_MODE_INPUT:
                port.widget.setX(inX)
                port.widget.set_port_width(max_in_width - port_offset)
            elif port.port_mode == PORT_MODE_OUTPUT:
                port.widget.setX(outX)
                port.widget.set_port_width(max_out_width - port_offset)

        # Horizontal portgroups and ports in portgroup re-positioning
        for portgrp in canvas.portgrp_list:
            if (portgrp.group_id != self._group_id
                    or not self._current_port_mode & portgrp.port_mode):
                continue

            if portgrp.widget is not None:
                if portgrp.port_mode == PORT_MODE_INPUT:
                    portgrp.widget.set_portgrp_width(max_in_width - port_offset)
                    portgrp.widget.setX(box_theme.port_offset() +1)
                elif portgrp.port_mode == PORT_MODE_OUTPUT:
                    portgrp.widget.set_portgrp_width(max_out_width - port_offset)
                    portgrp.widget.setX(outX)

            max_port_in_pg_width = canvas.theme.port_grouped_width
            portgrp_name = utils.get_portgroup_name(
                self._group_id, portgrp.port_id_list)

            for port in canvas.port_list:
                if (port.group_id == self._group_id
                        and port.port_id in portgrp.port_id_list
                        and port.widget is not None):
                    port_print_width = port.widget.get_text_width()

                    # change port in portgroup width only if
                    # portgrp will have a name
                    # to ensure that portgroup widget is large enough
                    if portgrp_name:
                        max_port_in_pg_width = max(max_port_in_pg_width,
                                                   port_print_width + 4)

            out_in_portgrpX = (self._width - box_theme.port_offset() - 12
                               - max_port_in_pg_width)

            portgrp.widget.set_ports_width(max_port_in_pg_width)

            for port in canvas.port_list:
                if (port.group_id == self._group_id
                        and port.port_id in portgrp.port_id_list
                        and port.widget is not None):
                    port.widget.set_port_width(max_port_in_pg_width)
                    if port.port_mode == PORT_MODE_INPUT:
                        port.widget.setX(inX)
                    elif port.port_mode == PORT_MODE_OUTPUT:
                        port.widget.setX(out_in_portgrpX)
    
    def update_positions(self, even_animated=False):
        if canvas.loading_items:
            return
        
        if (not even_animated
                and self in [b['widget'] for b in canvas.scene.move_boxes]):
            # do not change box disposition while box is moved by animation
            # update_positions will be called when animation is finished
            return

        self.prepareGeometryChange()

        self._current_port_mode = PORT_MODE_NULL
        for port in canvas.port_list:
            if port.group_id == self._group_id and port.port_id in self._port_list_ids:
                # used to know present port modes (INPUT or OUTPUT)
                self._current_port_mode |= port.port_mode

        port_types = [PORT_TYPE_AUDIO_JACK, PORT_TYPE_MIDI_JACK,
                      PORT_TYPE_MIDI_ALSA, PORT_TYPE_PARAMETER]
    
        align_port_types = self._should_align_port_types(port_types)

        widths_dict = self._set_ports_y_and_get_max_widths(port_types, align_port_types)        
        last_in_pos = widths_dict['last_in_pos']
        last_out_pos = widths_dict['last_out_pos']
        max_in_width = widths_dict['max_in_width']
        max_out_width = widths_dict['max_out_width']
        
        wrapped_port_pos = self._default_header_height

        self._width = 30
        if self._plugin_inline != self.INLINE_DISPLAY_DISABLED:
            self._width = 100

        self._width += max_in_width + max_out_width
        #self._width += max(max_in_width, max_out_width)
        self._width_in = max_in_width
        self._width_out = max_out_width

        box_theme = self.get_theme()
        box_height = max(last_in_pos, last_out_pos) + box_theme.box_footer()
        
        width_for_ports = self._width
        
        titles_dict = self._choose_title_disposition(box_height, width_for_ports)
        self._width = max(titles_dict['header_width'], width_for_ports)
        max_title_size = titles_dict['max_title_size']
        more_height = titles_dict['more_height']

        if more_height:
            self._push_down_ports(more_height)
            last_in_pos += more_height
            last_out_pos += more_height

        self._set_ports_x_positions(max_in_width, max_out_width)

        # wrapped/unwrapped sizes
        normal_height = max(last_in_pos, last_out_pos) + box_theme.box_footer()
        wrapped_height = wrapped_port_pos + canvas.theme.port_height + more_height
        self._header_height = self._default_header_height + more_height

        if self._wrapping:
            self._height = (normal_height
                            - (normal_height - wrapped_height)
                              * self._wrapping_ratio)
        elif self._unwrapping:
            self._height = (wrapped_height
                            + (normal_height - wrapped_height)
                              * self._wrapping_ratio)
        elif self._wrapped:
            self._height = wrapped_height
        else:
            self._height = normal_height
            
            self._unwrap_triangle_pos = UNWRAP_BUTTON_NONE
            if self._height >= 100:
                if last_out_pos > last_in_pos:
                    self._unwrap_triangle_pos = UNWRAP_BUTTON_LEFT
                elif last_in_pos > last_out_pos:
                    self._unwrap_triangle_pos = UNWRAP_BUTTON_RIGHT
                else:
                    self._unwrap_triangle_pos = UNWRAP_BUTTON_CENTER
        
        down_height = box_theme.fill_pen().widthF()

        self._wrapped_height = wrapped_height + down_height
        self._unwrapped_height = normal_height + down_height
        self._height += down_height

        # round self._height to the upper value
        self._height = float(int(self._height + 0.99))

        if self.has_top_icon():
            self.top_icon.align_at((self._width - max_title_size - 29)/2)

        if (self._width != self._ex_width
                or self._height != self._ex_height
                or self.scenePos() != self._ex_scene_pos):
            canvas.scene.resize_the_scene()

        self._ex_width = self._width
        self._ex_height = self._height
        self._ex_scene_pos = self.scenePos()

        self.repaint_lines(forced=True)
        if not (self._wrapping or self._unwrapping) and self.isVisible():
            canvas.scene.deplace_boxes_from_repulsers([self])
        self.update()
