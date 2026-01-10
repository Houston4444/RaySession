from typing import TYPE_CHECKING

from qtpy.QtGui import QIcon
from qtpy.QtWidgets import QToolButton

if TYPE_CHECKING:
    from gui_session import Session


class FavoriteToolButton(QToolButton):
    def __init__(self, parent):
        super().__init__(parent)
        self._template_name = ''
        self._template_icon = ''
        self._factory = True
        self._display_name = ''
        self._state = False
        self._favicon_not = QIcon(':scalable/breeze/draw-star.svg')
        self._favicon_yes = QIcon(':scalable/breeze/star-yellow.svg')

        self.session = None

        self.setIcon(self._favicon_not)

    def set_dark_theme(self):
        self._favicon_not = QIcon(':scalable/breeze-dark/draw-star.svg')
        if not self._state:
            self.setIcon(self._favicon_not)

    def set_session(self, session: 'Session'):
        self.session = session

    def set_template(self, template_name: str, template_icon: str,
                     factory: bool, display_name: str):
        self._template_name = template_name
        self._template_icon = template_icon
        self._factory = factory
        self._display_name = display_name

    def set_as_favorite(self, yesno: bool):
        self._state = yesno
        self.setIcon(self._favicon_yes if yesno else self._favicon_not)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if self.session is None:
            return

        if self._state:
            self.session.remove_favorite(self._template_name, self._factory)
        else:
            self.session.add_favorite(
                self._template_name, self._template_icon,
                self._factory, self._display_name)
