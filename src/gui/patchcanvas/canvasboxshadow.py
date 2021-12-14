#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# PatchBay Canvas engine using QGraphicsView/Scene
# Copyright (C) 2010-2019 Filipe Coelho <falktx@falktx.com>
# Copyright (C) 2019-2021 Mathieu Picot <picotmathieu@gmail.com>
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

from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QGraphicsDropShadowEffect

# ------------------------------------------------------------------------------------------------------------
# Imports (Custom)

from . import canvas

# ------------------------------------------------------------------------------------------------------------

class CanvasBoxShadow(QGraphicsDropShadowEffect):
    def __init__(self, parent):
        QGraphicsDropShadowEffect.__init__(self, parent)

        self.fake_parent = None

        self.setBlurRadius(20)
        self.setColor(canvas.theme.box_shadow_color)
        self.setOffset(0, 0)

    def set_opacity(self, opacity: float):
        color = QColor(canvas.theme.box_shadow_color)
        color.setAlphaF(opacity)
        self.setColor(color)

    def draw(self, painter):
        if self.fake_parent is not None:
            self.fake_parent.repaint_lines()
        QGraphicsDropShadowEffect.draw(self, painter)

# ------------------------------------------------------------------------------------------------------------
