#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# PatchBay Canvas engine using QGraphicsView/Scene
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

from enum import Enum
from typing import Union
from PyQt5.QtCore import pyqtSlot, QCoreApplication
from PyQt5.QtWidgets import QWidgetAction, QMenu, QAction
from PyQt5.QtGui import QIcon, QPixmap, QPen

import patchcanvas.utils as utils
from .init_values import (
    GroupObject,
    IconType,
    PortObject,
    PortSubType,
    PortgrpObject,
    canvas,
    ClipboardElement,
    CallbackAct,
    PortType,
    PortMode,
    ConnectionObject)
from .connect_menu_widgets import CheckFrame


_translate = QCoreApplication.translate


class _Dangerous(Enum):
    NO_CARE = 0
    NO = 1
    YES = 2


class _DataConnElement:
    port_id: int
    portgrp_id: int
    action: QWidgetAction
    check_frame: CheckFrame


class _DataDisconnElement:
    group_id: int
    portgrp_id: int
    port_id_list: list[int]
    action: QAction


class SubMenu(QMenu):
    def __init__(self, name: str, p_object: Union[PortObject, PortgrpObject], parent):
        QMenu.__init__(self, name, parent)
        self._p_object = p_object

    def connection_asked_from_box(
            self, port_id: int, portgrp_id: int, connect: bool):
        pass


class GroupConnectMenu(SubMenu):
    def __init__(self, group: GroupObject, p_object: Union[PortObject, PortgrpObject],
                 parent: 'SubMenu',
                 dangerous_mode=_Dangerous.NO_CARE):
        short_group_name = group.group_name
        
        if len(short_group_name) > 15 and '/' in short_group_name:
            short_group_name = short_group_name.partition('/')[2]

        SubMenu.__init__(self, short_group_name, p_object, parent)
        
        po = self._p_object
        
        self.setIcon(utils.get_group_icon(group.group_id, po.port_mode))
        self.hovered.connect(self._mouse_hover_menu)
        
        self._parent = parent
        self._group = group
        self._elements = list[_DataConnElement]()

        self._last_portgrp_id = 0
        
        theme = canvas.theme.box
        if group.icon_type == IconType.CLIENT:
            theme = theme.client
        elif group.icon_type == IconType.HARDWARE:
            theme = theme.hardware

        bg_color = theme.background_color().name()
        border_color = theme.fill_pen().color().name()
        
        self.setStyleSheet(
            f"QMenu{{background-color:{bg_color}; border: 1px solid {border_color}}}")

        for port in canvas.port_list:
            if (port.group_id == group.group_id
                    and port.port_type is po.port_type
                    and port.port_mode is not po.port_mode):
                if isinstance(po, PortgrpObject) and port.portgrp_id:
                    if port.portgrp_id != self._last_portgrp_id:
                        for portgrp in canvas.portgrp_list:
                            if (portgrp.group_id == port.group_id
                                    and portgrp.portgrp_id == port.portgrp_id):
                                pg_name, pts_name = utils.get_portgroup_short_name_splitted(
                                    portgrp.group_id, portgrp.portgrp_id)
                                
                                self.add_element(portgrp, pg_name, pts_name)
                                break
                else:
                    if (dangerous_mode is _Dangerous.YES
                            and po.port_subtype == port.port_subtype):
                        continue

                    if (dangerous_mode is _Dangerous.NO
                            and po.port_subtype != port.port_subtype):
                        continue

                    self.add_element(port, port.port_name, '', port.port_subtype)

    def group_id(self) -> int:
        return self._group.group_id

    def add_element(self, p_object: Union[PortObject, PortgrpObject],
                    port_name: str, port_name_end: str, port_subtype=PortSubType.REGULAR):
        if self._p_object.port_subtype is PortSubType.CV:
            port_name = f"CV| {port_name}"

        check_frame = CheckFrame(p_object, port_name, port_name_end, self)
        action = QWidgetAction(self)
        action.setDefaultWidget(check_frame)
        self.addAction(action)

        self._last_portgrp_id = p_object.portgrp_id

        element = _DataConnElement()
        element.port_id = p_object.port_id if isinstance(p_object, PortObject) else -1
        element.portgrp_id = p_object.portgrp_id
        element.action = action
        element.check_frame = check_frame
        self._elements.append(element)

    def remove_element(self, port_id: int, portgrp_id: int):
        for element in self._elements:
            if (element.port_id == port_id
                    and element.portgrp_id == portgrp_id):
                self.removeAction(element.action)
                self._elements.remove(element)
                break

    def count_elements(self) -> int:
        return len(self._elements)

    def get_first_element(self) -> _DataConnElement:
        return self._elements[0]

    def check_element(self, port_id: int, portgrp_id: int, check_state: int):
        for element in self._elements:
            if (element.port_id == port_id
                    and element.portgrp_id == portgrp_id):
                element.check_frame.set_check_state(check_state)
                break

    def connection_asked_from_box(self, port_id: int, portgrp_id: int,
                                  yesno: bool):
        self._parent.connection_asked_from_box(self.group_id(), port_id,
                                               portgrp_id, yesno)

    def keyPressEvent(self, event) -> None:
        return super().keyPressEvent(event)

    def _mouse_hover_menu(self, action: QWidgetAction):
        action.defaultWidget().setFocus()
        pass


