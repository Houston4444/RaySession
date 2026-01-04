
# Imports from standard library
from typing import TYPE_CHECKING

# third party imports
from qtpy.QtWidgets import QFrame, QMenu, QBoxLayout, QAction # type:ignore
from qtpy.QtGui import (
    QIcon, QFontMetrics, QContextMenuEvent, QMouseEvent)
from qtpy.QtCore import QSize, Qt, Signal, Slot # type:ignore

# Imports from src/shared
import ray
import osc_paths.ray as r

# Local imports
import child_dialogs
import snapshots_dialog
from gui_server_thread import GuiServerThread
from gui_tools import (client_status_string, _translate, is_dark_theme,
                       ray_icon, split_in_two, get_app_icon)

# Import UIs made with Qt-Designer
import ui.client_slot

if TYPE_CHECKING:
    from gui_client import Client
    from list_widget_clients import ListWidgetClients, ClientItem
    from qtpy.QtGui import QAction


class AlternativesMenu(QMenu):
    def __init__(self, parent: QMenu, client: 'Client'):
        super().__init__(parent)
        self.client = client
        # self.
        self.setTitle(_translate('client_slot', 'Alternatives'))
        self.setIcon(QIcon.fromTheme('widget-alternatives'))
        self.aboutToShow.connect(self._fill_alternatives)
    
    def _fill_alternatives(self):
        self.clear()
        session = self.client.session
        for alter_group in session.alternative_groups:
            if self.client.client_id not in alter_group:
                continue
            
            for alt_id in alter_group:
                if alt_id == self.client.client_id:
                    continue
                for trashed_client in session.trashed_clients:
                    if trashed_client.client_id == alt_id:
                        act = QAction(self)
                        act.setIcon(get_app_icon(trashed_client.icon, self))
                        act.setText(trashed_client.label)
                        act.setData(alt_id)
                        act.triggered.connect(self._alternative_selected)
                        self.addAction(act)
                        break
            break
        
        self.addSeparator()
        new_act = QAction(self)
        new_act.setIcon(QIcon.fromTheme('list-add'))
        new_act.setText(_translate('alternatives', 'New Alternative'))
        new_act.triggered.connect(self._new_alternative)
        self.addAction(new_act)

    @Slot()
    def _alternative_selected(self):
        alt_id: str = self.sender().data() # type:ignore
        server = GuiServerThread.instance()
        if server:
            server.to_daemon(
                r.client.SWITCH_ALTERNATIVE, self.client.client_id, alt_id)
        
    @Slot()
    def _new_alternative(self):
        print('yalo pour une nouvelle alternative')
    

