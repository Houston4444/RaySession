
from typing import TYPE_CHECKING, Union
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QLabel, 
                             QSpacerItem, QSizePolicy)
from PyQt5.QtGui import QPixmap, QColor


from .utils import get_group_icon
from .theme import StyleAttributer
from .init_values import (
    GroupObject,
    IconType,
    PortObject,
    PortSubType,
    PortgrpObject,
    canvas,
    PortType)

if TYPE_CHECKING:
    from .connect_menu import SubMenu


def theme_css(theme: StyleAttributer) -> str:
    pen = theme.fill_pen()
    
    return (f"background-color: {theme.background_color().name(QColor.HexArgb)};"
            f"color: {theme.text_color().name(QColor.HexArgb)};"
            f"border: {pen.widthF()}px solid {pen.color().name(QColor.HexArgb)}")

    
class PortCheckBox(QCheckBox):
    def __init__(self, p_object:  Union[PortObject, PortgrpObject],
                 parent: 'SubMenu'):
        QCheckBox.__init__(self, "", parent)
        self.setTristate(True)
        self._p_object = p_object
        self._parent = parent
        self.set_theme()

    def set_theme(self):
        po = self._p_object
        
        theme = canvas.theme.port
        line_theme = canvas.theme.line
        
        if isinstance(po, PortgrpObject):
            theme = canvas.theme.portgroup
            
        if po.port_type is PortType.AUDIO_JACK:
            theme = theme.audio
            line_theme = line_theme.audio
        elif po.port_type is PortType.MIDI_JACK:
            theme = theme.midi
            line_theme = line_theme.midi

        bg = theme.background_color().name(QColor.HexArgb)
        text_color = theme.text_color().name(QColor.HexArgb)
        border_color = theme.fill_pen().color().name(QColor.HexArgb)
        h_bg = theme.selected.background_color().name(QColor.HexArgb)
        h_text_color = theme.selected.text_color().name(QColor.HexArgb)
        ind_bg = canvas.theme.scene_background_color.name(QColor.HexArgb)
        checked_bg = line_theme.selected.background_color().name(QColor.HexArgb)
        
        border_width = theme.fill_pen().widthF()
        
        TOP, RIGHT, BOTTOM, LEFT = 0, 1, 2, 3
        SIDES = ['top', 'right', 'bottom', 'left']
        margin_texts = [f"margin-{side}: 2px" for side in SIDES]
        border_texts = [f"border-{side}: {border_width}px solid {border_color}"
                        for side in SIDES]
        radius_text = ""
        
        if isinstance(po, PortObject) and po.portgrp_id:
            if po.pg_pos == 0:
                margin_texts.pop(BOTTOM)
                radius_text = "border-bottom-left-radius: 0px; border-bottom-right-radius: 0px"
            elif po.pg_pos + 1 == po.pg_len:
                margin_texts.pop(TOP)
                radius_text = "border-top-left-radius: 0px; border-top-right-radius: 0px"
                
            if po.pg_pos != 0:
                border_texts[TOP] = f"border-top: 0px solid transparent"

        self.setStyleSheet(
            f"QCheckBox{{background-color: none;color: {text_color}; spacing: 0px;"
                       f"border-radius: 3px; {radius_text};}}"
            f"QCheckBox:hover{{background-color: none;color: {h_text_color}}}"
            f"QCheckBox::indicator{{background-color: {ind_bg};margin: 3px;"
                                  f"border-radius: 3px; border: 1px solid "
                                  f"{theme.fill_pen().color().name()}}}"
            f"QCheckBox::indicator:checked{{"
                f"background-color: {checked_bg}; border: 3px solid {ind_bg}}}"
            f"QCheckBox::indicator:indeterminate{{"
                f"background-color: qlineargradient("
                    f"x1: 0, y1: 0, x2: 1, y2: 1, "
                    f"stop: 0 {checked_bg}, stop: 0.55 {checked_bg}, "
                    f"stop: 0.60 {ind_bg}, stop: 1 {ind_bg}); "
                f"border: 3px solid {ind_bg}}}")

    def nextCheckState(self):
        po = self._p_object
        port_id = po.port_id if isinstance(po, PortObject) else -1
        
        self._parent.connection_asked_from_box(po, not self.isChecked())


