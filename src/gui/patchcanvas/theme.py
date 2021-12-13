#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# PatchBay Canvas Themes
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

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont, QPen, QPixmap

# ------------------------------------------------------------------------------------------------------------

theme_dict = {
    "box": {"border": (76, 77, 78),
            "border_width": 1,
            "background": (32, 34, 35),
            "background_2": (38, 40, 41),
            "font-name": "Deja Vu Sans",
            "font-size": 11,
            "font-state": "bold"},
    "box.selected": {},
    "box.hardware": {},
    "box.hardware.selected": {},
    "box.client": {},
    "box.client.selected": {},
    "box.monitor": {},
    "box.monitor.selected": {},
    "portgroup": {},
    "portgroup.selected": {}}


class Theme(object):
    # enum List
    THEME_SILVER_GOLD = 0
    THEME_BLACK_GOLD = 1
    THEME_MODERN_DARK = 2
    THEME_MAX = 3

    # enum BackgroundType
    THEME_BG_SOLID = 0
    THEME_BG_GRADIENT = 1

    def __init__(self, idx):
        object.__init__(self)

        self.idx = idx

        # don't manage different themes anymore with different sizes anymore
        # only color schemes and pen widths
        self.wrap_triangle_pen = QPen(QColor(56, 57, 58), 1, Qt.SolidLine)

        self.port_in_portgrp_width = 19
        self.port_height = 16
        self.port_offset = 0
        self.port_spacing = 2
        self.port_spacingT = 2
        
        self.box_spacing = 4
        self.box_spacing_hor = 24
        self.magnet = 12
        self.hardware_rack_width = 5

        self.set_theme(idx)

    def set_theme(self, idx):
        if idx == self.THEME_SILVER_GOLD:
            # Canvas
            self.canvas_bg = QColor(0, 0, 0)

            # Boxes
            self.box_pen = QPen(QColor(76, 77, 78), 1, Qt.SolidLine)
            self.box_pen_sel = QPen(QColor(206, 207, 208), 1, Qt.DashLine)
            self.box_bg_1 = QColor(32, 34, 35)
            self.box_bg_2 = QColor(38, 40, 41)
            self.box_shadow = QColor(89, 89, 89, 180)

            self.box_text = QPen(QColor(190, 190, 190), 0)
            self.box_text_sel = self.box_text

            self.box_font_name = "Deja Vu Sans"
            self.box_font_size = 11
            self.box_font_state = QFont.Bold

            # Ports
            self.port_text = QPen(QColor(48, 32, 0))
            self.port_font_name = "Deja Vu Sans"
            self.port_font_size = 11
            self.port_font_state = QFont.Normal

            self.port_audio_jack_pen = QPen(QColor(143, 119, 0), 1.4)
            self.port_audio_jack_pen_sel = self.port_audio_jack_pen
            self.port_midi_jack_pen = QPen(QColor(43, 23, 9), 1)
            self.port_midi_jack_pen_sel = self.port_midi_jack_pen
            self.port_midi_alsa_pen = QPen(QColor(93, 141, 46), 1)
            self.port_midi_alsa_pen_sel = QPen(QColor(93 + 30, 141 + 30, 46 + 30), 1)
            self.port_parameter_pen = QPen(QColor(137, 76, 43), 1)
            self.port_parameter_pen_sel = QPen(QColor(137 + 30, 76 + 30, 43 + 30), 1)
            self.port_cv_jack_pen = self.port_audio_jack_pen
            self.port_cv_jack_pen_sel = self.port_audio_jack_pen_sel

            self.port_audio_jack_bg = QColor(165, 165, 165)
            self.port_audio_jack_bg_sel = QColor(198, 161, 80)
            self.port_midi_jack_bg = QColor(77, 42, 16)
            self.port_midi_jack_bg_sel = QColor(160, 86, 33)
            self.port_midi_alsa_bg = QColor(64, 112, 18)
            self.port_midi_alsa_bg_sel = QColor(64 + 50, 112 + 50, 18 + 50)
            self.port_parameter_bg = QColor(101, 47, 16)
            self.port_parameter_bg_sel = QColor(101 + 50, 47 + 50, 16 + 50)
            self.port_cv_jack_bg = QColor(220, 220, 220)
            self.port_cv_jack_bg_sel = QColor(198, 161, 80)

            self.portgrp_audio_jack_pen = QPen(QColor(143, 119, 0), 1.4)
            self.portgrp_audio_jack_pen_sel = self.portgrp_audio_jack_pen
            self.portgrp_audio_jack_bg = QColor(185, 185, 185)
            self.portgrp_audio_jack_bg_sel = QColor(209, 170, 86)

            self.port_audio_jack_text = self.port_text
            self.port_audio_jack_text_sel = self.port_text
            self.port_midi_jack_text = QPen(QColor(255, 255, 150), 0)
            self.port_midi_jack_text_sel = self.port_midi_jack_text
            self.port_midi_alsa_text = self.port_text
            self.port_midi_alsa_text_sel = self.port_text
            self.port_parameter_text = self.port_text
            self.port_parameter_text_sel = self.port_text

            # Lines
            self.line_audio_jack = QColor(100, 100, 100)
            self.line_audio_jack_sel = QColor(198, 161, 80)
            self.line_audio_jack_glow = QColor(100, 100, 200)
            self.line_midi_jack = QColor(77, 42, 16)
            self.line_midi_jack_sel = QColor(160, 86, 33)
            self.line_midi_jack_glow = QColor(200, 100, 100)
            self.line_midi_alsa = QColor(93, 141, 46)
            self.line_midi_alsa_sel = QColor(93 + 90, 141 + 90, 46 + 90)
            self.line_midi_alsa_glow = QColor(100, 200, 100)
            self.line_parameter = QColor(137, 76, 43)
            self.line_parameter_sel = QColor(137 + 90, 76 + 90, 43 + 90)
            self.line_parameter_glow = QColor(166, 133, 133)

            self.rubberband_pen = QPen(QColor(206, 207, 208), 1, Qt.SolidLine)
            self.rubberband_brush = QColor(76, 77, 78, 100)

        if idx == self.THEME_BLACK_GOLD:
            # Canvas
            self.canvas_bg = QColor(0, 0, 0)

            # Boxes
            self.box_pen = QPen(QColor(76, 77, 78), 1, Qt.SolidLine)
            self.box_pen_sel = QPen(QColor(206, 207, 208), 1, Qt.DashLine)
            self.box_bg_1 = QColor(32, 34, 35)
            self.box_bg_2 = QColor(38, 40, 41)
            self.box_shadow = QColor(89, 89, 89, 180)

            self.box_text = QPen(QColor(210, 210, 210), 0)
            self.box_text_sel = self.box_text

            self.box_font_name = "Deja Vu Sans"
            self.box_font_size = 11
            self.box_font_state = QFont.Bold

            # Ports
            self.port_text = QPen(QColor(200, 200, 200))
            self.port_font_name = "Deja Vu Sans"
            self.port_font_size = 11
            self.port_font_state = QFont.Normal

            self.port_audio_jack_pen = QPen(QColor(100, 81, 0), 1.0)
            self.port_audio_jack_pen_sel = self.port_audio_jack_pen
            self.port_midi_jack_pen = QPen(QColor(43, 23, 9), 1)
            self.port_midi_jack_pen_sel = self.port_midi_jack_pen
            self.port_midi_alsa_pen = QPen(QColor(93, 141, 46), 1)
            self.port_midi_alsa_pen_sel = QPen(QColor(93 + 30, 141 + 30, 46 + 30), 1)
            self.port_parameter_pen = QPen(QColor(137, 76, 43), 1)
            self.port_parameter_pen_sel = QPen(QColor(137 + 30, 76 + 30, 43 + 30), 1)
            self.port_cv_jack_pen = self.port_audio_jack_pen
            self.port_cv_jack_pen_sel = self.port_audio_jack_pen_sel

            self.port_audio_jack_bg = QColor(40, 40, 48)
            self.port_audio_jack_bg_sel = QColor(198, 161, 80)
            #self.port_audio_jack_bg_sel = QColor(60, 60, 72)
            self.port_midi_jack_bg = QColor(77, 42, 16)
            self.port_midi_jack_bg_sel = QColor(160, 86, 33)
            self.port_midi_alsa_bg = QColor(64, 112, 18)
            self.port_midi_alsa_bg_sel = QColor(64 + 50, 112 + 50, 18 + 50)
            self.port_parameter_bg = QColor(101, 47, 16)
            self.port_parameter_bg_sel = QColor(101 + 50, 47 + 50, 16 + 50)
            self.port_cv_jack_bg = QColor(20, 20, 25)
            self.port_cv_jack_bg_sel = QColor(198, 161, 80)

            self.portgrp_audio_jack_pen = QPen(QColor(100, 81, 0), 1.0)
            self.portgrp_audio_jack_pen_sel = self.portgrp_audio_jack_pen
            self.portgrp_audio_jack_bg = QColor(25, 25, 30)
            self.portgrp_audio_jack_bg_sel = QColor(209, 170, 86)
            #self.portgrp_audio_jack_bg_sel = QColor(60, 60, 72)

            self.port_audio_jack_text = self.port_text
            self.port_audio_jack_text_sel = QPen(QColor(0, 0, 0))
            #self.port_audio_jack_text_sel = self.port_text
            self.port_midi_jack_text = QPen(QColor(255, 255, 150), 0)
            self.port_midi_jack_text_sel = self.port_midi_jack_text
            self.port_midi_alsa_text = self.port_text
            self.port_midi_alsa_text_sel = self.port_text
            self.port_parameter_text = self.port_text
            self.port_parameter_text_sel = self.port_text

            # Lines
            self.line_audio_jack = QColor(60, 60, 72)
            #self.line_audio_jack = QColor(80, 80, 96)
            #self.line_audio_jack_sel = QColor(100, 81, 0)
            self.line_audio_jack_sel = QColor(118, 118, 141)
            self.line_audio_jack_glow = QColor(100, 100, 200)
            self.line_midi_jack = QColor(77, 42, 16)
            self.line_midi_jack_sel = QColor(160, 86, 33)
            self.line_midi_jack_glow = QColor(200, 100, 100)
            self.line_midi_alsa = QColor(93, 141, 46)
            self.line_midi_alsa_sel = QColor(93 + 90, 141 + 90, 46 + 90)
            self.line_midi_alsa_glow = QColor(100, 200, 100)
            self.line_parameter = QColor(137, 76, 43)
            self.line_parameter_sel = QColor(137 + 90, 76 + 90, 43 + 90)
            self.line_parameter_glow = QColor(166, 133, 133)

            self.rubberband_pen = QPen(QColor(206, 207, 208), 1, Qt.SolidLine)
            self.rubberband_brush = QColor(76, 77, 78, 100)

        elif idx == self.THEME_MODERN_DARK:
            # Canvas
            self.canvas_bg = QColor(0, 0, 0)

            # Boxes
            self.box_pen = QPen(QColor(76, 77, 78), 1, Qt.SolidLine)
            self.box_pen_sel = QPen(QColor(206, 207, 208), 1, Qt.DashLine)
            self.box_bg_1 = QColor(32, 34, 35)
            self.box_bg_2 = QColor(38, 40, 41)
            self.box_shadow = QColor(89, 89, 89, 180)

            self.box_text = QPen(QColor(240, 240, 240), 0)
            self.box_text_sel = self.box_text
            self.box_font_name = "Deja Vu Sans"
            self.box_font_size = 11
            self.box_font_state = QFont.Bold

            # Ports
            self.port_text = QPen(QColor(250, 250, 250), 0)
            self.port_font_name = "Deja Vu Sans"
            self.port_font_size = 11
            self.port_font_state = QFont.Normal

            self.port_audio_jack_pen = QPen(QColor(63, 90, 126), 1)
            self.port_audio_jack_pen_sel = QPen(QColor(63 + 30, 90 + 30, 126 + 30), 1)
            self.port_midi_jack_pen = QPen(QColor(159, 44, 42), 1)
            self.port_midi_jack_pen_sel = QPen(QColor(159 + 30, 44 + 30, 42 + 30), 1)
            self.port_midi_alsa_pen = QPen(QColor(93, 141, 46), 1)
            self.port_midi_alsa_pen_sel = QPen(QColor(93 + 30, 141 + 30, 46 + 30), 1)
            self.port_parameter_pen = QPen(QColor(137, 76, 43), 1)
            self.port_parameter_pen_sel = QPen(QColor(137 + 30, 76 + 30, 43 + 30), 1)
            self.port_cv_jack_pen = self.port_audio_jack_pen
            self.port_cv_jack_pen_sel = self.port_audio_jack_pen_sel

            self.port_audio_jack_bg = QColor(35, 61, 99)
            self.port_audio_jack_bg_sel = QColor(35 + 50, 61 + 50, 99 + 50)
            self.port_midi_jack_bg = QColor(120, 15, 16)
            self.port_midi_jack_bg_sel = QColor(120 + 50, 15 + 50, 16 + 50)
            self.port_midi_alsa_bg = QColor(64, 112, 18)
            self.port_midi_alsa_bg_sel = QColor(64 + 50, 112 + 50, 18 + 50)
            self.port_parameter_bg = QColor(101, 47, 16)
            self.port_parameter_bg_sel = QColor(101 + 50, 47 + 50, 16 + 50)
            self.port_cv_jack_bg = QColor(18, 32, 50)
            self.port_cv_jack_bg_sel = self.port_audio_jack_bg_sel

            self.portgrp_audio_jack_pen = QPen(QColor(63, 90, 126), 1)
            self.portgrp_audio_jack_pen_sel = QPen(QColor(63 + 30, 90 + 30, 126 + 30), 1)
            self.portgrp_audio_jack_bg = QColor(26, 45, 71)
            self.portgrp_audio_jack_bg_sel = QColor(27 + 50, 47 + 50, 75 + 50)

            self.port_audio_jack_text = self.port_text
            self.port_audio_jack_text_sel = self.port_text
            self.port_midi_jack_text = self.port_text
            self.port_midi_jack_text_sel = self.port_text
            self.port_midi_alsa_text = self.port_text
            self.port_midi_alsa_text_sel = self.port_text
            self.port_parameter_text = self.port_text
            self.port_parameter_text_sel = self.port_text

            # Lines
            self.line_audio_jack = QColor(63, 90, 126)
            self.line_audio_jack_sel = QColor(63 + 90, 90 + 90, 126 + 90)
            self.line_audio_jack_glow = QColor(100, 100, 200)
            self.line_midi_jack = QColor(159, 44, 42)
            self.line_midi_jack_sel = QColor(159 + 90, 44 + 90, 42 + 90)
            self.line_midi_jack_glow = QColor(200, 100, 100)
            self.line_midi_alsa = QColor(93, 141, 46)
            self.line_midi_alsa_sel = QColor(93 + 90, 141 + 90, 46 + 90)
            self.line_midi_alsa_glow = QColor(100, 200, 100)
            self.line_parameter = QColor(137, 76, 43)
            self.line_parameter_sel = QColor(137 + 90, 76 + 90, 43 + 90)
            self.line_parameter_glow = QColor(166, 133, 133)

            self.rubberband_pen = QPen(QColor(206, 207, 208), 1, Qt.SolidLine)
            self.rubberband_brush = QColor(76, 77, 78, 100)

# ------------------------------------------------------------------------------------------------------------

def get_default_theme():
    return Theme.THEME_BLACK_GOLD

def get_theme_name(idx: int)->str:
    if idx == Theme.THEME_BLACK_GOLD:
        return "Black Gold"
    if idx == Theme.THEME_SILVER_GOLD:
        return "Silver Gold"
    if idx == Theme.THEME_MODERN_DARK:
        return "Modern Dark"
    return ""

def get_default_theme_name():
    return "Black Gold"

# ------------------------------------------------------------------------------------------------------------
