#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# PatchBay Canvas engine using QGraphicsView/Scene
# Copyright (C) 2010-2019 Filipe Coelho <falktx@falktx.com>
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

# ------------------------------------------------------------------------------------------------------------
# Imports (Global)

from PyQt5.QtCore import qCritical, QRectF, QFile
from PyQt5.QtGui import QPainter, QPalette, QIcon, QPixmap
from PyQt5.QtSvg import QGraphicsSvgItem, QSvgRenderer
from PyQt5.QtWidgets import QGraphicsColorizeEffect, QGraphicsPixmapItem

# ------------------------------------------------------------------------------------------------------------
# Imports (Custom)

from . import (
    canvas,
    icon2str,
    CanvasIconType,
    ICON_APPLICATION,
    ICON_HARDWARE,
    ICON_DISTRHO,
    ICON_FILE,
    ICON_PLUGIN,
    ICON_LADISH_ROOM,
    ICON_CLIENT,
    PORT_MODE_INPUT,
    PORT_MODE_OUTPUT
)

# ------------------------------------------------------------------------------------------------------------
def getAppIcon(icon_name):
    #dark = bool(
        #widget.palette().brush(
            #2, QPalette.WindowText).color().lightness() > 128)

    icon = QIcon.fromTheme(icon_name)

    if icon.isNull():
        for ext in ('svg', 'svgz', 'png'):
            filename = ":app_icons/%s.%s" % (icon_name, ext)
            darkname = ":app_icons/dark/%s.%s" % (icon_name, ext)

            #if dark and QFile.exists(darkname):
                #filename = darkname

            if QFile.exists(filename):
                del icon
                icon = QIcon()
                icon.addFile(filename)
                break
    return icon

class CanvasIconPixmap(QGraphicsPixmapItem):
    def __init__(self, icon_type, icon_name, name, parent):
        QGraphicsPixmapItem.__init__(self)
        self.setParentItem(parent)
        
        self.p_size = QRectF(6, 6, 24, 24)
        
        self.icon = None
        print('iniititi', name, icon_name, icon_type)
        if icon_type == ICON_CLIENT:
            print('offolc')
            self.icon = getAppIcon(icon_name)
            if self.icon:
                print('clclmd()')
                pixmap = self.icon.pixmap(24, 24)
            #pixmap = icon.pixmap(24, 24)
                self.setPixmap(pixmap)
        #self.setScale(0.25)
        #self.setOffset(16, 16)
                self.setOffset(4, 4)
    
    def setIcon(self, icon, name):
        icon_path = ":/app_icons/gx_head.png"
        #self.m_renderer = QSvgRenderer(icon_path, canvas.scene)
    
    def update_zoom(self, scale: float):
        if self.icon is None or scale <= 0.0:
            return

        pixmap = self.icon.pixmap(24 * scale, 24 * scale)
        self.setPixmap(pixmap)
        self.setScale(1.0 / scale)
        self.setOffset(4 * scale, 4 * scale)
    
    def boundingRect(self):
        return self.p_size
    
    #def paint(self, painter, option, widget):
        #if not self.m_renderer:
            #QGraphicsPixmapItem.paint(self, painter, option, widget)
            #return

        #painter.save()
        #painter.setRenderHint(QPainter.Antialiasing, False)
        #painter.setRenderHint(QPainter.TextAntialiasing, False)
        #self.m_renderer.render(painter, self.p_size)
        #painter.restore()
    
class CanvasIcon(QGraphicsSvgItem):
    def __init__(self, icon_type, name, port_mode, parent):
        QGraphicsSvgItem.__init__(self)
        self.setParentItem(parent)

        self.m_renderer = None
        self.p_size = QRectF(0, 0, 0, 0)

        self.m_colorFX = QGraphicsColorizeEffect(self)
        self.m_colorFX.setColor(canvas.theme.box_text.color())

        #self.setGraphicsEffect(self.m_colorFX)
        self.setIcon(icon_type, name, port_mode)

    def setIcon(self, icon, name, port_mode):
        name = name.lower()
        icon_path = ""

        if icon == ICON_APPLICATION:
            self.p_size = QRectF(3, 2, 19, 18)

            if "audacious" in name:
                icon_path = ":/scalable/pb_audacious.svg"
                self.p_size = QRectF(5, 4, 16, 16)
            elif "clementine" in name:
                icon_path = ":/scalable/pb_clementine.svg"
                self.p_size = QRectF(5, 4, 16, 16)
            elif "distrho" in name:
                icon_path = ":/scalable/pb_distrho.svg"
                self.p_size = QRectF(5, 4, 16, 16)
            elif "jamin" in name:
                icon_path = ":/scalable/pb_jamin.svg"
                self.p_size = QRectF(5, 3, 16, 16)
            elif "mplayer" in name:
                icon_path = ":/scalable/pb_mplayer.svg"
                self.p_size = QRectF(5, 4, 16, 16)
            elif "vlc" in name:
                icon_path = ":/scalable/pb_vlc.svg"
                self.p_size = QRectF(5, 3, 16, 16)

            else:
                icon_path = ":/scalable/pb_generic.svg"
                self.p_size = QRectF(4, 3, 24, 24)

        elif icon == ICON_HARDWARE:
            if name == "a2j":
                icon_path = ":/scalable/DIN-5.svg"
                self.p_size = QRectF(4, 4, 24, 24)
            else:
                print('oefkkllfl', port_mode)
                if port_mode & PORT_MODE_INPUT:
                    if port_mode & PORT_MODE_OUTPUT:
                        icon_path = ":/scalable/pb_hardware.svg"
                    else:
                        icon_path = ":/scalable/audio-input-microphone.svg"
                else:
                    icon_path = ":/scalable/audio-headphones.svg"
                self.p_size = QRectF(4, 4, 24, 24)

        elif icon == ICON_DISTRHO:
            icon_path = ":/scalable/pb_distrho.svg"
            self.p_size = QRectF(5, 4, 16, 16)

        elif icon == ICON_FILE:
            icon_path = ":/scalable/pb_file.svg"
            self.p_size = QRectF(5, 4, 16, 16)

        elif icon == ICON_PLUGIN:
            icon_path = ":/scalable/pb_plugin.svg"
            self.p_size = QRectF(5, 4, 16, 16)

        elif icon == ICON_LADISH_ROOM:
            # TODO - make a unique ladish-room icon
            icon_path = ":/scalable/pb_hardware.svg"
            self.p_size = QRectF(5, 2, 16, 16)

        else:
            self.p_size = QRectF(0, 0, 0, 0)
            qCritical("PatchCanvas::CanvasIcon.setIcon(%s, %s) - unsupported icon requested" % (
                      icon2str(icon), name.encode()))
            return

        self.m_renderer = QSvgRenderer(icon_path, canvas.scene)
        self.setSharedRenderer(self.m_renderer)
        self.update()

    def update_zoom(self, scale: float):
        pass

    def type(self):
        return CanvasIconType

    def boundingRect(self):
        return self.p_size

    def paint(self, painter, option, widget):
        if not self.m_renderer:
            QGraphicsSvgItem.paint(self, painter, option, widget)
            return

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.setRenderHint(QPainter.TextAntialiasing, False)
        self.m_renderer.render(painter, self.p_size)
        painter.restore()

# ------------------------------------------------------------------------------------------------------------
