# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file 'resources/ui/snapshot_name.ui'
#
# Created by: PyQt5 UI code generator 5.11.3
#
# WARNING! All changes made in this file will be lost!

from PyQt5 import QtCore, QtGui, QtWidgets

class Ui_Dialog(object):
    def setupUi(self, Dialog):
        Dialog.setObjectName("Dialog")
        Dialog.resize(401, 198)
        self.verticalLayout = QtWidgets.QVBoxLayout(Dialog)
        self.verticalLayout.setObjectName("verticalLayout")
        spacerItem = QtWidgets.QSpacerItem(20, 40, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Expanding)
        self.verticalLayout.addItem(spacerItem)
        self.label = QtWidgets.QLabel(Dialog)
        self.label.setObjectName("label")
        self.verticalLayout.addWidget(self.label)
        self.lineEdit = QtWidgets.QLineEdit(Dialog)
        self.lineEdit.setObjectName("lineEdit")
        self.verticalLayout.addWidget(self.lineEdit)
        spacerItem1 = QtWidgets.QSpacerItem(20, 40, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Expanding)
        self.verticalLayout.addItem(spacerItem1)
        self.labelExecutable = QtWidgets.QLabel(Dialog)
        self.labelExecutable.setAlignment(QtCore.Qt.AlignCenter)
        self.labelExecutable.setObjectName("labelExecutable")
        self.verticalLayout.addWidget(self.labelExecutable)
        self.horizontalLayout_2 = QtWidgets.QHBoxLayout()
        self.horizontalLayout_2.setObjectName("horizontalLayout_2")
        self.pushButtonSave = QtWidgets.QPushButton(Dialog)
        icon = QtGui.QIcon.fromTheme("document-save")
        self.pushButtonSave.setIcon(icon)
        self.pushButtonSave.setObjectName("pushButtonSave")
        self.horizontalLayout_2.addWidget(self.pushButtonSave)
        self.pushButtonSnapshot = QtWidgets.QPushButton(Dialog)
        icon = QtGui.QIcon.fromTheme("deep-history")
        self.pushButtonSnapshot.setIcon(icon)
        self.pushButtonSnapshot.setObjectName("pushButtonSnapshot")
        self.horizontalLayout_2.addWidget(self.pushButtonSnapshot)
        self.pushButtonCancel = QtWidgets.QPushButton(Dialog)
        icon = QtGui.QIcon.fromTheme("dialog-cancel")
        self.pushButtonCancel.setIcon(icon)
        self.pushButtonCancel.setObjectName("pushButtonCancel")
        self.horizontalLayout_2.addWidget(self.pushButtonCancel)
        self.verticalLayout.addLayout(self.horizontalLayout_2)

        self.retranslateUi(Dialog)
        self.pushButtonCancel.clicked.connect(Dialog.reject)
        self.pushButtonSnapshot.clicked.connect(Dialog.accept)
        QtCore.QMetaObject.connectSlotsByName(Dialog)

    def retranslateUi(self, Dialog):
        _translate = QtCore.QCoreApplication.translate
        Dialog.setWindowTitle(_translate("Dialog", "Name Snapshot"))
        self.label.setText(_translate("Dialog", "Snapshot Name :"))
        self.labelExecutable.setText(_translate("Dialog", "<html><head/><body><p>You can save the session before the snapshot.</p><p>Save is recommended,<br/>unless you made unwanted changes since the last session save.</p></body></html>"))
        self.pushButtonSave.setText(_translate("Dialog", "Save && Snapshot"))
        self.pushButtonSnapshot.setText(_translate("Dialog", "Snapshot Only"))
        self.pushButtonCancel.setText(_translate("Dialog", "Cancel"))