class DangerousMenu(SubMenu):
    def __init__(self, name, p_object: Union[PortObject, PortgrpObject], parent):
        SubMenu.__init__(self, name, p_object, parent)
        self.setIcon(QIcon.fromTheme('emblem-warning'))

        self.group_menus = list[GroupConnectMenu]()
        self.connection_list = list[ConnectionObject]()

    def add_group_menu(self, group: GroupObject):
        group_menu = GroupConnectMenu(group, self._p_object, self,
                                      dangerous_mode=_Dangerous.YES)
        self.group_menus.append(group_menu)
        self.addMenu(group_menu)

    def connection_asked_from_box(self, group_id: int, port_id: int,
                                  portgrp_id: int, yesno: bool):
        po = self._p_object
        
        if yesno:
            if isinstance(po, PortgrpObject) and portgrp_id:
                # in and out are portgroups
                utils.connect_portgroups(po.group_id, po.portgrp_id,
                                         group_id, portgrp_id)
            else:
                for self_port_id in po.get_port_ids():
                    utils.connect_ports(po.group_id, self_port_id,
                                        group_id, port_id)
        else:
            if isinstance(po, PortgrpObject) and portgrp_id:
                utils.connect_portgroups(po.group_id, po.portgrp_id,
                                         group_id, portgrp_id, disconnect=True)
            else:
                for connection in canvas.connection_list:
                    if connection.matches(po.group_id, po.get_port_ids(),
                                          group_id, [port_id]):
                        utils.canvas_callback(
                            CallbackAct.PORTS_DISCONNECT,
                            connection.connection_id)


