#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# PatchBay Canvas engine using QGraphicsView/Scene
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

from PyQt5.QtCore import pyqtSlot, QCoreApplication
from PyQt5.QtWidgets import QWidgetAction, QMenu, QCheckBox, QAction
from PyQt5.QtGui import QIcon, QPixmap

import patchcanvas.utils as utils

from .init_values import (
    canvas,
    ClipboardElement,
    ACTION_PORTS_DISCONNECT,
    PORT_TYPE_AUDIO_JACK,
    PORT_TYPE_MIDI_JACK,
    PortMode,
    ConnectionObject)


_translate = QCoreApplication.translate

DANGEROUS_NO_CARE = 0
DANGEROUS_NO = 1
DANGEROUS_YES = 2

class PortData:
    def __init__(self, group_id: int, port_id: int, port_type: int,
                 port_mode: int, portgrp_id: int, is_alternate: bool):
        self._group_id = group_id
        self._port_id = port_id
        self._port_type = port_type
        self._port_mode = port_mode
        self._portgrp_id = portgrp_id
        self._is_alternate = is_alternate
        self._port_id_list = [port_id]

        if portgrp_id:
            self._port_id_list = utils.get_portgroup_port_list(
                group_id, portgrp_id)


class PortCheckBox(QCheckBox):
    def __init__(self, port_id: int, portgrp_id: int, port_name: str,
                 port_type: int, parent):
        QCheckBox.__init__(self, port_name, parent)
        self.setTristate(True)
        self.setMinimumHeight(23)
        self.setMinimumWidth(100)

        # border_color = canvas.theme.port_audio_jack_pen.color().name()
        # sel_bg = canvas.theme.port_audio_jack_bg.name()
        # sel_text_color = canvas.theme.port_audio_jack_text.color().name()

        # if port_type == PORT_TYPE_MIDI_JACK:
        #     border_color = canvas.theme.port_midi_jack_pen.color().name()
        #     sel_bg = canvas.theme.port_midi_jack_bg.name()
        #     sel_text_color = canvas.theme.port_midi_jack_text.color().name()

        # #self.setStyleSheet(
        #     #"""QCheckBox:hover{background-color: %s;color: %s}
        #     #QCheckBox::indicator:hover{background-color: #202020;color: white}""" % (
        #         #sel_bg, sel_text_color))
        self._parent = parent
        self._port_id = port_id
        self._portgrp_id = portgrp_id

    def nextCheckState(self):
        self._parent.connection_asked_from_box(
            self._port_id, self._portgrp_id, not self.isChecked())


class SubMenu(QMenu):
    def __init__(self, name: str, port_data: PortData, parent):
        QMenu.__init__(self, name, parent)
        self._port_data = port_data
        self._group_id = port_data._group_id
        self._port_id = port_data._port_id
        self._port_type = port_data._port_type
        self._port_mode = port_data._port_mode
        self._portgrp_id = port_data._portgrp_id
        self._is_alternate = port_data._is_alternate
        self._port_id_list = port_data._port_id_list


