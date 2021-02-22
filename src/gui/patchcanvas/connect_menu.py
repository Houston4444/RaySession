

from PyQt5.QtCore import pyqtSlot, QCoreApplication
from PyQt5.QtWidgets import QWidgetAction, QMenu, QCheckBox, QAction
from PyQt5.QtGui import QIcon

from . import (
    canvas,
    clipboard_element_dict_t,
    ACTION_PORTS_CONNECT,
    ACTION_PORTS_DISCONNECT,
    PORT_TYPE_NULL,
    PORT_MODE_NULL,
    PORT_MODE_OUTPUT)

from .utils import(
    CanvasCallback,
    CanvasConnectionMatches,
    CanvasConnectionConcerns,
    CanvasGetGroupIcon,
    CanvasGetFullPortName,
    CanvasGetPortConnectionList)


_translate = QCoreApplication.translate


class PortCheckBox(QCheckBox):
    def __init__(self, port_id: int, port_name: str, parent):
        QCheckBox.__init__(self, port_name, parent)
        self.setMinimumHeight(23)
        self._parent = parent
        self._port_id = port_id
    
    def nextCheckState(self):
        self._parent.connection_asked_from_box(
            self._port_id, not self.isChecked())


class ConnectGroupMenu(QMenu):
    def __init__(self, group_id: int, group_name: str,
                 port_type: int, port_mode: int, parent):
        QMenu.__init__(self, group_name, parent)
        self._parent = parent
        
        # concerns the group submenu
        self._group_id = group_id
        
        # concerns the port creating the menu
        self._port_type = port_type
        self._port_mode = port_mode
        
        self.elements = []
        
        self._last_portgrp_id = 0
        
        for port in canvas.port_list:
            if (port.group_id == self._group_id
                    and port.port_type == self._port_type
                    and port.port_mode != self._port_mode):
                self.add_port(port.port_id, port.portgrp_id, port.port_name)

    def group_id(self)->int:
        return self._group_id

    def add_port(self, port_id: int, portgrp_id: int, port_name: str):
        check_box = PortCheckBox(port_id, port_name, self)
        action = QWidgetAction(self._parent)
        action.setDefaultWidget(check_box)
        
        if portgrp_id != self._last_portgrp_id:
            self.addSeparator()
        self._last_portgrp_id = portgrp_id
        
        self.addAction(action)
        
        self.elements.append(
            {'port_id': port_id, 'action': action, 'check_box': check_box})
    
    def remove_port(self, port_id: int):
        for element in self.elements:
            if element['port_id'] == port_id:
                self.removeAction(element['action'])
                self.elements.remove(element)
                break
    
    def check_port_connection(self, port_id: int, yesno: bool):
        for element in self.elements:
            if element['port_id'] == port_id:
                check_box = element['check_box']
                check_box.setChecked(yesno)
                break
    
    def connection_asked_from_box(self, port_id: int, yesno: bool):
        self._parent.connection_asked_from_box(self._group_id, port_id, yesno)
    

class ConnectMenu(QMenu):
    def __init__(self, group_id: int, port_id: int,
                 port_type: int, port_mode: int, parent):
        QMenu.__init__(self, _translate('patchbay', 'Connect'), parent)
        
        self._group_id = group_id
        self._port_id = port_id
        self._port_type = port_type
        self._port_mode = port_mode
        
        canvas.qobject.port_added.connect(self.port_added_to_canvas)
        canvas.qobject.port_removed.connect(self.port_removed_from_canvas)
        
        self.group_menus = []
        self.connection_list = []
        
        # add the needed groups (not the ports)
        for group in canvas.group_list:
            for port in canvas.port_list:
                if (port.group_id == group.group_id
                        and port.port_type == self._port_type
                        and port.port_mode != self._port_mode):
                    self.add_group_menu(group.group_id, group.group_name)
                    break
    
    def add_group_menu(self, group_id: int, group_name: str):
        if len(group_name) > 15:
            if '/' in group_name:
                group_name = group_name.partition('/')[2]
        
        group_menu = ConnectGroupMenu(group_id, group_name, self._port_type,
                                      self._port_mode, self)
        group_icon = CanvasGetGroupIcon(group_id, self._port_mode)
        group_menu.setIcon(group_icon)
        self.group_menus.append(group_menu)
        self.addMenu(group_menu)
    
    def connection_asked_from_box(self, group_id: int, port_id: int, yesno: bool):
        if yesno:
            if self._port_mode == PORT_MODE_OUTPUT:
                CanvasCallback(
                    ACTION_PORTS_CONNECT, '', '',
                    "%i:%i:%i:%i" % (self._group_id, self._port_id,
                                     group_id, port_id))
            else:
                CanvasCallback(
                    ACTION_PORTS_CONNECT, '', '',
                    "%i:%i:%i:%i" % (group_id, port_id,
                                     self._group_id, self._port_id))
        else:
            for connection in canvas.connection_list:
                if CanvasConnectionMatches(
                        connection, self._group_id, [self._port_id],
                        group_id, [port_id]):
                    CanvasCallback(
                        ACTION_PORTS_DISCONNECT, connection.connection_id, '', '')
                    break
    
    def port_added_to_canvas(self, group_id: int, port_id: int):
        for port in canvas.port_list:
            if port.group_id == group_id and port.port_id == port_id:
                if (port.port_type == self._port_type
                        and port.port_mode != self._port_mode):
                    for group_menu in self.group_menus:
                        if group_menu.group_id() == port.group_id:
                            group_menu.add_port(
                                port.port_id, port.portgrp_id, port.port_name)
                            break
                    else:
                        for group in canvas.group_list:
                            if group.group_id == port.group_id:
                                self.add_group_menu(
                                    group.group_id, group.group_name)
                                # this group menu will see itself the port
                                break
                break
    
    def port_removed_from_canvas(self, group_id: int, port_id: int):
        for group_menu in self.group_menus:
            if group_menu.group_id() == group_id:
                group_menu.remove_port(port_id)
                break
        
    
