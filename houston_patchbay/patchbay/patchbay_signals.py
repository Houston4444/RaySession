
from PyQt5.QtCore import QObject, pyqtSignal

# we need a QObject for pyqtSignal
class SignalsObject(QObject):
    port_types_view_changed = pyqtSignal(int)
    full_screen_toggle_wanted = pyqtSignal()
    filters_bar_toggle_wanted = pyqtSignal()

    def __init__(self):
        QObject.__init__(self)