class ConnectGroupMenu(SubMenu):
    def __init__(self, group_name: str, group_id: str, port_data, parent,
                 dangerous_mode=DANGEROUS_NO_CARE):
        SubMenu.__init__(self, group_name, port_data, parent)
        self._parent = parent
        self._menu_group_id = group_id
        self.elements = []

        self._last_portgrp_id = 0

        for port in canvas.port_list:
            if (port.group_id == self._menu_group_id
                    and port.port_type == self._port_type
                    and port.port_mode != self._port_mode):
                if self._portgrp_id and port.portgrp_id:
                    if port.portgrp_id != self._last_portgrp_id:
                        for portgrp in canvas.portgrp_list:
                            if (portgrp.group_id == port.group_id
                                    and portgrp.portgrp_id == port.portgrp_id):
                                portgrp_full_name = utils.get_portgroup_full_name(
                                    portgrp.group_id, portgrp.portgrp_id)
                                portgrp_name = '‖ ' \
                                    + portgrp_full_name.partition(':')[2]

                                # all portgroups items will have -1 as port_id
                                self.add_element(-1, port.portgrp_id,
                                                 portgrp_name)
                                break
                else:
                    if (dangerous_mode == DANGEROUS_YES
                            and self._is_alternate == port.is_alternate):
                        continue

                    if (dangerous_mode == DANGEROUS_NO
                            and self._is_alternate != port.is_alternate):
                        continue

                    self.add_element(port.port_id, port.portgrp_id,
                                     port.port_name, port.is_alternate)

    def group_id(self)->int:
        return self._menu_group_id

    def add_element(self, port_id: int, portgrp_id: int,
                    port_name: str, is_alternate=False):
        if self._port_type == PORT_TYPE_AUDIO_JACK and is_alternate:
            port_name = "CV| %s" % port_name

        check_box = PortCheckBox(port_id, portgrp_id, port_name,
                                 self._port_type, self)
        action = QWidgetAction(self._parent)
        action.setDefaultWidget(check_box)

        if not self._portgrp_id and portgrp_id != self._last_portgrp_id:
            self.addSeparator()
        self._last_portgrp_id = portgrp_id

        self.addAction(action)

        self.elements.append(
            {'port_id': port_id, 'portgrp_id': portgrp_id,
             'action': action, 'check_box': check_box})

    def remove_element(self, port_id: int, portgrp_id: int):
        for element in self.elements:
            if (element['port_id'] == port_id
                    and element['portgrp_id'] == portgrp_id):
                self.removeAction(element['action'])
                self.elements.remove(element)
                break

    def check_element(self, port_id: int, portgrp_id: int, check_state: int):
        for element in self.elements:
            if (element['port_id'] == port_id
                    and element['portgrp_id'] == portgrp_id):
                check_box = element['check_box']
                check_box.setCheckState(check_state)
                break

    def connection_asked_from_box(self, port_id: int, portgrp_id: int,
                                  yesno: bool):
        self._parent.connection_asked_from_box(self._menu_group_id, port_id,
                                               portgrp_id, yesno)

class DangerousMenu(SubMenu):
    def __init__(self, name, port_data, parent):
        SubMenu.__init__(self, name, port_data, parent)
        self.setIcon(QIcon.fromTheme('emblem-warning'))

        self.group_menus = []
        self.connection_list = []

    def add_group_menu(self, group_id: int, group_name: str):
        if len(group_name) > 15:
            if '/' in group_name:
                group_name = group_name.partition('/')[2]

        group_menu = ConnectGroupMenu(group_name, group_id,
                                      self._port_data, self,
                                      dangerous_mode=DANGEROUS_YES)
        group_icon = utils.get_group_icon(group_id, self._port_mode)
        group_menu.setIcon(group_icon)
        self.group_menus.append(group_menu)
        self.addMenu(group_menu)

    def connection_asked_from_box(self, group_id: int, port_id: int,
                                  portgrp_id: int, yesno: bool):
        if yesno:
            if self._portgrp_id and portgrp_id:
                # in and out are portgroups
                utils.connect_portgroups(self._group_id, self._portgrp_id,
                                        group_id, portgrp_id)
            else:
                for self_port_id in self._port_id_list:
                    utils.connect_ports(self._group_id, self_port_id,
                                        group_id, port_id)
        else:
            if self._portgrp_id and portgrp_id:
                utils.connect_portgroups(self._group_id, self._portgrp_id,
                                        group_id, portgrp_id, disconnect=True)
            else:
                for connection in canvas.connection_list:
                    if utils.connection_matches(
                            connection, self._group_id, self._port_id_list,
                            group_id, [port_id]):
                        utils.canvas_callback(
                            ACTION_PORTS_DISCONNECT,
                            connection.connection_id, '', '')


