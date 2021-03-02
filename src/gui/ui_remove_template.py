# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file 'resources/ui/remove_template.ui'
#
# Created by: PyQt5 UI code generator 5.11.3
#
# WARNING! All changes made in this file will be lost!

from PyQt5 import QtCore, QtGui, QtWidgets

class Ui_Dialog(object):
    def setupUi(self, Dialog):
        Dialog.setObjectName("Dialog")
        Dialog.setWindowModality(QtCore.Qt.NonModal)
        Dialog.resize(342, 72)
        Dialog.setModal(False)
        self.verticalLayout = QtWidgets.QVBoxLayout(Dialog)
        self.verticalLayout.setObjectName("verticalLayout")
        self.label = QtWidgets.QLabel(Dialog)
        self.label.setAlignment(QtCore.Qt.AlignCenter)
        self.label.setObjectName("label")
        self.verticalLayout.addWidget(self.label)
        self.horizontalLayout = QtWidgets.QHBoxLayout()
        self.horizontalLayout.setObjectName("horizontalLayout")
        self.pushButtonRemove = QtWidgets.QPushButton(Dialog)
        icon = QtGui.QIcon.fromTheme("edit-delete-remove")
        self.pushButtonRemove.setIcon(icon)
        self.pushButtonRemove.setObjectName("pushButtonRemove")
        self.horizontalLayout.addWidget(self.pushButtonRemove)
        self.pushButtonCancel = QtWidgets.QPushButton(Dialog)
        icon = QtGui.QIcon.fromTheme("dialog-cancel")
        self.pushButtonCancel.setIcon(icon)
        self.pushButtonCancel.setObjectName("pushButtonCancel")
        self.horizontalLayout.addWidget(self.pushButtonCancel)
        self.verticalLayout.addLayout(self.horizontalLayout)

        self.retranslateUi(Dialog)
        self.pushButtonCancel.clicked.connect(Dialog.reject)
        self.pushButtonRemove.clicked.connect(Dialog.accept)
        QtCore.QMetaObject.connectSlotsByName(Dialog)

    def retranslateUi(self, Dialog):
        _translate = QtCore.QCoreApplication.translate
        Dialog.setWindowTitle(_translate("Dialog", "Remove Template ?"))
        self.label.setText(_translate("Dialog", "<html><head/><body><p>Are you sure to want to remove this template ?</p></body></html>"))
        self.pushButtonRemove.setText(_translate("Dialog", "Remove"))
        self.pushButtonCancel.setText(_translate("Dialog", "Cancel"))

