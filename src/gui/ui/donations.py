# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file 'resources/ui/donations.ui'
#
# Created by: PyQt5 UI code generator 5.11.3
#
# WARNING! All changes made in this file will be lost!

from PyQt5 import QtCore, QtGui, QtWidgets

class Ui_Dialog(object):
    def setupUi(self, Dialog):
        Dialog.setObjectName("Dialog")
        Dialog.resize(427, 320)
        self.verticalLayout = QtWidgets.QVBoxLayout(Dialog)
        self.verticalLayout.setObjectName("verticalLayout")
        self.label = QtWidgets.QLabel(Dialog)
        self.label.setOpenExternalLinks(True)
        self.label.setObjectName("label")
        self.verticalLayout.addWidget(self.label)
        spacerItem = QtWidgets.QSpacerItem(20, 40, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Expanding)
        self.verticalLayout.addItem(spacerItem)
        self.checkBox = QtWidgets.QCheckBox(Dialog)
        self.checkBox.setChecked(False)
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
        Dialog.setWindowTitle(_translate("Dialog", "Donations"))
        self.label.setText(_translate("Dialog", "<html><head/><body><p>Hi !</p><p>it seems that you appreciate RaySession, that is already a good new.<br/>This software is free as in Speech and as in Beer,<br/>but it has required and still takes time.</p><p>Make a donation (even small) is a simple way to say &quot;Thank you&quot;.<br/>You can donate <a href=\"https://liberapay.com/Houston4444\"><span style=\" text-decoration: underline; color:#2980b9;\">here</span></a>.</p><p>If ever you donate nothing,<br/>this program will continue to work without limits of functionnality,<br/>without limit of duration, and even without insulting you ;) .</p></body></html>"))
        self.checkBox.setText(_translate("Dialog", "Do not show this message again"))