class ConnectMenu(SubMenu):
    def __init__(self, port_data, parent):
        SubMenu.__init__(self, _translate('patchbay', 'Connect'),
                         port_data, parent)
        #canvas.qobject.port_added.connect(self.port_added_to_canvas)
        #canvas.qobject.port_removed.connect(self.port_removed_from_canvas)

        self.group_menus = []
        self.connection_list = []

        dangerous_name = ''

        if self._port_type == PORT_TYPE_AUDIO_JACK:
            if (self._port_mode == PortMode.OUTPUT
                    and self._is_alternate):
                dangerous_name = _translate(
                    'patchbay', 'Audio | DANGEROUS !!!')
            elif (self._port_mode == PortMode.INPUT
                    and not self._is_alternate):
                dangerous_name = _translate(
                    'patchbay', 'CV | DANGEROUS !!!')

        self.dangerous_submenu = DangerousMenu(
            dangerous_name, port_data, self)

        has_dangerous_global = False

        # add the needed groups (not the ports)
        for group in canvas.group_list:
            has_dangerous = False
            has_regular = False

            for port in canvas.port_list:
                if (port.group_id == group.group_id
                        and port.port_type == self._port_type
                        and port.port_mode != self._port_mode):

                    if (self._port_type == PORT_TYPE_AUDIO_JACK
                            and (self._port_mode == PortMode.OUTPUT
                                 and self._is_alternate
                                 and not port.is_alternate)
                                or (self._port_mode == PortMode.INPUT
                                    and not self._is_alternate
                                    and port.is_alternate)):
                        if not has_dangerous:
                            self.dangerous_submenu.add_group_menu(
                                group.group_id, group.group_name)
                        has_dangerous = True
                        has_dangerous_global = True
                    else:
                        if not has_regular:
                            self.add_group_menu(group.group_id, group.group_name)
                        has_regular = True

                    if has_dangerous and has_regular:
                        break

        if has_dangerous_global:
            self.addSeparator()
            self.addMenu(self.dangerous_submenu)

    def add_group_menu(self, group_id: int, group_name: str):
        if len(group_name) > 15:
            if '/' in group_name:
                group_name = group_name.partition('/')[2]

        dangerous = DANGEROUS_NO_CARE
        if (self._port_type == PORT_TYPE_AUDIO_JACK
                and (self._port_mode == PortMode.OUTPUT
                     and self._is_alternate)
                    or (self._port_mode == PortMode.INPUT
                        and not self._is_alternate)):
            dangerous = DANGEROUS_NO

        group_menu = ConnectGroupMenu(group_name, group_id,
                                      self._port_data, self,
                                      dangerous_mode=dangerous)
        group_icon = utils.get_group_icon(group_id, self._port_mode)
        group_menu.setIcon(group_icon)
        self.group_menus.append(group_menu)
        self.addMenu(group_menu)

    def connection_asked_from_box(self, group_id: int, port_id: int,
                                  portgrp_id: int, yesno: bool):
        if yesno:
            if self._portgrp_id and portgrp_id:
                # in and out are portgroups
                utils.connect_portgroups(self._group_id, self._portgrp_id,
                                         group_id, portgrp_id)
            else:
                for self_port_id in self._port_id_list:
                    utils.connect_ports(self._group_id, self_port_id,
                                        group_id, port_id)
        else:
            if self._portgrp_id and portgrp_id:
                utils.connect_portgroups(self._group_id, self._portgrp_id,
                                         group_id, portgrp_id, disconnect=True)
            else:
                for connection in canvas.connection_list:
                    if utils.connection_matches(
                            connection, self._group_id, self._port_id_list,
                            group_id, [port_id]):
                        utils.canvas_callback(
                            ACTION_PORTS_DISCONNECT,
                            connection.connection_id, '', '')

    # TODO was initially added the fact menu was updated
    # when port was added or removed
    # for portgroup it seems to be much complicated
    # user will just have to re-open the menu

    #def port_added_to_canvas(self, group_id: int, port_id: int):
        #for port in canvas.port_list:
            #if port.group_id == group_id and port.port_id == port_id:
                #if (port.port_type != self._port_type
                        #or port.port_mode == self._port_mode):
                    #continue

                #for group_menu in self.group_menus:
                    #if group_menu.group_id() == port.group_id:
                        #if (self._portgrp_id and port.portgrp_id
                                #and group_menu.elements
                                #and (group_menu.elements[-1]['portgrp_id']
                                        #== port.portgrp_id)):
                            #pass
                        #else:
                            #group_menu.add_element(
                                #port.port_id, port.portgrp_id,
                                #port.port_name)
                        #break
                #else:
                    #for group in canvas.group_list:
                        #if group.group_id == port.group_id:
                            #self.add_group_menu(
                                #group.group_id, group.group_name)
                            ## this group menu will see itself the port
                            #break
                #break

    #def port_removed_from_canvas(self, group_id: int, port_id: int):
        #for group_menu in self.group_menus:
            #if group_menu.group_id() == group_id:
                #group_menu.remove_element(port_id, 0)
                #break


