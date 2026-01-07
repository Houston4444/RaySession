
# Imports from standard library
from pathlib import Path
import subprocess
import time
from typing import TYPE_CHECKING, Optional

# third party imports
from qtpy.QtCore import QTimer, Slot, QUrl, QLocale, Qt # type:ignore
from qtpy.QtGui import (QIcon, QDesktopServices, QFontMetrics,
                        QCloseEvent, QKeyEvent)
if TYPE_CHECKING:
    # FIX : QAction not found by pylance
    from qtpy.QtGui import QAction, QShortcut
from qtpy.QtWidgets import (
    QApplication, QMainWindow, QMenu,
    QMessageBox, QToolButton, QAbstractItemView,
    QBoxLayout, QSystemTrayIcon, QShortcut, QAction) # type:ignore

# Imports from HoustonPatchbay
from patchbay.bases.elements import ToolDisplayed
from patchbay.tools_widgets import PatchbayToolsWidget, TextWithIcons

# Imports from src/shared
from osclib import are_on_same_machine
import ray
import osc_paths
import osc_paths.ray as r
import osc_paths.ray.gui as rg

# Local imports
import add_application_dialog
import open_session_dialog
import dialogs
import snapshots_dialog
import preferences_dialog
import list_widget_clients
from gui_tools import (
    RS, ray_icon, CommandLineArgs, _translate, server_status_string,
    is_dark_theme, get_code_root, get_app_icon)
from gui_client import TrashedClient
from gui_server_thread import GuiServerThread
from utility_scripts import UtilityScriptLauncher

# Import UIs made with Qt-Designer
import ui.raysession

if TYPE_CHECKING:
    from .gui_session import SignaledSession


UI_PATCHBAY_UNDEF = 0
UI_PATCHBAY_HIDDEN = 1
UI_PATCHBAY_SHOWN = 2


