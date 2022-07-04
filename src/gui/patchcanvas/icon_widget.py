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
import os
import time

from PyQt5.QtCore import QRectF, QFile
from PyQt5.QtGui import QPainter, QIcon
from PyQt5.QtSvg import QGraphicsSvgItem, QSvgRenderer
from PyQt5.QtWidgets import QGraphicsPixmapItem

from .init_values import canvas, CanvasItemType, IconType, PortMode


_logger = logging.getLogger(__name__)
_app_icons_cache = {}


def get_app_icon(icon_name: str) -> QIcon:
    if icon_name in _app_icons_cache.keys():
        return _app_icons_cache[icon_name]
    
    icon = QIcon.fromTheme(icon_name)

    if icon.isNull():
        for ext in ('svg', 'svgz', 'png'):
            filename = ":app_icons/%s.%s" % (icon_name, ext)

            if QFile.exists(filename):
                del icon
                icon = QIcon()
                icon.addFile(filename)
                break

    if icon.isNull():
        for path in ('/usr/local', '/usr', '%s/.local' % os.getenv('HOME')):
            for ext in ('png', 'svg', 'svgz', 'xpm'):
                filename = "%s/share/pixmaps/%s.%s" % (path, icon_name, ext)
                if QFile.exists(filename):
                    del icon
                    icon = QIcon()
                    icon.addFile(filename)
                    break

    _app_icons_cache[icon_name] = icon

    return icon


class IconPixmapWidget(QGraphicsPixmapItem):
    def __init__(self, icon_type, icon_name, parent):
        QGraphicsPixmapItem.__init__(self, parent)

        self._size = QRectF(0.0, 0.0, 24.0, 24.0)
        self.icon = None
        self.x_offset = 4
        self.y_offset = 4

        if icon_type in (IconType.CLIENT, IconType.APPLICATION):
            self.set_icon(icon_type, icon_name)

    def set_icon(self, icon, name, port_mode=PortMode.NULL):
        self.icon = get_app_icon(name)
        if not self.icon.isNull():
            pixmap = self.icon.pixmap(24, 24)
            self.setPixmap(pixmap)
            #self.setOffset(4.0, 4.0)
            self.setPos(4.0, 4.0)

    def update_zoom(self, scale: float):
        if self.icon is None or scale <= 0.0:
            return

        pixmap = self.icon.pixmap(int(0.5 + 24 * scale), int(0.5 + 24 * scale))
        self.setPixmap(pixmap)
        self.setScale(1.0 / scale)

    def is_null(self)->bool:
        if self.icon is None:
            return True

        return self.icon.isNull()

    def set_pos(self, x: int, y: int):
        self.x_offset = x
        self.y_offset = y
        self.setPos(float(x), float(y))
        
    def type(self) -> CanvasItemType:
        return CanvasItemType.ICON


class IconSvgWidget(QGraphicsSvgItem):
    def __init__(self, icon_type, name, port_mode, parent):
        QGraphicsSvgItem.__init__(self, parent)
        self._renderer = None
        self._size = QRectF(4, 4, 24, 24)
        self.set_icon(icon_type, name, port_mode)

    def set_icon(self, icon_type: IconType, name: str, port_mode: PortMode):
        name = name.lower()
        icon_path = ""
        theme = canvas.theme.icon

        if icon_type == IconType.APPLICATION:
            self._size = QRectF(3, 2, 19, 18)

            if "audacious" in name:
                icon_path = ":/scalable/pb_audacious.svg"
                self._size = QRectF(5, 4, 16, 16)
            elif "clementine" in name:
                icon_path = ":/scalable/pb_clementine.svg"
                self._size = QRectF(5, 4, 16, 16)
            elif "distrho" in name:
                icon_path = ":/scalable/pb_distrho.svg"
                self._size = QRectF(5, 4, 16, 16)
            elif "jamin" in name:
                icon_path = ":/scalable/pb_jamin.svg"
                self._size = QRectF(5, 3, 16, 16)
            elif "mplayer" in name:
                icon_path = ":/scalable/pb_mplayer.svg"
                self._size = QRectF(5, 4, 16, 16)
            elif "vlc" in name:
                icon_path = ":/scalable/pb_vlc.svg"
                self._size = QRectF(5, 3, 16, 16)
            else:
                icon_path = ":/scalable/pb_generic.svg"
                self._size = QRectF(4, 4, 24, 24)

        elif icon_type == IconType.HARDWARE:
            if name == "a2j":
                icon_path = theme.hardware_midi
                self._size = QRectF(4, 4, 24, 24)
            else:
                if port_mode is PortMode.INPUT:
                    icon_path = theme.hardware_playback
                elif port_mode is PortMode.OUTPUT:
                    icon_path = theme.hardware_capture
                else:
                    icon_path = theme.hardware_grouped
                self._size = QRectF(4, 4, 24, 24)

        elif icon_type == IconType.DISTRHO:
            icon_path = ":/scalable/pb_distrho.svg"
            self._size = QRectF(5, 4, 16, 16)

        elif icon_type == IconType.FILE:
            icon_path = ":/scalable/pb_file.svg"
            self._size = QRectF(5, 4, 16, 16)

        elif icon_type == IconType.PLUGIN:
            icon_path = ":/scalable/pb_plugin.svg"
            self._size = QRectF(5, 4, 16, 16)

        elif icon_type == IconType.LADISH_ROOM:
            # TODO - make a unique ladish-room icon
            icon_path = ":/scalable/pb_hardware.svg"
            self._size = QRectF(5, 2, 16, 16)

        elif icon_type == IconType.INTERNAL:
            if name == 'monitor_capture':
                icon_path = theme.monitor_capture
            elif name == 'monitor_playback':
                icon_path = theme.monitor_playback
            else:
                icon_path = ":/canvas/dark/" + name
            self._size = QRectF(4, 4, 24, 24)

        else:
            self._size = QRectF(0, 0, 0, 0)
            _logger.critical(f"set_icon({str(icon_type)}, {name})"
                             " - unsupported icon requested")
            return

        self._renderer = QSvgRenderer(icon_path, canvas.scene)
        self.setSharedRenderer(self._renderer)
        self.update()
        
    def update_zoom(self, scale: float):
        pass

    def type(self) -> CanvasItemType:
        return CanvasItemType.ICON

    def is_null(self)->bool:
        return False

    def set_pos(self, x: int, y: int):
        self._size = QRectF(x, y, 24, 24)

    def boundingRect(self):
        return self._size

    def paint(self, painter, option, widget):
        if not self._renderer:
            QGraphicsSvgItem.paint(self, painter, option, widget)
            return

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.setRenderHint(QPainter.TextAntialiasing, False)
        self._renderer.render(painter, self._size)
        painter.restore()

# ------------------------------------------------------------------------------------------------------------



