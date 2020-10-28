from PyQt5.QtCore import Qt, QSize
from PyQt5.QtWidgets import (QDialogButtonBox, QListWidgetItem, QFrame,
                             QMenu, QAction)
from PyQt5.QtGui import QIcon, QPalette

import client_properties_dialog
import ray

from gui_tools import RS, _translate, isDarkTheme
from child_dialogs import ChildDialog
from gui_signaler import Signaler

import ui_add_application
import ui_template_slot
import ui_remove_template


class TemplateSlot(QFrame):
    def __init__(self, list_widget, item, session,
                 name, factory, client_data):
        QFrame.__init__(self)
        self.ui = ui_template_slot.Ui_Frame()
        self.ui.setupUi(self)

        self.list_widget = list_widget
        self.item = item
        self._session = session
        self.name = name
        self.factory = factory
        self.client_data = client_data

        self.ui.toolButtonIcon.setIcon(
            ray.getAppIcon(self.client_data.icon, self))
        self.ui.label.setText(name)
        self.ui.toolButtonUser.setVisible(not factory)

        self.user_menu = QMenu()
        act_remove_template = QAction(QIcon.fromTheme('edit-delete-remove'),
                                      _translate('menu', 'remove'),
                                      self.user_menu)
        act_remove_template.triggered.connect(self.removeTemplate)
        self.user_menu.addAction(act_remove_template)
        self.ui.toolButtonUser.setMenu(self.user_menu)

        self.is_favorite = False

        self.ui.toolButtonFavorite.setSession(self._session)
        self.ui.toolButtonFavorite.setTemplate(
            name, self.client_data.icon, self.factory)

        if isDarkTheme(self):
            self.ui.toolButtonUser.setIcon(
                QIcon(':scalable/breeze-dark/im-user.svg'))
            self.ui.toolButtonFavorite.setDarkTheme()

    def updateClientData(self, *args):
        self.client_data.update(*args)
        self.ui.toolButtonIcon.setIcon(
            ray.getAppIcon(self.client_data.icon, self))
        self.ui.toolButtonFavorite.setTemplate(
            self.name, self.client_data.icon, self.factory)

    def updateRayHackData(self, *args):
        if self.client_data.ray_hack is None:
            self.client_data.ray_hack = ray.RayHack.newFrom(*args)
        self.client_data.ray_hack.update(*args)

    def updateRayNetData(self, *args):
        if self.client_data.ray_net is None:
            self.client_data.ray_net = ray.RayNet.newFrom(*args)
        self.client_data.ray_net.update(*args)

    def removeTemplate(self):
        add_app_dialog = self.list_widget.parent()
        add_app_dialog.removeTemplate(self.name, self.factory)

    def setAsFavorite(self, bool_favorite):
        self.ui.toolButtonFavorite.setAsFavorite(bool_favorite)

    def mouseDoubleClickEvent(self, event):
        self.list_widget.parent().accept()


class TemplateItem(QListWidgetItem):
    def __init__(self, parent, session, icon, name, factory):
        QListWidgetItem.__init__(self, parent, QListWidgetItem.UserType + 1)

        self.client_data = ray.ClientData()
        self.f_widget = TemplateSlot(parent, self, session,
                                     name, factory, self.client_data)
        self.setData(Qt.UserRole, name)
        parent.setItemWidget(self, self.f_widget)
        self.setSizeHint(QSize(100, 28))

        self.f_factory = factory

    def __lt__(self, other):
        self_name = self.data(Qt.UserRole)
        other_name = other.data(Qt.UserRole)

        if other_name is None:
            return False

        if self_name == other_name:
            # make the user template on top
            return not self.f_factory

        return bool(self.data(Qt.UserRole).lower() < other.data(Qt.UserRole).lower())

    def matchesWith(self, factory, name):
        return bool(bool(factory) == bool(self.f_factory)
                    and name == self.data(Qt.UserRole))

    def updateClientData(self, *args):
        self.f_widget.updateClientData(*args)

    def updateRayHackData(self, *args):
        self.f_widget.updateRayHackData(*args)

    def setAsFavorite(self, bool_favorite: bool):
        self.f_widget.setAsFavorite(bool_favorite)


class RemoveTemplateDialog(ChildDialog):
    def __init__(self, parent, template_name):
        ChildDialog.__init__(self, parent)
        self.ui = ui_remove_template.Ui_Dialog()
        self.ui.setupUi(self)

        self.ui.label.setText(
            _translate('add_app_dialog',
                       '<p>Are you sure to want to remove<br>the template "%s" and all its files ?</p>')
                            % template_name)

        self.ui.pushButtonCancel.setFocus()

class AddApplicationDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui_add_application.Ui_DialogAddApplication()
        self.ui.setupUi(self)

        self._session = parent._session

        self.ui.checkBoxFactory.setChecked(RS.settings.value(
            'AddApplication/factory_box', True, type=bool))
        self.ui.checkBoxUser.setChecked(RS.settings.value(
            'AddApplication/user_box', True, type=bool))
        self.ui.checkBoxRayHack.setChecked(RS.settings.value(
            'AddApplication/ray_hack_box', True, type=bool))
        self.ui.widgetTemplateInfos.setVisible(False)

        self.ui.checkBoxFactory.stateChanged.connect(self.factoryBoxChanged)
        self.ui.checkBoxUser.stateChanged.connect(self.userBoxChanged)
        self.ui.checkBoxNsm.stateChanged.connect(self.nsmBoxChanged)
        self.ui.checkBoxRayHack.stateChanged.connect(self.rayHackBoxChanged)

        self.ui.templateList.currentItemChanged.connect(
            self.currentItemChanged)
        self.ui.templateList.setFocus(Qt.OtherFocusReason)
        self.ui.filterBar.textEdited.connect(self.updateFilteredList)
        self.ui.filterBar.updownpressed.connect(self.updownPressed)
        self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(False)

        self.user_menu = QMenu()
        act_remove_template = QAction(QIcon.fromTheme('edit-delete-remove'),
                                      _translate('menu', 'remove'),
                                      self.user_menu)
        act_remove_template.triggered.connect(self.removeCurrentTemplate)
        self.user_menu.addAction(act_remove_template)
        self.ui.toolButtonUser.setMenu(self.user_menu)
        self.ui.toolButtonFavorite.setSession(self._session)
        self.ui.widgetNonSaveable.setVisible(False)
        self.ui.toolButtonAdvanced.clicked.connect(self.toolButtonAdvancedClicked)

        if isDarkTheme(self):
            self.ui.toolButtonUser.setIcon(
                QIcon(':scalable/breeze-dark/im-user.svg'))
            self.ui.toolButtonFavorite.setDarkTheme()
            self.ui.toolButtonNoSave.setIcon(
                QIcon(':scalable/breeze-dark/document-nosave.svg'))

        self._signaler.user_client_template_found.connect(
            self.addUserTemplates)
        self._signaler.factory_client_template_found.connect(
            self.addFactoryTemplates)
        self._signaler.client_template_update.connect(
            self.updateClientTemplate)
        self._signaler.client_template_ray_hack_update.connect(
            self.updateClientTemplateRayHack)
        self._signaler.client_template_ray_net_update.connect(
            self.updateClientTemplateRayNet)
        self._signaler.favorite_added.connect(self.favoriteAdded)
        self._signaler.favorite_removed.connect(self.favoriteRemoved)

        self.toDaemon('/ray/server/list_user_client_templates')
        self.toDaemon('/ray/server/list_factory_client_templates')
        self.listing_finished = 0

        self.user_template_list = []
        self.factory_template_list = []

        self.server_will_accept = False
        self.has_selection = False

        self.serverStatusChanged(self._session.server_status)

        self.ui.filterBar.setFocus()

    def favoriteAdded(self, template_name: str,
                      template_icon: str, factory: bool):
        for i in range(self.ui.templateList.count()):
            item = self.ui.templateList.item(i)
            if item is None:
                continue

            if (item.data(Qt.UserRole) == template_name
                    and item.f_factory == factory):
                item.setAsFavorite(True)
                if item == self.ui.templateList.currentItem():
                    self.ui.toolButtonFavorite.setAsFavorite(True)
                break

    def favoriteRemoved(self, template_name: str, factory: bool):
        for i in range(self.ui.templateList.count()):
            item = self.ui.templateList.item(i)
            if item is None:
                continue

            if (item.data(Qt.UserRole) == template_name
                    and item.f_factory == factory):
                item.setAsFavorite(False)
                if item == self.ui.templateList.currentItem():
                    self.ui.toolButtonFavorite.setAsFavorite(False)
                break

    def factoryBoxChanged(self, state):
        if not state:
            self.ui.checkBoxUser.setChecked(True)

        self.updateFilteredList()

    def userBoxChanged(self, state):
        if not state:
            self.ui.checkBoxFactory.setChecked(True)

        self.updateFilteredList()

    def nsmBoxChanged(self, state):
        if not state:
            self.ui.checkBoxRayHack.setChecked(True)

        self.updateFilteredList()

    def rayHackBoxChanged(self, state):
        if not state:
            self.ui.checkBoxNsm.setChecked(True)

        self.updateFilteredList()

    def serverStatusChanged(self, server_status):
        self.server_will_accept = bool(
            server_status not in (
                ray.ServerStatus.OFF,
                ray.ServerStatus.CLOSE) and not self.server_copying)
        self.preventOk()

    def addUserTemplates(self, template_list):
        for template in template_list:
            template_name = template
            icon_name = ''

            if '/' in template:
                template_name, slash, icon_name = template.partition('/')

            if template_name in self.user_template_list:
                continue

            self.user_template_list.append(template_name)

            list_widget = TemplateItem(self.ui.templateList,
                                       self._session,
                                       icon_name,
                                       template_name,
                                       False)
            if self._session.isFavorite(template_name, False):
                list_widget.setAsFavorite(True)
            self.ui.templateList.addItem(list_widget)

            self.ui.templateList.sortItems()

        self.updateFilteredList()

    def addFactoryTemplates(self, template_list):
        for template in template_list:
            template_name = template
            icon_name = ''

            if '/' in template:
                template_name, slash, icon_name = template.partition('/')

            if template_name in self.factory_template_list:
                continue

            self.factory_template_list.append(template_name)

            list_widget = TemplateItem(self.ui.templateList,
                                       self._session,
                                       icon_name,
                                       template_name,
                                       True)
            if self._session.isFavorite(template_name, True):
                list_widget.setAsFavorite(True)
            self.ui.templateList.addItem(list_widget)
            self.ui.templateList.sortItems()

        self.updateFilteredList()

    def updateClientTemplate(self, args):
        factory = bool(args[0])
        template_name = args[1]

        for i in range(self.ui.templateList.count()):
            item = self.ui.templateList.item(i)

            if item.matchesWith(factory, template_name):
                item.updateClientData(*args[2:])
                if self.ui.templateList.currentItem() == item:
                    self.updateTemplateInfos(item)
                break

    def updateClientTemplateRayHack(self, args):
        factory = bool(args[0])
        template_name = args[1]

        for i in range(self.ui.templateList.count()):
            item = self.ui.templateList.item(i)

            if item.matchesWith(factory, template_name):
                item.updateRayHackData(*args[2:])
                if self.ui.templateList.currentItem() == item:
                    self.updateTemplateInfos(item)
                break

    def updateClientTemplateRayNet(self, args):
        factory = bool(args[0])
        template_name = args[1]

        for i in range(self.ui.templateList.count()):
            item = self.ui.templateList.item(i)

            if item.matchesWith(factory, template_name):
                item.updateRayNetData(*args[2:])
                if self.ui.templateList.currentItem() == item:
                    self.updateTemplateInfos(item)
                break

    def updateFilteredList(self, filt=''):
        filter_text = self.ui.filterBar.displayText()

        # show all items
        for i in range(self.ui.templateList.count()):
            self.ui.templateList.item(i).setHidden(False)

        # hide all non matching items
        for i in range(self.ui.templateList.count()):
            item = self.ui.templateList.item(i)
            template_name = item.data(Qt.UserRole)

            if not filter_text.lower() in template_name.lower():
                item.setHidden(True)

            if item.f_factory and not self.ui.checkBoxFactory.isChecked():
                item.setHidden(True)

            if not item.f_factory and not self.ui.checkBoxUser.isChecked():
                item.setHidden(True)

            if item.client_data is not None:
                if (item.client_data.protocol == ray.Protocol.RAY_HACK
                        and not self.ui.checkBoxRayHack.isChecked()):
                    item.setHidden(True)

                if (item.client_data.protocol != ray.Protocol.RAY_HACK
                        and not self.ui.checkBoxNsm.isChecked()):
                    item.setHidden(True)

        # if selected item not in list, then select the first visible
        if (not self.ui.templateList.currentItem()
                or self.ui.templateList.currentItem().isHidden()):
            for i in range(self.ui.templateList.count()):
                if not self.ui.templateList.item(i).isHidden():
                    self.ui.templateList.setCurrentRow(i)
                    break

        if (not self.ui.templateList.currentItem()
                or self.ui.templateList.currentItem().isHidden()):
            if self.ui.filterBar.text():
                self.ui.filterBar.setStyleSheet(
                    "QLineEdit { background-color: red}")
            self.ui.templateList.setCurrentItem(None)
        else:
            self.ui.filterBar.setStyleSheet("")
            self.ui.templateList.scrollTo(self.ui.templateList.currentIndex())

    def updownPressed(self, key):
        row = self.ui.templateList.currentRow()
        if key == Qt.Key_Up:
            if row == 0:
                return
            row -= 1
            while self.ui.templateList.item(row).isHidden():
                if row == 0:
                    return
                row -= 1
        elif key == Qt.Key_Down:
            if row == self.ui.templateList.count() - 1:
                return
            row += 1
            while self.ui.templateList.item(row).isHidden():
                if row == self.ui.templateList.count() - 1:
                    return
                row += 1
        self.ui.templateList.setCurrentRow(row)

    def updateTemplateInfos(self, item):
        self.ui.widgetTemplateInfos.setVisible(bool(item))
        self.ui.widgetNoTemplate.setVisible(not bool(item))

        if not item:
            return

        cdata = item.client_data
        self.ui.toolButtonIcon.setIcon(
            ray.getAppIcon(cdata.icon, self))
        self.ui.labelTemplateName.setText(item.data(Qt.UserRole))
        self.ui.labelDescription.setText(cdata.description)
        self.ui.labelProtocol.setText(ray.protocolToStr(cdata.protocol))
        self.ui.labelExecutable.setText(cdata.executable_path)
        self.ui.labelLabel.setText(cdata.label)
        self.ui.labelName.setText(cdata.name)

        for widget in (self.ui.labelProtocolTitle,
                       self.ui.labelProtocolColon,
                       self.ui.labelProtocol):
            widget.setVisible(bool(cdata.protocol != ray.Protocol.NSM))

        for widget in (self.ui.labelLabelTitle,
                        self.ui.labelLabelColon,
                        self.ui.labelLabel):
            widget.setVisible(bool(cdata.label))

        for widget in (self.ui.labelNameTitle,
                        self.ui.labelNameColon,
                        self.ui.labelName):
            widget.setVisible(bool(cdata.protocol == ray.Protocol.NSM))

        self.ui.toolButtonUser.setVisible(not item.f_factory)
        self.ui.toolButtonFavorite.setTemplate(
            item.data(Qt.UserRole), cdata.icon, item.f_factory)
        self.ui.toolButtonFavorite.setAsFavorite(self._session.isFavorite(
            item.data(Qt.UserRole), item.f_factory))

        self.ui.widgetNonSaveable.setVisible(bool(
            cdata.ray_hack is not None
            and cdata.protocol == ray.Protocol.RAY_HACK
            and cdata.ray_hack.no_save_level > 0))

        # little security
        # client_properties_dialog could crash if ray_hack has not been updated yet
        # (never seen this appears, but it could with slow systems)
        self.ui.toolButtonAdvanced.setEnabled(
            bool(cdata.protocol != ray.Protocol.RAY_HACK
                 or cdata.ray_hack is not None))

    def currentItemChanged(self, item, previous_item):
        self.has_selection = bool(item)
        self.updateTemplateInfos(item)
        self.preventOk()

    def toolButtonAdvancedClicked(self):
        item = self.ui.templateList.currentItem()
        if item is None:
            return

        properties_dialog = client_properties_dialog.ClientPropertiesDialog.create(
            self, item.client_data)
        properties_dialog.updateContents()
        properties_dialog.setForTemplate(item.data(Qt.UserRole))
        properties_dialog.show()

    def preventOk(self):
        self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(
            bool(self.server_will_accept and self.has_selection))

    def getSelectedTemplate(self):
        item = self.ui.templateList.currentItem()
        if item:
            return (item.data(Qt.UserRole), item.f_factory)

    def removeTemplate(self, template_name, factory):
        dialog = RemoveTemplateDialog(self, template_name)
        dialog.exec()
        if not dialog.result():
            return

        self.toDaemon('/ray/server/remove_client_template', template_name)

        for i in range(self.ui.templateList.count()):
            item = self.ui.templateList.item(i)

            if not item.f_factory and template_name == item.data(Qt.UserRole):
                item.setHidden(True)
                if item == self.ui.templateList.currentItem():
                    self.updateTemplateInfos(None)
                self.ui.templateList.removeItemWidget(item)
                break

    def removeCurrentTemplate(self):
        item = self.ui.templateList.currentItem()
        if not item:
            return

        self.removeTemplate(item.data(Qt.UserRole), False)

    def saveCheckBoxes(self):
        RS.settings.setValue(
            'AddApplication/factory_box',
            self.ui.checkBoxFactory.isChecked())
        RS.settings.setValue(
            'AddApplication/user_box',
            self.ui.checkBoxUser.isChecked())
        RS.settings.setValue(
            'AddApplication/ray_hack_box',
            self.ui.checkBoxRayHack.isChecked())
        RS.settings.sync()
