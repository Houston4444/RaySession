
from qtpy.QtWidgets import QCompleter, QDialogButtonBox

from .child_dialog import ChildDialog

from osclib import Address, verified_address
import ray

from gui_tools import ErrDaemon, _translate, RS

import ui.daemon_url


class DaemonUrlDialog(ChildDialog):
    def __init__(self, parent, err_code, ex_url):
        super().__init__(parent)
        self.ui = ui.daemon_url.Ui_Dialog()
        self.ui.setupUi(self)

        self.ui.lineEdit.textChanged.connect(self._allow_url)

        match err_code:
            case ErrDaemon.NO_ANNOUNCE:
                error_text = _translate(
                    "url_window",
                    "<p>daemon at<br><strong>%s</strong>"
                    "<br>didn't announce !<br></p>") % ex_url
            case ErrDaemon.NOT_OFF:
                error_text = _translate(
                    "url_window",
                    "<p>daemon at<br><strong>%s</strong>"
                    "<br>has a loaded session."
                    "<br>It can't be used for slave session</p>") % ex_url
            case ErrDaemon.WRONG_ROOT:
                error_text = _translate(
                    "url_window",
                    "<p>daemon at<br><strong>%s</strong>"
                    "<br>uses an other session root folder !<.p>") % ex_url
            case ErrDaemon.FORBIDDEN_ROOT:
                error_text = _translate(
                    "url_window",
                    "<p>daemon at<br><strong>%s</strong>"
                    "<br>uses a forbidden session root folder !<.p>") % ex_url
            case ErrDaemon.WRONG_VERSION:
                error_text = _translate(
                    "url_window",
                    "<p>daemon at<br><strong>%s</strong>"
                    "<br>uses another %s version.<.p>") % (
                        ex_url, ray.APP_TITLE)
            case _:
                error_text = _translate(
                    "url window",
                    "<p align=\"left\">To run a network session,"
                    "<br>open a terminal on another computer of this network."
                    "<br>Launch ray-daemon on port 1234 (for example)"
                    "<br>by typing the command :</p><p align=\"left\">"
                    "<code>ray-daemon -p 1234</code></p>"
                    "<p align=\"left\">Then paste below the first url"
                    "<br>that ray-daemon gives you at startup.</p><p></p>")

        self.ui.labelError.setText(error_text)
        self._ok_button.setEnabled(False)

        self.tried_urls = ray.get_list_in_settings(
            RS.settings, 'network/tried_urls')
        last_tried_url = RS.settings.value(
            'network/last_tried_url', '', type=str)

        self._completer = QCompleter(self.tried_urls)
        self.ui.lineEdit.setCompleter(self._completer) # type:ignore

        if ex_url:
            self.ui.lineEdit.setText(ex_url)
        elif last_tried_url:
            self.ui.lineEdit.setText(last_tried_url)

    @property
    def _ok_button(self):
        return self.ui.buttonBox.button(
            QDialogButtonBox.StandardButton.Ok) # type:ignore

    def _allow_url(self, text: str):
        if not text:
            self.ui.lineEdit.completer().complete()
            self._ok_button.setEnabled(False)
            return

        if not text.startswith('osc.udp://'):
            self._ok_button.setEnabled(False)
            return

        addr = verified_address(text)
        self._ok_button.setEnabled(isinstance(addr, Address))

    def get_url(self):
        return self.ui.lineEdit.text()

