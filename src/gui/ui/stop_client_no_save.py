# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file 'resources/ui/stop_client_no_save.ui'
#
# Created by: PyQt5 UI code generator 5.11.3
#
# WARNING! All changes made in this file will be lost!

from PyQt5 import QtCore, QtGui, QtWidgets

class Ui_Dialog(object):
    def setupUi(self, Dialog):
        Dialog.setObjectName("Dialog")
        Dialog.resize(400, 172)
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
        self.pushButtonStop = QtWidgets.QPushButton(Dialog)
        icon = QtGui.QIcon.fromTheme("media-playback-stop")
        self.pushButtonStop.setIcon(icon)
        self.pushButtonStop.setObjectName("pushButtonStop")
        self.horizontalLayout.addWidget(self.pushButtonStop)
        self.pushButtonCancel = QtWidgets.QPushButton(Dialog)
        icon = QtGui.QIcon.fromTheme("dialog-cancel")
        self.pushButtonCancel.setIcon(icon)
        self.pushButtonCancel.setObjectName("pushButtonCancel")
        self.horizontalLayout.addWidget(self.pushButtonCancel)
        self.verticalLayout_2.addLayout(self.horizontalLayout)

        self.retranslateUi(Dialog)
        self.pushButtonCancel.clicked.connect(Dialog.reject)
        self.pushButtonStop.clicked.connect(Dialog.accept)
        QtCore.QMetaObject.connectSlotsByName(Dialog)

    def retranslateUi(self, Dialog):
        _translate = QtCore.QCoreApplication.translate
        Dialog.setWindowTitle(_translate("Dialog", "Stop Client ?"))
        self.label.setText(_translate("Dialog", "<html><head/><body><p>We have no possibility to save the client <span style=\" font-weight:600;\">%s</span>.</p><p>For this reason, it\'s preferable that you close yourself this client,<br/>probably by closing its window, saving its changes or not.</p></body></html>"))
        self.checkBox.setText(_translate("Dialog", "Don\'t prevent to stop this client again (discouraged)"))
        self.pushButtonStop.setText(_translate("Dialog", "Stop Anyway"))
        self.pushButtonCancel.setText(_translate("Dialog", "Cancel"))

import resources_rc