class ConnectMenu(SubMenu):
    def __init__(self, p_object: Union[PortObject, PortgrpObject], parent):
        SubMenu.__init__(self, _translate('patchbay', 'Connect'),
                         p_object, parent)
        #canvas.qobject.port_added.connect(self.port_added_to_canvas)
        #canvas.qobject.port_removed.connect(self.port_removed_from_canvas)

        self.group_menus = list[GroupConnectMenu]()
        self.connection_list = list[ConnectionObject]()

        dangerous_name = ''
        has_dangerous_global = False

        po = p_object

        if po.port_type is PortType.AUDIO_JACK:
            if (po.port_mode is PortMode.OUTPUT
                    and po.port_subtype is PortSubType.CV):
                dangerous_name = _translate(
                    'patchbay', 'Audio | DANGEROUS !!!')
            elif (po.port_mode is PortMode.INPUT
                    and po.port_subtype is PortSubType.REGULAR):
                dangerous_name = _translate(
                    'patchbay', 'CV | DANGEROUS !!!')

        self.dangerous_submenu = DangerousMenu(
            dangerous_name, self._p_object, self)

        # add the needed groups (not the ports)
        for group in canvas.group_list:
            grp_has_dangerous = False
            grp_has_regular = False

            for port in canvas.port_list:
                if (port.group_id == group.group_id
                        and port.port_type is po.port_type
                        and port.port_mode is not po.port_mode):

                    if (po.port_type is PortType.AUDIO_JACK
                            and ((po.port_mode is PortMode.OUTPUT
                                  and po.port_subtype is PortSubType.CV
                                  and port.port_subtype is PortSubType.REGULAR)
                                 or (po.port_mode is PortMode.INPUT
                                     and not po.port_subtype is PortSubType.CV
                                     and port.port_subtype is PortSubType.CV))):
                        if not grp_has_dangerous:
                            self.dangerous_submenu.add_group_menu(group)
                        grp_has_dangerous = True
                        has_dangerous_global = True
                    else:
                        if not grp_has_regular:
                            self.add_group_menu(group)
                        grp_has_regular = True

                    if grp_has_dangerous and grp_has_regular:
                        break

        if has_dangerous_global:
            self.addSeparator()
            self.addMenu(self.dangerous_submenu)

    def add_group_menu(self, group: GroupObject):
        po = self._p_object
        dangerous = _Dangerous.NO_CARE
        if (po.port_type == PortType.AUDIO_JACK
                and ((po.port_mode is PortMode.OUTPUT
                      and po.port_subtype is PortSubType.CV)
                     or (po.port_mode is PortMode.INPUT
                         and not po.port_subtype is PortSubType.CV))):
            dangerous = _Dangerous.NO

        group_menu = GroupConnectMenu(group, self._p_object, self,
                                      dangerous_mode=dangerous)
        self.group_menus.append(group_menu)
        self.addMenu(group_menu)

    def connection_asked_from_box(self, group_id: int, port_id: int,
                                  portgrp_id: int, yesno: bool):
        po = self._p_object
        
        if yesno:
            if isinstance(po, PortgrpObject) and portgrp_id:
            # if self._portgrp_id and portgrp_id:
                # in and out are portgroups
                utils.connect_portgroups(po.group_id, po.portgrp_id,
                                         group_id, portgrp_id)
            else:
                for self_port_id in po.get_port_ids():
                    utils.connect_ports(po.group_id, self_port_id,
                                        group_id, port_id)
        else:
            if isinstance(po, PortgrpObject) and portgrp_id:
            # if self._portgrp_id and portgrp_id:
                utils.connect_portgroups(po.group_id, po.portgrp_id,
                                         group_id, portgrp_id, disconnect=True)
            else:
                for connection in canvas.connection_list:
                    if connection.matches(po.group_id, po.get_port_ids(),
                                          group_id, [port_id]):
                        utils.canvas_callback(
                            CallbackAct.PORTS_DISCONNECT,
                            connection.connection_id)

    def leaveEvent(self, event):
        # prevent to close the menu accidentaly when the mouse 
        # leaves the menu area
        pass

    # TODO was initially added the fact menu was updated
    # when port was added or removed
    # for portgroup it seems to be much complicated
    # user will just have to re-open the menu


class DisconnectMenu(SubMenu):
    def __init__(self, p_object: Union[PortObject, PortgrpObject], parent):
        SubMenu.__init__(self, _translate('patchbay', "Disconnect"),
                         p_object, parent)
        self._elements = list[_DataDisconnElement]()

        self._no_action_title = _translate('patchbay', 'No connections')
        self._no_action = self.addAction(self._no_action_title)
        self._no_action.setEnabled(False)

    @pyqtSlot()
    def apply_disconnection(self):
        action = self.sender()
        if action is None:
            return

        for element in self._elements:
            if element.action is action:
                for connection in canvas.connection_list:
                    if connection.matches(
                            self._p_object.group_id, self._p_object.get_port_ids(),
                            element.group_id, element.port_id_list):
                        utils.canvas_callback(
                            CallbackAct.PORTS_DISCONNECT,
                            connection.connection_id)
                break

    def add_element(self, group_id: int, port_id_list: list,
                    portgrp_id: int):
        if not port_id_list:
            return

        for element in self._elements:
            if (element.group_id == group_id
                    and element.port_id_list == port_id_list):
                # element already exists
                return

        # display actions in the group_id and port_id order
        i = 0
        following_action = None

        for element in self._elements:
            if (element.group_id > group_id
                    or (element.group_id == group_id
                        and element.port_id_list[0] > port_id_list[-1])):
                following_action = element.action
                break
            i += 1

        action_name = ""
        if isinstance(self._p_object, PortgrpObject) and portgrp_id:
            action_name = '‖ '
            action_name += utils.get_portgroup_full_name(group_id, portgrp_id)
        else:
            action_name = utils.get_full_port_name(group_id, port_id_list[0])

        icon = utils.get_group_icon(group_id, self._p_object.port_mode)

        action = QAction(action_name)
        action.setIcon(icon)
        action.triggered.connect(self.apply_disconnection)

        if following_action is None:
            self.addAction(action)
        else:
            self.insertAction(following_action, action)

        element = _DataDisconnElement()
        element.group_id = group_id
        element.portgrp_id = portgrp_id
        element.port_id_list = port_id_list
        element.action = action
        self._elements.insert(i, element)

        # remove "no connections" fake action
        if self._no_action is not None:
            self.removeAction(self._no_action)
            self._no_action = None

    def remove_element(self, group_id: int, port_id_list: int,
                       portgrp_id: int):
        for element in self._elements:
            if (element.group_id == group_id
                    and element.portgrp_id == portgrp_id
                    and element.port_id_list == port_id_list):
                self.removeAction(element.action)
                self._elements.remove(element)
                break
        else:
            return

        if not self._elements:
            self._no_action = self.addAction(self._no_action_title)
            self._no_action.setEnabled(False)