class ClientSlot(QFrame):
    clicked = Signal(str)
    
    def __init__(self, list_widget: 'ListWidgetClients',
                 list_widget_item: 'ClientItem', client: 'Client'):
        QFrame.__init__(self)
        self.ui = ui.client_slot.Ui_ClientSlotWidget()
        self.ui.setupUi(self)
        self.client = client
        self.main_win = self.client.session.main_win

        self.list_widget = list_widget
        self.list_widget_item = list_widget_item
        self._gui_state = False
        self._stop_is_kill = False
        self._very_short = False
        self._icon_on = QIcon()
        self._icon_off = QIcon()

        self.ui.toolButtonGUI.setVisible(False)
        if client.protocol is not ray.Protocol.RAY_HACK:
            self.ui.toolButtonHack.setVisible(False)

        # connect buttons to functions
        self.ui.toolButtonHack.order_hack_visibility.connect(
            self._order_hack_visibility)
        self.ui.toolButtonGUI.clicked.connect(self._change_gui_state)
        self.ui.startButton.clicked.connect(self._start_client)
        self.ui.stopButton.clicked.connect(self._stop_client)
        self.ui.saveButton.clicked.connect(self._save_client)
        self.ui.closeButton.clicked.connect(self._trash_client)
        self.ui.lineEditClientStatus.status_pressed.connect(self._abort_copy)

        self.ui.actionSaveAsApplicationTemplate.triggered.connect(
            self._save_as_application_template)
        self.ui.actionRename.triggered.connect(self._rename_dialog)
        self.ui.actionReturnToAPreviousState.triggered.connect(
            self._open_snapshots_dialog)
        self.ui.actionFindBoxesInPatchbay.triggered.connect(
            self._find_patchbay_boxes)
        self.ui.actionProperties.triggered.connect(
            self.client.show_properties_dialog)

        self._menu = QMenu(self)
        self._alternatives_menu = AlternativesMenu(self._menu, client)

        self._menu.addAction(
            self.ui.actionSaveAsApplicationTemplate) # type:ignore
        self._menu.addMenu(self._alternatives_menu)
        self._menu.addAction(
            self.ui.actionRename) # type:ignore
        self._menu.addAction(
            self.ui.actionReturnToAPreviousState) # type:ignore
        self._menu.addAction(
            self.ui.actionFindBoxesInPatchbay) # type:ignore
        self._menu.addAction(
            self.ui.actionProperties) # type:ignore

        self.ui.actionReturnToAPreviousState.setVisible(
            self.main_win.has_git)
        self.ui.actionFindBoxesInPatchbay.setEnabled(False)

        self.ui.iconButton.setMenu(self._menu) # type:ignore
        
        dark = is_dark_theme(self)
        
        self._save_icon = ray_icon('document-save', dark)
        self._saved_icon = ray_icon('document-saved', dark)
        self._unsaved_icon = ray_icon('document-unsaved', dark)
        self._no_save_icon = ray_icon('document-nosave', dark)
        self._icon_visible = ray_icon('visibility', dark)
        self._icon_invisible = ray_icon('hint', dark)
        self._stop_icon = ray_icon('media-playback-stop', dark)
        self._kill_icon = ray_icon('media-playback-stop_red', dark)

        self.ui.startButton.setIcon(
            ray_icon('media-playback-start', dark)) # type:ignore
        self.ui.closeButton.setIcon(
            ray_icon('window-close', dark)) # type:ignore
        self.ui.saveButton.setIcon(
            self._save_icon) # type:ignore
        self.ui.stopButton.setIcon(
            self._stop_icon) # type:ignore

        if ':optional-gui:' in self.client.capabilities:
            self.set_gui_state(self.client.gui_state)
            self.ui.toolButtonGUI.setVisible(True)

        if self.client.has_dirty:
            self.set_dirty_state(self.client.dirty_state)

        self.update_client_data()

    @classmethod
    def to_daemon(cls, *args):
        server = GuiServerThread.instance()
        if server:
            server.to_daemon(*args)

    def _change_gui_state(self):
        if self._gui_state:
            self.to_daemon(r.client.HIDE_OPTIONAL_GUI, self.client_id)
        else:
            self.to_daemon(r.client.SHOW_OPTIONAL_GUI, self.client_id)

    def _order_hack_visibility(self, state):
        if self.client.protocol is not ray.Protocol.RAY_HACK:
            return

        if state:
            self.client.show_properties_dialog(second_tab=True)
        else:
            self.client.close_properties_dialog()

    def _start_client(self):
        self.to_daemon(r.client.RESUME, self.client_id)

    def _stop_client(self):
        if self._stop_is_kill:
            self.to_daemon(r.client.KILL, self.client_id)
            return

        # we need to prevent accidental stop with a window confirmation
        # under conditions
        self.main_win.stop_client(self.client_id)

    def _save_client(self):
        self.to_daemon(r.client.SAVE, self.client_id)

    def _trash_client(self):
        self.to_daemon(r.client.TRASH, self.client_id)

    def _abort_copy(self):
        self.main_win.abort_copy_client(self.client_id)

    def _save_as_application_template(self):
        dialog = child_dialogs.SaveTemplateClientDialog(
            self.main_win, self.client)
        dialog.exec()
        if not dialog.result():
            return

        template_name = dialog.get_template_name()
        self.to_daemon(r.client.SAVE_AS_TEMPLATE,
                       self.client_id, template_name)

    def _open_snapshots_dialog(self):
        dialog = snapshots_dialog.ClientSnapshotsDialog(
            self.main_win, self.client)
        dialog.exec()
        if dialog.result():
            snapshot = dialog.get_selected_snapshot()
            if snapshot is None:
                return
            self.to_daemon(r.client.OPEN_SNAPSHOT,
                          self.client_id, snapshot)

    def _find_patchbay_boxes(self):
        self.main_win.set_patchbay_filter_text('client:' + self.client_id)
        self.list_widget_item.setSelected(True)

    def _rename_dialog(self):
        dialog = child_dialogs.ClientRenameDialog(self.main_win,
                                                  self.client)
        dialog.exec()
        if dialog.result():
            label = dialog.get_new_label()
            
            if dialog.is_identifiant_renamed():
                self.to_daemon(
                    r.client.FULL_RENAME,
                    self.client.client_id,
                    label)
                return

            self.client.label = label
            self.client.send_properties_to_daemon()

    def _set_very_short(self, yesno: bool):
        self._very_short = yesno

        if yesno:
            if not (self.ui.startButton.isEnabled()
                    or self.ui.stopButton.isEnabled()):
                self.ui.startButton.setVisible(True)
                self.ui.stopButton.setVisible(False)
            else:
                self.ui.startButton.setVisible(
                    self.ui.startButton.isEnabled())
                self.ui.stopButton.setVisible(self.ui.stopButton.isEnabled())
            self.ui.toolButtonHack.setVisible(False)
        else:
            self.ui.startButton.setVisible(True)
            self.ui.stopButton.setVisible(True)
            self.ui.toolButtonHack.setVisible(
                self.client.protocol is ray.Protocol.RAY_HACK)

    def _set_fat(self, yesno: bool, very_fat=False):
        if yesno:
            self.ui.mainLayout.setDirection(
                QBoxLayout.Direction.TopToBottom) # type:ignore
            self.ui.spacerLeftOfDown.setVisible(True)
            self.list_widget_item.setSizeHint(
                QSize(100, 80 if very_fat else 70))
        else:
            self.ui.spacerLeftOfDown.setVisible(False)
            self.ui.mainLayout.setDirection(
                QBoxLayout.Direction.LeftToRight) # type:ignore
            self.list_widget_item.setSizeHint(QSize(100, 45))

    def _gray_icon(self, gray: bool):
        if gray:
            self.ui.iconButton.setIcon(self._icon_off) # type:ignore
        else:
            self.ui.iconButton.setIcon(self._icon_on) # type:ignore

    @property
    def client_id(self) -> str:
        return self.client.client_id

    def update_layout(self):
        font = self.ui.ClientName.font()
        main_size = QFontMetrics(font).horizontalAdvance(
            self.client.prettier_name())

        layout_width = self.list_widget.width()

        self._set_very_short(layout_width < 233)

        scroll_bar = self.list_widget.verticalScrollBar()
        if scroll_bar is not None and scroll_bar.isVisible():
            layout_width -= scroll_bar.width()

        max_label_width = layout_width - 231

        if self.ui.toolButtonGUI.isVisible():
            max_label_width -= self.ui.toolButtonGUI.width()
        if self.ui.toolButtonHack.isVisible():
            max_label_width -= self.ui.toolButtonHack.width()

        if main_size <= max_label_width:
            self.ui.ClientName.setText(self.client.prettier_name())
            self._set_fat(False)
            return

        # split title in two lines
        top, bottom = split_in_two(self.client.prettier_name())

        max_size = 0

        for text in (top, bottom):
            if not text:
                continue

            size = QFontMetrics(font).horizontalAdvance(text)
            max_size = max(max_size, size)

        if max_size <= max_label_width:
            self.ui.ClientName.setText('\n'.join((top, bottom)))
            self._set_fat(False)
            return

        # responsive design, put label at top of the controls
        # if there is not enought space for label

        max_label_width = layout_width - 50

        if main_size <= max_label_width:
            self._set_fat(True)
            self.ui.ClientName.setText(self.client.prettier_name())
            return

        self._set_fat(True, very_fat=True)

        top, bottom = split_in_two(self.client.prettier_name())
        self.ui.ClientName.setText('\n'.join((top, bottom)))

    def update_client_data(self):
        # set main label and main layout
        self.update_layout()

        # set tool tip
        tool_tip = (
            '<html><head/><body>'
            '<p>'
                '<span style="font-weight:600;">'
                    f'{self.client.name}<br>'
                '</span>'
                '<span style="font-style:italic;">'
                    f'{self.client.description}'
                '</span>'
            '</p>'
            '<p></p>'
            '<p>'
                f"{_translate('client_slot', 'Protocol')} : "
                f'{self.client.protocol.to_string()}'
                '<br>'
                f"{_translate('client_slot', 'Executable')} : "
                f"{self.client.executable}"
                '<br>'
                f"{_translate('client_slot', 'client id')} : "
                f'{self.client.client_id}'
            '</p>'
            '</body></html>'
        )

        self.ui.ClientName.setToolTip(tool_tip)

        # set icon
        self._icon_on = get_app_icon(self.client.icon, self)
        self._icon_off = QIcon(
            self._icon_on.pixmap(32, 32, QIcon.Mode.Disabled))

        self._gray_icon(
            bool(self.client.status in (
                    ray.ClientStatus.STOPPED,
                    ray.ClientStatus.PRECOPY)))

        if not self.ui.toolButtonGUI.isVisible():
            self.ui.toolButtonGUI.setVisible(
                bool(':optional-gui:' in self.client.capabilities))
            self.set_gui_state(self.client.gui_state)
        
        if (self.client.protocol is ray.Protocol.RAY_HACK
                and self.client.ray_hack is not None):
            if self.client.ray_hack.relevant_no_save_level():
                self.ui.saveButton.setIcon(self._no_save_icon) # type:ignore
            else:
                self.ui.saveButton.setIcon(self._save_icon) # type:ignore

    def update_status(self, status: ray.ClientStatus):
        self.ui.lineEditClientStatus.setText(client_status_string(status))
        self.ui.lineEditClientStatus.setEnabled(
            status is not ray.ClientStatus.STOPPED)
        self.ui.actionFindBoxesInPatchbay.setEnabled(
            status not in (ray.ClientStatus.STOPPED,
                           ray.ClientStatus.PRECOPY))

        ray_hack = bool(self.client.protocol is ray.Protocol.RAY_HACK)

        match status:
            case (ray.ClientStatus.LAUNCH | ray.ClientStatus.OPEN
                  | ray.ClientStatus.SWITCH | ray.ClientStatus.NOOP
                  | ray.ClientStatus.LOSE):
                self.ui.startButton.setEnabled(False)
                self.ui.stopButton.setEnabled(True)
                self.ui.saveButton.setEnabled(False)
                self.ui.closeButton.setEnabled(False)
                self.ui.ClientName.setStyleSheet(
                    'QLabel {font-weight : bold}')
                self.ui.ClientName.setEnabled(True)
                self.ui.toolButtonGUI.setEnabled(True)
                self._gray_icon(False)

                if self._very_short:
                    self.ui.startButton.setVisible(False)
                    self.ui.stopButton.setVisible(True)
                    
                self.ui.actionFindBoxesInPatchbay.setEnabled(True)

            case ray.ClientStatus.READY:
                self.ui.startButton.setEnabled(False)
                self.ui.stopButton.setEnabled(True)
                self.ui.closeButton.setEnabled(False)
                self.ui.ClientName.setStyleSheet(
                    'QLabel {font-weight : bold}')
                self.ui.ClientName.setEnabled(True)
                self.ui.toolButtonGUI.setEnabled(True)
                self.ui.saveButton.setEnabled(True)
                self._gray_icon(False)

                if self._very_short:
                    self.ui.startButton.setVisible(False)
                    self.ui.stopButton.setVisible(True)
                
                self.ui.actionFindBoxesInPatchbay.setEnabled(True)

            case ray.ClientStatus.STOPPED:
                self.ui.startButton.setEnabled(True)
                self.ui.stopButton.setEnabled(False)
                self.ui.saveButton.setEnabled(False)
                self.ui.closeButton.setEnabled(True)
                self.ui.ClientName.setStyleSheet(
                    'QLabel {font-weight : normal}')
                self.ui.ClientName.setEnabled(False)
                self.ui.toolButtonGUI.setEnabled(False)
                self._gray_icon(True)

                if self._very_short:
                    self.ui.startButton.setVisible(True)
                    self.ui.stopButton.setVisible(False)

                self.ui.saveButton.setIcon(self._save_icon) # type:ignore
                self.ui.stopButton.setIcon(self._stop_icon) # type:ignore
                self._stop_is_kill = False

                if not ray_hack:
                    self.set_gui_state(False)
                    
                self.ui.actionFindBoxesInPatchbay.setEnabled(False)

            case ray.ClientStatus.PRECOPY:
                self.ui.startButton.setEnabled(False)
                self.ui.stopButton.setEnabled(False)
                self.ui.saveButton.setEnabled(False)
                self.ui.closeButton.setEnabled(True)
                self.ui.ClientName.setStyleSheet(
                    'QLabel {font-weight : normal}')
                self.ui.ClientName.setEnabled(False)
                self.ui.toolButtonGUI.setEnabled(False)
                self._gray_icon(True)

                if self._very_short:
                    self.ui.startButton.setVisible(True)
                    self.ui.stopButton.setVisible(False)

                self.ui.saveButton.setIcon(self._save_icon) # type:ignore
                self.ui.stopButton.setIcon(self._stop_icon) # type:ignore
                self._stop_is_kill = False
                
                self.ui.actionFindBoxesInPatchbay.setEnabled(False)

            case ray.ClientStatus.COPY:
                self.ui.saveButton.setEnabled(False)

    def allow_kill(self):
        self._stop_is_kill = True
        self.ui.stopButton.setIcon(self._kill_icon) # type:ignore

    def flash_if_open(self, flash: bool):
        if flash:
            self.ui.lineEditClientStatus.setText(
                client_status_string(ray.ClientStatus.OPEN))
        else:
            self.ui.lineEditClientStatus.setText('')

    def set_hack_button_state(self, state: bool):
        self.ui.toolButtonHack.setChecked(state)

    def show_gui_button(self):
        self.ui.toolButtonGUI.setIcon(self._icon_invisible) # type:ignore
        self.ui.toolButtonGUI.setVisible(True)

    def set_gui_state(self, state: bool):
        if state:
            self.ui.toolButtonGUI.setIcon(self._icon_visible) # type:ignore
        else:
            self.ui.toolButtonGUI.setIcon(self._icon_invisible) # type:ignore

        self._gui_state = state

    def set_dirty_state(self, dirty: bool):
        self.ui.saveButton.setIcon(
            self._unsaved_icon if dirty else self._saved_icon) # type:ignore

    def set_progress(self, progress: float):
        self.ui.lineEditClientStatus.set_progress(progress)

    def set_daemon_options(self, options: ray.Option):
        self.ui.actionReturnToAPreviousState.setVisible(
            ray.Option.HAS_GIT in options)

    def patchbay_is_shown(self, yesno: bool):
        self.ui.actionFindBoxesInPatchbay.setVisible(yesno)

    def contextMenuEvent(self, event: QContextMenuEvent):
        act_selected = self._menu.exec(self.mapToGlobal(event.pos()))
        event.accept()
        
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if (event.button() == Qt.MouseButton.LeftButton
                and self.client.status is not ray.ClientStatus.STOPPED
                and self.client.jack_client_name
                and self.list_widget_item.isSelected()):
            self.client.session.patchbay_manager.select_client_box(
                self.client.jack_client_name)
        super().mousePressEvent(event)
