#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# PatchBay Canvas engine using QGraphicsView/Scene
# Copyright (C) 2010-2019 Filipe Coelho <falktx@falktx.com>
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

from dataclasses import dataclass

from PyQt5.QtCore import (QRectF, QMarginsF, Qt)
from PyQt5.QtWidgets import QGraphicsView

from .init_values import (
    canvas,
    options,
    PortMode,
    Direction)

from .scene_moth import PatchSceneMoth
from .box_widget import BoxWidget


@dataclass
class BoxAndRect:
    rect: QRectF
    item: BoxWidget
    
        
@dataclass
class ToMoveBox:
    directions: list[Direction]
    pos: float
    item: BoxWidget
    repulser: BoxAndRect
        
    def __lt__(self, other: 'ToMoveBox'):
        if self.directions != other.directions:
            return self.directions < other.directions
        return self.pos < other.pos
    

class PatchScene(PatchSceneMoth):
    " This class part of the scene is for repulsive boxes option"
    " because the algorythm is not simple and takes a lot of lines."
    " See scene_abstract.py for others scene methods."
    def __init__(self, parent, view: QGraphicsView):
        PatchSceneMoth.__init__(self, parent, view)

    def deplace_boxes_from_repulsers(self, repulser_boxes: list[BoxWidget],
                                     wanted_direction=Direction.NONE,
                                     new_scene_rect=None):
        ''' This function change the place of boxes in order to have no box overlapping
            other boxes.'''
        def get_direction(fixed_rect: QRectF, moving_rect: QRectF,
                          parent_directions=list[Direction]()) -> Direction:
            if (moving_rect.top() <= fixed_rect.center().y() <= moving_rect.bottom()
                    or fixed_rect.top() <= moving_rect.center().y() <= fixed_rect.bottom()):
                if (fixed_rect.right() < moving_rect.center().x()
                        and fixed_rect.center().x() < moving_rect.left()):
                    if Direction.LEFT in parent_directions:
                        return Direction.LEFT
                    return Direction.RIGHT
                
                if (fixed_rect.left() > moving_rect.center().x()
                        and fixed_rect.center().x() > moving_rect.right()):
                    if Direction.RIGHT in parent_directions:
                        return Direction.RIGHT
                    return Direction.LEFT
            
            if fixed_rect.center().y() <= moving_rect.center().y():
                if Direction.UP in parent_directions:
                    return Direction.UP
                return Direction.DOWN
            
            if Direction.DOWN in parent_directions:
                return Direction.DOWN
            return Direction.UP
        
        def repulse(direction: Direction, fixed, moving,
                    fixed_port_mode: int, moving_port_mode: int) -> QRectF:
            ''' returns a QRectF to be placed at side of fixed_rect
                where fixed_rect is an already determinated futur place
                for a box '''
                
            if isinstance(fixed, BoxWidget):
                fixed_rect = fixed.boundingRect().translated(fixed.pos())
            else:
                fixed_rect = fixed
            
            if isinstance(moving, BoxWidget):
                rect = moving.boundingRect().translated(moving.pos())
            else:
                rect = moving
            
            x = rect.left()
            y = rect.top()
            
            if direction in (Direction.LEFT, Direction.RIGHT):
                spacing = box_spacing

                if direction == Direction.LEFT:
                    if (fixed_port_mode & PortMode.INPUT
                            or moving_port_mode & PortMode.OUTPUT):
                        spacing = box_spacing_hor
                    x = fixed_rect.left() - spacing - rect.width()
                    if x < 0:
                        x -= 1.0
                    x = float(int(x))
                else:
                    if (fixed_port_mode & PortMode.OUTPUT
                            or moving_port_mode & PortMode.INPUT):
                        spacing = box_spacing_hor
                    x = fixed_rect.right() + spacing
                    if x < 0:
                        x -= 1.0
                    x = float(int(x + 0.99))

                top_diff = abs(fixed_rect.top() - rect.top())
                bottom_diff = abs(fixed_rect.bottom() - rect.bottom())

                if bottom_diff > top_diff and top_diff <= magnet:
                    y = fixed_rect.top()
                elif bottom_diff <= magnet:
                    y = fixed_rect.bottom() - rect.height()
            
            elif direction in (Direction.UP, Direction.DOWN):
                if direction == Direction.UP:
                    y = fixed_rect.top() - box_spacing - rect.height()
                    if y < 0:
                        y -= 1.0
                    y = float(int(y))
                else:
                    y = fixed_rect.bottom() + box_spacing
                    if y < 0:
                        y -= 1.0
                    y = float(int(y + 0.99))
                
                left_diff = abs(fixed_rect.left() - rect.left())
                right_diff = abs(fixed_rect.right() - rect.right())
                
                if right_diff > left_diff and left_diff <= magnet:
                    x = fixed_rect.left()
                elif right_diff <= magnet:
                    x = fixed_rect.right() - rect.width()

            return QRectF(x, y, rect.width(), rect.height())

        def rect_has_to_move_from(
                repulser_rect: QRectF, rect: QRectF,
                repulser_port_mode: int, rect_port_mode: int)->bool:
            left_spacing = right_spacing = box_spacing
            
            if (repulser_port_mode & PortMode.INPUT
                    or rect_port_mode & PortMode.OUTPUT):
                left_spacing = box_spacing_hor
            
            if (repulser_port_mode & PortMode.OUTPUT
                    or rect_port_mode & PortMode.INPUT):
                right_spacing = box_spacing_hor
            
            large_repulser_rect = repulser_rect.adjusted(
                - left_spacing, - box_spacing,
                right_spacing, box_spacing)

            return rect.intersects(large_repulser_rect)

        # --- function start ---
        if not options.prevent_overlap:
            return
        
        box_spacing = canvas.theme.box_spacing
        box_spacing_hor = canvas.theme.box_spacing_horizontal
        magnet = canvas.theme.magnet

        to_move_boxes = list[ToMoveBox]()
        repulsers = list[BoxAndRect]()
        wanted_directions = [wanted_direction]
        
        for box in repulser_boxes:
            srect = box.boundingRect()

            if new_scene_rect is not None:
                srect = new_scene_rect
            else:
                # if box is already moving, consider its end position
                for moving_box in self.move_boxes:
                    if moving_box.widget is box:
                        srect.translate(moving_box.to_pt)
                        break
                else:
                    srect.translate(box.pos())

            repulser = BoxAndRect(srect, box)
            repulsers.append(repulser)
            items_to_move = list[BoxAndRect]()

            search_rect = srect.marginsAdded(QMarginsF(4.0, 4.0, 4.0, 4.0))

            for widget in self.items(search_rect, Qt.IntersectsItemShape, Qt.AscendingOrder):
                if not isinstance(widget, BoxWidget):
                    continue
                
                if (widget in repulser_boxes
                        or widget in [b.item for b in to_move_boxes]
                        or widget in [b.widget for b in self.move_boxes]):
                    continue

                irect = widget.sceneBoundingRect()

                if rect_has_to_move_from(
                        repulser.rect, irect,
                        repulser.item.get_current_port_mode(),
                        widget.get_current_port_mode()):
                    items_to_move.append(BoxAndRect(irect, widget))

            for moving_box in self.move_boxes:
                if (moving_box.widget in repulser_boxes
                        or moving_box.widget in [b.item for b in to_move_boxes]):
                    continue

                widget = moving_box.widget
                irect = widget.boundingRect()
                irect.translate(moving_box.to_pt)
                
                if rect_has_to_move_from(
                        repulser.rect, irect,
                        repulser.item.get_current_port_mode(),
                        widget.get_current_port_mode()):
                    items_to_move.append(BoxAndRect(irect, widget))
            
            for item_to_move in items_to_move:
                item = item_to_move.item
                irect = item_to_move.rect
                    
                # evaluate in which direction should go the box
                direction = get_direction(srect, irect, wanted_directions)
                to_move_box = ToMoveBox([direction], 0.0, item, repulser)                
                
                # stock a position only for sorting reason
                if direction is Direction.RIGHT:
                    to_move_box.pos = irect.left()
                elif direction is Direction.LEFT:
                    to_move_box.pos = - irect.right()
                elif direction is Direction.DOWN:
                    to_move_box.pos = irect.top()
                elif direction is Direction.UP:
                    to_move_box.pos = - irect.bottom()

                to_move_boxes.append(to_move_box)

        to_move_boxes.sort()
        
        # !!! to_move_boxes list is dynamic
        # elements can be added to the list while iteration !!!
        for to_move_box in to_move_boxes:
            item = to_move_box.item
            repulser = to_move_box.repulser            
            irect = item.boundingRect().translated(item.pos())

            directions = to_move_box.directions.copy()
            new_direction = get_direction(repulser.rect, irect, directions)
            directions.append(new_direction)

            # calculate the new position of the box repulsed by its repulser
            new_rect = repulse(new_direction, repulser.rect, item,
                               repulser.item.get_current_port_mode(),
                               item.get_current_port_mode())
            
            active_repulsers = list[BoxAndRect]()
            
            # while there is a repulser rect at new box position
            # move the future box position
            while True:
                # list just here to prevent infinite loop
                # we save the repulsers that already have moved the rect
                for repulser in repulsers:
                    if rect_has_to_move_from(
                            repulser.rect, new_rect,
                            repulser.item.get_current_port_mode(),
                            item.get_current_port_mode()):

                        if repulser in active_repulsers:
                            continue
                        active_repulsers.append(repulser)
                        
                        new_direction = get_direction(
                            repulser.rect, new_rect, directions)
                        new_rect = repulse(
                            new_direction, repulser.rect, new_rect,
                            repulser.item._current_port_mode,
                            item._current_port_mode)
                        directions.append(new_direction)
                        break
                else:
                    break

            # Now we know where the box will be definitely positioned
            # So, this is now a repulser for other boxes
            repulser = BoxAndRect(new_rect, item)
            repulsers.append(repulser)
            
            # check which existing boxes exists at the new place of the box
            # and add them to this to_move_boxes iteration
            adding_list = list[ToMoveBox]()
            
            search_rect = new_rect.marginsAdded(QMarginsF(4.0, 4.0, 4.0, 4.0))
            
            for widget in self.items(search_rect):
                if not isinstance(widget, BoxWidget):
                    continue
                if (widget in repulser_boxes
                        or widget in [b.item for b in to_move_boxes]
                        or widget in [b.widget for b in self.move_boxes]):
                    continue
                
                mirect = widget.boundingRect().translated(widget.pos())
                if rect_has_to_move_from(
                        new_rect, mirect,
                        to_move_box.item.get_current_port_mode(),
                        widget.get_current_port_mode()):
                    
                    adding_list.append(
                        ToMoveBox(directions, mirect.right(), widget, repulser))                        
            
            for moving_box in self.move_boxes:
                mitem = moving_box.widget
                assert isinstance(mitem, BoxWidget)
                
                if (mitem in repulser_boxes
                        or mitem in [b.item for b in to_move_boxes]):
                    continue

                rect = mitem.boundingRect()
                rect.translate(moving_box.to_pt)
                
                if rect_has_to_move_from(
                        new_rect, rect,
                        to_move_box.item.get_current_port_mode(),
                        mitem.get_current_port_mode()):

                    adding_list.append(
                        ToMoveBox(directions, 0.0, moving_box.widget, repulser))

            for to_move_box in adding_list:
                to_move_boxes.append(to_move_box)

            # now we decide where the box is moved
            pos_offset = item.boundingRect().topLeft()
            to_send_rect = new_rect.translated(- pos_offset)
            self.add_box_to_animation(
                item, to_send_rect.left(), to_send_rect.top())

    def bring_neighbors_and_deplace_boxes(
            self, box_widget: BoxWidget, new_scene_rect: QRectF):
        neighbors = [box_widget]
        limit_top = box_widget.pos().y()
        
        for neighbor in neighbors:
            srect = neighbor.boundingRect()
            for moving_box in self.move_boxes:
                if moving_box.widget is neighbor:
                    srect.translate(moving_box.to_pt)
                    break
            else:
                srect.translate(neighbor.pos())

            for item in self.items(
                    srect.adjusted(0, 0, 0,
                                   canvas.theme.box_spacing + 1)):
                if item not in neighbors and isinstance(item, BoxWidget):
                    nrect = item.boundingRect().translated(item.pos())
                    if nrect.top() >= limit_top:
                        neighbors.append(item)
        
        neighbors.remove(box_widget)
        
        less_y = box_widget.boundingRect().height() - new_scene_rect.height()

        repulser_boxes = list[BoxWidget]()

        for neighbor in neighbors:
            self.add_box_to_animation(
                neighbor, neighbor.pos().x(), neighbor.pos().y() - less_y)
            repulser_boxes.append(neighbor)
        repulser_boxes.append(box_widget)
        
        self.deplace_boxes_from_repulsers(
            repulser_boxes, wanted_direction=Direction.UP)