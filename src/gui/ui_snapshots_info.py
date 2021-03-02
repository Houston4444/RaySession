# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file 'resources/ui/snapshots_info.ui'
#
# Created by: PyQt5 UI code generator 5.11.3
#
# WARNING! All changes made in this file will be lost!

from PyQt5 import QtCore, QtGui, QtWidgets

class Ui_Dialog(object):
    def setupUi(self, Dialog):
        Dialog.setObjectName("Dialog")
        Dialog.resize(403, 300)
        self.verticalLayout = QtWidgets.QVBoxLayout(Dialog)
        self.verticalLayout.setObjectName("verticalLayout")
        self.label = QtWidgets.QLabel(Dialog)
        self.label.setObjectName("label")
        self.verticalLayout.addWidget(self.label)
        spacerItem = QtWidgets.QSpacerItem(20, 40, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Expanding)
        self.verticalLayout.addItem(spacerItem)
        self.checkBox = QtWidgets.QCheckBox(Dialog)
        self.checkBox.setChecked(True)
        self.checkBox.setObjectName("checkBox")
        self.verticalLayout.addWidget(self.checkBox)
        self.buttonBox = QtWidgets.QDialogButtonBox(Dialog)
        self.buttonBox.setOrientation(QtCore.Qt.Horizontal)
        self.buttonBox.setStandardButtons(QtWidgets.QDialogButtonBox.Ok)
        self.buttonBox.setObjectName("buttonBox")
        self.verticalLayout.addWidget(self.buttonBox)

        self.retranslateUi(Dialog)
        self.buttonBox.accepted.connect(Dialog.accept)
        self.buttonBox.rejected.connect(Dialog.reject)
        QtCore.QMetaObject.connectSlotsByName(Dialog)

    def retranslateUi(self, Dialog):
        _translate = QtCore.QCoreApplication.translate
        Dialog.setWindowTitle(_translate("Dialog", "Snapshots Informations"))
        self.label.setText(_translate("Dialog", "<html><head/><body><p>Snapshots are NOT backups !!!</p><p>Besides, It\'s not overrated to copy your session folder elsewhere<br/>before to ask a previous snapshot.</p><p>Snapshots ignore audio files and other big files (&gt;50Mb),<br/>else snapshot process would be too long, <br/>and the session folder size would be too big.</p><p>That being said, you can decide that your work in the last hours<br/>was not a good idea and return to a previous snapshot !</p></body></html>"))
        self.checkBox.setText(_translate("Dialog", "Do not show this message again"))

