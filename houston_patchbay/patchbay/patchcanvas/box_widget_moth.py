#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# PatchBay Canvas engine using QGraphicsView/Scene
# Copyright (C) 2010-2019 Filipe Coelho <falktx@falktx.com>
# Copyright (C) 2019-2022 Mathieu Picot <picotmathieu@gmail.com>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License as
# published by the Free Software Foundation; either version 2 of
# the License, or any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# For a full copy of the GNU General Public License see the doc/GPL.txt file.

import logging
from math import ceil
from struct import pack
import time
from sip import voidptr
import sys
from enum import Enum
from PyQt5.QtCore import Qt, QPoint, QPointF, QRectF, QTimer
from PyQt5.QtGui import (QCursor, QFontMetrics, QImage, QFont,
                         QLinearGradient, QPainter, QPen, QPolygonF,
                         QColor, QIcon, QPixmap, QPainterPath, QBrush)
from PyQt5.QtWidgets import QGraphicsItem, QMenu, QApplication

from .init_values import (
    CanvasItemType,
    PortObject,
    PortgrpObject,
    canvas,
    features,
    options,
    CallbackAct,
    PortMode,
    BoxLayoutMode,
    MAX_PLUGIN_ID_ALLOWED,
    IconType,
    Direction)

from .utils import canvas_callback, is_dark_theme, get_icon
from .box_widget_shadow import BoxWidgetShadow
from .icon_widget import IconSvgWidget, IconPixmapWidget
from .port_widget import PortWidget
from .portgroup_widget import PortgroupWidget
from .line_widget import LineWidget
from .theme import BoxStyleAttributer

_translate = QApplication.translate
_logger = logging.getLogger(__name__)


class UnwrapButton(Enum):
    NONE = 0
    LEFT = 1
    CENTER = 2
    RIGHT = 3


class TitleLine:
    text = ''
    size = 0
    x = 0
    y = 0
    is_little = False

    def __init__(self, text: str, theme: BoxStyleAttributer, little=False):
        self.theme = theme
        self.text = text
        self.is_little = little
        self.x = 0
        self.y = 0

        self.font = None
        self.size = theme.get_text_width(text)

    def get_font(self) -> QFont:
        return self.theme.font()


class DisconnectElement:
    group_id: int
    connection_in_ids: list[int]
    connection_out_ids: list[int]


