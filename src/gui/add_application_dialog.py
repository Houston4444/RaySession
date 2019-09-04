from PyQt5.QtCore import Qt, QTimer, QSize
from PyQt5.QtWidgets import QDialogButtonBox, QListWidgetItem, QFrame
from PyQt5.QtGui import QIcon, QPalette

import ray

from gui_tools import RS
from child_dialogs import ChildDialog

import ui_add_application
import ui_template_slot

class TemplateSlot(QFrame):
    def __init__(self, icon, name, factory, favorite):
        QFrame.__init__(self)
        self.ui = ui_template_slot.Ui_Frame()
        self.ui.setupUi(self)
        
        self.ui.toolButtonIcon.setIcon(icon)
        self.ui.label.setText(name)
        self.ui.toolButtonUser.setVisible(not factory)
        
        if (self.palette().brush(2, QPalette.WindowText).color().lightness()
                > 128):
            self.ui.toolButtonUser.setIcon(
                QIcon(':scalable/breeze-dark/im-user.svg'))
            self.ui.toolButtonFavorite.setIcon(
                QIcon(':scalable/breeze-dark/draw-star.svg'))
     
     
class TemplateItem(QListWidgetItem):
    def __init__(self, parent, icon, name, factory, favorite):
        QListWidgetItem.__init__(self, parent, QListWidgetItem.UserType + 1)
        self.f_widget = TemplateSlot(icon, name, factory, favorite)
        self.setData(Qt.UserRole, name)
        parent.setItemWidget(self, self.f_widget)
        self.setSizeHint(QSize(100, 28))
        
        self.f_factory = factory
        
    def __lt__(self, other):
        self_name = self.data(Qt.UserRole)
        other_name = other.data(Qt.UserRole)
        
        if other_name == None:
            return False
        
        if self_name == other_name:
            # make the user template on top
            return not self.f_factory
            
        return bool(self.data(Qt.UserRole).lower() < other.data(Qt.UserRole).lower())

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
                
            if template_name in self.user_template_list:
                continue

            self.user_template_list.append(template_name)
            
            list_widget = TemplateItem(self.ui.templateList,
                                       ray.getAppIcon(icon_name, self),
                                       template_name, 
                                       False, 
                                       False)

            self.ui.templateList.addItem(list_widget)
            
            self.ui.templateList.sortItems()

        self.updateFilteredList()

    def addFactoryTemplates(self, template_list):
        for template in template_list:
            template_name = template
            icon_name = ''

            if '/' in template:
                template_name = template.split('/')[0]
                icon_name = template.split('/')[1]
                
            if template_name in self.factory_template_list:
                continue

            self.factory_template_list.append(template_name)
            
            list_widget = TemplateItem(self.ui.templateList,
                                       ray.getAppIcon(icon_name, self),
                                       template_name, 
                                       True, 
                                       False)

            self.ui.templateList.addItem(list_widget)
            self.ui.templateList.sortItems()

        self.updateFilteredList()

    def updateFilteredList(self, filt=''):
        filter_text = self.ui.filterBar.displayText()

        # show all items
        for i in range(self.ui.templateList.count()):
            self.ui.templateList.item(i).setHidden(False)
            
        #liist = []
        #for i in range(self.ui.templateList.count()):
            #item = self.ui.templateList.item(i)
            #if filter_text in item.data(Qt.UserRole):
                #liist.append(item)

        #seen_template_list = []

        # hide all non matching items
        for i in range(self.ui.templateList.count()):
            
            
            item = self.ui.templateList.item(i)
            template_name = item.data(Qt.UserRole)

            #if item not in liist:
                #item.setHidden(True)
                #continue
            
            if not filter_text.lower() in template_name.lower():
                item.setHidden(True)
            
            if item.f_factory and not self.ui.checkBoxFactory.isChecked():
                item.setHidden(True)
            
            if not item.f_factory and not self.ui.checkBoxUser.isChecked():
                item.setHidden(True)

            #if (self.ui.checkBoxFactory.isChecked()
                    #and self.ui.checkBoxUser.isChecked()):
                #if template_name in seen_template_list:
                    #item.setHidden(True)
                #else:
                    #seen_template_list.append(template_name)

            #elif self.ui.checkBoxFactory.isChecked():
                #if template_name not in self.factory_template_list:
                    #item.setHidden(True)
                    #continue

                #if template_name in seen_template_list:
                    #item.setHidden(True)
                #else:
                    #seen_template_list.append(template_name)

            #elif self.ui.checkBoxUser.isChecked():
                #if template_name not in self.user_template_list:
                    #item.setHidden(True)

                #if template_name in seen_template_list:
                    #item.setHidden(True)
                #else:
                    #seen_template_list.append(template_name)
        #self.ui.templateList.sortItems()

        # if selected item not in list, then select the first visible
        if (not self.ui.templateList.currentItem()
                or self.ui.templateList.currentItem().isHidden()):
            for i in range(self.ui.templateList.count()):
                if not self.ui.templateList.item(i).isHidden():
                    self.ui.templateList.setCurrentRow(i)
                    break

        if (not self.ui.templateList.currentItem()
                or self.ui.templateList.currentItem().isHidden()):
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
        item = self.ui.templateList.currentItem()
        if item:
            return (item.data(Qt.UserRole), item.f_factory)

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