class ClipboardMenu(SubMenu):
    def __init__(self, p_object: Union[PortObject, PortgrpObject], parent):
        SubMenu.__init__(self, _translate('patchbay', 'Clipboard'),
                         p_object, parent)

        cut_action = self.addAction(
            _translate('patchbay', 'Cut connections'))
        cut_action.setIcon(QIcon.fromTheme('edit-cut'))
        cut_action.triggered.connect(self.cut_connections)

        copy_action = self.addAction(
            _translate('patchbay', 'Copy connections'))
        copy_action.setIcon(QIcon.fromTheme('edit-copy'))
        copy_action.triggered.connect(self.copy_connections)

        po = self._p_object

        for self_port_id in po.get_port_ids():
            con_list = utils.get_port_connection_list(
                po.group_id, self_port_id)
            if con_list:
                break

        if not con_list:
            cut_action.setEnabled(False)
            copy_action.setEnabled(False)

        for cb_element in canvas.clipboard:
            if (cb_element.port_type is po.port_type
                    and cb_element.port_mode is po.port_mode
                    and cb_element.port_id not in po.get_port_ids()):
                paste_action = self.addAction(
                    _translate('patchbay', 'Paste connections'))
                paste_action.setIcon(QIcon.fromTheme('edit-paste'))
                paste_action.triggered.connect(self.paste_connections)
                break

    def write_clipboard(self, cut: bool):
        canvas.clipboard.clear()
        canvas.clipboard_cut = cut

        po = self._p_object

        for self_port_id in po.get_port_ids():
            group_port_ids = list[tuple[int]]()

            for connection in canvas.connection_list:
                if po.port_mode is PortMode.OUTPUT:
                    if (connection.group_out_id == po.group_id
                            and connection.port_out_id == self_port_id):
                        group_port_ids.append((connection.group_in_id,
                                               connection.port_in_id))
                elif po.port_mode is PortMode.INPUT:
                    if (connection.group_in_id == po.group_id
                            and connection.port_in_id == self_port_id):
                        group_port_ids.append((connection.group_out_id,
                                               connection.port_out_id))

            element = ClipboardElement()
            element.group_id = po.group_id
            element.port_id = self_port_id
            element.port_type = po.port_type
            element.port_mode = po.port_mode
            element.group_port_ids = group_port_ids

            canvas.clipboard.append(element)

    def cut_connections(self):
        self.write_clipboard(True)

    def copy_connections(self):
        self.write_clipboard(False)

    def paste_connections(self):
        po = self._p_object
        
        for i in range(len(po.get_port_ids())):
            for j in range(len(canvas.clipboard)):
                if i % len(canvas.clipboard) != j % len(po.get_port_ids()):
                    continue

                self_port_id = po.get_port_ids()[i]
                element = canvas.clipboard[j]

                if (element.port_type is po.port_type
                        and element.port_mode is po.port_mode):
                    for group_port_id in element.group_port_ids:
                        group_id, port_id = group_port_id

                        if canvas.clipboard_cut:
                            # remove the original connection if still exists
                            for connection in canvas.connection_list:
                                if connection.matches(
                                        element.group_id, [element.port_id],
                                        group_id, [port_id]):
                                    utils.canvas_callback(
                                        CallbackAct.PORTS_DISCONNECT,
                                        connection.connection_id)
                                    break

                        utils.connect_ports(po.group_id, self_port_id,
                                            group_id, port_id)
                    break

        # once paste, de-activate cut to prevent recut of connections
        # if they have been remade by user
        canvas.clipboard_cut = False


