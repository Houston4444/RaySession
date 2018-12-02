# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file 'resources/ui/new_executable.ui'
#
# Created by: PyQt5 UI code generator 5.11.3
#
# WARNING! All changes made in this file will be lost!

from PyQt5 import QtCore, QtGui, QtWidgets

class Ui_DialogNewExecutable(object):
    def setupUi(self, DialogNewExecutable):
        DialogNewExecutable.setObjectName("DialogNewExecutable")
        DialogNewExecutable.setWindowModality(QtCore.Qt.NonModal)
        DialogNewExecutable.resize(221, 124)
        DialogNewExecutable.setModal(False)
        self.verticalLayout = QtWidgets.QVBoxLayout(DialogNewExecutable)
        self.verticalLayout.setObjectName("verticalLayout")
        self.labelExecutable = QtWidgets.QLabel(DialogNewExecutable)
        self.labelExecutable.setObjectName("labelExecutable")
        self.verticalLayout.addWidget(self.labelExecutable)
        self.lineEdit = QtWidgets.QLineEdit(DialogNewExecutable)
        self.lineEdit.setObjectName("lineEdit")
        self.verticalLayout.addWidget(self.lineEdit)
        self.checkBoxProxy = QtWidgets.QCheckBox(DialogNewExecutable)
        self.checkBoxProxy.setObjectName("checkBoxProxy")
        self.verticalLayout.addWidget(self.checkBoxProxy)
        self.buttonBox = QtWidgets.QDialogButtonBox(DialogNewExecutable)
        self.buttonBox.setEnabled(True)
        self.buttonBox.setOrientation(QtCore.Qt.Horizontal)
        self.buttonBox.setStandardButtons(QtWidgets.QDialogButtonBox.Cancel|QtWidgets.QDialogButtonBox.Ok)
        self.buttonBox.setObjectName("buttonBox")
        self.verticalLayout.addWidget(self.buttonBox)

        self.retranslateUi(DialogNewExecutable)
        self.buttonBox.accepted.connect(DialogNewExecutable.accept)
        self.buttonBox.rejected.connect(DialogNewExecutable.reject)
        QtCore.QMetaObject.connectSlotsByName(DialogNewExecutable)

    def retranslateUi(self, DialogNewExecutable):
        _translate = QtCore.QCoreApplication.translate
        DialogNewExecutable.setWindowTitle(_translate("DialogNewExecutable", "New Executable Client"))
        self.labelExecutable.setText(_translate("DialogNewExecutable", "Executable :"))
        self.checkBoxProxy.setToolTip(_translate("DialogNewExecutable", "<html><head/><body><p>If program is not compatible with the NSM API, </p><p>you should launch it in proxy to define a config file !</p></body></html>"))
        self.checkBoxProxy.setText(_translate("DialogNewExecutable", "Run via Proxy"))

