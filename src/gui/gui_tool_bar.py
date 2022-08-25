from PyQt5.QtCore import Qt, QPoint
from PyQt5.QtGui import QMouseEvent, QIcon
from PyQt5.QtWidgets import QLabel, QApplication, QAction, QToolBar, QToolButton

from .gui_tools import RS
from .patchbay.tools_widgets import PatchbayToolsWidget
from .patchbay.tool_bar import PatchbayToolBar
from .patchbay.patchbay_manager import PatchbayManager

_translate = QApplication.translate

class RayToolBar(PatchbayToolBar):
    def __init__(self, parent):
        super().__init__(parent)
        self.force_main_actions_icons_only : bool = RS.settings.value(
            'tool_bar/icons_only', False, type=bool)
    
    def set_patchbay_manager(self, patchbay_manager: PatchbayManager):
        super().set_patchbay_manager(patchbay_manager)
        self._set_main_actions_icon_only(
            self.force_main_actions_icons_only)
    
    def _set_main_actions_icon_only(self, yesno: bool):
        if yesno:
            self.setToolButtonStyle(Qt.ToolButtonIconOnly)
        else:
            self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        
        # for action in self.actions():
        #     tool_button = self.widgetForAction(action)            
        #     if not isinstance(tool_button, QToolButton):
        #         continue

        #     if yesno:
        #         tool_button.setToolButtonStyle(Qt.ToolButtonIconOnly)
        #     else:
        #         tool_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.force_main_actions_icons_only = yesno
    
    def mousePressEvent(self, event: QMouseEvent):
        child_widget = self.childAt(event.pos())
        QToolBar.mousePressEvent(self, event)

        if not (event.button() == Qt.RightButton
                and (child_widget is None
                     or isinstance(child_widget, (QLabel, PatchbayToolsWidget)))):
            return

        context_actions = self._make_context_actions()
        menu = self._make_context_menu(context_actions)
        
        act_text_with_icons = QAction(QIcon.fromTheme('format-text-direction-symbolic'),
                                      _translate('gui_tool_bar', 'Text with session actions'))
        act_text_with_icons.setCheckable(True)
        act_text_with_icons.setChecked(not self.force_main_actions_icons_only)
        menu.addSeparator()
        menu.addAction(act_text_with_icons)
        
        # execute the menu, exit if no action
        point = event.screenPos().toPoint()
        point.setY(self.mapToGlobal(QPoint(0, self.height())).y())
        selected_act = menu.exec(point)
        if selected_act is None:
            return
        
        if selected_act is act_text_with_icons:
            self._set_main_actions_icon_only(not act_text_with_icons.isChecked())
            return

        for key, act in context_actions.items():
            if act is selected_act:
                if act.isChecked():
                    self._displayed_widgets |= key
                else:
                    self._displayed_widgets &= ~key

        self._change_visibility()
