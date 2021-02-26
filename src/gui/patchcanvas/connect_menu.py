

from PyQt5.QtCore import pyqtSlot, QCoreApplication, Qt
from PyQt5.QtWidgets import QWidgetAction, QMenu, QCheckBox, QAction
from PyQt5.QtGui import QIcon

from . import (
    canvas,
    clipboard_element_dict_t,
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
    CanvasGetGroupIcon,
    CanvasGetFullPortName,
    CanvasGetPortConnectionList,
    CanvasConnectPorts,
    CanvasGetPortGroupFullName,
    CanvasGetPortGroupPortList,
    CanvasConnectPortGroups,
    CanvasPortGroupConnectionState)


_translate = QCoreApplication.translate


class PortCheckBox(QCheckBox):
    def __init__(self, port_id: int, portgrp_id: int, port_name: str, parent):
        QCheckBox.__init__(self, port_name, parent)
        self.setTristate(True)
        self.setMinimumHeight(23)
        self._parent = parent
        self._port_id = port_id
        self._portgrp_id = portgrp_id
    
    def nextCheckState(self):
        self._parent.connection_asked_from_box(
            self._port_id, self._portgrp_id, not self.isChecked())


class SubMenu(QMenu):
    def __init__(self, name: str, port_data, parent):
        QMenu.__init__(self, name, parent)
        self._port_data = port_data
        self._group_id = port_data._group_id
        self._port_id = port_data._port_id
        self._port_type = port_data._port_type
        self._port_mode = port_data._port_mode
        self._portgrp_id = port_data._portgrp_id
        self._port_id_list = port_data._port_id_list
        

class PortData:
    def __init__(self, group_id: int, port_id: int, port_type: int,
                 port_mode: int, portgrp_id: int):
        self._group_id = group_id
        self._port_id = port_id
        self._port_type = port_type
        self._port_mode = port_mode
        self._portgrp_id = portgrp_id
        self._port_id_list = [port_id]
        
        if portgrp_id:
            self._port_id_list = CanvasGetPortGroupPortList(group_id,
                                                            portgrp_id)
            

class ConnectGroupMenu(SubMenu):
    def __init__(self, group_name: str, group_id: str, port_data, parent):
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
                                portgrp_full_name = CanvasGetPortGroupFullName(
                                    portgrp.group_id, portgrp.portgrp_id)
                                portgrp_name = '‖ ' \
                                    + portgrp_full_name.partition(':')[2]
                                
                                # all portgroups items will have -1 as port_id
                                self.add_element(-1, port.portgrp_id,
                                                 portgrp_name)
                                break
                else:
                    self.add_element(port.port_id, port.portgrp_id,
                                     port.port_name)

    def group_id(self)->int:
        return self._menu_group_id

    def add_element(self, port_id: int, portgrp_id: int, port_name: str):
        check_box = PortCheckBox(port_id, portgrp_id, port_name, self)
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
        print('checkcck eleement', port_id, portgrp_id, check_state)
        for element in self.elements:
            print('ellle', element['port_id'], element['portgrp_id'])
            if (element['port_id'] == port_id
                    and element['portgrp_id'] == portgrp_id):
                check_box = element['check_box']
                check_box.setCheckState(check_state)
                break
    
    def connection_asked_from_box(self, port_id: int, portgrp_id: int,
                                  yesno: bool):
        self._parent.connection_asked_from_box(self._group_id, port_id,
                                               portgrp_id, yesno)
    

