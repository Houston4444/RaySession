# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file 'resources/ui/waiting_close_user.ui'
#
# Created by: PyQt5 UI code generator 5.11.3
#
# WARNING! All changes made in this file will be lost!

from PyQt5 import QtCore, QtGui, QtWidgets

class Ui_Dialog(object):
    def setupUi(self, Dialog):
        Dialog.setObjectName("Dialog")
        Dialog.resize(353, 272)
        self.verticalLayout = QtWidgets.QVBoxLayout(Dialog)
        self.verticalLayout.setObjectName("verticalLayout")
        self.label = QtWidgets.QLabel(Dialog)
        self.label.setObjectName("label")
        self.verticalLayout.addWidget(self.label)
        self.horizontalLayout = QtWidgets.QHBoxLayout()
        self.horizontalLayout.setObjectName("horizontalLayout")
        spacerItem = QtWidgets.QSpacerItem(40, 20, QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum)
        self.horizontalLayout.addItem(spacerItem)
        self.labelSaveIcon = QtWidgets.QLabel(Dialog)
        self.labelSaveIcon.setText("")
        self.labelSaveIcon.setPixmap(QtGui.QPixmap(":/scalable/breeze/document-nosave.svg"))
        self.labelSaveIcon.setObjectName("labelSaveIcon")
        self.horizontalLayout.addWidget(self.labelSaveIcon)
        spacerItem1 = QtWidgets.QSpacerItem(40, 20, QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum)
        self.horizontalLayout.addItem(spacerItem1)
        self.verticalLayout.addLayout(self.horizontalLayout)
        spacerItem2 = QtWidgets.QSpacerItem(20, 40, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Expanding)
        self.verticalLayout.addItem(spacerItem2)
        self.label_2 = QtWidgets.QLabel(Dialog)
        self.label_2.setAlignment(QtCore.Qt.AlignRight|QtCore.Qt.AlignTrailing|QtCore.Qt.AlignVCenter)
        self.label_2.setObjectName("label_2")
        self.verticalLayout.addWidget(self.label_2)
        spacerItem3 = QtWidgets.QSpacerItem(20, 40, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Expanding)
        self.verticalLayout.addItem(spacerItem3)
        self.checkBox = QtWidgets.QCheckBox(Dialog)
        self.checkBox.setObjectName("checkBox")
        self.verticalLayout.addWidget(self.checkBox)
        self.horizontalLayout_2 = QtWidgets.QHBoxLayout()
        self.horizontalLayout_2.setObjectName("horizontalLayout_2")
        spacerItem4 = QtWidgets.QSpacerItem(40, 20, QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum)
        self.horizontalLayout_2.addItem(spacerItem4)
        self.pushButtonUndo = QtWidgets.QPushButton(Dialog)
        icon = QtGui.QIcon.fromTheme("edit-undo")
        self.pushButtonUndo.setIcon(icon)
        self.pushButtonUndo.setObjectName("pushButtonUndo")
        self.horizontalLayout_2.addWidget(self.pushButtonUndo)
        self.pushButtonOk = QtWidgets.QPushButton(Dialog)
        icon = QtGui.QIcon.fromTheme("dialog-ok")
        self.pushButtonOk.setIcon(icon)
        self.pushButtonOk.setObjectName("pushButtonOk")
        self.horizontalLayout_2.addWidget(self.pushButtonOk)
        self.pushButtonSkip = QtWidgets.QPushButton(Dialog)
        icon = QtGui.QIcon.fromTheme("go-next-skip")
        self.pushButtonSkip.setIcon(icon)
        self.pushButtonSkip.setObjectName("pushButtonSkip")
        self.horizontalLayout_2.addWidget(self.pushButtonSkip)
        self.verticalLayout.addLayout(self.horizontalLayout_2)

        self.retranslateUi(Dialog)
        self.pushButtonOk.clicked.connect(Dialog.accept)
        QtCore.QMetaObject.connectSlotsByName(Dialog)

    def retranslateUi(self, Dialog):
        _translate = QtCore.QCoreApplication.translate
        Dialog.setWindowTitle(_translate("Dialog", "Close clients yourself !"))
        self.label.setText(_translate("Dialog", "<html><head/><body><p align=\"center\">Some active clients do not offer any save possibility !</p><p align=\"center\">Therefore, it is best that you close these clients yourself,<br/>probably by closing their windows and saving changes.</p><p align=\"center\"><span style=\" font-weight:600;\">Please close yourself the programs with this save icon:</span></p></body></html>"))
        self.label_2.setText(_translate("Dialog", "<html><head/><body><p>You\'ve got 2 minutes !<br/><span style=\" font-style:italic;\">You can do it without closing this dialog window.</span></p></body></html>"))
        self.checkBox.setText(_translate("Dialog", "Do not show again"))
        self.pushButtonUndo.setText(_translate("Dialog", "Undo"))
        self.pushButtonOk.setText(_translate("Dialog", "Ok"))
        self.pushButtonSkip.setText(_translate("Dialog", "Skip"))

import resources_rc
