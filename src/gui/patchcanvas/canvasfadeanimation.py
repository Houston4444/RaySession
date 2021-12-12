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

from PyQt5.QtCore import QAbstractAnimation

# ------------------------------------------------------------------------------------------------------------


class CanvasFadeAnimation(QAbstractAnimation):
    def __init__(self, item, show):
        QAbstractAnimation.__init__(self)

        self._show = show
        self._duration = 0
        self._item = item

    def item(self):
        return self._item

    def force_stop(self):
        self.blockSignals(True)
        self.stop()

    def set_duration(self, time):
        if self._item.opacity() == 0 and not self._show:
            self._duration = 0
        else:
            self._item.show()
            self._duration = time

# ------------------------------------------------------------------------------------------------------------
