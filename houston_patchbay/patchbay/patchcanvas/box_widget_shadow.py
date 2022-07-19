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

from typing import TYPE_CHECKING
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QGraphicsDropShadowEffect, QGraphicsObject

from .init_values import canvas
from .theme import StyleAttributer

if TYPE_CHECKING:
    from .box_widget import BoxWidget


class BoxWidgetShadow(QGraphicsDropShadowEffect):
    def __init__(self, parent: QGraphicsObject):
        QGraphicsDropShadowEffect.__init__(self, parent)

        self._fake_parent = None
        self._theme = None

        self.setBlurRadius(20)
        self.setOffset(0, 2)

    def set_theme(self, theme: StyleAttributer):
        self._theme = theme 
        self.setColor(theme.background_color())

    def set_opacity(self, opacity: float):
        color = QColor(self._theme.background_color())
        color.setAlphaF(opacity)
        self.setColor(color)

    def set_fake_parent(self, parent: 'BoxWidget'):
        self._fake_parent = parent

    def draw(self, painter):
        if self._fake_parent is not None:
            if ((self._fake_parent.boundingRect().height()
                 * canvas.scene.get_zoom_scale())
                >= canvas.scene._view.height()):
                # workaround for a visual bug with cached QGraphicsItem,
                # QDropShadowEffect and big zoom.
                # see https://bugreports.qt.io/browse/QTBUG-77400
                self._fake_parent.set_in_cache(False)
            else:
                self._fake_parent.set_in_cache(True)

            self._fake_parent.repaint_lines()
        QGraphicsDropShadowEffect.draw(self, painter)

# ------------------------------------------------------------------------------------------------------------