class BoxWidgetMoth(QGraphicsItem):
    # inline display is not usable in RaySession
    # but this patchcanvas module has been forked from Carla
    # and all about inline_display has been kept (we never know)
    # but never tested.
    INLINE_DISPLAY_DISABLED = 0
    INLINE_DISPLAY_ENABLED  = 1
    INLINE_DISPLAY_CACHED   = 2

    def __init__(self, group_id: int, group_name: str,
                 icon_type: int, icon_name: str):
        QGraphicsItem.__init__(self)
        self.setCacheMode(QGraphicsItem.DeviceCoordinateCache)

        # Save Variables, useful for later
        self._group_id = group_id
        self._group_name = group_name
        self._icon_type = icon_type

        # plugin Id, < 0 if invalid
        self._plugin_id = -1
        self._plugin_ui = False
        self._plugin_inline = self.INLINE_DISPLAY_DISABLED

        # Base Variables
        self._width = 50
        self._width_in = 0
        self._width_out = 0
        self._header_width = self._width
        self._header_height = 0
        self._wrapped_width = 0
        self._unwrapped_width = 0
        self._wrapped_height = 0
        self._unwrapped_height = 0
        self._height = self._header_height + 1
        self._ports_y_start = self._header_height
        self._ex_width = self._width
        self._ex_height = self._height
        self._ex_scene_pos = self.scenePos()
        self._ex_ports_y_segments_dict = {}

        self._last_pos = QPointF()
        self._splitted = False
        self._splitted_mode = PortMode.NULL
        self._current_port_mode = PortMode.NULL # depends of present ports

        self._cursor_moving = False
        self._mouse_down = False
        self._inline_data = None
        self._inline_image = None
        self._inline_scaling = 1.0

        self._connection_lines = list[LineWidget]()

        self._is_hardware = bool(icon_type == IconType.HARDWARE)
        self._icon_name = icon_name

        self._title_lines = list[TitleLine]()
        self._header_line_left = None
        self._header_line_right = None
        
        self._wrapped = False
        self._wrapping = False
        self._unwrapping = False
        self._wrapping_ratio = 1.0
        self._unwrap_triangle_pos = UnwrapButton.NONE

        self._port_list = list[PortObject]()
        self._portgrp_list = list[PortgrpObject]()

        # Icon
        if icon_type in (IconType.HARDWARE, IconType.INTERNAL):
            port_mode = PortMode.NULL
            if self._splitted:
                port_mode = self._splitted_mode
            self.top_icon = IconSvgWidget(
                icon_type, icon_name, port_mode, self)
        else:
            self.top_icon = IconPixmapWidget(icon_type, icon_name, self)
            if self.top_icon.is_null():
                top_icon = self.top_icon
                self.top_icon = None
                del top_icon

        # Shadow
        shadow_theme = canvas.theme.box_shadow
        if self._is_hardware:
            shadow_theme = shadow_theme.hardware
        elif self._icon_type is IconType.CLIENT:
            shadow_theme = shadow_theme.client
        elif self.is_monitor():
            shadow_theme = shadow_theme.monitor
        
        self.shadow = None
        # FIXME FX on top of graphic items make them lose high-dpi
        # See https://bugreports.qt.io/browse/QTBUG-65035
        if options.eyecandy and canvas.scene.get_device_pixel_ratio_f() == 1.0:
            self.shadow = BoxWidgetShadow(self.toGraphicsObject())
            self.shadow.set_fake_parent(self)
            self.shadow.set_theme(shadow_theme)
            self.setGraphicsEffect(self.shadow)

        # Final touches
        self.setFlags(QGraphicsItem.ItemIsFocusable
                      | QGraphicsItem.ItemIsMovable
                      | QGraphicsItem.ItemIsSelectable)

        # Wait for at least 1 port
        if options.auto_hide_groups:
            self.setVisible(False)

        if options.auto_select_items:
            self.setAcceptHoverEvents(True)

        self._is_semi_hidden = False
        
        self._can_handle_gui = False # used for optional-gui switch
        self._gui_visible = False

        self._current_layout_mode = BoxLayoutMode.LARGE
        self._title_under_icon = False
        self._painter_path = QPainterPath()
                
        self.update_positions()

        canvas.scene.addItem(self)
        QTimer.singleShot(0, self.fix_pos)

    def _get_layout_mode_for_this(self):
        group = canvas.get_group(self._group_id)
        if group is None:
            # TODO log something
            return BoxLayoutMode.AUTO
        
        if self._current_port_mode in group.layout_modes.keys():
            return group.layout_modes[self._current_port_mode]
        else:
            return BoxLayoutMode.AUTO

    def get_group_id(self):
        return self._group_id

    def get_group_name(self):
        return self._group_name

    def is_monitor(self):
        return (self._icon_type is IconType.INTERNAL
                and self._icon_name in ('monitor_playback', 'monitor_capture'))

    def is_splitted(self):
        return self._splitted

    def get_splitted_mode(self):
        return self._splitted_mode

    def get_current_port_mode(self):
        return self._current_port_mode
    
    def redraw_inline_display(self):
        if self._plugin_inline == self.INLINE_DISPLAY_CACHED:
            self._plugin_inline = self.INLINE_DISPLAY_ENABLED
            self.update()

    def remove_as_plugin(self):
        #del self._inline_image
        #self._inline_data = None
        #self._inline_image = None
        #self._inline_scaling = 1.0

        self._plugin_id = -1
        self._plugin_ui = False
        #self._plugin_inline = self.INLINE_DISPLAY_DISABLED

    def set_as_plugin(self, plugin_id, has_ui, has_inline_display):
        if has_inline_display and not options.inline_displays:
            has_inline_display = False

        if not has_inline_display:
            del self._inline_image
            self._inline_data = None
            self._inline_image = None
            self._inline_scaling = 1.0

        self._plugin_id = plugin_id
        self._plugin_ui = has_ui
        self._plugin_inline = (self.INLINE_DISPLAY_ENABLED if has_inline_display
                               else self.INLINE_DISPLAY_DISABLED)
        self.update()

    def set_icon(self, icon_type, icon_name):
        if icon_type == IconType.HARDWARE:
            self.remove_icon_from_scene()
            port_mode = PortMode.NULL
            if self._splitted:
                port_mode = self._splitted_mode
            self.top_icon = IconSvgWidget(icon_type, icon_name, port_mode, self)
            return

        if self.top_icon is not None:
            self.top_icon.set_icon(icon_type, icon_name, self._current_port_mode)
        else:
            self.top_icon = IconPixmapWidget(icon_type, icon_name, self)

        self.update_positions()

    def has_top_icon(self)->bool:
        if self.top_icon is None:
            return False

        return not self.top_icon.is_null()

    def set_optional_gui_state(self, visible: bool):
        self._can_handle_gui = True
        self._gui_visible = visible
        self.update()

    def set_split(self, split, mode=PortMode.NULL):
        self._splitted = split
        self._splitted_mode = mode
        self._current_port_mode = mode
        
        if self._is_hardware:
            self.set_icon(IconType.HARDWARE, self._icon_name)
        
        if self.shadow is not None:
            if split:
                if mode is PortMode.INPUT:
                    self.shadow.setOffset(4, 2)
                elif mode is PortMode.OUTPUT:
                    self.shadow.setOffset(-4, 2)
            else:
                self.shadow.setOffset(0, 2)

    def set_group_name(self, group_name: str):
        self._group_name = group_name
        self.update_positions()

    def set_shadow_opacity(self, opacity):
        if self.shadow:
            self.shadow.set_opacity(opacity)

    def add_port_from_group(self, port: PortObject):
        self.setVisible(True)

        new_widget = PortWidget(port, self)
        if self._wrapped:
            new_widget.setVisible(False)

        return new_widget

    def add_portgroup_from_group(self, portgroup: PortgrpObject):
        new_widget = PortgroupWidget(portgroup, self)

        if self._wrapped:
            new_widget.setVisible(False)

        return new_widget

    def add_line_to_box(self, line: 'LineWidget'):
        self._connection_lines.append(line)
        self.reset_lines_z_value(self.isSelected())

    def remove_line_from_box(self, line: 'LineWidget'):
        if line in self._connection_lines:
            self._connection_lines.remove(line)

    def check_item_pos(self):
        if canvas.size_rect.isNull():
            return
        
        pos = self.scenePos()
        if not (canvas.size_rect.contains(pos) and
                canvas.size_rect.contains(
                    pos + QPointF(self._width, self._height))):
            if pos.x() < canvas.size_rect.x():
                self.setPos(canvas.size_rect.x(), pos.y())
            elif pos.x() + self._width > canvas.size_rect.width():
                self.setPos(canvas.size_rect.width() - self._width, pos.y())

            pos = self.scenePos()
            if pos.y() < canvas.size_rect.y():
                self.setPos(pos.x(), canvas.size_rect.y())
            elif pos.y() + self._height > canvas.size_rect.height():
                self.setPos(pos.x(), canvas.size_rect.height() - self._height)

    def remove_icon_from_scene(self):
        if self.top_icon is None:
            return

        item = self.top_icon
        self.top_icon = None
        canvas.scene.removeItem(item)
        del item
        
    def animate_wrapping(self, ratio: float):
        # we expose wrapping ratio only for prettier animation
        # say self._wrapping_ratio = ratio would also works fine
        if self._wrapping:
            self._wrapping_ratio = ratio ** 0.25
        else:
            self._wrapping_ratio = ratio ** 4

        if ratio == 1.00:
            # counter is terminated
            if self._unwrapping:
                self.hide_ports_for_wrap(False)
            
            self._wrapping = False
            self._unwrapping = False
        
        self.setX(self._x_before_wrap
                  + (self._x_after_wrap - self._x_before_wrap)
                    * self._wrapping_ratio)

        self.update_positions()

    def hide_ports_for_wrap(self, hide: bool):
        for portgrp in canvas.list_portgroups(group_id=self._group_id):
            if self._splitted and self._splitted_mode != portgrp.port_mode:
                continue

            if portgrp.widget is not None:
                portgrp.widget.setVisible(not hide)

        for port in canvas.list_ports(group_id=self._group_id):
            if (self._splitted
                    and self._splitted_mode != port.port_mode):
                continue

            if port.widget is not None:
                port.widget.setVisible(not hide)

    def is_wrapped(self) -> bool:
        return self._wrapped

    def set_wrapped(self, yesno: bool, animate=True):
        if yesno == self._wrapped:
            return

        self._wrapped = yesno

        if yesno:
            self.hide_ports_for_wrap(True)

        if not animate:
            return

        self._wrapping = yesno
        self._unwrapping = not yesno
        canvas.scene.add_box_to_animation_wrapping(self, yesno)
        
        self._x_before_wrap = self.x()
        self._x_after_wrap = self._x_before_wrap
        if self._has_side_title() and self._current_port_mode is PortMode.INPUT:
            if yesno:
                self._x_after_wrap = self._x_before_wrap + self._width - self._wrapped_width
            else:
                self._x_after_wrap = self._x_before_wrap + self._width - self._unwrapped_width
        
        x_diff = self._x_after_wrap - self._x_before_wrap
        hws = canvas.theme.hardware_rack_width
        
        if yesno:
            new_bounding_rect = QRectF(0, 0, self._width, self._wrapped_height)
            if self._is_hardware:
                new_bounding_rect = QRectF(- hws, - hws, self._width + 2 * hws,
                                           self._wrapped_height + 2 * hws)
            
            canvas.scene.bring_neighbors_and_deplace_boxes(self, new_bounding_rect)

        else:
            new_bounding_rect = QRectF(x_diff, 0, self._unwrapped_width, self._unwrapped_height)
            if self._is_hardware:
                new_bounding_rect = QRectF(x_diff - hws, - hws , self._unwrapped_width + 2 * hws,
                                           self._unwrapped_height + 2 * hws)
            
            canvas.scene.deplace_boxes_from_repulsers(
                [self],
                new_scene_rect=new_bounding_rect.translated(self.pos()),
                wanted_direction=Direction.DOWN)

    def update_positions(self, even_animated=False):
        # see canvasbox.py
        pass

    def repaint_lines(self, forced=False, fast_move=False):
        if forced or self.pos() != self._last_pos:
            for line in self._connection_lines:                
                line.update_line_pos(fast_move=fast_move)

        self._last_pos = self.pos()

    def reset_lines_z_value(self, under: bool):
        if self._current_port_mode is not PortMode.BOTH:
            return
        
        for connection in canvas.list_connections(
                group_in_id=self._group_id, group_out_id=self._group_id):
            if connection.widget is not None:
                connection.widget.setZValue(
                    self.zValue() - 1 if under else self.zValue() + 1)

    def semi_hide(self, yesno: bool):
        self._is_semi_hidden = yesno
        if yesno:
            self.setOpacity(canvas.semi_hide_opacity)
        else:
            self.setOpacity(1.0)

    def update_opacity(self):
        if not self._is_semi_hidden:
            return
        
        self.setOpacity(canvas.semi_hide_opacity)

    def _has_side_title(self):
        return bool(
            self._current_port_mode is not PortMode.BOTH
            and self._current_layout_mode == BoxLayoutMode.LARGE)

    def wrap_unwrap_at_point(self, scene_pos: QPointF) -> bool:
        ''' orders a wrap or unwrap on the box if scene_pos is on the
            triangle wrapper '''
        if self._wrapped:
            # unwrap the box if scene_pos is in one of the triangles zones
            triangle_rect_out = QRectF(0.0, self._height - 24.0, 24.0, 24.0)
            triangle_rect_in = QRectF(
                self._width - 24.0, self._height - 24.0, 24.0, 24.0)

            mode = PortMode.INPUT
            wrap = False

            for trirect in triangle_rect_out, triangle_rect_in:
                trirect.translate(self.scenePos())
                if (self._current_port_mode & mode
                        and trirect.contains(scene_pos)):
                    wrap = True
                    break

                mode = PortMode.OUTPUT

            if wrap:
                canvas_callback(
                    CallbackAct.GROUP_WRAP, self._group_id,
                    self._splitted_mode, False)
                return True
            
        elif self._unwrap_triangle_pos is not UnwrapButton.NONE:
            # wrap the box if scene_pos is on the triangle zone
            trirect = QRectF(0, self._height - 16, 16, 16)
            
            if self._unwrap_triangle_pos is UnwrapButton.CENTER:
                trirect = QRectF(self._width_in + 8, self._height - 16, 16, 16)
            elif self._unwrap_triangle_pos is UnwrapButton.RIGHT:
                trirect = QRectF(self._width - 16, self._height -16, 16, 16)
                
            trirect.translate(self.scenePos())
            if trirect.contains(scene_pos):
                canvas_callback(
                    CallbackAct.GROUP_WRAP, self._group_id,
                    self._splitted_mode, True)
                return True
        
        return False

    def type(self) -> CanvasItemType:
        return CanvasItemType.BOX

    # --- protected Qt Functions redefined here ---
    # --
    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemSelectedHasChanged:
            self.reset_lines_z_value(bool(value))

        return super().itemChange(change, value)

    def contextMenuEvent(self, event):
        if canvas.is_line_mov:
            return

        event.accept()
        canvas.menu_shown = True
        menu = QMenu()

        dark = '-dark' if is_dark_theme(menu) else ''

        # Disconnect menu stuff
        discMenu = QMenu(_translate('patchbay', "Disconnect"), menu)
        discMenu.setIcon(
            QIcon(QPixmap(':scalable/breeze%s/lines-disconnector' % dark)))

        conn_list_ids = list[int]()
        disconnect_list = list[DisconnectElement]()

        for port in self._port_list:
            for connection in canvas.list_connections(port):
                conn_list_ids.append(connection.connection_id)
                other_group_id = connection.group_in_id
                group_port_mode = PortMode.INPUT

                if self._splitted:
                    if self._splitted_mode is PortMode.INPUT:
                        other_group_id = connection.group_out_id
                        group_port_mode = PortMode.OUTPUT
                else:
                    if other_group_id == self._group_id:
                        other_group_id = connection.group_out_id
                        group_port_mode = PortMode.OUTPUT

                for disconnect_element in disconnect_list:
                    if disconnect_element.group_id == other_group_id:
                        if group_port_mode is PortMode.INPUT:
                            disconnect_element.connection_in_ids.append(
                                connection.connection_id)
                        else:
                            disconnect_element.connection_out_ids.append(
                                connection.connection_id)
                        break
                else:
                    disconnect_element = DisconnectElement()
                    disconnect_element.group_id = other_group_id
                    disconnect_element.connection_in_ids = list[int]()
                    disconnect_element.connection_out_ids = list[int]()

                    if group_port_mode is PortMode.INPUT:
                        disconnect_element.connection_in_ids.append(
                            connection.connection_id)
                    else:
                        disconnect_element.connection_out_ids.append(
                            connection.connection_id)

                    disconnect_list.append(disconnect_element)

        if disconnect_list:
            for disconnect_element in disconnect_list:
                group = canvas.get_group(disconnect_element.group_id)
                if group is None:
                    continue

                if (group.split
                        and disconnect_element.connection_in_ids
                        and disconnect_element.connection_out_ids):
                    ins_label = " (inputs)"
                    outs_label = " (outputs)"

                    if group.icon_type == IconType.HARDWARE:
                        ins_label = " (playbacks)"
                        outs_label = " (captures)"

                    act_x_disc1 = discMenu.addAction(
                        group.group_name + outs_label)
                    act_x_disc1.setIcon(get_icon(
                        group.icon_type, group.icon_name, PortMode.OUTPUT))
                    act_x_disc1.setData(
                        disconnect_element.connection_out_ids)
                    act_x_disc1.triggered.connect(
                        canvas.qobject.port_context_menu_disconnect)

                    act_x_disc2 = discMenu.addAction(
                        group.group_name + ins_label)
                    act_x_disc2.setIcon(get_icon(
                        group.icon_type, group.icon_name, PortMode.INPUT))
                    act_x_disc2.setData(
                        disconnect_element.connection_in_ids)
                    act_x_disc2.triggered.connect(
                        canvas.qobject.port_context_menu_disconnect)
                else:
                    port_mode = PortMode.NULL
                    if not disconnect_element.connection_in_ids:
                        port_mode = PortMode.OUTPUT
                    elif not disconnect_element.connection_out_ids:
                        port_mode = PortMode.INPUT

                    act_x_disc = discMenu.addAction(group.group_name)
                    icon = get_icon(
                        group.icon_type, group.icon_name, port_mode)
                    act_x_disc.setIcon(icon)
                    act_x_disc.setData(
                        disconnect_element.connection_out_ids
                        + disconnect_element.connection_in_ids)
                    act_x_disc.triggered.connect(
                        canvas.qobject.port_context_menu_disconnect)
        else:
            act_x_disc = discMenu.addAction("No connections")
            act_x_disc.setEnabled(False)

        menu.addMenu(discMenu)
        act_x_disc_all = menu.addAction(
            _translate('patchbay', "Disconnect &All"))
        act_x_disc_all.setIcon(
            QIcon(QPixmap(':scalable/breeze%s/lines-disconnector' % dark)))
        act_x_sep1 = menu.addSeparator()
        act_x_info = menu.addAction(_translate('patchbay', "Info"))
        act_x_rename = menu.addAction(_translate('patchbay', "Rename"))
        act_x_sep2 = menu.addSeparator()
        split_join_name = _translate('patchbay', "Split")
        split_join_icon = QIcon.fromTheme('split')
        if self._splitted:
            split_join_name = _translate('patchbay', "Join")
            split_join_icon = QIcon.fromTheme('join')
        act_x_split_join = menu.addAction(split_join_name)
        act_x_split_join.setIcon(split_join_icon)

        wrap_title = _translate('patchbay', 'Wrap')
        wrap_icon = QIcon.fromTheme('pan-up-symbolic')
        if self._wrapped:
            wrap_title = _translate('patchbay', 'Unwrap')
            wrap_icon = QIcon.fromTheme('pan-down-symbolic')

        act_x_wrap = menu.addAction(wrap_title)
        act_x_wrap.setIcon(wrap_icon)
            
        act_auto_layout = menu.addAction(
            _translate('patchbay', 'Automatic layout'))
        act_auto_layout.setVisible(
            self._get_layout_mode_for_this() != BoxLayoutMode.AUTO)
        act_auto_layout.setIcon(QIcon.fromTheme('auto-scale-x'))

        act_switch_layout = menu.addAction(
            _translate('patchbay', 'Change layout'))
        act_switch_layout.setIcon(QIcon.fromTheme('view-split-left-right'))

        if not features.group_info:
            act_x_info.setVisible(False)

        if not features.group_rename:
            act_x_rename.setVisible(False)

        if not (features.group_info and features.group_rename):
            act_x_sep1.setVisible(False)

        if self._plugin_id >= 0 and self._plugin_id <= MAX_PLUGIN_ID_ALLOWED:
            menu.addSeparator()
            act_p_edit = menu.addAction("Edit")
            act_p_ui = menu.addAction("Show Custom UI")
            menu.addSeparator()
            act_p_clone = menu.addAction("Clone")
            act_p_rename = menu.addAction("Rename...")
            act_p_replace = menu.addAction("Replace...")
            act_p_remove = menu.addAction("Remove")

            if not self._plugin_ui:
                act_p_ui.setVisible(False)

        else:
            act_p_edit = act_p_ui = None
            act_p_clone = act_p_rename = None
            act_p_replace = act_p_remove = None

        if not (self._splitted or self._current_port_mode is PortMode.BOTH):
            act_x_sep2.setVisible(False)
            act_x_split_join.setVisible(False)

        self.setFlag(QGraphicsItem.ItemIsMovable, False)
        act_selected = menu.exec_(event.screenPos())

        if act_selected is None:
            pass

        elif act_selected == act_x_disc_all:
            for conn_id in conn_list_ids:
                canvas.callback(CallbackAct.PORTS_DISCONNECT, conn_id)

        elif act_selected == act_x_info:
            canvas.callback(CallbackAct.GROUP_INFO, self._group_id)

        elif act_selected == act_x_rename:
            canvas.callback(CallbackAct.GROUP_RENAME, self._group_id)

        elif act_selected == act_x_split_join:
            if self._splitted:
                canvas.qobject.groups_to_join.append(self._group_id)
                group = canvas.get_group(self._group_id)
                if group is None:
                    return

                for widget in group.widgets:
                    canvas.scene.add_box_to_animation(
                        widget, group.null_pos.x(), group.null_pos.y())
                # canvas.callback(CallbackAct.GROUP_JOIN, self._group_id)
            else:
                canvas.callback(CallbackAct.GROUP_SPLIT, self._group_id)

        elif act_selected == act_auto_layout:
            canvas.callback(CallbackAct.GROUP_LAYOUT_CHANGE, self._group_id,
                            self._current_port_mode, BoxLayoutMode.AUTO)

        elif act_selected == act_switch_layout:
            next_layout = BoxLayoutMode.HIGH
            if self._current_layout_mode == BoxLayoutMode.HIGH:
                next_layout = BoxLayoutMode.LARGE
            
            canvas.callback(CallbackAct.GROUP_LAYOUT_CHANGE, self._group_id,
                            self._current_port_mode, next_layout)

        elif act_selected == act_p_edit:
            canvas.callback(CallbackAct.PLUGIN_EDIT, self._plugin_id)

        elif act_selected == act_p_ui:
            canvas.callback(CallbackAct.PLUGIN_SHOW_UI, self._plugin_id)

        elif act_selected == act_p_clone:
            canvas.callback(CallbackAct.PLUGIN_CLONE, self._plugin_id)

        elif act_selected == act_p_rename:
            canvas.callback(CallbackAct.PLUGIN_RENAME, self._plugin_id)

        elif act_selected == act_p_replace:
            canvas.callback(CallbackAct.PLUGIN_REPLACE, self._plugin_id)

        elif act_selected == act_p_remove:
            canvas.callback(CallbackAct.PLUGIN_REMOVE, self._plugin_id)

        elif act_selected == act_x_wrap:
            canvas.callback(CallbackAct.GROUP_WRAP, self._group_id,
                            self._splitted_mode, not self._wrapped)
        
        if act_selected is None:
            canvas.menu_click_pos = QCursor.pos()
        else:
            self.setFlag(QGraphicsItem.ItemIsMovable, True)

    def keyPressEvent(self, event):
        if self._plugin_id >= 0 and event.key() == Qt.Key_Delete:
            event.accept()
            canvas.callback(CallbackAct.PLUGIN_REMOVE, self._plugin_id)
            return
        QGraphicsItem.keyPressEvent(self, event)

    def hoverEnterEvent(self, event):
        if options.auto_select_items:
            if len(canvas.scene.selectedItems()) > 0:
                canvas.scene.clearSelection()
            self.setSelected(True)
        QGraphicsItem.hoverEnterEvent(self, event)

    def mouseDoubleClickEvent(self, event):
        if self._can_handle_gui:
            canvas.callback(
                CallbackAct.CLIENT_SHOW_GUI, self._group_id,
                not self._gui_visible)

        if self._plugin_id >= 0:
            event.accept()
            canvas.callback(
                CallbackAct.PLUGIN_SHOW_UI if self._plugin_ui else CallbackAct.PLUGIN_EDIT,
                self._plugin_id)
            return

        QGraphicsItem.mouseDoubleClickEvent(self, event)

    def mousePressEvent(self, event):
        canvas.last_z_value += 1
        self.setZValue(canvas.last_z_value)
        
        self._cursor_moving = False
        if canvas.menu_shown and canvas.menu_click_pos == QCursor.pos():
            # prevent box move if user just quit a context menu with click outside
            # because it moves the box at the very strange position
            # if the cursor didn't move between the click for menu quit 
            # and the next one (this one).
            # strange Qt Bug.
            self.setFlag(QGraphicsItem.ItemIsMovable, False)
        
        elif event.button() == Qt.RightButton:
            event.accept()
            canvas.scene.clearSelection()
            self.setSelected(True)
            self._mouse_down = False
            return

        elif event.button() == Qt.LeftButton:
            if self.sceneBoundingRect().contains(event.scenePos()):
                if self.wrap_unwrap_at_point(event.scenePos()):
                    event.ignore()
                    return

                self.setFlag(QGraphicsItem.ItemIsMovable, True)
                self._mouse_down = True
        else:
            self._mouse_down = False

        QGraphicsItem.mousePressEvent(self, event)

    def mouseMoveEvent(self, event):
        if canvas.scene.resizing_scene:
            # QGraphicsScene.setSceneRect calls this method indirectly
            # and resize_the_scene can be called from this method
            # So, here we avoid a RecursionError
            return

        if self._mouse_down:
            if not self._cursor_moving:
                canvas.scene.set_cursor(QCursor(Qt.SizeAllCursor))
                self._cursor_moving = True
                canvas.scene.fix_temporary_scroll_bars()

            QGraphicsItem.mouseMoveEvent(self, event)

            rep_time = time.time()
            for item in canvas.scene.get_selected_boxes():
                item.repaint_lines(fast_move=True)
            # print('repline', time.time() - rep_time)

            canvas.scene.resize_the_scene()
            return

        QGraphicsItem.mouseMoveEvent(self, event)

    def mouseReleaseEvent(self, event):
        if self._cursor_moving:
            canvas.scene.unset_cursor()
            self.repaint_lines(forced=True)
            canvas.scene.reset_scroll_bars()
            self.fix_pos_after_move()

            # get all selected boxes
            repulsers = []
            for widget in canvas.list_boxes():
                if widget.isSelected():
                    repulsers.append(widget)

            canvas.scene.deplace_boxes_from_repulsers(repulsers)

            QTimer.singleShot(0, canvas.scene.update)

        self._mouse_down = False

        if (QApplication.keyboardModifiers() & Qt.ShiftModifier
                and not self._cursor_moving):
            return
        
        self._cursor_moving = False
        
        QGraphicsItem.mouseReleaseEvent(self, event)
    
    def fix_pos(self):
        self.setX(round(self.x()))
        self.setY(round(self.y()))

    def send_move_callback(self):
        canvas_callback(CallbackAct.GROUP_MOVE, self._group_id,
                        self._splitted_mode, round(self.x()), round(self.y()))

        group = canvas.get_group(self._group_id)
        if group is None:
            _logger.warning(
                "send_move_callback - "
                f"Box has no group_id {self._group_id} in canvas")
            return
        
        pos = QPoint(round(self.x()), round(self.y()))

        if self._splitted_mode is PortMode.NULL:
            group.null_pos = pos
        elif self._splitted_mode is PortMode.INPUT:
            group.in_pos = pos
        elif self._splitted_mode is PortMode.OUTPUT:
            group.out_pos = pos

    def fix_pos_after_move(self):
        for box in canvas.scene.get_selected_boxes():
            box.fix_pos()
            box.send_move_callback()

    def set_in_cache(self, yesno: bool):
        cache_mode = self.cacheMode()
        if yesno and cache_mode == QGraphicsItem.DeviceCoordinateCache:
            return
        
        if not yesno and cache_mode == QGraphicsItem.NoCache:
            return

        # toggle cache_mode value
        if cache_mode == QGraphicsItem.DeviceCoordinateCache:
            cache_mode = QGraphicsItem.NoCache
        else:
            cache_mode = QGraphicsItem.DeviceCoordinateCache
        
        self.setCacheMode(cache_mode)
        for port in self._port_list:
            if port.widget is not None:
                port.widget.setCacheMode(cache_mode)
        
        for portgroup in self._portgrp_list:
            if (self._current_port_mode & portgroup.port_mode
                    and portgroup.widget is not None):
                portgroup.widget.setCacheMode(cache_mode)

    def boundingRect(self):
        if self._is_hardware:
            hws = canvas.theme.hardware_rack_width
            
            return QRectF(- hws, - hws,
                          self._width + 2 * hws,
                          self._height + 2 * hws)
        return QRectF(0, 0, self._width, self._height)

    def paint(self, painter, option, widget):
        if canvas.loading_items:
            return

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)

        # define theme for box, wrappers and header lines
        theme = canvas.theme.box
        wtheme = canvas.theme.box_wrapper
        hltheme = canvas.theme.box_header_line
        
        if self._is_hardware:
            theme = theme.hardware
            wtheme = wtheme.hardware
            hltheme = hltheme.hardware
        elif self._icon_type is IconType.CLIENT:
            theme = theme.client
            wtheme = wtheme.client
            hltheme = hltheme.client
        elif (self._icon_type is IconType.INTERNAL
                and self._icon_name == 'monitor_playback'):
            theme = theme.monitor
            wtheme = wtheme.monitor
            hltheme = hltheme.monitor

        if self.isSelected():
            theme = theme.selected
            wtheme = wtheme.selected
            hltheme = hltheme.selected

        bg_image = theme.background_image()

        # draw the background image if exists
        if bg_image:
            painter.setBrush(QBrush(bg_image))
            painter.setPen(Qt.NoPen)
            painter.drawPath(self._painter_path)
        
        # draw the main rectangle
        pen = theme.fill_pen()
        pen.setWidthF(pen.widthF() + 0.00001)
        
        painter.setPen(pen)
        pen_width = pen.widthF()
        line_hinting = pen_width / 2.0
        
        color_main = theme.background_color()
        color_alter = theme.background2_color()

        if color_alter is not None:
            max_size = max(self._height, self._width)
            box_gradient = QLinearGradient(0, 0, max_size, max_size)
            gradient_size = 20

            box_gradient.setColorAt(0, color_main)
            tot = int(max_size / gradient_size)
            for i in range(tot):
                if i % 2 == 0:
                    box_gradient.setColorAt((i/tot) ** 0.7, color_main)
                else:
                    box_gradient.setColorAt((i/tot) ** 0.7, color_alter)

            painter.setBrush(box_gradient)
        else:
            painter.setBrush(color_main)
        
        painter.drawPath(self._painter_path)
        
        # draw hardware box decoration (flyrack like)
        self._paint_hardware_rack(painter, line_hinting)

        # Draw plugin inline display if supported
        self._paint_inline_display(painter)

        # Draw toggle GUI client button
        if self._can_handle_gui:
            header_rect = QRectF(3, 3, self._width - 6, self._header_height - 6)
            if self._has_side_title():
                if self._current_port_mode is PortMode.INPUT:
                    header_rect = QRectF(
                        self._width - self._header_width + 3, 3,
                        self._header_width - 6, self._header_height -6)
                elif self._current_port_mode is PortMode.OUTPUT:
                    header_rect = QRectF(
                        3, 3, self._header_width - 6, self._header_height - 6)
            
            header_rect.adjust(line_hinting * 2, line_hinting * 2,
                               -2 * line_hinting, -2 * line_hinting)
            
            gui_theme = canvas.theme.gui_button
            if self._gui_visible:
                gui_theme = gui_theme.gui_visible
            else:
                gui_theme = gui_theme.gui_hidden
            
            painter.setBrush(gui_theme.background_color())
            painter.setPen(gui_theme.fill_pen())
            
            radius = gui_theme.border_radius()
            if radius == 0.0:
                painter.drawRect(header_rect)
            else:
                painter.drawRoundedRect(header_rect, radius, radius)

        # draw Pipewire Monitor (or PulseAudio bridges) decorations
        elif self.is_monitor() and not self._current_port_mode is PortMode.BOTH:
            if self._current_port_mode is PortMode.OUTPUT:
                bor_gradient = QLinearGradient(0, 0, self._height, self._height)
            else:
                bor_gradient = QLinearGradient(
                    self._width, 0, self._height, self._width - self._height)
            
            mon_theme = canvas.theme.monitor_decoration
            if self.isSelected():
                mon_theme = mon_theme.selected
            
            color_main = mon_theme.background_color()
            color_alter = mon_theme.background2_color()

            if color_alter is not None:
                tot = int(self._height / 20)
                for i in range(tot):
                    if i % 2 == 0:
                        bor_gradient.setColorAt(i/tot, color_main)
                    else:
                        bor_gradient.setColorAt(i/tot, color_alter)

                painter.setBrush(bor_gradient)
            else:
                painter.setBrush(color_main)

            painter.setPen(mon_theme.fill_pen())

            BAND_MON_WIDTH = 9
            TRIANGLE_MON_SIZE_TOP = 7
            triangle_mon_size_bottom = 0
            if (self._wrapping or self._unwrapping
                    or (not self._wrapped
                        and self._unwrap_triangle_pos is not UnwrapButton.NONE)):
                triangle_mon_size_bottom = 13

            bmw = BAND_MON_WIDTH
            tms_top = TRIANGLE_MON_SIZE_TOP
            tms_bot = triangle_mon_size_bottom

            xside = pen_width
            xband = pen_width + bmw
            xtop = pen_width + bmw + tms_top
            xbot = pen_width + bmw + tms_bot

            if self._current_port_mode is PortMode.INPUT:
                xside = self._width - xside
                xband = self._width - xband
                xtop = self._width - xtop
                xbot = self._width - xbot                

            mon_poly = QPolygonF()
            mon_poly += QPointF(xside, pen_width)
            mon_poly += QPointF(xtop, pen_width)
            mon_poly += QPointF(xband, pen_width + tms_top)
            mon_poly += QPointF(xband, self._height - tms_bot - pen_width)
            mon_poly += QPointF(xbot, self._height - pen_width)
            mon_poly += QPointF(xside, self._height - pen_width)
            
            painter.drawPolygon(mon_poly)

        # may draw horizontal lines around title (header lines)
        if (self._header_line_left is not None
                and self._header_line_right is not None):
            painter.setPen(hltheme.fill_pen())
            painter.drawLine(*self._header_line_left)
            painter.drawLine(*self._header_line_right)

        normal_color = theme.text_color()
        opac_color = QColor(normal_color)
        opac_color.setAlpha(int(normal_color.alpha() / 2))
        
        text_pen = QPen(normal_color)
        opac_text_pen = QPen(opac_color)

        # draw title lines
        for title_line in self._title_lines:
            painter.setFont(title_line.get_font())
            
            if title_line.is_little:
                painter.setPen(opac_text_pen)
            else:
                painter.setPen(text_pen)

            if (self.is_monitor()
                    and title_line == self._title_lines[-1]
                    and self._group_name.endswith(' Monitor')):
                # Title line endswith " Monitor"
                # Draw "Monitor" in yellow
                # but keep the rest in white
                pre_text = title_line.text.rpartition(' Monitor')[0]
                painter.drawText(
                    ceil(title_line.x), ceil(title_line.y), pre_text)

                x_pos = title_line.x
                if pre_text:
                    t_font = title_line.get_font()
                    x_pos += QFontMetrics(t_font).width(pre_text)
                    x_pos += QFontMetrics(t_font).width(' ')

                painter.setPen(QPen(canvas.theme.monitor_color, 0))
                painter.drawText(ceil(x_pos), ceil(title_line.y), 'Monitor')
            else:
                painter.drawText(ceil(title_line.x), ceil(title_line.y),
                                 title_line.text)

        # draw (un)wrapper triangles
        painter.setPen(wtheme.fill_pen())
        painter.setBrush(wtheme.background_color())

        if self._wrapped:
            for port_mode in PortMode.INPUT, PortMode.OUTPUT:
                if self._current_port_mode & port_mode:
                    if self._has_side_title():
                        side = 9
                        offset = 4
                        ypos = self._height - offset
                        
                        triangle = QPolygonF()
                        if port_mode is PortMode.INPUT:
                            xpos = offset
                            triangle += QPointF(xpos, ypos)
                            triangle += QPointF(xpos, ypos - side)
                            triangle += QPointF(xpos + side, ypos)
                        else:
                            xpos = self._width - offset
                            triangle += QPointF(xpos, ypos)
                            triangle += QPointF(xpos, ypos - side)
                            triangle += QPointF(xpos - side, ypos)
                    else:
                        side = 6
                        xpos = 6
                        ypos = self._header_height

                        if port_mode is PortMode.OUTPUT:
                            xpos = self._width - (xpos + 2 * side)

                        triangle = QPolygonF()
                        triangle += QPointF(xpos, ypos + 2)
                        triangle += QPointF(xpos + 2 * side, ypos + 2)
                        triangle += QPointF(xpos + side, ypos + side + 2)
                    
                    painter.drawPolygon(triangle)

        elif self._unwrap_triangle_pos is UnwrapButton.LEFT:
            side = 6
            xpos = 4
            ypos = self._height - 4
            triangle = QPolygonF()
            triangle += QPointF(xpos, ypos)
            triangle += QPointF(xpos + 2 * side, ypos)
            triangle += QPointF(xpos + side, ypos -side)

            painter.drawPolygon(triangle)
        
        elif self._unwrap_triangle_pos is UnwrapButton.RIGHT:
            side = 6
            xpos = self._width - 2 * side - 4
            
            ypos = self._height - 4
            triangle = QPolygonF()
            triangle += QPointF(xpos, ypos)
            triangle += QPointF(xpos + 2 * side, ypos)
            triangle += QPointF(xpos + side, ypos -side)
            painter.drawPolygon(triangle)
        
        elif self._unwrap_triangle_pos is UnwrapButton.CENTER:
            side = 7
            xpos = (self._width_in + self._width - self._width_out) / 2 - side
            
            ypos = self._height - 3 + 0.5
            triangle = QPolygonF()
            triangle += QPointF(xpos, ypos + 2)
            triangle += QPointF(xpos + 2 * side, ypos + 2)
            triangle += QPointF(xpos + side, ypos -side + 2)
            painter.drawPolygon(triangle)

        painter.restore()

    def _paint_hardware_rack(self, painter: QPainter, lineHinting: float):
        if not self._is_hardware:
            return
        
        d = canvas.theme.hardware_rack_width
        
        theme = canvas.theme.hardware_rack
        if self.isSelected():
            theme = theme.selected
        
        background1 = theme.background_color()
        background2 = theme.background2_color()
        
        if background2 is not None:
            hw_gradient = QLinearGradient(-d, -d, self._width +d, self._height +d)
            hw_gradient.setColorAt(0, background1)
            hw_gradient.setColorAt(0.5, background2)
            hw_gradient.setColorAt(1, background1)

            painter.setBrush(hw_gradient)
        else:
            painter.setBrush(background1)
            
        painter.setPen(theme.fill_pen())
        if self._current_port_mode is not PortMode.BOTH:
            hardware_poly = QPolygonF()

            if self._current_port_mode is PortMode.INPUT:
                hardware_poly += QPointF(- lineHinting, - lineHinting)
                hardware_poly += QPointF(- lineHinting, self._ports_y_start)
                hardware_poly += QPointF(-d /2.0, self._ports_y_start)
                hardware_poly += QPointF(-d, self._ports_y_start - d / 2.0)
                hardware_poly += QPointF(-d, -d / 2.0)
                hardware_poly += QPointF(-d / 2.0, -d)
                hardware_poly += QPointF(self._width + d/2.0, -d)
                hardware_poly += QPointF(self._width + d, -d / 2.0)
                hardware_poly += QPointF(self._width + d, self._height + d/2.0)
                hardware_poly += QPointF(self._width + d/2.0, self._height + d)
                hardware_poly += QPointF(-d/2.0, self._height +d)
                hardware_poly += QPointF(-d, self._height +d/2.0)
                hardware_poly += QPointF(-d, self._height -3 + d/2.0)
                hardware_poly += QPointF(-d/2.0, self._height -3)
                hardware_poly += QPointF(- lineHinting, self._height -3)
                hardware_poly += QPointF(- lineHinting, self._height + lineHinting)
                hardware_poly += QPointF(self._width + lineHinting,
                                            self._height + lineHinting)
                hardware_poly += QPointF(self._width + lineHinting, - lineHinting)
            else:
                hardware_poly += QPointF(self._width + lineHinting, - lineHinting)
                hardware_poly += QPointF(self._width + lineHinting, self._ports_y_start)
                hardware_poly += QPointF(self._width + d/2.0, self._ports_y_start)
                hardware_poly += QPointF(self._width + d, self._ports_y_start - d/2.0)
                hardware_poly += QPointF(self._width +d, -d / 2.0)
                hardware_poly += QPointF(self._width + d/2.0, -d)
                hardware_poly += QPointF(-d / 2.0, -d)
                hardware_poly += QPointF(-d, -d/2.0)
                hardware_poly += QPointF(-d, self._height + d/2.0)
                hardware_poly += QPointF(-d/2.0, self._height + d)
                hardware_poly += QPointF(self._width + d/2.0, self._height + d)
                hardware_poly += QPointF(self._width + d, self._height + d/2.0)
                hardware_poly += QPointF(self._width +d, self._height -3 + d/2.0)
                hardware_poly += QPointF(self._width + d/2, self._height -3)
                hardware_poly += QPointF(self._width + lineHinting, self._height -3)
                hardware_poly += QPointF(self._width + lineHinting,
                                            self._height + lineHinting)
                hardware_poly += QPointF(-lineHinting, self._height + lineHinting)
                hardware_poly += QPointF(-lineHinting, -lineHinting)

            painter.drawPolygon(hardware_poly)
        else:
            hw_poly_top = QPolygonF()
            hw_poly_top += QPointF(-lineHinting, -lineHinting)
            hw_poly_top += QPointF(-lineHinting, self._ports_y_start)
            hw_poly_top += QPointF(-d /2.0, self._ports_y_start)
            hw_poly_top += QPointF(-d, self._ports_y_start - d / 2.0)
            hw_poly_top += QPointF(-d, -d / 2.0)
            hw_poly_top += QPointF(-d / 2.0, -d)
            hw_poly_top += QPointF(self._width + d/2.0, -d)
            hw_poly_top += QPointF(self._width + d, -d / 2.0)
            hw_poly_top += QPointF(self._width + d, self._ports_y_start - d/2)
            hw_poly_top += QPointF(self._width + d/2, self._ports_y_start)
            hw_poly_top += QPointF(self._width + lineHinting, self._ports_y_start)
            hw_poly_top += QPointF(self._width + lineHinting, -lineHinting)
            painter.drawPolygon(hw_poly_top)

            hw_poly_bt = QPolygonF()
            hw_poly_bt += QPointF(-lineHinting, self._height + lineHinting)
            hw_poly_bt += QPointF(-lineHinting, self._height -3)
            hw_poly_bt += QPointF(-d/2, self._height -3)
            hw_poly_bt += QPointF(-d, self._height -3 + d/2)
            hw_poly_bt += QPointF(-d, self._height + d/2)
            hw_poly_bt += QPointF(-d/2, self._height + d)
            hw_poly_bt += QPointF(self._width + d/2, self._height + d)
            hw_poly_bt += QPointF(self._width + d, self._height + d/2)
            hw_poly_bt += QPointF(self._width + d, self._height -3 + d/2)
            hw_poly_bt += QPointF(self._width + d/2, self._height -3)
            hw_poly_bt += QPointF(self._width + lineHinting, self._height -3)
            hw_poly_bt += QPointF(self._width + lineHinting, self._height + lineHinting)
            painter.drawPolygon(hw_poly_bt)

    def _paint_inline_display(self, painter: QPainter):
        if self._plugin_inline == self.INLINE_DISPLAY_DISABLED:
            return
        if not options.inline_displays:
            return

        inwidth  = self._width - self._width_in - self._width_out - 16
        inheight = self._height - self._header_height - self.get_theme().port_spacing() - 3
        scaling  = canvas.scene.get_scale_factor() * canvas.scene.get_device_pixel_ratio_f()

        if (self._plugin_id >= 0
                and self._plugin_id <= MAX_PLUGIN_ID_ALLOWED
                and (self._plugin_inline == self.INLINE_DISPLAY_ENABLED
                     or self._inline_scaling != scaling)):
            data = canvas.callback(CallbackAct.INLINE_DISPLAY, self._plugin_id,
                                   int(inwidth*scaling), int(inheight*scaling))
            if data is None:
                return

            # invalidate old image first
            del self._inline_image

            self._inline_data = pack("%iB" % (data['height'] * data['stride']),
                                     *data['data'])
            self._inline_image = QImage(
                voidptr(self._inline_data), data['width'], data['height'],
                data['stride'], QImage.Format_ARGB32)
            self._inline_scaling = scaling
            self._plugin_inline = self.INLINE_DISPLAY_CACHED

        if self._inline_image is None:
            sys.stderr.write("ERROR: inline display image is None for\n",
                             self._plugin_id, self._group_name)
            return

        swidth = self._inline_image.width() / scaling
        sheight = self._inline_image.height() / scaling

        srcx = int(self._width_in
                   + (self._width - self._width_in - self._width_out) / 2
                   - swidth / 2)
        srcy = int(self._header_height + 1 + (inheight - sheight) / 2)

        painter.drawImage(QRectF(srcx, srcy, swidth, sheight), self._inline_image)
    
    def get_theme(self, for_wrapper=False) -> BoxStyleAttributer:
        theme = canvas.theme.box
        if for_wrapper:
            theme = canvas.theme.box_wrapper
        
        if self._is_hardware:
            theme = theme.hardware
        elif self._icon_type == IconType.CLIENT:
            theme = theme.client
        elif self.is_monitor():
            theme = theme.monitor
        
        return theme