class MainWindow(QMainWindow):
    def __init__(self, session: 'SignaledSession'):
        QMainWindow.__init__(self)
        self.ui = ui.raysession.Ui_MainWindow()
        self.ui.setupUi(self)

        self.session = session
        self.daemon_manager = self.session.daemon_manager

        self.mouse_is_inside = False
        self.terminate_request = False

        self.notes_dialog = None

        self.util_script_launcher = UtilityScriptLauncher(self, session)

        # timer for keep focus while client opening
        self._timer_raisewin = QTimer()
        self._timer_raisewin.setInterval(50)
        self._timer_raisewin.timeout.connect(self._raise_window)

        # timer for flashing effect of 'open' status
        self._timer_flicker_open = QTimer()
        self._timer_flicker_open.setInterval(400)
        self._timer_flicker_open.timeout.connect(self._flash_open)
        self.flash_open_list = []
        self._flash_open_bool = False

        # timer for too long snapshots, display snapshot progress dialog
        self._timer_snapshot = QTimer()
        self._timer_snapshot.setSingleShot(True)
        self._timer_snapshot.setInterval(2000)
        self._timer_snapshot.timeout.connect(
            self._show_snapshot_progress_dialog)

        self.server_copying = False

        self._keep_focus = RS.settings.value('keepfocus', False, type=bool)
        self.ui.actionKeepFocus.setChecked(self._keep_focus)

        # do not enable keep focus option under Wayland
        # because activate a window from it self on Wayland not allowed
        if ray.get_window_manager() is ray.WindowManager.WAYLAND:
            self._keep_focus = False
            self.ui.actionKeepFocus.setEnabled(False)

        # calculate tool button size with action labels
        self._tool_bar_main_actions_width = 0
        for action in (self.ui.actionNewSession,
                       self.ui.actionOpenSession,
                       self.ui.actionControlMenu):
            button = self.ui.toolBar.widgetForAction(action)
            if isinstance(button, QToolButton):
                self._tool_bar_main_actions_width += button.iconSize().width()
                self._tool_bar_main_actions_width += \
                    QFontMetrics(button.font()).horizontalAdvance(button.text())
            self._tool_bar_main_actions_width += 6

        # manage geometry depending of use of embedded jack patchbay
        self._patchbay_tools : Optional[PatchbayToolsWidget] = None
        
        show_patchbay = RS.settings.value(
            'MainWindow/show_patchbay', True, type=bool)
        self.ui.actionShowJackPatchbay.setChecked(show_patchbay)
        self.waiting_for_patchbay = show_patchbay

        if show_patchbay:
            patchbay_geom = RS.settings.value('MainWindow/patchbay_geometry')
            if patchbay_geom:
                self.restoreGeometry(patchbay_geom)

            self.ui.graphicsView.setVisible(True)

            splitter_sizes = RS.settings.value(
                'MainWindow/splitter_canvas_sizes', [420, 706], type=list)

            self.ui.splitterMainVsCanvas.setSizes(
                int(s) for s in splitter_sizes)

        else:
            self.ui.graphicsView.setVisible(False)
            self.ui.splitterMainVsCanvas.setSizes([100, 0])
            self.ui.splitterMainVsCanvas.set_active(False)

            geom = RS.settings.value('MainWindow/geometry')

            if geom:
                self.restoreGeometry(geom)
            else:
                rect = self.geometry()
                x = rect.x()
                y = rect.y()
                height = rect.height()
                self.setMinimumWidth(450)
                self.setGeometry(x, y, 460, height)

        splitter_sizes = RS.settings.value(
            "MainWindow/splitter_messages", [466, 84], type=list)

        self.ui.splitterSessionVsMessages.setSizes(
            [int(s) for s in splitter_sizes])

        if RS.settings.value('MainWindow/WindowState'):
            self.restoreState(RS.settings.value('MainWindow/WindowState'))
        show_menu_bar = RS.settings.value(
            'MainWindow/ShowMenuBar', False, type=bool)
        if not show_menu_bar:
            self.ui.actionShowMenuBar.activate(QAction.ActionEvent.Trigger)
        self.ui.actionToggleShowMessages.toggled.connect(
            self._show_messages_widget)

        self.ui.actionToggleShowMessages.setChecked(
            bool(self.ui.splitterSessionVsMessages.sizes()[1] > 0))

        self._force_tool_bar_icon_only = False

        # set default action for tools buttons
        self.ui.closeButton.setDefaultAction(self.ui.actionCloseSession)
        self.ui.toolButtonSaveSession.setDefaultAction(
            self.ui.actionSaveSession)
        self.ui.toolButtonAbortSession.setDefaultAction(
            self.ui.actionAbortSession)
        self.ui.toolButtonNotes.setDefaultAction(
            self.ui.actionSessionNotes)
        self.ui.toolButtonFileManager.setDefaultAction(
            self.ui.actionOpenSessionFolder)
        self.ui.toolButtonAddApplication.setDefaultAction(
            self.ui.actionAddApplication)
        self.ui.toolButtonAddExecutable.setDefaultAction(
            self.ui.actionAddExecutable)
        self.ui.toolButtonSnapshots.setDefaultAction(
            self.ui.actionReturnToAPreviousState)

        # connect actions
        self.ui.actionNewSession.triggered.connect(self._create_new_session)
        self.ui.actionOpenSession.triggered.connect(self._open_session)
        self.ui.actionConvertArdourSession.triggered.connect(
            self.util_script_launcher.convert_ardour_to_session)
        self.ui.actionConvertHydrogenRhNsm.triggered.connect(
            self.util_script_launcher.convert_ray_hack_to_nsm_hydrogen)
        self.ui.actionConvertJackMixerRhNsm.triggered.connect(
            self.util_script_launcher.convert_ray_hack_to_nsm_jack_mixer)
        self.ui.actionConvertToNsmFileFormat.triggered.connect(
            self.util_script_launcher.convert_to_nsm_file_format)
        self.ui.actionQuit.triggered.connect(self._action_quit_app)
        self.ui.actionSaveSession.triggered.connect(self._save_session)
        self.ui.actionCloseSession.triggered.connect(self._close_session)
        self.ui.actionAbortSession.triggered.connect(self._abort_session)
        self.ui.actionRenameSession.triggered.connect(
            self._rename_session_action)
        self.ui.actionRenameSession_2.triggered.connect(
            self._rename_session_action)
        self.ui.actionDuplicateSession.triggered.connect(
            self._duplicate_session)
        self.ui.actionDuplicateSession_2.triggered.connect(
            self._duplicate_session)
        self.ui.actionSaveTemplateSession.triggered.connect(
            self._save_template_session)
        self.ui.actionSaveTemplateSession_2.triggered.connect(
            self._save_template_session)
        self.ui.actionSessionNotes.triggered.connect(
            self._toggle_notes_visibility)
        self.ui.actionReturnToAPreviousState.triggered.connect(
            self._return_to_a_previous_state)
        self.ui.actionOpenSessionFolder.triggered.connect(
            self._open_file_manager)
        self.ui.actionAddApplication.triggered.connect(self._add_application)
        self.ui.actionAddExecutable.triggered.connect(self._add_executable)
        self.ui.actionShowJackPatchbay.toggled.connect(self._show_jack_patchbay)
        self.ui.actionKeepFocus.toggled.connect(self._toggle_keep_focus)
        self.ui.actionBookmarkSessionFolder.triggered.connect(
            self._bookmark_session_folder_toggled)
        self.ui.actionDesktopsMemory.triggered.connect(
            self._desktops_memory_toggled)
        self.ui.actionAutoSnapshot.triggered.connect(
            self._auto_snapshot_toggled)
        self.ui.actionSessionScripts.triggered.connect(
            self._session_scripts_toggled)
        self.ui.actionRememberOptionalGuiStates.triggered.connect(
            self._remember_optional_gui_states_toggled)
        self.ui.actionAboutRaySession.triggered.connect(self._about_raysession)
        self.ui.actionAboutQt.triggered.connect(QApplication.aboutQt)
        self.ui.actionOnlineManual.triggered.connect(self._online_manual)
        self.ui.actionInternalManual.triggered.connect(self._internal_manual)
        self.ui.actionDonate.triggered.connect(self.donate)
        self.ui.actionSystemTrayIconOptions.triggered.connect(
            self._open_systray_options)
        self.ui.actionPreferences.triggered.connect(
            self._show_preferences_dialog)

        self.ui.lineEditServerStatus.status_pressed.connect(
            self._status_bar_pressed)
        self.ui.stackedWidgetSessionName.name_changed.connect(
            self._rename_session_conditionnaly)
        self.ui.frameCurrentSession.frame_resized.connect(
            self._session_frame_resized)
        self.session.patchbay_manager.sg.full_screen_toggle_wanted.connect(
            self.toggle_scene_full_screen)
        self.session.patchbay_manager.sg.filters_bar_toggle_wanted.connect(
            self.toggle_patchbay_filters_bar)

        # set session menu
        self._session_menu = QMenu()
        self._session_menu.addAction(self.ui.actionSaveTemplateSession_2)
        self._session_menu.addAction(self.ui.actionDuplicateSession_2)
        self._session_menu.addAction(self.ui.actionRenameSession_2)
        self.ui.toolButtonSessionMenu.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup)
        self.ui.toolButtonSessionMenu.setMenu(self._session_menu)

        # set control menu
        self._control_menu = QMenu()
        self._control_menu.addAction(self.ui.actionShowMenuBar)
        self._control_menu.addAction(self.ui.actionToggleShowMessages)
        self._control_menu.addAction(self.ui.actionShowJackPatchbay)
        self._control_menu.addSeparator()
        self._control_menu.addAction(self.ui.actionKeepFocus)
        self._control_menu.addSeparator()
        self._control_menu.addAction(self.ui.actionBookmarkSessionFolder)
        self._control_menu.addAction(self.ui.actionAutoSnapshot)
        self._control_menu.addAction(self.ui.actionDesktopsMemory)
        self._control_menu.addAction(self.ui.actionSessionScripts)
        self._control_menu.addAction(self.ui.actionRememberOptionalGuiStates)
        self._control_menu.addSeparator()
        self._control_menu.addAction(self.ui.actionPreferences)

        control_tool_button = \
            self.ui.toolBar.widgetForAction(self.ui.actionControlMenu)
        
        if isinstance(control_tool_button, QToolButton):
            control_tool_button.setPopupMode(
                QToolButton.ToolButtonPopupMode.InstantPopup)
            control_tool_button.setMenu(self._control_menu)
            control_tool_button.setStyleSheet(
                "QToolButton{border: none} QToolButton::menu-indicator{image: none}")

        self.ui.toolButtonControl2.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup)
        self.ui.toolButtonControl2.setMenu(self._control_menu)

        # set favorites menu
        self._favorites_menu = QMenu(_translate('menu', 'Favorites'))
        self._favorites_menu.setIcon(QIcon(':scalable/breeze/star-yellow'))
        self.ui.toolButtonFavorites.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup)
        self.ui.toolButtonFavorites.setMenu(self._favorites_menu)
        self.ui.menuAdd.addMenu(self._favorites_menu)

        # set trash menu
        self._trash_menu = QMenu()
        self.ui.trashButton.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup)
        self.ui.trashButton.setMenu(self._trash_menu)

        # connect OSC signals from daemon
        sg = self.session.signaler
        sg.server_progress.connect(self._server_progress)
        sg.server_status_changed.connect(self._server_status_changed)
        sg.server_copying.connect(self._server_copying)
        sg.daemon_url_request.connect(self._show_daemon_url_window)
        sg.client_properties_state_changed.connect(
            self._client_properties_state_changed)

        # set spare icons if system icons not available
        dark = is_dark_theme(self)

        if self.ui.actionNewSession.icon().isNull():
            self.ui.actionNewSession.setIcon(
                ray_icon('folder-new', dark))
        if self.ui.actionOpenSession.icon().isNull():
            self.ui.actionOpenSession.setIcon(
                ray_icon('document-open', dark))

        if self.ui.actionControlMenu.icon().isNull():
            self.ui.actionControlMenu.setIcon(
                QIcon.fromTheme('configuration_section'))
            if self.ui.actionControlMenu.icon().isNull():
                self.ui.actionControlMenu.setIcon(
                    ray_icon('configure', dark))

        if self.ui.actionOpenSessionFolder.icon().isNull():
            self.ui.actionOpenSessionFolder.setIcon(
                ray_icon('system-file-manager', dark))

        if self.ui.actionAddApplication.icon().isNull():
            self.ui.actionAddApplication.setIcon(
                ray_icon('list-add', dark))

        if self.ui.actionAddExecutable.icon().isNull():
            self.ui.actionAddExecutable.setIcon(
                QIcon.fromTheme('system-run'))
            if self.ui.actionAddExecutable.icon().isNull():
                self.ui.actionAddExecutable.setIcon(
                    ray_icon('run-install'))

        self.ui.actionReturnToAPreviousState.setIcon(
            ray_icon('media-seek-backward', dark))

        self.ui.actionRememberOptionalGuiStates.setIcon(
            ray_icon('visibility', dark))
        self.ui.trashButton.setIcon(
            ray_icon('trash-empty', dark))
        if self.ui.trashButton.icon().isNull():
            self.ui.trashButton.setIcon(
                ray_icon('trash', dark))

        self.ui.actionDuplicateSession.setIcon(
            ray_icon('xml-node-duplicate', dark))
        self.ui.actionDuplicateSession_2.setIcon(
            ray_icon('xml-node-duplicate', dark))
        self.ui.actionSaveTemplateSession.setIcon(
            ray_icon('document-save-as-template', dark))
        self.ui.actionSaveTemplateSession_2.setIcon(
            ray_icon('document-save-as-template', dark))
        self.ui.actionCloseSession.setIcon(
            ray_icon('window-close', dark))
        self.ui.actionAbortSession.setIcon(
            ray_icon('list-remove', dark))
        self.ui.actionSaveSession.setIcon(
            ray_icon('document-save', dark))
        self.ui.toolButtonSaveSession.setIcon(
            ray_icon('document-save', dark))
        self.ui.actionSessionNotes.setIcon(
            ray_icon('notes', dark))
        self.ui.toolButtonNotes.setIcon(
            ray_icon('notes', dark))
        self.ui.actionDesktopsMemory.setIcon(
            ray_icon('view-list-icons', dark))
        self.ui.toolButtonSessionMenu.setIcon(
            ray_icon('application-menu', dark))
        self.ui.listWidget.set_session(self.session)
        self.ui.listWidget.currentItemChanged.connect(
            self._list_widget_item_changed)

        # concerns patchbay filters bar (activable with Ctrl+F)
        self.ui.framePatchbayFilters.set_patchbay_manager(
            self.session.patchbay_manager)
        self.ui.framePatchbayFilters.setVisible(False)
        filter_bar_shortcut = QShortcut('Ctrl+F', self)
        filter_bar_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        filter_bar_shortcut.activated.connect(
            self.toggle_patchbay_filters_bar)
        refresh_shortcut = QShortcut('Ctrl+R', self)
        refresh_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        refresh_shortcut.activated.connect(
            self.session.patchbay_manager.refresh)
        refresh_shortcut_alt = QShortcut('F5', self)
        refresh_shortcut_alt.setContext(Qt.ShortcutContext.ApplicationShortcut)
        refresh_shortcut_alt.activated.connect(
            self.session.patchbay_manager.refresh)

        # prevent to hide the session frame with session/messages splitter
        self.ui.splitterSessionVsMessages.setCollapsible(0, False)
        self.ui.splitterSessionVsMessages.splitterMoved.connect(
            self._splitter_session_vs_messages_moved)

        self._canvas_menu = None

        self.set_nsm_locked(CommandLineArgs.under_nsm)

        self._script_info_dialog: \
            dialogs.ScriptInfoDialog | None = None
        self._script_action_dialog: \
            dialogs.ScriptUserActionDialog | None = None

        # disable "keep focus" if daemon is not on this machine (it takes no
        # sense in this case)
        if not self.daemon_manager.is_local:
            self.ui.actionKeepFocus.setChecked(False)
            self.ui.actionKeepFocus.setEnabled(False)

        self.server_progress = 0.0
        self._progress_dialog_visible = False

        self.has_git = False

        self._were_visible_before_fullscreen = 0
        self._geom_before_fullscreen = None
        self._splitter_pos_before_fullscreen = [100, 100]
        self._fullscreen_patchbay = False
        self.hidden_maximized = False
        
        # systray icon and related
        self.wild_shutdown: bool = RS.settings.value(
            'wild_shutdown', False, type=bool)
        self.systray_mode = ray.Systray(
            RS.settings.value(
                'systray_mode', ray.Systray.SESSION_ONLY.value, type=int))
        self.reversed_systray_menu: bool = RS.settings.value(
            'reversed_systray_menu', False, type=bool)

        systray_icon = QIcon.fromTheme('raysession')
        if systray_icon.isNull():
            systray_icon = QIcon(':main_icon/48x48/raysession')

        self._systray = QSystemTrayIcon(self)
        self._systray.activated.connect(self._systray_activated)
        self._systray.setIcon(systray_icon)
        self._systray.setToolTip(ray.APP_TITLE)
        self._systray_menu = QMenu()
        self._systray_menu_add = QMenu(self._systray_menu)

        self._build_systray_menu()

        if (not CommandLineArgs.under_nsm
            and (self.systray_mode is ray.Systray.ALWAYS
                    or (self.systray_mode is ray.Systray.SESSION_ONLY
                        and self.session.server_status is not ray.ServerStatus.OFF))):
            self._systray.show()

        self.preferences_dialog: \
            Optional[preferences_dialog.PreferencesDialog] = None

        self._startup_time = time.time()

    def _splitter_session_vs_messages_moved(self, pos: int, index: int):
        self.ui.actionToggleShowMessages.setChecked(
            bool(pos < self.ui.splitterSessionVsMessages.height() -10))

    def _session_frame_resized(self):
        width = self.ui.frameCurrentSession.width()

        if width <= 283:
            # reorganize the window because session frame is not large
            self.ui.layoutSessionDown.setDirection(
                QBoxLayout.Direction.TopToBottom)

            # move down the session name label
            self.ui.layoutTopSession.removeWidget(
                self.ui.stackedWidgetSessionName)
            self.ui.layoutSessionDown.insertWidget(
                0, self.ui.stackedWidgetSessionName)

            # keep the file manager tool button at bottom left
            # of the session header
            self.ui.layoutSessionToolsLeft.removeWidget(
                self.ui.fullButtonFolder)
            self.ui.layoutSessionToolsRight.insertWidget(
                0, self.ui.fullButtonFolder)

            # set visible spacer between file manager button
            # and snapshots buttons
            self.ui.widgetPreRewindSpacer.setVisible(True)
        else:
            self.ui.layoutSessionDown.setDirection(
                QBoxLayout.Direction.LeftToRight)
            self.ui.layoutSessionDown.removeWidget(
                self.ui.stackedWidgetSessionName)
            self.ui.layoutTopSession.insertWidget(
                4, self.ui.stackedWidgetSessionName)
            self.ui.layoutSessionToolsRight.removeWidget(
                self.ui.fullButtonFolder)
            self.ui.layoutSessionToolsLeft.insertWidget(
                0, self.ui.fullButtonFolder)
            self.ui.widgetPreRewindSpacer.setVisible(False)

        add_app = self.ui.toolButtonAddApplication
        add_exe = self.ui.toolButtonAddExecutable

        if width >= 419:
            add_app.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            add_exe.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        elif width >= 350:
            add_app.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            add_exe.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonIconOnly)
        elif width > 283:
            add_app.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonIconOnly)
            add_exe.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonIconOnly)
        elif width > 260:
            add_app.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            add_exe.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        else:
            add_app.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            add_exe.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonIconOnly)

    @classmethod
    def to_daemon(cls, *args):
        server = GuiServerThread.instance()
        if server:
            server.to_daemon(*args)

    def _show_messages_widget(self, yesno: bool):
        sizes = [10, 0]
        if yesno:
            sizes = [30, 10]

        self.ui.splitterSessionVsMessages.setSizes(sizes)

    def _open_file_manager(self):
        self.to_daemon(r.session.OPEN_FOLDER)

    def change_systray_options(
            self, systray_mode: ray.Systray, wild_shutdown: bool,
            reversed_systray_menu: bool):        
        self.systray_mode = systray_mode
        self.wild_shutdown = wild_shutdown
        
        if reversed_systray_menu != self.reversed_systray_menu:
            self.reversed_systray_menu = reversed_systray_menu
            self._build_systray_menu()

        RS.settings.setValue('systray_mode', self.systray_mode.value)
        RS.settings.setValue('wild_shutdown', self.wild_shutdown)
        RS.settings.setValue('reversed_systray_menu',
                             self.reversed_systray_menu)

        if self.systray_mode is ray.Systray.OFF:
            self._systray.hide()
        elif self.systray_mode is ray.Systray.SESSION_ONLY:
            if self.session.server_status is ray.ServerStatus.OFF:
                self._systray.hide()
            else:
                self._systray.show()
        elif self.systray_mode is ray.Systray.ALWAYS:
            self._systray.show()

    def _open_systray_options(self):
        self._show_preferences_dialog()
        if self.preferences_dialog is not None:
            self.preferences_dialog.set_on_tab(
                preferences_dialog.PreferencesTab.SYSTRAY)

    def _raise_window(self):
        if self.mouse_is_inside:
            self.activateWindow()

    def _toggle_keep_focus(self, keep_focus: bool):
        self._keep_focus = keep_focus
        if self.daemon_manager.is_local:
            RS.settings.setValue('keepfocus', self._keep_focus)
        if not keep_focus:
            self._timer_raisewin.stop()

    def _set_option(self, option: ray.Option, state: bool):
        option_int = option.value
        if not state:
            option_int = - option_int
        self.to_daemon(r.server.SET_OPTION, option_int)

    def _bookmark_session_folder_toggled(self, state: bool):
        self._set_option(ray.Option.BOOKMARK_SESSION, state)

    def _desktops_memory_toggled(self, state: bool):
        self._set_option(ray.Option.DESKTOPS_MEMORY, state)

    def _auto_snapshot_toggled(self, state: bool):
        self._set_option(ray.Option.SNAPSHOTS, state)

    def _session_scripts_toggled(self, state: bool):
        self._set_option(ray.Option.SESSION_SCRIPTS, state)

    def _remember_optional_gui_states_toggled(self, state: bool):
        self._set_option(ray.Option.GUI_STATES, state)

    def _flash_open(self):
        for client in self.session.clients:
            if client.status is ray.ClientStatus.OPEN:
                client.widget.flash_if_open(self._flash_open_bool)

        self._flash_open_bool = not self._flash_open_bool

    def _action_quit_app(self):
        self._quit_app()

    def _quit_app(self) -> bool:
        if self.wild_shutdown and not CommandLineArgs.under_nsm:
            self.daemon_manager.disannounce()
            QTimer.singleShot(10, QApplication.quit)
            return True

        if self.session.is_running():
            self.show()
            dialog = dialogs.QuitAppDialog(self)
            dialog.exec()
            if not dialog.result():
                return False

        self._quit_app_now()
        return True

    def _quit_app_now(self):
        self.daemon_manager.stop()

    def _create_new_session(self):
        # from systray menu, better to show main window in the background
        # before open dialog
        self.show()

        dialog = dialogs.NewSessionDialog(self)
        dialog.exec()
        if not dialog.result():
            return

        session_short_path = dialog.get_session_short_path()
        template_name = dialog.get_template_name()

        RS.settings.setValue('last_used_template', template_name)

        if not template_name:
            self.to_daemon(r.server.NEW_SESSION, session_short_path)
            return

        if template_name.startswith('///'):
            if template_name == '///' + ray.FACTORY_SESSION_TEMPLATES[1]:
                if not RS.is_hidden(RS.HD_JackConfigScript):
                    # display jack_config_script info dialog
                    # and manage ray-jack_checker auto_start

                    session_path = \
                        Path(CommandLineArgs.session_root) / session_short_path
                    dialog = dialogs.JackConfigInfoDialog(
                        self, session_path)
                    dialog.exec()
                    if not dialog.result():
                        return

                    RS.set_hidden(
                        RS.HD_JackConfigScript, dialog.not_again_value())

                    autostart_jack_checker = dialog.auto_start_value()
                    action = 'set_jack_checker_autostart'
                    if not autostart_jack_checker:
                        action = 'unset_jack_checker_autostart'

                    self.to_daemon(r.server.EXOTIC_ACTION, action)

            elif template_name == '///' + ray.FACTORY_SESSION_TEMPLATES[2]:
                if not RS.is_hidden(RS.HD_SessionScripts):
                    # display session scripts info dialog
                    session_path = \
                        Path(CommandLineArgs.session_root) / session_short_path

                    dialog = dialogs.SessionScriptsInfoDialog(
                        self, session_path)
                    dialog.exec()
                    if not dialog.result():
                        return

                    RS.set_hidden(RS.HD_SessionScripts, dialog.not_again_value())

        self.to_daemon(r.server.NEW_SESSION, session_short_path, template_name)

    def _open_session(self):
        # from systray, better to show main window in the background
        # before open dialog
        self.show()

        dialog = open_session_dialog.OpenSessionDialog(self)
        dialog.exec()
        if not dialog.result():
            return

        session_name = dialog.get_selected_session()
        if session_name is None:
            return
        save_previous = int(dialog.want_to_save_previous())

        self.to_daemon(r.server.OPEN_SESSION, session_name, save_previous)

    def _close_session(self):
        self.to_daemon(r.session.CLOSE)

    def _abort_session(self):
        self.show()
        dialog = dialogs.AbortSessionDialog(self)
        dialog.exec()

        if dialog.result():
            self.to_daemon(r.session.ABORT)

    def _rename_session_action(self):
        if not self.session.is_renameable:
            QMessageBox.information(
                self,
                _translate("rename_session", "Rename Session"),
                _translate("rename_session",
                           "<p>In order to rename current session,<br>"
                           + "please first stop all clients.<br>"
                           + "then, double click on session name.</p>"))
            return

        self.ui.stackedWidgetSessionName.toggle_edit()

    def _duplicate_session(self):
        dialog = dialogs.NewSessionDialog(self, True)
        dialog.exec()
        if not dialog.result():
            return

        session_name = dialog.get_session_short_path()
        self.to_daemon(r.session.DUPLICATE, session_name)

    def _save_template_session(self):
        dialog = dialogs.SaveTemplateSessionDialog(self)
        dialog.exec()
        if not dialog.result():
            return

        session_template_name = dialog.get_template_name()
        self.to_daemon(r.session.SAVE_AS_TEMPLATE, session_template_name)

    def _return_to_a_previous_state(self):
        dialog = snapshots_dialog.SessionSnapshotsDialog(self)
        dialog.exec()
        if not dialog.result():
            return

        snapshot = dialog.get_selected_snapshot()
        if snapshot is None:
            return
        self.to_daemon(r.session.OPEN_SNAPSHOT, snapshot)

    def _about_raysession(self):
        dialog = dialogs.AboutRaySessionDialog(self)
        dialog.exec()

    def _online_manual(self):
        short_locale = 'en'
        locale_str = QLocale.system().name()
        if (len(locale_str) > 2 and '_' in locale_str
                and locale_str[:2] in ('en', 'fr', 'de')):
            short_locale = locale_str[:2]

        QDesktopServices.openUrl(
            QUrl('http://raysession.tuxfamily.org/%s/manual.html'
                 % short_locale))

    def _internal_manual(self):
        short_locale = 'en'
        manual_dir = get_code_root() / 'manual'
        locale_str = QLocale.system().name()
        manual_file = manual_dir / locale_str[:2] / 'manual.html'
        
        if (len(locale_str) > 2 and '_' in locale_str
                and manual_file.is_file()):
            short_locale = locale_str[:2]

        QDesktopServices.openUrl(
            QUrl(str(manual_dir / short_locale / 'manual.html')))

    def _save_session(self):
        self.to_daemon(r.session.SAVE)

    def _toggle_notes_visibility(self):
        if (self.notes_dialog is None or not self.notes_dialog.isVisible()):
            self.to_daemon(r.session.SHOW_NOTES)
        else:
            self.to_daemon(r.session.HIDE_NOTES)

    def _add_application(self):
        if self.session.server_status in (
                ray.ServerStatus.CLOSE,
                ray.ServerStatus.OFF):
            return

        dialog = add_application_dialog.AddApplicationDialog(self)
        dialog.exec()
        dialog.save_check_boxes()

        if dialog.result():
            template_name, factory = dialog.get_selected_template()
            unique_id = dialog.get_selected_unique_id()
            self.to_daemon(
                r.session.ADD_CLIENT_TEMPLATE,
                int(factory),
                template_name,
                'start',
                unique_id)

    def _add_executable(self):
        if self.session.server_status in (
                ray.ServerStatus.CLOSE,
                ray.ServerStatus.OFF):
            return

        dialog = dialogs.NewExecutableDialog(self)
        dialog.exec()
        if not dialog.result():
            return

        command, auto_start, bool_ray_hack, \
            prefix_mode, prefix, client_id, jack_naming = dialog.get_selection()

        self.to_daemon(
            r.session.ADD_EXEC, command, int(auto_start),
            int(bool_ray_hack), prefix_mode, prefix, client_id, int(jack_naming))

    def _show_jack_patchbay(self, yesno: bool):
        self.save_window_settings(
            UI_PATCHBAY_HIDDEN if yesno else UI_PATCHBAY_SHOWN)

        if self._canvas_menu is not None:
            self._canvas_menu.setVisible(yesno)

        rect = self.geometry()
        x = rect.x()
        y = rect.y()
        height = rect.height()

        if yesno:
            self.to_daemon(r.server.ASK_FOR_PATCHBAY, '')

            patchbay_geom = RS.settings.value('MainWindow/patchbay_geometry')
            sizes = RS.settings.value('MainWindow/splitter_canvas_sizes')

            if patchbay_geom:
                self.restoreGeometry(patchbay_geom)
            else:
                self.setGeometry(x, y, max(rect.width(), 1024), height)

            if sizes:
                self.ui.splitterMainVsCanvas.setSizes([int(s) for s in sizes])

        else:
            self.session.patchbay_manager.disannounce()

            if self.isMaximized():
                self.showNormal()

            geom = RS.settings.value('MainWindow/geometry')
            if geom:
                self.restoreGeometry(geom)
            else:
                self.setGeometry(x, y, 460, height)
            self.ui.splitterMainVsCanvas.setSizes([100, 0])
            
            self._patchbay_tools = None

        self.ui.toolBarTransport.setVisible(yesno)
        self.ui.toolBarJack.setVisible(yesno)
        self.ui.toolBarCanvas.setVisible(yesno)

        self.ui.graphicsView.setVisible(yesno)
        self.ui.framePatchbayFilters.setVisible(False)
        self.ui.splitterMainVsCanvas.set_active(yesno)
        self.ui.listWidget.patchbay_is_shown(yesno)

    def _status_bar_pressed(self):
        status = self.session.server_status

        if status not in (
                ray.ServerStatus.PRECOPY,
                ray.ServerStatus.COPY,
                ray.ServerStatus.SNAPSHOT,
                ray.ServerStatus.OUT_SNAPSHOT,
                ray.ServerStatus.WAIT_USER):
            return

        if status in (ray.ServerStatus.PRECOPY, ray.ServerStatus.COPY):
            if not self.server_copying:
                return

            dialog = dialogs.AbortServerCopyDialog(self)
            dialog.exec()

            if not dialog.result():
                return

            self.to_daemon(r.server.ABORT_COPY)

        elif status in (ray.ServerStatus.SNAPSHOT,
                        ray.ServerStatus.OUT_SNAPSHOT):
            self._show_snapshot_progress_dialog()

        elif status is ray.ServerStatus.WAIT_USER:
            dialog = dialogs.WaitingCloseUserDialog(self)
            dialog.exec()

    def _rename_session_conditionnaly(self, new_session_name):
        self.to_daemon(r.session.RENAME, new_session_name)

    def _show_snapshot_progress_dialog(self):
        if self._progress_dialog_visible:
            return

        self._progress_dialog_visible = True

        dialog = dialogs.SnapShotProgressDialog(self)
        dialog.server_progress(self.server_progress)
        dialog.exec()

        self._progress_dialog_visible = False

        if not dialog.result():
            return

        self.to_daemon(r.server.ABORT_SNAPSHOT)

    def _show_daemon_url_window(self, err_code, ex_url=''):
        if not CommandLineArgs.under_nsm:
            server = GuiServerThread.instance()
            if server and are_on_same_machine(server.url, ex_url):
                # here we are in the case daemon and GUI have not the same VERSION
                # If a session is running, inform user
                # else, just stop the daemon and quit
                
                session_path = subprocess.run(
                    ['ray_control', 'get_session_path'], capture_output=True)
                if session_path.stdout:
                    dialog = dialogs.WrongVersionLocalDialog(self)
                    dialog.exec()
                    if dialog.result():
                        subprocess.run(['ray_control', 'quit'])
                        self._quit_app_now()
                    
                else:
                    subprocess.run(['ray_control', 'quit'])
                    self._quit_app_now()
                return
        
        dialog = dialogs.DaemonUrlDialog(self, err_code, ex_url)
        dialog.exec()
        if not dialog.result():
            if (CommandLineArgs.under_nsm
                    and self.daemon_manager.launched_before):
                QApplication.quit()
            return

        new_url = dialog.get_url()

        tried_urls = ray.get_list_in_settings(RS.settings, 'network/tried_urls')
        if new_url not in tried_urls:
            tried_urls.append(new_url)

        RS.settings.setValue('network/tried_urls', tried_urls)
        RS.settings.setValue('network/last_tried_url', new_url)

        self.session.signaler.daemon_url_changed.emit(new_url)

    def _client_properties_state_changed(self, client_id: str, visible: bool):
        self.ui.listWidget.client_properties_state_changed(
            client_id, visible)

    def _server_progress(self, progress: float):
        self.server_progress = progress
        self.ui.lineEditServerStatus.set_progress(progress)

    def _server_copying(self, copying: bool):
        self.server_copying = copying
        self._server_status_changed(self.session.server_status)

    def _server_status_changed(self, server_status: ray.ServerStatus):
        self.session.update_server_status(server_status)

        self.ui.lineEditServerStatus.setText(
            server_status_string(server_status))
        self.ui.frameCurrentSession.setEnabled(
            bool(server_status is not ray.ServerStatus.OFF))

        if self.systray_mode is ray.Systray.SESSION_ONLY:
            if server_status is ray.ServerStatus.OFF:
                self._systray.hide()
            else:
                self._systray.show()

        if server_status in (ray.ServerStatus.SNAPSHOT,
                             ray.ServerStatus.OUT_SNAPSHOT):
            self._timer_snapshot.start()
        elif self._timer_snapshot.isActive():
            self._timer_snapshot.stop()

        if server_status is ray.ServerStatus.COPY:
            self.ui.actionSaveSession.setEnabled(False)
            self.ui.actionCloseSession.setEnabled(False)
            self.ui.actionAbortSession.setEnabled(False)
            self.ui.actionReturnToAPreviousState.setEnabled(False)
            return

        if server_status is ray.ServerStatus.PRECOPY:
            self.ui.actionSaveSession.setEnabled(False)
            self.ui.actionCloseSession.setEnabled(False)
            self.ui.actionAbortSession.setEnabled(True)
            self.ui.actionDuplicateSession.setEnabled(False)
            self.ui.actionDuplicateSession_2.setEnabled(False)
            self.ui.actionSaveTemplateSession.setEnabled(False)
            self.ui.actionSaveTemplateSession_2.setEnabled(False)
            self.ui.actionReturnToAPreviousState.setEnabled(False)
            self.ui.actionAddApplication.setEnabled(False)
            self.ui.actionAddExecutable.setEnabled(False)
            self.ui.actionOpenSessionFolder.setEnabled(True)
            self.ui.actionSessionNotes.setEnabled(False)
            return

        close_or_off = bool(
            server_status in (
                ray.ServerStatus.CLOSE,
                ray.ServerStatus.WAIT_USER,
                ray.ServerStatus.OUT_SAVE,
                ray.ServerStatus.OUT_SNAPSHOT,
                ray.ServerStatus.OFF))
        ready = bool(server_status is ray.ServerStatus.READY)

        self.ui.actionSaveSession.setEnabled(ready)
        self.ui.actionCloseSession.setEnabled(ready)
        self.ui.actionAbortSession.setEnabled(
            not bool(server_status in (ray.ServerStatus.CLOSE,
                                       ray.ServerStatus.OFF)))
        self.ui.actionDuplicateSession.setEnabled(not close_or_off)
        self.ui.actionDuplicateSession_2.setEnabled(not close_or_off)
        self.ui.actionReturnToAPreviousState.setEnabled(not close_or_off)
        self.ui.actionRenameSession.setEnabled(ready)
        self.ui.actionRenameSession_2.setEnabled(ready)
        self.ui.actionSaveTemplateSession.setEnabled(not close_or_off)
        self.ui.actionSaveTemplateSession_2.setEnabled(not close_or_off)
        self.ui.actionAddApplication.setEnabled(not close_or_off)
        self.ui.actionAddExecutable.setEnabled(not close_or_off)
        self.ui.toolButtonFavorites.setEnabled(
            bool(self.session.favorite_list and not close_or_off))
        self._favorites_menu.setEnabled(
            bool(self.session.favorite_list and not close_or_off))
        self.ui.actionOpenSessionFolder.setEnabled(
            bool(server_status is not ray.ServerStatus.OFF))
        self.ui.actionSessionNotes.setEnabled(
            bool(server_status is not ray.ServerStatus.OFF))

        self.ui.stackedWidgetSessionName.set_editable(
            ready and self.session.is_renameable)

        self.ui.trashButton.setEnabled(bool(self.session.trashed_clients)
                                       and not close_or_off)

        self._systray_menu_add.setEnabled(not close_or_off)

        if (CommandLineArgs.under_nsm
                and not CommandLineArgs.out_daemon
                and ready
                and self.session.is_renameable):
            self.ui.stackedWidgetSessionName.set_on_edit()

        if self.server_copying:
            self.ui.actionSaveSession.setEnabled(False)
            self.ui.actionCloseSession.setEnabled(False)

        if CommandLineArgs.under_nsm:
            self.ui.actionNewSession.setEnabled(False)
            self.ui.actionOpenSession.setEnabled(False)
            self.ui.actionDuplicateSession.setEnabled(False)
            self.ui.actionCloseSession.setEnabled(False)
            self.ui.actionAbortSession.setEnabled(False)
            self.ui.menuRecentSessions.setEnabled(False)

        if server_status is ray.ServerStatus.OFF:
            if self.terminate_request:
                self.daemon_manager.stop()

        if server_status is ray.ServerStatus.WAIT_USER:
            if not RS.is_hidden(RS.HD_WaitCloseUser):
                dialog = dialogs.WaitingCloseUserDialog(self)
                dialog.exec()

    def _build_systray_menu(self):
        is_shown = self._systray.isVisible()
        self._systray.hide()
        self._systray_menu.clear()
        self._systray_menu_add.clear()

        del self._systray_menu
        del self._systray_menu_add

        self._systray_menu = QMenu()
        self._systray_menu_add = QMenu(
            _translate('menu', 'Add'), self._systray_menu)
        self._systray_menu_add.addMenu(self._favorites_menu)
        self._systray_menu_add.addAction(self.ui.actionAddApplication)
        self._systray_menu_add.addAction(self.ui.actionAddExecutable)
        self._systray_menu_add.setIcon(QIcon.fromTheme('list-add'))
        self._systray_menu_add.setEnabled(
            self.session.server_status not in
                (ray.ServerStatus.OFF, ray.ServerStatus.CLOSE,
                 ray.ServerStatus.WAIT_USER, ray.ServerStatus.OUT_SAVE,
                 ray.ServerStatus.OUT_SNAPSHOT))

        if self.reversed_systray_menu:
            self._systray_menu.addAction(self.ui.actionQuit)
            self._systray_menu.addSeparator()
            self._systray_menu.addAction(self.ui.actionSystemTrayIconOptions)
            self._systray_menu.addSeparator()
            self._systray_menu.addMenu(self.ui.menuRecentSessions)
            self._systray_menu.addAction(self.ui.actionOpenSession)
            self._systray_menu.addAction(self.ui.actionNewSession)
            self._systray_menu.addSeparator()
            self._systray_menu.addAction(self.ui.actionAbortSession)
            self._systray_menu.addAction(self.ui.actionCloseSession)
            self._systray_menu.addMenu(self._systray_menu_add)
            self._systray_menu.addAction(self.ui.actionSaveSession)
        else:
            self._systray_menu.addAction(self.ui.actionSaveSession)
            self._systray_menu.addMenu(self._systray_menu_add)
            self._systray_menu.addAction(self.ui.actionCloseSession)
            self._systray_menu.addAction(self.ui.actionAbortSession)
            self._systray_menu.addSeparator()
            self._systray_menu.addAction(self.ui.actionNewSession)
            self._systray_menu.addAction(self.ui.actionOpenSession)
            self._systray_menu.addMenu(self.ui.menuRecentSessions)
            self._systray_menu.addSeparator()
            self._systray_menu.addAction(self.ui.actionSystemTrayIconOptions)
            self._systray_menu.addSeparator()
            self._systray_menu.addAction(self.ui.actionQuit)
        self._systray.setContextMenu(self._systray_menu)

        if is_shown:
            self._systray.show()

    def _systray_activated(self, reason: QSystemTrayIcon.ActivationReason):
        if reason not in (QSystemTrayIcon.ActivationReason.Trigger,
                          QSystemTrayIcon.ActivationReason.DoubleClick):
            return

        wayland = bool(ray.get_window_manager() is ray.WindowManager.WAYLAND)

        if self.isMinimized():
            if self.hidden_maximized:
                self.showMaximized()
            else:
                self.showNormal()
            if not wayland:
                self.activateWindow()
        elif self.isHidden():
            self.show()
            if not wayland:
                self.activateWindow()
        elif self.isActiveWindow():
            self.hide()
        elif wayland:
            self.hide()
        else:
            self.activateWindow()

    ###FUNCTIONS RELATED TO SIGNALS FROM OSC SERVER#######

    def toggle_scene_full_screen(self):
        VISIBLE_MAXIMIZED = 0x1
        VISIBLE_MENUBAR = 0x2

        if self._fullscreen_patchbay:
            for toolbar in (self.ui.toolBar, self.ui.toolBarTransport,
                            self.ui.toolBarJack, self.ui.toolBarCanvas):
                toolbar.setVisible(True)
            
            if self._were_visible_before_fullscreen & VISIBLE_MENUBAR:
                self.ui.menuBar.setVisible(True)

            if self._were_visible_before_fullscreen & VISIBLE_MAXIMIZED:
                self.showNormal()
                self.showMaximized()
            else:
                self.showNormal()
                if self._geom_before_fullscreen is not None:
                    self.setGeometry(self._geom_before_fullscreen)

            self.ui.splitterMainVsCanvas.setSizes(
                self._splitter_pos_before_fullscreen)

            self._fullscreen_patchbay = False
        else:
            self._were_visible_before_fullscreen = \
                VISIBLE_MAXIMIZED * int(self.isMaximized()) \
                + VISIBLE_MENUBAR * int(self.ui.menuBar.isVisible())

            self._geom_before_fullscreen = self.geometry()

            self.ui.menuBar.setVisible(False)

            for toolbar in (self.ui.toolBar, self.ui.toolBarTransport,
                            self.ui.toolBarJack, self.ui.toolBarCanvas):
                toolbar.setVisible(False)

            self._splitter_pos_before_fullscreen = \
                self.ui.splitterMainVsCanvas.sizes()
            self.ui.splitterMainVsCanvas.setSizes([0, 100])
            self._fullscreen_patchbay = True
            self.showFullScreen()

    def add_patchbay_tools(
            self, tools_widget: PatchbayToolsWidget, canvas_menu):
        self._patchbay_tools = tools_widget
        self._patchbay_tools.change_text_with_icons(
            TextWithIcons.by_name(
                RS.settings.value('tool_bar/text_with_icons', 'AUTO')))
        self._patchbay_tools.set_tool_bars(
            self.ui.toolBar, self.ui.toolBarTransport,
            self.ui.toolBarJack, self.ui.toolBarCanvas)
        
        default_disp_wdg = (
            ToolDisplayed.ZOOM_SLIDER
            | ToolDisplayed.HIDDENS_BOX
            | ToolDisplayed.TRANSPORT_PLAY_STOP
            | ToolDisplayed.BUFFER_SIZE
            | ToolDisplayed.SAMPLERATE
            | ToolDisplayed.XRUNS
            | ToolDisplayed.DSP_LOAD)
        
        default_disp_wdg = default_disp_wdg.filtered_by_string(
            RS.settings.value('tool_bar/jack_elements', '', type=str))
        
        # if not default_disp_wdg & ToolDisplayed.PORT_TYPES_VIEW:
        #     RS.settings.setValue(
        #         'Canvas/default_port_types_view',
        #         PortTypesViewFlag.ALL.value)

        tools_widget.change_tools_displayed(default_disp_wdg)

        self._canvas_menu = self.ui.menuBar.addMenu(canvas_menu)

    def create_client_widget(self, client):
        return self.ui.listWidget.create_client_widget(client)

    def re_create_list_widget(self):
        # this function shouldn't exist,
        # it is a workaround for a bug with python-qt.
        # (when reorder widgets sometimes one widget is totally hidden
        # until user resize the window)
        # It has to be modified when ui_raysession is modified.

        self.ui.listWidget.clear()
        self.ui.verticalLayout.removeWidget(self.ui.listWidget)
        del self.ui.listWidget
        self.ui.listWidget = list_widget_clients.ListWidgetClients(
            self.ui.frameCurrentSession)
        self.ui.listWidget.setAcceptDrops(True)
        self.ui.listWidget.setStyleSheet("QFrame{border:none}")
        self.ui.listWidget.setDragEnabled(True)
        self.ui.listWidget.setDragDropMode(
            QAbstractItemView.DragDropMode.InternalMove)
        self.ui.listWidget.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.ui.listWidget.setUniformItemSizes(False)
        self.ui.listWidget.setBatchSize(80)
        self.ui.listWidget.setObjectName("listWidget")
        self.ui.listWidget.set_session(self.session)
        self.ui.verticalLayout.addWidget(self.ui.listWidget)
        self.ui.listWidget.currentItemChanged.connect(
            self._list_widget_item_changed)

    def set_nsm_locked(self, nsm_locked: bool):
        self.ui.actionNewSession.setEnabled(not nsm_locked)
        self.ui.actionOpenSession.setEnabled(not nsm_locked)
        self.ui.actionDuplicateSession.setEnabled(not nsm_locked)
        self.ui.actionCloseSession.setEnabled(not nsm_locked)
        self.ui.actionAbortSession.setEnabled(not nsm_locked)

        self.ui.toolBar.setVisible(True)
        self.ui.toolButtonNoRole.setVisible(nsm_locked)
        self.ui.toolButtonAbortSession.setVisible(not nsm_locked)
        self.ui.closeButton.setVisible(not nsm_locked)
        self.ui.toolButtonControl2.setVisible(nsm_locked)

        self.ui.stackedWidgetSessionName.set_editable(
            nsm_locked and not CommandLineArgs.out_daemon)
        self.ui.actionRenameSession.setEnabled(
            nsm_locked and not CommandLineArgs.out_daemon)
        self.ui.actionRenameSession_2.setEnabled(
            nsm_locked and not CommandLineArgs.out_daemon)

        frame_style_sheet = "SessionFrame{border-radius:4px;"

        if nsm_locked and CommandLineArgs.out_daemon:
            frame_style_sheet += "background-color: rgba(100, 181, 100, 35)}"
        elif nsm_locked:
            frame_style_sheet += "background-color: rgba(100, 100, 181, 35)}"
        else:
            frame_style_sheet += "background-color: rgba(127, 127, 127, 35)}"

        self.ui.frameCurrentSession.setStyleSheet(frame_style_sheet)

    def _list_widget_item_changed(
            self, current: list_widget_clients.ClientItem, previous):
        if current is None:
            return

        self.session.patchbay_manager.select_client_box(
            current.widget.client.jack_client_name)

    def set_daemon_options(self, options: ray.Option):
        self.ui.actionBookmarkSessionFolder.setChecked(
            ray.Option.BOOKMARK_SESSION in options)
        self.ui.actionDesktopsMemory.setChecked(
            ray.Option.DESKTOPS_MEMORY in options)
        self.ui.actionAutoSnapshot.setChecked(
            ray.Option.SNAPSHOTS in options)
        self.ui.actionSessionScripts.setChecked(
            ray.Option.SESSION_SCRIPTS in options)
        self.ui.actionRememberOptionalGuiStates.setChecked(
            ray.Option.GUI_STATES in options)

        has_wmctrl = ray.Option.HAS_WMCTRL in options
        self.ui.actionDesktopsMemory.setEnabled(has_wmctrl)
        if has_wmctrl:
            self.ui.actionDesktopsMemory.setText(
                _translate('actions', 'Desktops Memory'))

        has_git = ray.Option.HAS_GIT in options
        self.ui.actionAutoSnapshot.setEnabled(has_git)
        self.ui.actionReturnToAPreviousState.setVisible(has_git)
        self.ui.toolButtonSnapshots.setVisible(has_git)
        if has_git:
            self.ui.actionAutoSnapshot.setText(
                _translate('actions', 'Auto Snapshot at Save'))

        self.has_git = has_git

    def donate(self, display_no_again=False):
        dialog = dialogs.DonationsDialog(self, display_no_again)
        dialog.exec()

    def _show_preferences_dialog(self):
        if self.preferences_dialog is None:
            self.preferences_dialog = preferences_dialog.PreferencesDialog(self)
        
        self.preferences_dialog.show()

    def edit_notes(self, close=False):
        icon_str = 'notes'
        if close:
            if self.session.notes:
                icon_str = 'notes-nonempty'
            if self.notes_dialog is not None and self.notes_dialog.isVisible():
                self.notes_dialog.close()
        else:
            if self.notes_dialog is None:
                self.notes_dialog = dialogs.SessionNotesDialog(self)
            self.notes_dialog.show()
            icon_str = 'notes-editing'

        self.ui.actionSessionNotes.setIcon(
            ray_icon(icon_str, is_dark_theme(self)))

    def stop_client(self, client_id):
        client = self.session.get_client(client_id)
        if not client:
            return

        if client.check_last_save:
            if (client.protocol is ray.Protocol.RAY_HACK
                    and client.ray_hack is not None
                    and client.ray_hack.relevant_no_save_level()):
                dialog = dialogs.StopClientNoSaveDialog(self, client_id)
                dialog.exec()
                if not dialog.result():
                    return

            elif client.status is ray.ClientStatus.READY:
                if client.has_dirty:
                    if client.dirty_state:
                        dialog = dialogs.StopClientDialog(self, client_id)
                        dialog.exec()
                        if not dialog.result():
                            return

                # last save (or start) more than 60 seconds ago
                elif (time.time() - client.last_save) >= 60:
                    dialog = dialogs.StopClientDialog(self, client_id)
                    dialog.exec()
                    if not dialog.result():
                        return

        self.to_daemon(r.client.STOP, client_id)

    def remove_client(self, client_id: str):
        self.ui.listWidget.remove_client_widget(client_id)

    def abort_copy_client(self, client_id: str):
        if not self.server_copying:
            return

        client = self.session.get_client(client_id)
        if not client or client.status not in (
                ray.ClientStatus.COPY, ray.ClientStatus.PRECOPY):
            return

        dialog = dialogs.AbortClientCopyDialog(self, client_id)
        dialog.exec()

        if not dialog.result():
            return

        self.to_daemon(r.server.ABORT_COPY)

    def client_status_changed(self, client_id: str, status: ray.ClientStatus):
        # launch/stop flashing status if 'open'
        for client in self.session.clients:
            if client.status is ray.ClientStatus.OPEN:
                if not self._timer_flicker_open.isActive():
                    self._timer_flicker_open.start()
                break
        else:
            self._timer_flicker_open.stop()

        # launch/stop timer_raisewin if keep focus
        if self._keep_focus:
            for client in self.session.clients:
                if client.status is ray.ClientStatus.OPEN:
                    if not self._timer_raisewin.isActive():
                        self._timer_raisewin.start()
                    break
            else:
                self._timer_raisewin.stop()
                if status is ray.ClientStatus.READY:
                    self._raise_window()

    def print_message(self, message: str):
        self.ui.textEditMessages.appendPlainText(
            time.strftime("%H:%M:%S") + '  ' + message)

    def rename_session(self, session_name: str, session_path: str):
        if session_name:
            self.setWindowTitle('%s - %s' % (ray.APP_TITLE, session_name))
            self.ui.stackedWidgetSessionName.set_text(session_name)
            if self.notes_dialog is not None:
                self.notes_dialog.update_session()
        else:
            self.setWindowTitle(ray.APP_TITLE)
            self.ui.stackedWidgetSessionName.set_text(
                _translate('main view', 'No Session Loaded'))
            if self.notes_dialog is not None:
                self.notes_dialog.hide()

        self.update_recent_sessions_menu()

    def set_session_name_editable(self, set_edit: bool):
        self.ui.stackedWidgetSessionName.set_editable(set_edit)

    def update_recent_sessions_menu(self):
        self.ui.menuRecentSessions.clear()

        for sess in self.session.recent_sessions:
            sess_action = self.ui.menuRecentSessions.addAction(sess)
            if sess_action is None:
                continue

            if sess == self.session.get_short_path():
                # disable running session
                sess_action.setEnabled(False)

            sess_action.setData(sess)
            sess_action.triggered.connect(self.launch_recent_session)

        self.ui.menuRecentSessions.setEnabled(bool(self.session.recent_sessions))
        self._build_systray_menu()

        # here we start the startup dialog
        # FIXME - not a good place
        if (not RS.is_hidden(RS.HD_StartupRecentSessions)
                and time.time() - self._startup_time < 5
                and self.session.recent_sessions
                and self.session.server_status is ray.ServerStatus.OFF):
            # ahah, dirty way to prevent a dialog once again
            self._startup_time -= 5

            dialog = dialogs.StartupDialog(self)
            dialog.exec()

            if dialog.result():
                self.to_daemon(r.server.OPEN_SESSION,
                               dialog.get_selected_session())
            elif dialog.get_clicked_action() == dialog.ACTION_NEW:
                self._create_new_session()
            elif dialog.get_clicked_action() == dialog.ACTION_OPEN:
                self._open_session()

            if dialog.not_again_value():
                RS.set_hidden(RS.HD_StartupRecentSessions)

    def error_message(self, message: str):
        error_dialog = dialogs.ErrorDialog(self, message)
        error_dialog.exec()

    def opening_nsm_session(self):
        if RS.is_hidden(RS.HD_OpenNsmSession):
            return

        dialog = dialogs.OpenNsmSessionInfoDialog(self)
        dialog.exec()

    def trash_add(self, trashed_client: TrashedClient):
        act_x_trashed = self._trash_menu.addAction(
            get_app_icon(trashed_client.icon, self),
            trashed_client.prettier_name())
        act_x_trashed.setData(trashed_client.client_id)
        act_x_trashed.triggered.connect(self.show_client_trash_dialog)

        self.ui.trashButton.setEnabled(
            bool(not self.session.server_status in (
                ray.ServerStatus.OFF, ray.ServerStatus.OUT_SAVE,
                ray.ServerStatus.WAIT_USER, ray.ServerStatus.OUT_SNAPSHOT,
                ray.ServerStatus.CLOSE)))

        return act_x_trashed

    def trash_remove(self, menu_action: QAction):
        self._trash_menu.removeAction(menu_action)

        if not self.session.trashed_clients:
            self.ui.trashButton.setEnabled(False)

    def trash_clear(self):
        self._trash_menu.clear()
        self.ui.trashButton.setEnabled(False)

    @Slot()
    def launch_recent_session(self):
        try:
            session_name = str(self.sender().data()) # type:ignore
        except BaseException:
            return

        self.to_daemon(r.server.OPEN_SESSION, session_name)

    @Slot()
    def show_client_trash_dialog(self):
        try:
            client_id = str(self.sender().data()) # type:ignore
        except BaseException:
            return

        for trashed_client in self.session.trashed_clients:
            if trashed_client.client_id == client_id:
                break
        else:
            return

        dialog = dialogs.ClientTrashDialog(self, trashed_client)
        dialog.exec()
        if not dialog.result():
            return

        self.to_daemon(r.trashed_client.RESTORE, client_id)

    @Slot()
    def launch_favorite(self):
        template_name, factory = self.sender().data() # type:ignore
        self.to_daemon(r.session.ADD_CLIENT_TEMPLATE,
                       int(factory), template_name, 'start', '')

    def toggle_patchbay_filters_bar(self):
        if not self.ui.graphicsView.isVisible():
            return

        self.ui.framePatchbayFilters.setVisible(
            not self.ui.framePatchbayFilters.isVisible())

    def set_patchbay_filter_text(self, text: str):
        ''' used by client widget to find patchbay boxes '''
        self.ui.framePatchbayFilters.setVisible(True)
        self.ui.framePatchbayFilters.set_filter_text(text)

    def update_favorites_menu(self):
        self._favorites_menu.clear()

        enable = bool(
            self.session.favorite_list
            and not self.session.server_status in (
                ray.ServerStatus.OFF, ray.ServerStatus.CLOSE,
                ray.ServerStatus.OUT_SAVE, ray.ServerStatus.OUT_SNAPSHOT))

        self.ui.toolButtonFavorites.setEnabled(enable)

        for favorite in self.session.favorite_list:
            act_app = self._favorites_menu.addAction(
                get_app_icon(favorite.icon, self), favorite.name)
            act_app.setData([favorite.name, favorite.factory])
            act_app.triggered.connect(self.launch_favorite)

        self._favorites_menu.setEnabled(
            bool(enable and self.session.favorite_list))
        self._build_systray_menu()

    def show_script_info(self, text: str):
        if self._script_info_dialog is None:
            self._script_info_dialog = dialogs.ScriptInfoDialog(self)
        self._script_info_dialog.set_info_label(text)
        self._script_info_dialog.show()

    def hide_script_info_dialog(self):
        if self._script_info_dialog is not None:
            self._script_info_dialog.close()
        self._script_info_dialog = None

    def show_script_user_action_dialog(self, text: str):
        if self._script_action_dialog is not None:
            self._script_action_dialog.close()
            self.to_daemon(
                osc_paths.ERROR, rg.SCRIPT_USER_ACTION,
                ray.Err.NOT_NOW, 'another script_user_action take place')

        self._script_action_dialog = dialogs.ScriptUserActionDialog(self)
        self._script_action_dialog.set_main_text(text)
        self._script_action_dialog.show()

    def hide_script_user_action_dialog(self):
        if self._script_action_dialog:
            self._script_action_dialog.close()
            del self._script_action_dialog
            self._script_action_dialog = None

    def daemon_crash(self):
        QMessageBox.critical(
            self, _translate('errors', "daemon crash!"),
            _translate('errors', "ray-daemon crashed, sorry !"))
        QApplication.quit()

    def save_window_settings(self, patchbay_mode=UI_PATCHBAY_UNDEF):
        if self.isFullScreen():
            return

        with_patchbay = False
        if patchbay_mode == UI_PATCHBAY_UNDEF:
            with_patchbay = self.ui.actionShowJackPatchbay.isChecked()
        elif patchbay_mode == UI_PATCHBAY_SHOWN:
            with_patchbay = True

        geom_path = 'MainWindow/geometry'
        if with_patchbay:
            geom_path = 'MainWindow/patchbay_geometry'
            RS.settings.setValue(
                'MainWindow/splitter_canvas_sizes',
                self.ui.splitterMainVsCanvas.sizes())

        RS.settings.setValue(geom_path, self.saveGeometry())
        RS.settings.setValue('MainWindow/WindowState', self.saveState())

        RS.settings.setValue(
            'MainWindow/ShowMenuBar',
            self.ui.menuBar.isVisible())
        RS.settings.setValue('MainWindow/show_patchbay',
                             self.ui.actionShowJackPatchbay.isChecked())
        RS.settings.setValue('MainWindow/splitter_messages',
                             self.ui.splitterSessionVsMessages.sizes())

        if with_patchbay:
            if self._patchbay_tools is not None:
                RS.settings.setValue(
                    'tool_bar/jack_elements',
                    self._patchbay_tools._tools_displayed.to_save_string())
                RS.settings.setValue(
                    'tool_bar/text_with_icons',
                    self._patchbay_tools._text_with_icons.name)

        RS.settings.sync()

    # Reimplemented Qt Functions

    def closeEvent(self, event: QCloseEvent):
        self.save_window_settings()
        self.session.patchbay_manager.save_patchcanvas_cache()
        self.session.patchbay_manager.save_settings()
        
        self.hidden_maximized = self.isMaximized()

        if self._systray.isVisible() and self.session.is_running():
            if not RS.is_hidden(RS.HD_SystrayClose):
                dialog = dialogs.SystrayCloseDialog(self)
                dialog.exec()

                if not dialog.result():
                    event.ignore()
                    return

                if dialog.not_again():
                    RS.set_hidden(RS.HD_SystrayClose)

            self.hide()
            return

        if self._quit_app():
            QMainWindow.closeEvent(self, event)
        else:
            event.ignore()

    def leaveEvent(self, event):
        if self.isActiveWindow():
            self.mouse_is_inside = False
        super().leaveEvent(event)

    def enterEvent(self, event):
        self.mouse_is_inside = True
        super().enterEvent(event)

    def showEvent(self, event):
        if CommandLineArgs.under_nsm:
            if self.session.nsm_child is not None:
                self.session.nsm_child.send_gui_state(True)
        QMainWindow.showEvent(self, event)

    def hideEvent(self, event):
        self.hidden_maximized = self.isMaximized()

        if CommandLineArgs.under_nsm:
            if self.session.nsm_child is not None:
                self.session.nsm_child.send_gui_state(False)
        QMainWindow.hideEvent(self, event)

    def resizeEvent(self, event):
        if self._fullscreen_patchbay and not self.isFullScreen():
            self.toggle_scene_full_screen()

        super().resizeEvent(event)
        
        if self.ui.actionShowJackPatchbay.isChecked():
            if self._patchbay_tools is not None:
                self._patchbay_tools.main_win_resize(self)
        else:
            text_with_icons = TextWithIcons.by_name(
                RS.settings.value('tool_bar/text_with_icons', 'AUTO'))
            
            if text_with_icons is TextWithIcons.NO:
                self.ui.toolBar.setToolButtonStyle(
                    Qt.ToolButtonStyle.ToolButtonIconOnly)
            else:
                 self.ui.toolBar.setToolButtonStyle(
                     Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
                 if self.ui.toolBar.sizeHint().width() > self.width():
                     self.ui.toolBar.setToolButtonStyle(
                         Qt.ToolButtonStyle.ToolButtonIconOnly)
                     
    def keyPressEvent(self, event: QKeyEvent):
        super().keyPressEvent(event)
        self.session.patchbay_manager.key_press_event(event)