class DisconnectMenu(SubMenu):
    def __init__(self, port_data, parent):
        SubMenu.__init__(self, _translate('patchbay', "Disconnect"),
                         port_data, parent)
        self.elements = []

        self._no_action_title = _translate('patchbay', 'No connections')
        self._no_action = self.addAction(self._no_action_title)
        self._no_action.setEnabled(False)

    @pyqtSlot()
    def apply_disconnection(self):
        action = self.sender()
        if action is None:
            return

        for element in self.elements:
            if element['action'] == action:
                for connection in canvas.connection_list:
                    if utils.connection_matches(
                            connection, self._group_id, self._port_id_list,
                            element['group_id'], element['port_id_list']):
                        utils.canvas_callback(
                            ACTION_PORTS_DISCONNECT,
                            connection.connection_id, '', '')
                break

    def add_element(self, group_id: int, port_id_list: list,
                    portgrp_id: int):
        if not port_id_list:
            return

        for element in self.elements:
            if (element['group_id'] == group_id
                    and element['port_id_list'] == port_id_list):
                # element already exists
                return

        # display actions in the group_id and port_id order
        i = 0
        following_action = None

        for element in self.elements:
            if (element['group_id'] > group_id
                    or (element['group_id'] == group_id
                        and element['port_id_list'][0] > port_id_list[-1])):
                following_action = element['action']
                break
            i += 1

        action_name = ""
        if self._portgrp_id and portgrp_id:
            action_name = '‖ '
            action_name += utils.get_portgroup_full_name(group_id, portgrp_id)
        else:
            action_name = utils.get_full_port_name(group_id, port_id_list[0])

        icon = utils.get_group_icon(group_id, self._port_mode)

        action = QAction(action_name)
        action.setIcon(icon)
        action.triggered.connect(self.apply_disconnection)

        if following_action is None:
            self.addAction(action)
        else:
            self.insertAction(following_action, action)

        element = {'group_id': group_id,
                   'port_id_list': port_id_list,
                   'portgrp_id': portgrp_id,
                   'action': action}

        self.elements.insert(i, element)

        # remove "no connections" fake action
        if self._no_action is not None:
            self.removeAction(self._no_action)
            self._no_action = None

    def remove_element(self, group_id: int, port_id_list: int,
                       portgrp_id: int):
        for element in self.elements:
            if (element['group_id'] == group_id
                    and element['portgrp_id'] == portgrp_id
                    and element['port_id_list'] == port_id_list):
                self.removeAction(element['action'])
                self.elements.remove(element)
                break
        else:
            return

        if not self.elements:
            self._no_action = self.addAction(self._no_action_title)
            self._no_action.setEnabled(False)