class CheckFrame(QFrame):
    def __init__(self, p_object: Union[PortObject, PortgrpObject],
                 port_name: str, port_name_end: str,
                 parent: 'SubMenu'):
        QFrame.__init__(self, parent)
        self._p_object = p_object
        self._parent = parent
        
        self._check_box = PortCheckBox(p_object, parent)
        self._label_left = QLabel(port_name)
        self._layout = QHBoxLayout(self)
        self._layout.setSpacing(0)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.addWidget(self._check_box)
        self._layout.addWidget(self._label_left)
        spacer = QSpacerItem(2, 2, QSizePolicy.Expanding, QSizePolicy.Minimum)
        self._layout.addSpacerItem(spacer)
        self._label_right = None
        if port_name_end:
            self._label_right = QLabel(port_name_end)
            self._layout.addWidget(self._label_right)
        self._set_theme()

    def _set_theme(self):
        po = self._p_object

        theme = canvas.theme.port
        line_theme = canvas.theme.line        

        if isinstance(po, PortgrpObject):
            theme = canvas.theme.portgroup
            
        if po.port_type is PortType.AUDIO_JACK:
            theme = theme.cv if po.port_subtype is PortSubType.CV else theme.audio
            line_theme = line_theme.audio
            
        elif po.port_type is PortType.MIDI_JACK:
            theme = theme.midi
            line_theme = line_theme.midi

        text_color = theme.text_color().name()
        border_color = theme.fill_pen().color().name()
        h_text_color = theme.selected.text_color().name()
        
        border_width = theme.fill_pen().widthF()
        
        TOP, RIGHT, BOTTOM, LEFT = 0, 1, 2, 3
        SIDES = ['top', 'right', 'bottom', 'left']
        margin_texts = [f"margin-{side}: 2px" for side in SIDES]
        border_texts = [f"border-{side}: {border_width}px solid {border_color}"
                        for side in SIDES]
        radius_text = ""
        
        if isinstance(po, PortObject) and po.portgrp_id:
            if po.pg_pos == 0:
                margin_texts.pop(BOTTOM)
                radius_text = "border-bottom-left-radius: 0px; border-bottom-right-radius: 0px"
            elif po.pg_pos + 1 == po.pg_len:
                margin_texts.pop(TOP)
                radius_text = "border-top-left-radius: 0px; border-top-right-radius: 0px"
                
            if po.pg_pos != 0:
                border_texts[TOP] = f"border-top: 0px solid transparent"

        margins_text = ';'.join(margin_texts)
        borders_text = ';'.join(border_texts)

        self.setFont(theme.font())
        self.setStyleSheet(
            f"CheckFrame{{{theme_css(theme)}; spacing: 0px;"
            f"{borders_text}; border-radius: 3px; {radius_text};"
            f"{margins_text}; padding-right: 0px}}"
            f"CheckFrame:focus{{{theme_css(theme.selected)}}};")
        
        self._label_left.setFont(theme.font())
        self._label_left.setStyleSheet(
            f"QLabel{{color: {text_color}}} QLabel:focus{{color: {h_text_color}}} ")
        
        if self._label_right is not None:
            port_theme = canvas.theme.port
            if po.port_type is PortType.AUDIO_JACK:
                port_theme = port_theme.audio
            elif po.port_type is PortType.MIDI_JACK:
                port_theme = port_theme.midi

            self._label_right.setFont(port_theme.font())
            self._label_right.setStyleSheet(
                f"QLabel{{margin-left: 3px; margin-right: 0px; padding: 0px; {theme_css(port_theme)}}} "
                f"QLabel:focus{{{theme_css(port_theme.selected)}}}")

    def set_check_state(self, check_state: int):
        self._check_box.setCheckState(check_state)

    def connection_asked_from_box(self, group_id: int, port_id: int,
                                  portgrp_id: int, yesno: bool):
        self._parent.connection_asked_from_box(group_id, port_id, portgrp_id, yesno)
    
    def mousePressEvent(self, event):
        self._check_box.nextCheckState()
        
    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Space, Qt.Key_Return):
            self._check_box.nextCheckState()
            return
        QFrame.keyPressEvent(self, event)
        
    def enterEvent(self, event):
        super().enterEvent(event)
        self.setFocus()
        # self._label_right.setSelec
        

class GroupFrame(QFrame):
    ''' this class is not used now. The idea was to have group menu actions
        styled as their boxes are in the canvas, but it implies too much
        changes. Default Qt theme works for QMenu works better for the moment. '''

    def __init__(self, group: GroupObject, parent: 'SubMenu'):
        super().__init__(parent)
        self._group = group
        
        icon = get_group_icon(group.group_id, parent._port_mode)
        self._label_icon = QLabel()
        self._label_icon.setPixmap(icon.pixmap(QSize(16, 16)))
        self._label_group_name = QLabel(group.group_name)

        self._layout = QHBoxLayout(self)
        self._layout.setSpacing(0)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.addWidget(self._label_icon)
        self._layout.addWidget(self._label_group_name)
        
        theme = canvas.theme.box
        self._label_group_name.setStyleSheet(f"GroupFrame{{{theme_css(theme)}}}")
        