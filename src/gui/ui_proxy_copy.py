# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file 'resources/ui/proxy_copy.ui'
#
# Created by: PyQt5 UI code generator 5.11.3
#
# WARNING! All changes made in this file will be lost!

from PyQt5 import QtCore, QtGui, QtWidgets

class Ui_Dialog(object):
    def setupUi(self, Dialog):
        Dialog.setObjectName("Dialog")
        Dialog.resize(459, 145)
        self.verticalLayout_2 = QtWidgets.QVBoxLayout(Dialog)
        self.verticalLayout_2.setObjectName("verticalLayout_2")
        self.labelFileNotInFolder = QtWidgets.QLabel(Dialog)
        self.labelFileNotInFolder.setObjectName("labelFileNotInFolder")
        self.verticalLayout_2.addWidget(self.labelFileNotInFolder)
        self.label = QtWidgets.QLabel(Dialog)
        self.label.setObjectName("label")
        self.verticalLayout_2.addWidget(self.label)
        self.horizontalLayout = QtWidgets.QHBoxLayout()
        self.horizontalLayout.setObjectName("horizontalLayout")
        spacerItem = QtWidgets.QSpacerItem(40, 20, QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum)
        self.horizontalLayout.addItem(spacerItem)
        self.pushButtonCopyRename = QtWidgets.QPushButton(Dialog)
        icon = QtGui.QIcon.fromTheme("edit-copy")
        self.pushButtonCopyRename.setIcon(icon)
        self.pushButtonCopyRename.setObjectName("pushButtonCopyRename")
        self.horizontalLayout.addWidget(self.pushButtonCopyRename)
        self.pushButtonCopy = QtWidgets.QPushButton(Dialog)
        icon = QtGui.QIcon.fromTheme("edit-copy")
        self.pushButtonCopy.setIcon(icon)
        self.pushButtonCopy.setObjectName("pushButtonCopy")
        self.horizontalLayout.addWidget(self.pushButtonCopy)
        self.pushButtonUseThisFile = QtWidgets.QPushButton(Dialog)
        icon = QtGui.QIcon.fromTheme("dialog-cancel")
        self.pushButtonUseThisFile.setIcon(icon)
        self.pushButtonUseThisFile.setObjectName("pushButtonUseThisFile")
        self.horizontalLayout.addWidget(self.pushButtonUseThisFile)
        self.verticalLayout_2.addLayout(self.horizontalLayout)

        self.retranslateUi(Dialog)
        self.pushButtonCopy.clicked.connect(Dialog.accept)
        self.pushButtonUseThisFile.clicked.connect(Dialog.reject)
        QtCore.QMetaObject.connectSlotsByName(Dialog)

    def retranslateUi(self, Dialog):
        _translate = QtCore.QCoreApplication.translate
        Dialog.setWindowTitle(_translate("Dialog", "Copy File ?"))
        self.labelFileNotInFolder.setText(_translate("Dialog", "file is not in proxy directory."))
        self.label.setText(_translate("Dialog", "<html><head/><body><p>Do you want to copy this file to proxy directory or to use directly this file ?</p></body></html>"))
        self.pushButtonCopyRename.setToolTip(_translate("Dialog", "Copy file and rename it with session name"))
        self.pushButtonCopyRename.setText(_translate("Dialog", "Copy And Rename File"))
        self.pushButtonCopy.setText(_translate("Dialog", "Copy File"))
        self.pushButtonUseThisFile.setText(_translate("Dialog", "Use This File"))