class ClipboardMenu(SubMenu):
    def __init__(self, port_data, parent):
        SubMenu.__init__(self, _translate('patchbay', 'Clipboard'),
                         port_data, parent)

        cut_action = self.addAction(
            _translate('patchbay', 'Cut connections'))
        cut_action.setIcon(QIcon.fromTheme('edit-cut'))
        cut_action.triggered.connect(self.cut_connections)

        copy_action = self.addAction(
            _translate('patchbay', 'Copy connections'))
        copy_action.setIcon(QIcon.fromTheme('edit-copy'))
        copy_action.triggered.connect(self.copy_connections)

        has_connection = False
        for self_port_id in self._port_id_list:
            con_list = utils.get_port_connection_list(
                self._group_id, self_port_id)
            if con_list:
                has_connection = True
                break

        if not con_list:
            cut_action.setEnabled(False)
            copy_action.setEnabled(False)

        for cb_element in canvas.clipboard:
            if (cb_element.port_type == self._port_type
                    and cb_element.port_mode == self._port_mode
                    and cb_element.port_id != self._port_id):
                paste_action = self.addAction(
                    _translate('patchbay', 'Paste connections'))
                paste_action.setIcon(QIcon.fromTheme('edit-paste'))
                paste_action.triggered.connect(self.paste_connections)
                break

    def write_clipboard(self, cut: bool):
        canvas.clipboard.clear()
        canvas.clipboard_cut = cut

        for self_port_id in self._port_id_list:
            group_port_ids = []

            for connection in canvas.connection_list:
                if self._port_mode == PortMode.OUTPUT:
                    if (connection.group_out_id == self._group_id
                            and connection.port_out_id == self_port_id):
                        group_port_ids.append((connection.group_in_id,
                                            connection.port_in_id))
                elif self._port_mode == PortMode.INPUT:
                    if (connection.group_in_id == self._group_id
                            and connection.port_in_id == self_port_id):
                        group_port_ids.append((connection.group_out_id,
                                            connection.port_out_id))

            element = ClipboardElement()
            element.group_id = self._group_id
            element.port_id = self_port_id
            element.port_type = self._port_type
            element.port_mode = self._port_mode
            element.group_port_ids = group_port_ids

            canvas.clipboard.append(element)

    def cut_connections(self):
        self.write_clipboard(True)

    def copy_connections(self):
        self.write_clipboard(False)

    def paste_connections(self):
        for i in range(len(self._port_id_list)):
            for j in range(len(canvas.clipboard)):
                if i % len(canvas.clipboard) != j % len(self._port_id_list):
                    continue
                self_port_id = self._port_id_list[i]
                element = canvas.clipboard[j]

                if (element.port_type == self._port_type
                        and element.port_mode == self._port_mode):
                    for group_port_id in element.group_port_ids:
                        group_id, port_id = group_port_id

                        if canvas.clipboard_cut:
                            # remove the original connection if still exists
                            for connection in canvas.connection_list:
                                if utils.connection_matches(
                                        connection,
                                        element.group_id, [element.port_id],
                                        group_id, [port_id]):
                                    utils.canvas_callback(
                                        ACTION_PORTS_DISCONNECT,
                                        connection.connection_id, 0, '')
                                    break

                        utils.connect_ports(self._group_id, self_port_id,
                                           group_id, port_id)
                    break

        # once past, de-activate cut to prevent recut of connections
        # if they have been remade by user
        canvas.clipboard_cut = False


