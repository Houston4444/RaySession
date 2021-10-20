# here we are sure the box area with margins contains other boxes.
        # Check if box area without margins contains others boxes,
        # if not, then we will move this box at regular margin
        # from the other boxes
        #for item in canvas.scene.items(srect):
            #if item.type() == CanvasBoxType and item is not self:
                #break
        #else:
            #print('on passe par la self repulsion')
            
            #left_item = None
            #top_item = None
            #right_item = None
            #bottom_item = None
            #left_item_right = 0
            #top_item_bottom = 0
            #right_item_left = 0
            #bottom_item_top = 0
            
            #for item in items_to_move:
                #irect = item.boundingRect()
                #irect.translate(item.pos())
                
                #if irect.right() <= srect.left():
                    #if left_item is None or irect.right() > left_item_right:
                        #left_item = item
                        #left_item_right = irect.right()
                    
                #if irect.bottom() <= srect.top():
                    #if top_item is None or irect.bottom() > top_item_bottom:
                        #top_item = item
                        #top_item_bottom = irect.bottom()
                    
                #if irect.left() >= srect.right():
                    #if right_item is None or irect.left() < right_item_left:
                        #right_item = item
                        #right_item_left = irect.left()
                    
                #if irect.top() >= srect.bottom():
                    #if bottom_item is None or irect.top() < bottom_item_top:
                        #bottom_item = item
                        #bottom_item_top = irect.top()
            
            #if not ((left_item and right_item) or (top_item and bottom_item)):
                #rect = None

                #if left_item is not None:
                    #rect = repulse(
                        #DIRECTION_RIGHT,
                        #left_item.boundingRect().translated(left_item.pos()),
                        #self)
                #if top_item is not None:
                    #rect = repulse(
                        #DIRECTION_DOWN,
                        #top_item.boundingRect().translated(top_item.pos()),
                        #self)
                #if right_item is not None:
                    #rect = repulse(
                        #DIRECTION_LEFT,
                        #right_item.boundingRect().translated(right_item.pos()),
                        #self)
                #if bottom_item is not None:
                    #rect = repulse(
                        #DIRECTION_UP,
                        #bottom_item.boundingRect().translated(bottom_item.pos()),
                        #self)
                
                #pos_point = rect.topLeft()
                #pos_point -= self.boundingRect().topLeft()
                
                #canvas.scene.add_box_to_animation(self, pos_point.x(), pos_point.y())
                #return
