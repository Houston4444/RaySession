# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file 'resources/ui/add_application.ui'
#
# Created by: PyQt5 UI code generator 5.11.3
#
# WARNING! All changes made in this file will be lost!

from PyQt5 import QtCore, QtGui, QtWidgets

class Ui_DialogAddApplication(object):
    def setupUi(self, DialogAddApplication):
        DialogAddApplication.setObjectName("DialogAddApplication")
        DialogAddApplication.setWindowModality(QtCore.Qt.NonModal)
        DialogAddApplication.resize(336, 407)
        DialogAddApplication.setModal(False)
        self.verticalLayout = QtWidgets.QVBoxLayout(DialogAddApplication)
        self.verticalLayout.setObjectName("verticalLayout")
        self.groupBox = QtWidgets.QGroupBox(DialogAddApplication)
        self.groupBox.setTitle("")
        self.groupBox.setObjectName("groupBox")
        self.verticalLayout_3 = QtWidgets.QVBoxLayout(self.groupBox)
        self.verticalLayout_3.setObjectName("verticalLayout_3")
        self.horizontalLayout_2 = QtWidgets.QHBoxLayout()
        self.horizontalLayout_2.setObjectName("horizontalLayout_2")
        self.label = QtWidgets.QLabel(self.groupBox)
        self.label.setObjectName("label")
        self.horizontalLayout_2.addWidget(self.label)
        self.filterBar = OpenSessionFilterBar(self.groupBox)
        self.filterBar.setObjectName("filterBar")
        self.horizontalLayout_2.addWidget(self.filterBar)
        self.verticalLayout_3.addLayout(self.horizontalLayout_2)
        self.horizontalLayout = QtWidgets.QHBoxLayout()
        self.horizontalLayout.setObjectName("horizontalLayout")
        self.checkBoxFactory = QtWidgets.QCheckBox(self.groupBox)
        self.checkBoxFactory.setLayoutDirection(QtCore.Qt.LeftToRight)
        self.checkBoxFactory.setChecked(True)
        self.checkBoxFactory.setObjectName("checkBoxFactory")
        self.horizontalLayout.addWidget(self.checkBoxFactory)
        self.checkBoxUser = QtWidgets.QCheckBox(self.groupBox)
        self.checkBoxUser.setChecked(True)
        self.checkBoxUser.setObjectName("checkBoxUser")
        self.horizontalLayout.addWidget(self.checkBoxUser)
        self.verticalLayout_3.addLayout(self.horizontalLayout)
        self.verticalLayout.addWidget(self.groupBox)
        self.templateList = QtWidgets.QListWidget(DialogAddApplication)
        self.templateList.setAlternatingRowColors(False)
        self.templateList.setObjectName("templateList")
        self.verticalLayout.addWidget(self.templateList)
        self.buttonBox = QtWidgets.QDialogButtonBox(DialogAddApplication)
        self.buttonBox.setEnabled(True)
        self.buttonBox.setOrientation(QtCore.Qt.Horizontal)
        self.buttonBox.setStandardButtons(QtWidgets.QDialogButtonBox.Cancel|QtWidgets.QDialogButtonBox.Ok)
        self.buttonBox.setObjectName("buttonBox")
        self.verticalLayout.addWidget(self.buttonBox)

        self.retranslateUi(DialogAddApplication)
        self.buttonBox.accepted.connect(DialogAddApplication.accept)
        self.buttonBox.rejected.connect(DialogAddApplication.reject)
        QtCore.QMetaObject.connectSlotsByName(DialogAddApplication)

    def retranslateUi(self, DialogAddApplication):
        _translate = QtCore.QCoreApplication.translate
        DialogAddApplication.setWindowTitle(_translate("DialogAddApplication", "Add Application"))
        self.label.setText(_translate("DialogAddApplication", "Filter :"))
        self.checkBoxFactory.setText(_translate("DialogAddApplication", "Factory"))
        self.checkBoxUser.setText(_translate("DialogAddApplication", "User"))
        self.templateList.setSortingEnabled(True)

from opensessionfilterbar import OpenSessionFilterBar