class MainPortContextMenu(QMenu):
    def __init__(self, group_id: int, port_id: int, portgrp_id=0):
        QMenu.__init__(self)

        #self.setStyleSheet(
            #"""QMenu{background-color:#202020; border: 1px solid;
            #border-color: red; border-radius: 4px};
            #QMenu::item{background-color:#999900};
            #QMenu::item:selected{background-color: red}""")

        if portgrp_id:
            # menu is for a portgroup
            for portgrp in canvas.portgrp_list:
                if (portgrp.group_id == group_id
                        and portgrp.portgrp_id == portgrp_id):
                    port_type = portgrp.port_type
                    port_mode = portgrp.port_mode
                    is_alternate = False
                    break
            else:
                return
        else:
            # menu is for a port
            for port in canvas.port_list:
                if port.group_id == group_id and port.port_id == port_id:
                    port_type = port.port_type
                    port_mode = port.port_mode
                    is_alternate = port.is_alternate
                    break
            else:
                return

        # border_color = canvas.theme.port_audio_jack_pen.color().name()
        # sel_bg = canvas.theme.port_audio_jack_bg.name()
        # sel_text_color = canvas.theme.port_audio_jack_text.color().name()

        # if port_type == PORT_TYPE_MIDI_JACK:
        #     border_color = canvas.theme.port_midi_jack_pen.color().name()
        #     sel_bg = canvas.theme.port_midi_jack_bg.name()
        #     sel_text_color = canvas.theme.port_midi_jack_text.color().name()

        # style_str = """QMenu{background-color:#202020; border: 1px solid;
        #     border-color: %s; border-radius: 4px}
        #     QMenu::item{background-color: #202020;color: white}
        #     QMenu::item:disabled{color: #777777}
        #     QMenu::item:selected{background-color: %s; color:%s}""" % (
        #         border_color, sel_bg, sel_text_color)

        # #self.setStyleSheet(style_str)

        PortData.__init__(self, group_id, port_id, port_type,
                          port_mode, portgrp_id, is_alternate)

        self.connection_list = list[ConnectionObject]()

        canvas.qobject.connection_added.connect(
            self.connection_added_to_canvas)
        canvas.qobject.connection_removed.connect(
            self.connection_removed_from_canvas)

        port_data = PortData(group_id, port_id, port_type,
                             port_mode, portgrp_id, is_alternate)

        dark = ''
        if utils.is_dark_theme(self):
            dark = '-dark'

        self.connect_menu = ConnectMenu(port_data, self)
        self.connect_menu.setIcon(
            QIcon(QPixmap(':scalable/breeze%s/lines-connector' % dark)))
        self.addMenu(self.connect_menu)

        self.disconnect_menu = DisconnectMenu(port_data, self)
        self.disconnect_menu.setIcon(
            QIcon(QPixmap(':scalable/breeze%s/lines-disconnector' % dark)))
        self.addMenu(self.disconnect_menu)

        disconnect_all_action = self.addAction(
            _translate('patchbay', "Disconnect All"))
        disconnect_all_action.setIcon(
            QIcon(QPixmap(':scalable/breeze%s/lines-disconnector' % dark)))
        disconnect_all_action.triggered.connect(self.disconnect_all)

        self.clipboard_menu = ClipboardMenu(port_data, self)
        self.clipboard_menu.setIcon(QIcon.fromTheme('edit-paste'))
        self.addMenu(self.clipboard_menu)

        self.addSeparator()

        for connection in canvas.connection_list:
            if utils.connection_concerns(
                    connection, self._group_id, self._port_id_list):
                self.add_connection(connection)

    def get_port_attributes(self)->tuple:
        return (self._group_id, self._port_id,
                self._port_type, self._port_mode)

    def disconnect_all(self):
        for connection in self.connection_list:
            utils.canvas_callback(ACTION_PORTS_DISCONNECT,
                           connection.connection_id, 0, '')

    def add_connection(self, connection):
        self.connection_list.append(connection)

        for port in canvas.port_list:
            if ((self._port_mode == PortMode.OUTPUT
                        and port.group_id == connection.group_in_id
                        and port.port_id == connection.port_in_id)
                    or (self._port_mode == PortMode.INPUT
                        and port.group_id == connection.group_out_id
                        and port.port_id == connection.port_out_id)):
                group_id = port.group_id
                port_id = port.port_id
                portgrp_id = port.portgrp_id
                port_id_list = [port_id]

                if self._portgrp_id and portgrp_id:
                    port_id = -1
                    port_id_list = utils.get_portgroup_port_list(
                        group_id, portgrp_id)

                con_state = utils.get_portgroup_connection_state(
                    self._group_id, self._port_id_list,
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
                if not utils.connection_concerns(
                        connection, self._group_id, self._port_id_list):
                    return

                self.add_connection(connection)

    def connection_removed_from_canvas(self, connection_id: int):
        for connection in self.connection_list:
            if connection.connection_id == connection_id:
                for port in canvas.port_list:
                    if ((self._port_mode == PortMode.OUTPUT
                            and port.group_id == connection.group_in_id
                            and port.port_id == connection.port_in_id)
                        or (self._port_mode == PortMode.INPUT
                            and port.group_id == connection.group_out_id
                            and port.port_id == connection.port_out_id)):
                        group_id = port.group_id
                        port_id = port.port_id
                        portgrp_id = port.portgrp_id

                        if self._portgrp_id and portgrp_id:
                            port_id = -1
                            port_id_list = utils.get_portgroup_port_list(
                                group_id, portgrp_id)
                        else:
                            port_id_list = [port_id]

                        con_state = utils.get_portgroup_connection_state(
                            self._group_id, self._port_id_list,
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