class ConnectMenu(SubMenu):
    def __init__(self, port_data, parent):
        SubMenu.__init__(self, _translate('patchbay', 'Connect'),
                         port_data, parent)
        
        #canvas.qobject.port_added.connect(self.port_added_to_canvas)
        #canvas.qobject.port_removed.connect(self.port_removed_from_canvas)
        
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
        
        group_menu = ConnectGroupMenu(group_name, group_id,
                                      self._port_data, self)
        group_icon = CanvasGetGroupIcon(group_id, self._port_mode)
        group_menu.setIcon(group_icon)
        self.group_menus.append(group_menu)
        self.addMenu(group_menu)
    
    def connection_asked_from_box(self, group_id: int, port_id: int,
                                  portgrp_id: int, yesno: bool):
        if yesno:
            if self._portgrp_id and portgrp_id:
                # in and out are portgroups
                CanvasConnectPortGroups(self._group_id, self._portgrp_id,
                                        group_id, portgrp_id)
            else:
                for self_port_id in self._port_id_list:
                    CanvasConnectPorts(self._group_id, self_port_id,
                                        group_id, port_id)
        else:
            if self._portgrp_id and portgrp_id:
                CanvasConnectPortGroups(self._group_id, self._portgrp_id,
                                        group_id, portgrp_id, disconnect=True)
            else:
                for connection in canvas.connection_list:
                    if CanvasConnectionMatches(
                            connection, self._group_id, self._port_id_list,
                            group_id, [port_id]):
                        CanvasCallback(
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
                    if CanvasConnectionMatches(
                            connection, self._group_id, self._port_id_list,
                            element['group_id'], element['port_id_list']):
                        CanvasCallback(
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
            action_name += CanvasGetPortGroupFullName(group_id, portgrp_id)
        else:
            action_name = CanvasGetFullPortName(group_id, port_id_list[0])
            
        icon = CanvasGetGroupIcon(group_id, self._port_mode)
        
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
            con_list = CanvasGetPortConnectionList(self._group_id,
                                                   self_port_id)
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
                if self._port_mode == PORT_MODE_OUTPUT:
                    if (connection.group_out_id == self._group_id
                            and connection.port_out_id == self_port_id):
                        group_port_ids.append((connection.group_in_id,
                                            connection.port_in_id))
                elif self._port_mode == PORT_MODE_INPUT:
                    if (connection.group_in_id == self._group_id
                            and connection.port_in_id == self_port_id):
                        group_port_ids.append((connection.group_out_id,
                                            connection.port_out_id))
        
            element = clipboard_element_dict_t()
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
                                if CanvasConnectionMatches(
                                        connection,
                                        element.group_id, [element.port_id],
                                        group_id, [port_id]):
                                    CanvasCallback(
                                        ACTION_PORTS_DISCONNECT,
                                        connection.connection_id, 0, '')
                                    break
                        
                        CanvasConnectPorts(self._group_id, self_port_id,
                                           group_id, port_id)
                    break
        
        # once past, de-activate cut to prevent recut of connections
        # if they have been remade by user
        canvas.clipboard_cut = False
    

class MainPortContextMenu(QMenu):
    def __init__(self, group_id: int, port_id: int, portgrp_id=0):
        QMenu.__init__(self)
        
        for port in canvas.port_list:
            if port.group_id == group_id and port.port_id == port_id:
                port_type = port.port_type
                port_mode = port.port_mode
                break
        else:
            return
        
        PortData.__init__(self, group_id, port_id,
                          port_type, port_mode, portgrp_id)
        
        self.connection_list = []
        
        canvas.qobject.connection_added.connect(
            self.connection_added_to_canvas)
        canvas.qobject.connection_removed.connect(
            self.connection_removed_from_canvas)
        
        port_data = PortData(group_id, port_id, port_type,
                             port_mode, portgrp_id)
        
        self.connect_menu = ConnectMenu(port_data, self)
        self.connect_menu.setIcon(QIcon.fromTheme('gtk-connect'))
        self.addMenu(self.connect_menu)
        
        self.disconnect_menu = DisconnectMenu(port_data, self)
        self.disconnect_menu.setIcon(QIcon.fromTheme('gtk-disconnect'))
        self.addMenu(self.disconnect_menu)
        
        disconnect_all_action = self.addAction(
            _translate('patchbay', "Disconnect All"))
        disconnect_all_action.setIcon(QIcon.fromTheme('gtk-disconnect'))
        disconnect_all_action.triggered.connect(self.disconnect_all)
        
        self.clipboard_menu = ClipboardMenu(port_data, self)
        self.addMenu(self.clipboard_menu)
        
        self.addSeparator()
        
        for connection in canvas.connection_list:
            if CanvasConnectionConcerns(
                    connection, self._group_id, self._port_id_list):
                self.add_connection(connection)
    
    def get_port_attributes(self)->tuple:
        return (self._group_id, self._port_id,
                self._port_type, self._port_mode)
    
    def disconnect_all(self):
        for connection in self.connection_list:
            CanvasCallback(ACTION_PORTS_DISCONNECT,
                           connection.connection_id, 0, '')
    
    def add_connection(self, connection):
        self.connection_list.append(connection)
        
        for port in canvas.port_list:
            if ((self._port_mode == PORT_MODE_OUTPUT
                        and port.group_id == connection.group_in_id
                        and port.port_id == connection.port_in_id)
                    or (self._port_mode == PORT_MODE_INPUT
                        and port.group_id == connection.group_out_id
                        and port.port_id == connection.port_out_id)):
                group_id = port.group_id
                port_id = port.port_id
                portgrp_id = port.portgrp_id
                port_id_list = [port_id]
                
                if self._portgrp_id and portgrp_id:
                    port_id = -1
                    port_id_list = CanvasGetPortGroupPortList(
                        group_id, portgrp_id)
                
                con_state = CanvasPortGroupConnectionState(
                    self._group_id, self._port_id_list,
                    group_id, port_id_list)

                for group_menu in self.connect_menu.group_menus:
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
                if not CanvasConnectionConcerns(
                        connection, self._group_id, self._port_id_list):
                    return
                
                self.add_connection(connection)

    def connection_removed_from_canvas(self, connection_id: int):
        for connection in self.connection_list:
            if connection.connection_id == connection_id:
                for port in canvas.port_list:
                    if ((self._port_mode == PORT_MODE_OUTPUT
                            and port.group_id == connection.group_in_id
                            and port.port_id == connection.port_in_id)
                        or (self._port_mode == PORT_MODE_INPUT
                            and port.group_id == connection.group_out_id
                            and port.port_id == connection.port_out_id)):
                        group_id = port.group_id
                        port_id = port.port_id
                        portgrp_id = port.portgrp_id
                        
                        if self._portgrp_id and portgrp_id:
                            port_id = -1
                            port_id_list = CanvasGetPortGroupPortList(
                                group_id, portgrp_id)
                        else:
                            port_id_list = [port_id]
                        
                        con_state = CanvasPortGroupConnectionState(
                            self._group_id, self._port_id_list,
                            group_id, port_id_list)
                        
                        for group_menu in self.connect_menu.group_menus:
                            if group_menu.group_id() == group_id:
                                group_menu.check_element(
                                    port_id, portgrp_id, con_state)
                                break
                            
                        self.disconnect_menu.remove_element(
                            group_id, port_id_list, portgrp_id)
                        break

                self.connection_list.remove(connection)
                break
