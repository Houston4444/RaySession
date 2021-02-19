
from PyQt5.QtWidgets import QWidgetAction, QMenu, QCheckBox

from . import (
    canvas,
    ACTION_PORTS_CONNECT,
    ACTION_PORTS_DISCONNECT,
    PORT_TYPE_NULL,
    PORT_MODE_NULL,
    PORT_MODE_OUTPUT,
    PORT_MODE_INPUT)

from .utils import(
    CanvasCallback,
    CanvasConnectionMatches,
    CanvasConnectionConcerns,
    CanvasGetGroupIcon)


class PortCheckBox(QCheckBox):
    def __init__(self, port_id: int, port_name:str, parent):
        QCheckBox.__init__(self, port_name, parent)
        self.setMinimumHeight(23)
        #self.setStyleSheet("QCheckBox{background-color:#CCCCCC; color:#333333; border-color:#333333}")
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
    def __init__(self, group_id, port_id, parent):
        QMenu.__init__(self, "Connect", parent)
        
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
        
        canvas.qobject.port_added.connect(self.port_added_to_canvas)
        canvas.qobject.port_removed.connect(self.port_removed_from_canvas)
        canvas.qobject.connection_added.connect(
            self.connection_added_to_canvas)
        canvas.qobject.connection_removed.connect(
            self.connection_removed_from_canvas)
        
        all_groups = []
        
        self.group_menus = []
        self.connection_list = []
        
        for group in canvas.group_list:
            for port in canvas.port_list:
                if (port.group_id == group.group_id
                        and port.port_type == self._port_type
                        and port.port_mode != self._port_mode):
                    self.add_group_menu(group.group_id, group.group_name)
                    break
        
        for connection in canvas.connection_list:
            if CanvasConnectionConcerns(
                    connection, self._group_id, [self._port_id]):
                self.connection_list.append(connection)
                
                if self._port_mode == PORT_MODE_OUTPUT:
                    for group_menu in self.group_menus:
                        if group_menu.group_id() == connection.group_in_id:
                            group_menu.check_port_connection(
                                connection.port_in_id, True)
                            break
                else:
                    for group_menu in self.group_menus:
                        if group_menu.group_id() == connection.group_out_id:
                            group_menu.check_port_connection(
                                connection.port_out_id, True)
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
                        ACTION_PORTS_DISCONNECT, connection.connection_id, '' , '')
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
        
    def connection_added_to_canvas(self, connection_id:int):
        for connection in canvas.connection_list:
            if connection.connection_id == connection_id:
                if not CanvasConnectionConcerns(
                        connection, self._group_id, [self._port_id]):
                    return
                
                self.connection_list.append(connection)
                
                if self._port_mode == PORT_MODE_OUTPUT:
                    for group_menu in self.group_menus:
                        if group_menu.group_id() == connection.group_in_id:
                            group_menu.check_port_connection(
                                connection.port_in_id, True)
                            break
                else:
                    for group_menu in self.group_menus:
                        if group_menu.group_id() == connection.group_out_id:
                            group_menu.check_port_connection(
                                connection.port_out_id, True)
                            break

    def connection_removed_from_canvas(self, connection_id:int):
        for connection in self.connection_list:
            if connection.connection_id == connection_id:
                if self._port_mode == PORT_MODE_OUTPUT:
                    for group_menu in self.group_menus:
                        if group_menu.group_id() == connection.group_in_id:
                            group_menu.check_port_connection(
                                connection.port_in_id, False)
                            break
                else:
                    for group_menu in self.group_menus:
                        if group_menu.group_id() == connection.group_out_id:
                            group_menu.check_port_connection(
                                connection.port_out_id, False)
                            break

                self.connection_list.remove(connection)
                break
