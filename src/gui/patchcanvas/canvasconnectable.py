
import time
from typing import TYPE_CHECKING
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QCursor
from PyQt5.QtWidgets import QGraphicsItem

import patchcanvas.utils as utils
from .init_values import (
    ConnectionObject,
    CanvasItemType,
    PortMode,
    PortType,
    canvas,
    options)
from .canvasbezierlinemov import CanvasBezierLineMov

if TYPE_CHECKING:
    from .canvasbox import CanvasBox

class CanvasDisconnectable(QGraphicsItem):
    def __init__(self):
        super().__init__()
        
    def trigger_disconnect(self):
        pass
    

class CanvasConnectable(CanvasDisconnectable):
    def __init__(self, group_id: int, port_ids: tuple[int],
                 port_mode: PortMode, port_type: PortType,
                 is_alternate: bool, parent: 'CanvasBox'):
        super().__init__()
        self.setParentItem(parent)
        self.setCacheMode(QGraphicsItem.DeviceCoordinateCache)
        self.setFlags(QGraphicsItem.ItemIsSelectable)

        self._group_id = group_id
        self._port_ids = port_ids
        self._port_mode = port_mode
        self._port_type = port_type
        self._is_alternate = is_alternate
        
        # needed for line mov
        self._line_mov_list = list[CanvasBezierLineMov]()
        self._dotcon_list = list[ConnectionObject]()
        self._last_rclick_item = None
        self._r_click_time = 0
        self._hover_item = None
        self._mouse_down = False
        self._cursor_moving = False
        self._has_connections = False
        
    def get_group_id(self) -> int:
        return self._group_id

    def get_port_ids(self) -> tuple[int]:
        return self._port_ids

    def get_port_mode(self) -> PortMode:
        return self._port_mode

    def get_port_type(self) -> PortType:
        return self._port_type

    def is_alternate(self):
        return False

    def is_connectable_to(self, other: 'CanvasConnectable',
                          accept_same_port_mode=False)->bool:
        print('rijfirf', 'isconto', self._port_ids, other._port_ids)
        if self._port_type != other.get_port_type():
            return False

        if not accept_same_port_mode:
            if self._port_mode == other.get_port_mode():
                return False

        if self._port_type == PortType.AUDIO_JACK:
            if other.get_port_mode() == self._port_mode:
                return bool(self.is_alternate() == other.is_alternate())
            # absolutely forbidden to connect an output CV port
            # to an input audio port.
            # It could destroy material.
            if self._port_mode is PortMode.OUTPUT:
                if self.is_alternate():
                    return other.is_alternate()
                return True

            if self._port_mode is PortMode.INPUT:
                if self.is_alternate():
                    return True
                return not other.is_alternate()

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
            line_mov = CanvasBezierLineMov(
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
        pass
        
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

            for connection in canvas.connection_list:
                if utils.connection_concerns(
                        connection, self._group_id, self._port_ids):
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
                        if connection in canvas.connection_list:
                            connection.widget.ready_to_disc = True
                            connection.widget.update_line_gradient()

        QGraphicsItem.mousePressEvent(self, event)
        
    def mouseMoveEvent(self, event):
        if not self._mouse_down:
            QGraphicsItem.mouseMoveEvent(self, event)
            return

        if not self._cursor_moving:
            self.setCursor(QCursor(Qt.CrossCursor))
            self._cursor_moving = True

            for connection in canvas.connection_list:
                if utils.connection_concerns(
                        connection, self._group_id, self._port_ids):
                    connection.widget.locked = True

        if not self._line_mov_list:
            self._last_rclick_item = None
            canvas.last_z_value += 1
            self.setZValue(canvas.last_z_value)
            canvas.last_z_value += 1

            for port in canvas.port_list:
                if (port.group_id == self._group_id
                        and port.port_id in self._port_ids):
                    port.widget.setZValue(canvas.last_z_value)

            for i in range(len(self._port_ids)):
                line_mov = CanvasBezierLineMov(
                    self._port_mode, self._port_type, i,
                    len(self._port_ids), self)

                self._line_mov_list.append(line_mov)

            canvas.is_line_mov = True
            canvas.last_z_value += 1
            self.parentItem().setZValue(canvas.last_z_value)

        item = None
        items = canvas.scene.items(event.scenePos(), Qt.ContainsItemShape,
                                   Qt.AscendingOrder)
        for i in range(len(items)):
            if items[i].type() in (CanvasItemType.PORT,
                                   CanvasItemType.PORTGROUP):
                if items[i] != self:
                    if not item:
                        item = items[i]
                    elif (items[i].parentItem().zValue()
                          > item.parentItem().zValue()):
                        item = items[i]

        if self._hover_item and self._hover_item != item:
            self._hover_item.setSelected(False)

        # if item has same port mode
        # verify we can use it for cut and paste connections
        if (item is not None
                and item.get_port_type() == self._port_type
                and item.get_port_mode() == self._port_mode):
            item_valid = False

            if (self._has_connections
                    and item.type() in (CanvasItemType.PORTGROUP, CanvasItemType.PORT)
                    and len(item.get_port_ids()) == len(self._port_ids)):
                for connection in canvas.connection_list:
                    if utils.connection_concerns(
                            connection, item.get_group_id(),
                            item.get_port_ids()):
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
              and self._hover_item != item
              and item.get_port_type() == self._port_type):
            item.setSelected(True)

            if item == self._hover_item:
                # prevent unneeded operations
                pass

            elif item.type() is CanvasItemType.PORT:
                self._hover_item = item
                self.reset_dot_lines()
                self.reset_line_mov_positions()
                for line_mov in self._line_mov_list:
                    line_mov.set_destination_portgrp_pos(0, 1)

                self._dotcon_list.clear()

                for connection in canvas.connection_list:
                    if utils.connection_matches(
                            connection,
                            self._group_id, self._port_ids,
                            self._hover_item.get_group_id(),
                            [self._hover_item.get_port_id()]):
                        self._dotcon_list.append(connection)

                if len(self._dotcon_list) == len(self._port_ids):
                    for connection in self._dotcon_list:
                        connection.widget.ready_to_disc = True
                        connection.widget.update_line_gradient()
                    for line_mov in self._line_mov_list:
                        line_mov.ready_to_disc = True

            elif item.type() is CanvasItemType.PORTGROUP:
                self._hover_item = item
                self.reset_dot_lines()
                self.reset_line_mov_positions()

                if item.get_port_mode() == self._port_mode:
                    for connection in canvas.connection_list:
                        if utils.connection_concerns(
                                connection,
                                self._group_id, self._port_ids):
                            connection.widget.ready_to_disc = True
                            connection.widget.update_line_gradient()
                            self._dotcon_list.append(connection)

                    for line_mov in self._line_mov_list:
                        line_mov.ready_to_disc = True
                else:
                    if (self._hover_item.get_port_list_len()
                            <= len(self._line_mov_list)):
                        for i in range(len(self._line_mov_list)):
                            line_mov = self._line_mov_list[i]
                            line_mov.set_destination_portgrp_pos(
                                i % self._hover_item.get_port_list_len(),
                                self._hover_item.get_port_list_len())
                    else:
                        start_n_linemov = len(self._line_mov_list)

                        for i in range(self._hover_item.get_port_list_len()):
                            if i < start_n_linemov:
                                line_mov = self._line_mov_list[i]
                                line_mov.set_destination_portgrp_pos(
                                    i, self._hover_item.get_port_list_len())
                            else:
                                port_posinportgrp = i % len(self._port_ids)
                                line_mov  = CanvasBezierLineMov(
                                    self._port_mode,
                                    self._port_type,
                                    port_posinportgrp,
                                    self._hover_item.get_port_list_len(),
                                    self)

                                line_mov.set_destination_portgrp_pos(
                                    i, self._hover_item.get_port_list_len())
                                self._line_mov_list.append(line_mov)

                    self._dotcon_list.clear()
                    symetric_con_list = []
                    for portself_id in self._port_ids:
                        for porthover_id in self._hover_item.get_port_ids():
                            for connection in canvas.connection_list:
                                if utils.connection_matches(
                                        connection,
                                        self._group_id, [portself_id],
                                        self._hover_item.get_group_id(),
                                        [porthover_id]):
                                    if (self._port_ids.index(portself_id)
                                        % len(self._hover_item.get_port_ids_list())
                                            == (self._hover_item.get_port_ids_list().index(porthover_id)
                                                % len(self._port_ids))):
                                        self._dotcon_list.append(connection)
                                        symetric_con_list.append(connection)
                                    else:
                                        self._dotcon_list.append(connection)
                                        connection.widget.ready_to_disc = True
                                        connection.widget.update_line_gradient()

                    biggest_list = self._hover_item.get_port_ids_list()
                    if (len(self._port_ids)
                            >= len(self._hover_item.get_port_ids_list())):
                        biggest_list = self._port_ids

                    if len(symetric_con_list) == len(biggest_list):
                        for connection in self._dotcon_list:
                            connection.widget.ready_to_disc = True
                            connection.widget.update_line_gradient()
                        for line_mov in self._line_mov_list:
                            line_mov.ready_to_disc = True
        else:
            if item != self._hover_item:
                self._hover_item = None
                self._last_rclick_item = None
                self.reset_dot_lines()
                self.reset_line_mov_positions()

        for line_mov in self._line_mov_list:
            line_mov.update_line_pos(event.scenePos())
        return event.accept()

        QGraphicsItem.mouseMoveEvent(self, event)
        
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self._mouse_down:

                for line_mov in self._line_mov_list:
                    item = line_mov
                    canvas.scene.removeItem(item)
                    del item
                self._line_mov_list.clear()

                for connection in canvas.connection_list:
                    if utils.connection_concerns(
                            connection, self._group_id, self._port_ids):
                        connection.widget.locked = False

                if self._hover_item:
                    if (self._last_rclick_item != self._hover_item
                            and time.time() > self._r_click_time + 0.3):
                        self._connect_to_hover()
                    canvas.scene.clearSelection()

                elif self._last_rclick_item:
                    canvas.scene.clearSelection()

            if self._cursor_moving:
                self.setCursor(QCursor(Qt.ArrowCursor))

            self._hover_item = None
            self._mouse_down = False
            self._cursor_moving = False
            canvas.is_line_mov = False
        QGraphicsItem.mouseReleaseEvent(self, event)
        
    def itemChange(self, change, value: bool):
        if change == QGraphicsItem.ItemSelectedHasChanged:
            for connection in canvas.connection_list:
                if utils.connection_concerns(
                        connection, self._group_id, self._port_ids):
                    connection.widget.set_line_selected(value)

        return QGraphicsItem.itemChange(self, change, value)