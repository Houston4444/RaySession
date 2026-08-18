from patchbay import PatchGraphicsView
from patchbay.widgets import filter_frame, tool_bar


class CanvasGroupFilterFrame(filter_frame.FilterFrame):
    def __init__(self, parent):
        super().__init__(parent)
        

class RayToolBar(tool_bar.PatchbayToolBar):
    def __init__(self, parent):
        super().__init__(parent)