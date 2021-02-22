# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file 'resources/ui/script_user_action.ui'
#
# Created by: PyQt5 UI code generator 5.11.3
#
# WARNING! All changes made in this file will be lost!

from PyQt5 import QtCore, QtGui, QtWidgets

class Ui_Dialog(object):
    def setupUi(self, Dialog):
        Dialog.setObjectName("Dialog")
        Dialog.resize(372, 161)
        self.verticalLayout_2 = QtWidgets.QVBoxLayout(Dialog)
        self.verticalLayout_2.setObjectName("verticalLayout_2")
        self.infoLabel = QtWidgets.QLabel(Dialog)
        self.infoLabel.setObjectName("infoLabel")
        self.verticalLayout_2.addWidget(self.infoLabel)
        self.infoLine = QtWidgets.QLabel(Dialog)
        self.infoLine.setObjectName("infoLine")
        self.verticalLayout_2.addWidget(self.infoLine)
        self.label = QtWidgets.QLabel(Dialog)
        self.label.setWordWrap(True)
        self.label.setObjectName("label")
        self.verticalLayout_2.addWidget(self.label)
        self.buttonBox = QtWidgets.QDialogButtonBox(Dialog)
        self.buttonBox.setOrientation(QtCore.Qt.Horizontal)
        self.buttonBox.setStandardButtons(QtWidgets.QDialogButtonBox.Ignore|QtWidgets.QDialogButtonBox.Yes)
        self.buttonBox.setObjectName("buttonBox")
        self.verticalLayout_2.addWidget(self.buttonBox)

        self.retranslateUi(Dialog)
        self.buttonBox.accepted.connect(Dialog.accept)
        self.buttonBox.rejected.connect(Dialog.reject)
        QtCore.QMetaObject.connectSlotsByName(Dialog)

    def retranslateUi(self, Dialog):
        _translate = QtCore.QCoreApplication.translate
        Dialog.setWindowTitle(_translate("Dialog", "Script User Action"))
        self.infoLabel.setText(_translate("Dialog", "Info Label"))
        self.infoLine.setText(_translate("Dialog", "<html><head/><body><p><hr/></p></body></html>"))
        self.label.setText(_translate("Dialog", "Script user action text. Are you ready ?"))

