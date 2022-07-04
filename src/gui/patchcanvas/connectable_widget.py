
import time
from typing import TYPE_CHECKING
from PyQt5.QtCore import Qt, QRectF, QPointF
from PyQt5.QtGui import QCursor
from PyQt5.QtWidgets import QGraphicsItem

from .init_values import (CallbackAct, ConnectableObject, ConnectionObject, PortMode, PortSubType,
                          PortType, canvas, options)
from .line_move_widget import LineMoveWidget

if TYPE_CHECKING:
    from .box_widget import BoxWidget
    

class ConnectableWidget(QGraphicsItem):
    """ This class is the mother class for port and portgroups
        widgets because the way to manage the connection process
        is the same for both. """
    
    if TYPE_CHECKING:
        _hover_item: 'ConnectableWidget'

    def __init__(self, connectable: ConnectableObject, parent: 'BoxWidget'):
        QGraphicsItem.__init__(self, parent)
        self.setFlags(QGraphicsItem.ItemIsSelectable)
        self.setCacheMode(QGraphicsItem.DeviceCoordinateCache)
        
        if options.auto_select_items:
            self.setAcceptHoverEvents(True)

        self._po = connectable
        self._group_id = connectable.group_id
        self._port_ids = connectable.get_port_ids()
        self._port_mode = connectable.port_mode
        self._port_type = connectable.port_type
        self._port_subtype = connectable.port_subtype
        
        # needed for line mov
        self._line_mov_list = list[LineMoveWidget]()
        self._dotcon_list = list[ConnectionObject]()
        self._last_rclick_item = None
        self._r_click_time = 0
        self._hover_item = None
        self._mouse_down = False
        self._cursor_moving = False
        self._has_connections = False
        
        self._last_mouse_point = QPointF(0.0, 0.0)

        # needed for selecting portgroup and ports together        
        self.mouse_releasing = False
        self.changing_select_state = False
        
    def get_group_id(self) -> int:
        return self._group_id

    def get_port_ids(self) -> tuple[int]:
        return self._port_ids

    def get_port_mode(self) -> PortMode:
        return self._port_mode

    def get_port_type(self) -> PortType:
        return self._port_type

    def get_port_subtype(self) -> PortSubType:
        return self._port_subtype

    def get_connection_distance(self) -> float:
        # overclassed
        return 0.0

    def trigger_disconnect(self):
        " used to disconnect ports/portgroups from Ctrl+Middle Click "
        conn_ids_to_remove = list[int]()
        
        for connection in canvas.list_connections(self._po):
            conn_ids_to_remove.append(connection.connection_id)
                
        for conn_id in conn_ids_to_remove:
            canvas.callback(CallbackAct.PORTS_DISCONNECT, conn_id)

    def is_connectable_to(self, other: 'ConnectableWidget',
                          accept_same_port_mode=False)->bool:
        if self._port_type != other.get_port_type():
            return False

        if not accept_same_port_mode:
            if self._port_mode == other.get_port_mode():
                return False

        if self._port_type == PortType.AUDIO_JACK:
            if other.get_port_mode() == self._port_mode:
                return bool(self._port_subtype == other.get_port_subtype())
            # absolutely forbidden to connect an output CV port
            # to an input audio port.
            # It could destroy material.
            if self._port_mode is PortMode.OUTPUT:
                if self._port_subtype is PortSubType.CV:
                    return other.get_port_subtype() is PortSubType.CV
                return True

            if self._port_mode is PortMode.INPUT:
                if self._port_subtype is PortSubType.CV:
                    return True
                return not (other._port_subtype is PortSubType.CV)

        return True
    
    def reset_line_mov_positions(self):
        self_ports_len = len(self._port_ids)
        
        for i in range(len(self._line_mov_list)):
            line_mov = self._line_mov_list[i]
            if i < self_ports_len:
                line_mov.set_destination_portgrp_pos(i, self_ports_len)
            else:
                item = line_mov
                canvas.scene.removeItem(item)
                del item

        while len(self._line_mov_list) < self_ports_len:
            line_mov = LineMoveWidget(
                self._port_mode, self._port_type, len(self._line_mov_list),
                self_ports_len, self)

            self._line_mov_list.append(line_mov)

        self._line_mov_list = self._line_mov_list[:self_ports_len]
        
    def reset_dot_lines(self):
        for connection in self._dotcon_list:
            if connection.widget.ready_to_disc:
                connection.widget.ready_to_disc = False
                connection.widget.update_line_gradient()

        for line_mov in self._line_mov_list:
            line_mov.ready_to_disc = False
        self._dotcon_list.clear()
        
    def _connect_to_hover(self):
        if self._hover_item is None:
            return

        hover_port_ids = self._hover_item.get_port_ids()
        if not hover_port_ids:
            return

        hover_group_id = self._hover_item.get_group_id()
        con_list = list[ConnectionObject]()
        ports_connected_list = list[list[int]]()

        maxportgrp = max(len(self._port_ids), len(hover_port_ids))

        if self._hover_item.get_port_mode() is self._port_mode:
            # Copy connections from this widget to the other one (hover)
            
            for i in range(len(self._port_ids)):
                for connection in canvas.list_connections(self._po):
                    if connection.concerns(self._group_id, [self._port_ids[i]]):
                        canvas.callback(CallbackAct.PORTS_DISCONNECT,
                                        connection.connection_id)

                        for j in range(len(hover_port_ids)):
                            if len(hover_port_ids) >= len(self._port_ids):
                                if j % len(self._port_ids) != i:
                                    continue
                            else:
                                if i % len(hover_port_ids) != j:
                                    continue

                            if self._port_mode is PortMode.OUTPUT:
                                canvas.callback(
                                    CallbackAct.PORTS_CONNECT,                                        
                                    hover_group_id, hover_port_ids[j],
                                    connection.group_in_id, connection.port_in_id)
                            else:
                                canvas.callback(
                                    CallbackAct.PORTS_CONNECT,
                                    connection.group_out_id, connection.port_out_id,
                                    hover_group_id, hover_port_ids[j])
            return

        for i in range(len(self._port_ids)):
            port_id = self._port_ids[i]
            for j in range(len(hover_port_ids)):
                hover_port_id = hover_port_ids[j]

                for connection in canvas.list_connections(self._po):
                    if connection.matches(self._group_id, [port_id],
                                          hover_group_id, [hover_port_id]):
                        if i % len(hover_port_ids) == j % len(self._port_ids):
                            con_list.append(connection)
                            ports_connected_list.append(
                                [port_id, hover_port_id])
                        else:
                            canvas.callback(CallbackAct.PORTS_DISCONNECT,
                                            connection.connection_id)

        if len(con_list) == maxportgrp:
            for connection in con_list:
                canvas.callback(CallbackAct.PORTS_DISCONNECT,
                                connection.connection_id)
        else:
            for i in range(len(self._port_ids)):
                port_id = self._port_ids[i]
                
                for j in range(len(hover_port_ids)):
                    hover_port_id = hover_port_ids[j]

                    if i % len(hover_port_ids) == j % len(self._port_ids):
                        if not [port_id, hover_port_id] in ports_connected_list:
                            if self._port_mode is PortMode.OUTPUT:
                                canvas.callback(
                                    CallbackAct.PORTS_CONNECT,
                                    self._group_id, port_id,
                                    hover_group_id, hover_port_id)                                    
                            else:
                                canvas.callback(
                                    CallbackAct.PORTS_CONNECT,
                                    hover_group_id, hover_port_id,
                                    self._group_id, port_id)
    
    def parentItem(self) -> 'BoxWidget':
        # only here to say IDE parent is a CanvasBox
        return super().parentItem()
    
    def hoverEnterEvent(self, event):
        if options.auto_select_items:
            self.setSelected(True)
        QGraphicsItem.hoverEnterEvent(self, event)

    def hoverLeaveEvent(self, event):
        if options.auto_select_items:
            self.setSelected(False)
        QGraphicsItem.hoverLeaveEvent(self, event)
        
    def mousePressEvent(self, event):
        if canvas.scene.get_zoom_scale() <= 0.4:
            # prefer move box if zoom is too low
            event.ignore()
            return
        
        if event.button() == Qt.LeftButton:
            self._hover_item = None
            self._mouse_down = True
            self._cursor_moving = False

            for connection in canvas.list_connections(self._po):
                self._has_connections = True
                break
            else:
                self._has_connections = False

        elif event.button() == Qt.RightButton:
            if canvas.is_line_mov:
                if self._hover_item:
                    self._r_click_time = time.time()
                    self._connect_to_hover()
                    self._last_rclick_item = self._hover_item

                    for line_mov in self._line_mov_list:
                        line_mov.ready_to_disc = not line_mov.ready_to_disc
                        line_mov.update_line_pos(event.scenePos())

                    for connection in self._dotcon_list:
                        if connection in canvas.list_connections(self._po):
                            connection.widget.ready_to_disc = True
                            connection.widget.update_line_gradient()
                else:
                    box_under = canvas.scene.get_box_at(event.scenePos())
                    if box_under is not None and box_under is not self.parentItem():
                        box_under.wrap_unwrap_at_point(event.scenePos())

        QGraphicsItem.mousePressEvent(self, event)

    def mouseMoveEvent(self, event):
        starti = time.time()  
        if (not event.buttons() & Qt.LeftButton 
                and canvas.scene.flying_connectable is not self):
            QGraphicsItem.mouseMoveEvent(self, event)
            return

        if not self._cursor_moving:
            canvas.scene.set_cursor(QCursor(Qt.CrossCursor))
            self._cursor_moving = True

        if not self._line_mov_list:
            self._last_rclick_item = None
            canvas.last_z_value += 1
            self.setZValue(canvas.last_z_value)
            canvas.last_z_value += 1

            for port in canvas.list_ports(group_id=self._group_id):
                if port.port_id in self._port_ids:
                    port.widget.setZValue(canvas.last_z_value)

            for i in range(len(self._port_ids)):
                line_mov = LineMoveWidget(
                    self._port_mode, self._port_type, i,
                    len(self._port_ids), self)

                self._line_mov_list.append(line_mov)

            canvas.is_line_mov = True
            canvas.last_z_value += 1
            self.parentItem().setZValue(canvas.last_z_value)

        item = canvas.scene.get_connectable_item_at(event.scenePos(), self)
        
        if self._hover_item is not None and item is not self._hover_item:
            self._hover_item.setSelected(False)

        # if item has same port mode
        # verify we can use it for cut and paste connections
        if (item is not None
                and item.get_port_type() is self._port_type
                and item.get_port_mode() is self._port_mode):
            item_valid = False

            if (self._has_connections
                    and len(item.get_port_ids()) == len(self._port_ids)):
                for connection in canvas.list_connections(group_id=item.get_group_id()):
                    if connection.concerns(item.get_group_id(), item.get_port_ids()):
                        break
                else:
                    item_valid = True

            if not item_valid:
                item = None

        if (item is not None
                and not self.is_connectable_to(
                    item, accept_same_port_mode=True)):
            # prevent connection from an out CV port to a non CV port input
            # because it is very dangerous for monitoring
            pass

        elif (item is not None
              and item is not self._hover_item
              and item.get_port_type() is self._port_type):
            item.setSelected(True)

            if item is self._hover_item:
                # prevent unneeded operations
                pass

            else:
                self._hover_item = item
                hover_len = len(item.get_port_ids())
                self.reset_dot_lines()
                self.reset_line_mov_positions()

                if item.get_port_mode() is self._port_mode:
                    for connection in canvas.list_connections(self._po):
                        connection.widget.ready_to_disc = True
                        connection.widget.update_line_gradient()
                        self._dotcon_list.append(connection)

                    for line_mov in self._line_mov_list:
                        line_mov.ready_to_disc = True
                else:
                    if hover_len <= len(self._line_mov_list):
                        for i in range(len(self._line_mov_list)):
                            line_mov = self._line_mov_list[i]
                            line_mov.set_destination_portgrp_pos(
                                i % hover_len, hover_len)
                    else:
                        start_n_linemov = len(self._line_mov_list)

                        for i in range(hover_len):
                            if i < start_n_linemov:
                                line_mov = self._line_mov_list[i]
                                line_mov.set_destination_portgrp_pos(
                                    i, hover_len)
                            else:
                                port_posinportgrp = i % len(self._port_ids)
                                line_mov  = LineMoveWidget(
                                    self._port_mode,
                                    self._port_type,
                                    port_posinportgrp,
                                    hover_len,
                                    self)

                                line_mov.set_destination_portgrp_pos(
                                    i, hover_len)
                                self._line_mov_list.append(line_mov)

                    self._dotcon_list.clear()
                    symetric_con_list = []
                    for portself_id in self._port_ids:
                        for porthover_id in self._hover_item.get_port_ids():
                            for connection in canvas.list_connections(group_id=self._group_id):
                                if connection.matches(
                                        self._group_id, [portself_id],
                                        self._hover_item.get_group_id(),
                                        [porthover_id]):
                                    if (self._port_ids.index(portself_id)
                                        % hover_len
                                            == (self._hover_item.get_port_ids().index(porthover_id)
                                                % len(self._port_ids))):
                                        self._dotcon_list.append(connection)
                                        symetric_con_list.append(connection)
                                    else:
                                        self._dotcon_list.append(connection)
                                        connection.widget.ready_to_disc = True
                                        connection.widget.update_line_gradient()

                    biggest_list = (self._port_ids if len(self._port_ids) >= hover_len
                                    else self._hover_item.get_port_ids())

                    if len(symetric_con_list) == len(biggest_list):
                        for connection in self._dotcon_list:
                            connection.widget.ready_to_disc = True
                            connection.widget.update_line_gradient()
                        for line_mov in self._line_mov_list:
                            line_mov.ready_to_disc = True
        else:
            if item is not self._hover_item:
                self._hover_item = None
                self._last_rclick_item = None
                self.reset_dot_lines()
                self.reset_line_mov_positions()

        for line_mov in self._line_mov_list:
            line_mov.update_line_pos(event.scenePos())

        QGraphicsItem.mouseMoveEvent(self, event)
                
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self._mouse_down or canvas.scene.flying_connectable is self:
                for line_mov in self._line_mov_list:
                    item = line_mov
                    canvas.scene.removeItem(item)
                    del item
                self._line_mov_list.clear()

                if self._hover_item:
                    if (self._last_rclick_item is not self._hover_item
                            and time.time() > self._r_click_time + 0.3):
                        self._connect_to_hover()
                    canvas.scene.clearSelection()

                elif self._last_rclick_item:
                    canvas.scene.clearSelection()

            if self._cursor_moving:
                canvas.scene.set_cursor(QCursor(Qt.ArrowCursor))

            self._hover_item = None
            self._mouse_down = False
            self._cursor_moving = False
            canvas.is_line_mov = False
        
        self.mouse_releasing = True
        QGraphicsItem.mouseReleaseEvent(self, event)
        self.mouse_releasing = False