class DisconnectMenu(QMenu):
    def __init__(self, group_id: int, port_id: int,
                 port_type: int, port_mode: int, parent):
        QMenu.__init__(self, _translate('patchbay', "Disconnect"), parent)
        self.elements = []
        self._group_id = group_id
        self._port_id = port_id
        self._port_type = port_type
        self._port_mode = port_mode
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
                CanvasCallback(ACTION_PORTS_DISCONNECT,
                               element['connection_id'], 0, '')
                break
    
    def add_port_entry(self, group_id: int, port_id: int, connection_id: int):
        # display actions in the group_id and port_id order
        i = 0
        following_action = None
        
        for element in self.elements:
            if (element['group_id'] > group_id
                    or (element['group_id'] == group_id
                        and element['port_id'] > port_id)):
                following_action = element['action']
                break
            i += 1
        
        full_port_name = CanvasGetFullPortName(group_id, port_id)

        icon = CanvasGetGroupIcon(group_id, self._port_mode)
        
        action = QAction(full_port_name)
        action.setIcon(icon)
        action.triggered.connect(self.apply_disconnection)
        
        if following_action is None:
            self.addAction(action)
        else:
            self.insertAction(following_action, action)
        
        element = {'group_id': group_id,
                   'port_id': port_id,
                   'connection_id': connection_id,
                   'action': action}
        
        self.elements.insert(i, element)
        
        # remove "no connections" fake action
        if self._no_action is not None:
            self.removeAction(self._no_action)
            self._no_action = None
    
    def remove_port_entry(self, group_id: int, port_id: int):
        for element in self.elements:
            if (element['group_id'] == group_id
                    and element['port_id'] == port_id):
                self.removeAction(element['action'])
                self.elements.remove(element)
                break
        
        if not self.elements:
            self._no_action = self.addAction(self._no_action_title)
            self._no_action.setEnabled(False)


class ClipboardMenu(QMenu):
    def __init__(self, group_id: int, port_id: int,
                 port_type: int, port_mode: int, parent):
        QMenu.__init__(self, _translate('patchbay', 'Clipboard'), parent)
        self._group_id = group_id
        self._port_id = port_id
        self._port_type = port_type
        self._port_mode = port_mode
        
        
        cut_action = self.addAction(
            _translate('patchbay', 'Cut connections'))
        cut_action.setIcon(QIcon.fromTheme('edit-cut'))
        cut_action.triggered.connect(self.cut_connections)
        
        copy_action = self.addAction(
            _translate('patchbay', 'Copy connections'))
        copy_action.setIcon(QIcon.fromTheme('edit-copy'))
        copy_action.triggered.connect(self.copy_connections)
        
        con_list = CanvasGetPortConnectionList(self._group_id, self._port_id)
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
        
        group_port_ids = []
        
        for connection in canvas.connection_list:
            if self._port_mode == PORT_MODE_OUTPUT:
                if (connection.group_out_id == self._group_id
                        and connection.port_out_id == self._port_id):
                    group_port_ids.append((connection.group_in_id,
                                           connection.port_in_id))
            else:
                if (connection.group_in_id == self._group_id
                        and connection.port_in_id == self._port_id):
                    group_port_ids.append((connection.group_out_id,
                                           connection.port_out_id))
        
        element = clipboard_element_dict_t()
        element.group_id = self._group_id
        element.port_id = self._port_id
        element.port_type = self._port_type
        element.port_mode = self._port_mode
        element.group_port_ids = group_port_ids
        
        canvas.clipboard.append(element)
    
    def cut_connections(self):
        self.write_clipboard(True)
    
    def copy_connections(self):
        self.write_clipboard(False)
    
    def paste_connections(self):
        for element in canvas.clipboard:
            if (element.port_type == self._port_type
                    and element.port_mode == self._port_mode):
                for group_port_id in element.group_port_ids:
                    group_id, port_id = group_port_id
                    
                    if canvas.clipboard_cut:
                        # remove the original connection if still exists
                        for connection in canvas.connection_list:
                            print(connection.group_out_id, connection.port_out_id,
                                  connection.group_in_id, connection.port_in_id)
                            print(self._group_id, self._port_id, group_id, port_id)
                            if CanvasConnectionMatches(
                                    connection,
                                    element.group_id, [element.port_id],
                                    group_id, [port_id]):
                                CanvasCallback(
                                    ACTION_PORTS_DISCONNECT,
                                    connection.connection_id, 0, '')
                                break
                    
                    if self._port_mode == PORT_MODE_OUTPUT:
                        CanvasCallback(
                            ACTION_PORTS_CONNECT, 0, 0,
                            "%i:%i:%i:%i" % (self._group_id, self._port_id,
                                             group_id, port_id))
                    else:
                        CanvasCallback(
                            ACTION_PORTS_CONNECT, 0, 0,
                            "%i:%i:%i:%i" % (group_id, port_id,
                                             self._group_id, self._port_id))
                break
    

