# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file 'resources/ui/stop_client.ui'
#
# Created by: PyQt5 UI code generator 5.11.3
#
# WARNING! All changes made in this file will be lost!

from PyQt5 import QtCore, QtGui, QtWidgets

class Ui_Dialog(object):
    def setupUi(self, Dialog):
        Dialog.setObjectName("Dialog")
        Dialog.resize(315, 159)
        self.verticalLayout_2 = QtWidgets.QVBoxLayout(Dialog)
        self.verticalLayout_2.setObjectName("verticalLayout_2")
        spacerItem = QtWidgets.QSpacerItem(20, 40, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Expanding)
        self.verticalLayout_2.addItem(spacerItem)
        self.label = QtWidgets.QLabel(Dialog)
        self.label.setAlignment(QtCore.Qt.AlignCenter)
        self.label.setObjectName("label")
        self.verticalLayout_2.addWidget(self.label)
        spacerItem1 = QtWidgets.QSpacerItem(20, 40, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Expanding)
        self.verticalLayout_2.addItem(spacerItem1)
        self.checkBox = QtWidgets.QCheckBox(Dialog)
        self.checkBox.setObjectName("checkBox")
        self.verticalLayout_2.addWidget(self.checkBox)
        self.horizontalLayout = QtWidgets.QHBoxLayout()
        self.horizontalLayout.setObjectName("horizontalLayout")
        spacerItem2 = QtWidgets.QSpacerItem(40, 20, QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum)
        self.horizontalLayout.addItem(spacerItem2)
        self.pushButtonSaveStop = QtWidgets.QPushButton(Dialog)
        icon = QtGui.QIcon.fromTheme("media-playback-stop")
        self.pushButtonSaveStop.setIcon(icon)
        self.pushButtonSaveStop.setObjectName("pushButtonSaveStop")
        self.horizontalLayout.addWidget(self.pushButtonSaveStop)
        self.pushButtonStop = QtWidgets.QPushButton(Dialog)
        icon = QtGui.QIcon.fromTheme("media-playback-stop")
        self.pushButtonStop.setIcon(icon)
        self.pushButtonStop.setObjectName("pushButtonStop")
        self.horizontalLayout.addWidget(self.pushButtonStop)
        self.pushButtonClancel = QtWidgets.QPushButton(Dialog)
        icon = QtGui.QIcon.fromTheme("dialog-cancel")
        self.pushButtonClancel.setIcon(icon)
        self.pushButtonClancel.setObjectName("pushButtonClancel")
        self.horizontalLayout.addWidget(self.pushButtonClancel)
        self.verticalLayout_2.addLayout(self.horizontalLayout)

        self.retranslateUi(Dialog)
        self.pushButtonClancel.clicked.connect(Dialog.reject)
        self.pushButtonStop.clicked.connect(Dialog.accept)
        QtCore.QMetaObject.connectSlotsByName(Dialog)

    def retranslateUi(self, Dialog):
        _translate = QtCore.QCoreApplication.translate
        Dialog.setWindowTitle(_translate("Dialog", "Stop Client ?"))
        self.label.setText(_translate("Dialog", "<html><head/><body><p><span style=\" font-weight:600;\">%s</span> contains unsaved changes. </p><p>Do you really want to stop it ?</p></body></html>"))
        self.checkBox.setText(_translate("Dialog", "Don\'t prevent to stop this client again !"))
        self.pushButtonSaveStop.setText(_translate("Dialog", "Save && Stop"))
        self.pushButtonStop.setText(_translate("Dialog", "Just Stop"))
        self.pushButtonClancel.setText(_translate("Dialog", "Cancel"))

import resources_rc