class ConnectableContextMenu(QMenu):
    def __init__(self, p_object: Union[PortObject, PortgrpObject]):
        QMenu.__init__(self)

        self._p_object = p_object
        po = self._p_object

        self.connection_list = list[ConnectionObject]()

        canvas.qobject.connection_added.connect(
            self.connection_added_to_canvas)
        canvas.qobject.connection_removed.connect(
            self.connection_removed_from_canvas)

        dark = '-dark' if utils.is_dark_theme(self) else ''

        self.connect_menu = ConnectMenu(self._p_object, self)
        self.connect_menu.setIcon(
            QIcon(QPixmap(':scalable/breeze%s/lines-connector' % dark)))
        self.addMenu(self.connect_menu)

        self.disconnect_menu = DisconnectMenu(self._p_object, self)
        self.disconnect_menu.setIcon(
            QIcon(QPixmap(':scalable/breeze%s/lines-disconnector' % dark)))
        self.addMenu(self.disconnect_menu)

        disconnect_all_action = self.addAction(
            _translate('patchbay', "Disconnect All"))
        disconnect_all_action.setIcon(
            QIcon(QPixmap(':scalable/breeze%s/lines-disconnector' % dark)))
        disconnect_all_action.triggered.connect(self.disconnect_all)

        self.clipboard_menu = ClipboardMenu(self._p_object, self)
        self.clipboard_menu.setIcon(QIcon.fromTheme('edit-paste'))
        self.addMenu(self.clipboard_menu)

        self.addSeparator()

        for connection in canvas.connection_list:
            if connection.concerns(po.group_id, po.get_port_ids()):
                self.add_connection(connection)

    def disconnect_all(self):
        for connection in self.connection_list:
            utils.canvas_callback(CallbackAct.PORTS_DISCONNECT,
                                  connection.connection_id)

    def add_connection(self, connection: ConnectionObject):
        self.connection_list.append(connection)

        po = self._p_object

        for port in canvas.port_list:
            if ((po.port_mode is PortMode.OUTPUT
                        and port.group_id == connection.group_in_id
                        and port.port_id == connection.port_in_id)
                    or (po.port_mode is PortMode.INPUT
                        and port.group_id == connection.group_out_id
                        and port.port_id == connection.port_out_id)):
                group_id = port.group_id
                port_id = port.port_id
                portgrp_id = port.portgrp_id
                port_id_list = [port_id]

                if isinstance(po, PortgrpObject) and portgrp_id:
                    port_id = -1
                    port_id_list = utils.get_portgroup_port_list(
                        group_id, portgrp_id)

                con_state = utils.get_portgroup_connection_state(
                    po.group_id, po.get_port_ids(),
                    group_id, port_id_list)

                for group_menu in self.connect_menu.group_menus:
                    if group_menu.group_id() == group_id:
                        group_menu.check_element(
                            port_id, portgrp_id, con_state)
                        break

                for group_menu in self.connect_menu.dangerous_submenu.group_menus:
                    if group_menu.group_id() == group_id:
                        group_menu.check_element(
                            port_id, portgrp_id, con_state)
                        break

                self.disconnect_menu.add_element(group_id, port_id_list,
                                                 portgrp_id)
                break

    def connection_added_to_canvas(self, connection_id: int):
        for connection in canvas.connection_list:
            if connection.connection_id == connection_id:
                # if connection.concerns(self._group_id, self._port_id_list):
                #     return

                self.add_connection(connection)

    def connection_removed_from_canvas(self, connection_id: int):
        po = self._p_object
        
        for connection in self.connection_list:
            if connection.connection_id == connection_id:
                for port in canvas.port_list:
                    if ((po.port_mode is PortMode.OUTPUT
                            and port.group_id == connection.group_in_id
                            and port.port_id == connection.port_in_id)
                        or (po.port_mode is PortMode.INPUT
                            and port.group_id == connection.group_out_id
                            and port.port_id == connection.port_out_id)):
                        group_id = port.group_id
                        port_id = port.port_id
                        portgrp_id = port.portgrp_id

                        if isinstance(po, PortgrpObject) and portgrp_id:
                            port_id = -1
                            port_id_list = utils.get_portgroup_port_list(
                                group_id, portgrp_id)
                        else:
                            port_id_list = [port_id]

                        con_state = utils.get_portgroup_connection_state(
                            po.group_id, po.get_port_ids(),
                            group_id, port_id_list)

                        for group_menu in self.connect_menu.group_menus:
                            if group_menu.group_id() == group_id:
                                group_menu.check_element(
                                    port_id, portgrp_id, con_state)
                                break

                        for group_menu in self.connect_menu.dangerous_submenu.group_menus:
                            if group_menu.group_id() == group_id:
                                group_menu.check_element(
                                    port_id, portgrp_id, con_state)
                                break

                        self.disconnect_menu.remove_element(
                            group_id, port_id_list, portgrp_id)
                        break

                self.connection_list.remove(connection)
                break