class MainContextMenu(QMenu):
    def __init__(self, group_id: int, port_id: int):
        QMenu.__init__(self)
        
        self._group_id = group_id
        self._port_id = port_id
        self._port_type = PORT_TYPE_NULL
        self._port_mode = PORT_MODE_NULL
        
        for port in canvas.port_list:
            if port.group_id == group_id and port.port_id == port_id:
                self._port_type = port.port_type
                self._port_mode = port.port_mode
                break
        else:
            return
        
        self.connection_list = []
        
        canvas.qobject.connection_added.connect(
            self.connection_added_to_canvas)
        canvas.qobject.connection_removed.connect(
            self.connection_removed_from_canvas)
        
        self.connect_menu = ConnectMenu(
            group_id, port_id, self._port_type, self._port_mode, self)
        self.connect_menu.setIcon(QIcon.fromTheme('gtk-connect'))
        self.addMenu(self.connect_menu)
        
        self.disconnect_menu = DisconnectMenu(
            group_id, port_id, self._port_type, self._port_mode, self)
        self.disconnect_menu.setIcon(QIcon.fromTheme('gtk-disconnect'))
        self.addMenu(self.disconnect_menu)
        
        disconnect_all_action = self.addAction("Disconnect All")
        disconnect_all_action.setIcon(QIcon.fromTheme('gtk-disconnect'))
        disconnect_all_action.triggered.connect(self.disconnect_all)
        
        self.clipboard_menu = ClipboardMenu(
            group_id, port_id, self._port_type, self._port_mode, self)
        self.addMenu(self.clipboard_menu)
        
        self.addSeparator()
        
        for connection in canvas.connection_list:
            if CanvasConnectionConcerns(
                    connection, self._group_id, [self._port_id]):
                self.add_connection(connection)
    
    def disconnect_all(self):
        for connection in self.connection_list:
            CanvasCallback(ACTION_PORTS_DISCONNECT,
                           connection.connection_id, 0, '')
    
    def add_connection(self, connection):
        self.connection_list.append(connection)
                
        if self._port_mode == PORT_MODE_OUTPUT:
            for group_menu in self.connect_menu.group_menus:
                if group_menu.group_id() == connection.group_in_id:
                    group_menu.check_port_connection(
                        connection.port_in_id, True)
                    break
            
            self.disconnect_menu.add_port_entry(
                connection.group_in_id, connection.port_in_id,
                connection.connection_id)
        else:
            for group_menu in self.connect_menu.group_menus:
                if group_menu.group_id() == connection.group_out_id:
                    group_menu.check_port_connection(
                        connection.port_out_id, True)
                    break
            
            self.disconnect_menu.add_port_entry(
                connection.group_out_id, connection.port_out_id,
                connection.connection_id)
    
    def connection_added_to_canvas(self, connection_id: int):
        for connection in canvas.connection_list:
            if connection.connection_id == connection_id:
                if not CanvasConnectionConcerns(
                        connection, self._group_id, [self._port_id]):
                    return
                
                self.add_connection(connection)

    def connection_removed_from_canvas(self, connection_id: int):
        for connection in self.connection_list:
            if connection.connection_id == connection_id:
                if self._port_mode == PORT_MODE_OUTPUT:
                    for group_menu in self.connect_menu.group_menus:
                        if group_menu.group_id() == connection.group_in_id:
                            group_menu.check_port_connection(
                                connection.port_in_id, False)
                            break
                        
                    self.disconnect_menu.remove_port_entry(
                        connection.group_in_id, connection.port_in_id)
                else:
                    for group_menu in self.connect_menu.group_menus:
                        if group_menu.group_id() == connection.group_out_id:
                            group_menu.check_port_connection(
                                connection.port_out_id, False)
                            break
                    
                    self.disconnect_menu.remove_port_entry(
                        connection.group_out_id, connection.port_out_id)

                self.connection_list.remove(connection)
                break
