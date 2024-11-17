from enum import IntEnum
from typing import TYPE_CHECKING

from qtpy.QtWidgets import QApplication, QMessageBox
from qtpy.QtCore import Slot

from child_dialogs import ChildDialog
from gui_server_thread import GuiServerThread
from gui_tools import RS
import ray

import ui.settings

if TYPE_CHECKING:
    from main_window import MainWindow


_translate = QApplication.translate


class PreferencesTab(IntEnum):
    DAEMON = 0
    DISPLAY = 1
    SYSTRAY = 2


class PreferencesDialog(ChildDialog):
    def __init__(self, parent: 'MainWindow'):
        super().__init__(parent)
        self.ui = ui.settings.Ui_dialogPreferences()
        self.ui.setupUi(self)
        
        self._main_win = parent
        wui = self._main_win.ui
        
        # auto connect and fill checkboxes with matching actions
        self._check_box_actions = {
            self.ui.checkBoxBookmarks: wui.actionBookmarkSessionFolder,
            self.ui.checkBoxAutoSnapshot: wui.actionAutoSnapshot,
            self.ui.checkBoxDesktopsMemory: wui.actionDesktopsMemory,
            self.ui.checkBoxSessionScripts: wui.actionSessionScripts,
            self.ui.checkBoxGuiStates: wui.actionRememberOptionalGuiStates,
            self.ui.checkBoxMenuBar: wui.actionShowMenuBar,
            self.ui.checkBoxMessages: wui.actionToggleShowMessages,
            self.ui.checkBoxJackPatchbay: wui.actionShowJackPatchbay,
            self.ui.checkBoxKeepFocus: wui.actionKeepFocus
        }
            
        for check_box, action in self._check_box_actions.items():
            check_box.setText(action.text())
            check_box.setIcon(action.icon())
            check_box.setToolTip(action.toolTip())
            check_box.setChecked(action.isChecked())
            check_box.stateChanged.connect(self._check_box_state_changed)
            action.changed.connect(self._action_changed)

        # connect other widgets
        self.ui.pushButtonPatchbayPreferences.clicked.connect(
            self._main_win.session.patchbay_manager.show_options_dialog)
        self.ui.pushButtonReappear.clicked.connect(
            self._make_all_dialogs_reappear)
        self.ui.checkboxStartupDialogs.stateChanged.connect(
            self._show_startup_dialog)
        
        # update directly hiddens dialogs changes in this window
        self._main_win.session.signaler.hiddens_changed.connect(
            self._hiddens_changed)

        # fill startup dialog started checkbox
        self.ui.checkboxStartupDialogs.setChecked(
            not RS.is_hidden(RS.HD_StartupRecentSessions))

        # fill systray checkboxes
        self.ui.groupBoxSystray.setChecked(
            self._main_win.systray_mode is not ray.Systray.OFF)
        self.ui.checkBoxOnlySessionRunning.setChecked(
            self._main_win.systray_mode is ray.Systray.SESSION_ONLY)
        self.ui.checkBoxReversedMenu.setChecked(
            self._main_win.reversed_systray_menu)
        self.ui.checkBoxShutdown.setChecked(
            self._main_win.wild_shutdown)
        
        # connect systray checkboxes
        self.ui.groupBoxSystray.toggled.connect(self._systray_changed)
        for check_box in (self.ui.checkBoxOnlySessionRunning,
                          self.ui.checkBoxReversedMenu,
                          self.ui.checkBoxShutdown):
            check_box.stateChanged.connect(self._systray_changed)

        # terminal command
        self.ui.pushButtonResetTerminal.clicked.connect(
            self._reset_terminal_command)
        self.ui.toolButtonTerminal.setToolTip(
            self.ui.labelTerminalCommand.toolTip())
        self.ui.lineEditTerminalCommand.setToolTip(
            self.ui.labelTerminalCommand.toolTip())
        self.ui.lineEditTerminalCommand.textEdited.connect(
            self._terminal_edited)
        self.ui.lineEditTerminalCommand.setText(
            self._main_win.session.terminal_command)

    @Slot()
    def _check_box_state_changed(self):
        sender = self.sender()
        for check_box, action in self._check_box_actions.items():
            if check_box is sender:
                action.setChecked(check_box.isChecked())
                break
    
    @Slot()
    def _action_changed(self):
        sender = self.sender()
        for checkbox, action in self._check_box_actions.items():
            if action is sender:
                checkbox.setChecked(action.isChecked())
                break
    
    @Slot()
    def _systray_changed(self):
        self._main_win.change_systray_options(
            self._get_systray_mode(),
            self.ui.checkBoxShutdown.isChecked(),
            self.ui.checkBoxReversedMenu.isChecked()
        )
    
    def _get_systray_mode(self) -> ray.Systray:
        if self.ui.groupBoxSystray.isChecked():
            if self.ui.checkBoxOnlySessionRunning.isChecked():
                return ray.Systray.SESSION_ONLY
            return ray.Systray.ALWAYS
        return ray.Systray.OFF
    
    def _make_all_dialogs_reappear(self):
        button = QMessageBox.question(
            self,
            _translate('hidden_dialogs', 'Make reappear dialog windows'),
            _translate('hidden_dialogs',
                       'Do you want to make reappear all dialogs you wanted to hide ?'))
        
        if button == QMessageBox.StandardButton.Yes:
            RS.reset_hiddens()
    
    def _show_startup_dialog(self, yesno: int):
        RS.set_hidden(RS.HD_StartupRecentSessions, not yesno)
        
    def _hiddens_changed(self, hiddens: int):
        self.ui.pushButtonReappear.setEnabled(bool(hiddens > 0))
        self.ui.checkboxStartupDialogs.setChecked(
            not hiddens & RS.HD_StartupRecentSessions)
        
    def set_on_tab(self, tab: PreferencesTab):
        self.ui.tabWidget.setCurrentIndex(int(tab))
        
    def set_terminal_command(self, command: str):
        if not self.ui.lineEditTerminalCommand.text():
            # prevent to auto-fill the line input when user clears it
            # because when we send empty command to deamon
            # it sends the default terminal command
            return

        if command != self.ui.lineEditTerminalCommand.text():
            self.ui.lineEditTerminalCommand.setText(command)
        
    def _reset_terminal_command(self):
        server = GuiServerThread.instance()
        if server is not None:        
            server.to_daemon('/ray/server/set_terminal_command', '')
            
    def _terminal_edited(self, text: str):
        server = GuiServerThread.instance()
        if server is not None:        
            server.to_daemon('/ray/server/set_terminal_command', text)