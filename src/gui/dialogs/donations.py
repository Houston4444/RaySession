
from qtpy.QtCore import QUrl
from qtpy.QtGui import QIcon, QDesktopServices

from gui_tools import RS, is_dark_theme
from .child_dialog import ChildDialog

import ui.donations


class DonationsDialog(ChildDialog):
    def __init__(self, parent, display_no_again):
        ChildDialog.__init__(self, parent)
        self.ui = ui.donations.Ui_Dialog()
        self.ui.setupUi(self)

        dark = '-dark' if is_dark_theme(self) else ''
        self.ui.toolButtonImage.setIcon(
            QIcon(f':scalable/breeze{dark}/handshake-deal.svg')) # type:ignore

        self.ui.toolButtonDonate.clicked.connect(self._donate)

        self.ui.checkBox.setVisible(display_no_again)
        self.ui.checkBox.clicked.connect(self._check_box_clicked)

    def _check_box_clicked(self, state):
        RS.set_hidden(RS.HD_Donations, state)
        
    def _donate(self):
        QDesktopServices.openUrl(
            QUrl('https://liberapay.com/Houston4444'))