from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QDialogButtonBox, QListWidgetItem

import ray

from gui_tools import RS
from child_dialogs import ChildDialog

import ui_add_application

class AddApplicationDialog(ChildDialog):
    def __init__(self, parent):
        ChildDialog.__init__(self, parent)
        self.ui = ui_add_application.Ui_DialogAddApplication()
        self.ui.setupUi(self)

        self.ui.checkBoxFactory.setChecked(RS.settings.value(
            'AddApplication/factory_box', True, type=bool))
        self.ui.checkBoxUser.setChecked(RS.settings.value(
            'AddApplication/user_box', True, type=bool))

        self.ui.checkBoxFactory.stateChanged.connect(self.factoryBoxChanged)
        self.ui.checkBoxUser.stateChanged.connect(self.userBoxChanged)

        self.ui.templateList.currentItemChanged.connect(
            self.currentItemChanged)
        self.ui.templateList.setFocus(Qt.OtherFocusReason)
        self.ui.filterBar.textEdited.connect(self.updateFilteredList)
        self.ui.filterBar.updownpressed.connect(self.updownPressed)
        self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(False)

        self._signaler.user_client_template_found.connect(
            self.addUserTemplates)
        self._signaler.factory_client_template_found.connect(
            self.addFactoryTemplates)
        self.toDaemon('/ray/server/list_user_client_templates')
        self.toDaemon('/ray/server/list_factory_client_templates')

        self.user_template_list = []
        self.factory_template_list = []

        self.server_will_accept = False
        self.has_selection = False

        self.serverStatusChanged(self._session.server_status)
        
        self.toDaemon('/ray/server/list_sessions', 'opre', 'pof')

    def factoryBoxChanged(self, state):
        if not state:
            self.ui.checkBoxUser.setChecked(True)

        self.updateFilteredList()

    def userBoxChanged(self, state):
        if not state:
            self.ui.checkBoxFactory.setChecked(True)

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
                template_name = template.split('/')[0]
                icon_name = template.split('/')[1]

            self.user_template_list.append(template_name)

            self.ui.templateList.addItem(
                QListWidgetItem(
                    ray.getAppIcon(
                        icon_name,
                        self),
                    template_name,
                    self.ui.templateList))

            self.ui.templateList.sortItems()

        self.updateFilteredList()

    def addFactoryTemplates(self, template_list):
        for template in template_list:
            template_name = template
            icon_name = ''

            if '/' in template:
                template_name = template.split('/')[0]
                icon_name = template.split('/')[1]

            self.factory_template_list.append(template_name)

            self.ui.templateList.addItem(
                QListWidgetItem(
                    ray.getAppIcon(
                        icon_name,
                        self),
                    template_name,
                    self.ui.templateList))

            self.ui.templateList.sortItems()

        self.updateFilteredList()

    def updateFilteredList(self, filt=''):
        filter_text = self.ui.filterBar.displayText()

        # show all items
        for i in range(self.ui.templateList.count()):
            self.ui.templateList.item(i).setHidden(False)

        liist = self.ui.templateList.findItems(filter_text, Qt.MatchContains)

        seen_template_list = []

        # hide all non matching items
        for i in range(self.ui.templateList.count()):
            template_name = self.ui.templateList.item(i).text()

            if self.ui.templateList.item(i) not in liist:
                self.ui.templateList.item(i).setHidden(True)
                continue

            if self.ui.checkBoxFactory.isChecked() and self.ui.checkBoxUser.isChecked():
                if template_name in seen_template_list:
                    self.ui.templateList.item(i).setHidden(True)
                else:
                    seen_template_list.append(template_name)

            elif self.ui.checkBoxFactory.isChecked():
                if template_name not in self.factory_template_list:
                    self.ui.templateList.item(i).setHidden(True)
                    continue

                if template_name in seen_template_list:
                    self.ui.templateList.item(i).setHidden(True)
                else:
                    seen_template_list.append(template_name)

            elif self.ui.checkBoxUser.isChecked():
                if template_name not in self.user_template_list:
                    self.ui.templateList.item(i).setHidden(True)

                if template_name in seen_template_list:
                    self.ui.templateList.item(i).setHidden(True)
                else:
                    seen_template_list.append(template_name)

        # if selected item not in list, then select the first visible
        if not self.ui.templateList.currentItem(
        ) or self.ui.templateList.currentItem().isHidden():
            for i in range(self.ui.templateList.count()):
                if not self.ui.templateList.item(i).isHidden():
                    self.ui.templateList.setCurrentRow(i)
                    break

        if not self.ui.templateList.currentItem(
        ) or self.ui.templateList.currentItem().isHidden():
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

    def currentItemChanged(self, item, previous_item):
        self.has_selection = bool(item)
        self.preventOk()

    def preventOk(self):
        self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(
            bool(self.server_will_accept and self.has_selection))

    def getSelectedTemplate(self):
        if self.ui.templateList.currentItem():
            return self.ui.templateList.currentItem().text()

    def isTemplateFactory(self, template_name):
        if not self.ui.checkBoxUser.isChecked():
            return True

        # If both factory and user boxes are checked, priority to user template
        if template_name in self.user_template_list:
            return False

        return True

    def saveCheckBoxes(self):
        RS.settings.setValue(
            'AddApplication/factory_box',
            self.ui.checkBoxFactory.isChecked())
        RS.settings.setValue(
            'AddApplication/user_box',
            self.ui.checkBoxUser.isChecked())
        RS.settings.sync()
