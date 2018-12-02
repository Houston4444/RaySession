# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file 'resources/ui/open_session.ui'
#
# Created by: PyQt5 UI code generator 5.11.3
#
# WARNING! All changes made in this file will be lost!

from PyQt5 import QtCore, QtGui, QtWidgets

class Ui_DialogOpenSession(object):
    def setupUi(self, DialogOpenSession):
        DialogOpenSession.setObjectName("DialogOpenSession")
        DialogOpenSession.setWindowModality(QtCore.Qt.NonModal)
        DialogOpenSession.resize(336, 379)
        DialogOpenSession.setModal(False)
        self.verticalLayout = QtWidgets.QVBoxLayout(DialogOpenSession)
        self.verticalLayout.setObjectName("verticalLayout")
        self.horizontalLayout = QtWidgets.QHBoxLayout()
        self.horizontalLayout.setObjectName("horizontalLayout")
        self.labelNsmFolder = QtWidgets.QLabel(DialogOpenSession)
        self.labelNsmFolder.setAlignment(QtCore.Qt.AlignLeading|QtCore.Qt.AlignLeft|QtCore.Qt.AlignVCenter)
        self.labelNsmFolder.setObjectName("labelNsmFolder")
        self.horizontalLayout.addWidget(self.labelNsmFolder)
        self.currentNsmFolder = QtWidgets.QLabel(DialogOpenSession)
        self.currentNsmFolder.setStyleSheet("font-style :  italic")
        self.currentNsmFolder.setObjectName("currentNsmFolder")
        self.horizontalLayout.addWidget(self.currentNsmFolder)
        self.toolButtonFolder = QtWidgets.QToolButton(DialogOpenSession)
        icon = QtGui.QIcon.fromTheme("folder-open")
        self.toolButtonFolder.setIcon(icon)
        self.toolButtonFolder.setObjectName("toolButtonFolder")
        self.horizontalLayout.addWidget(self.toolButtonFolder)
        self.verticalLayout.addLayout(self.horizontalLayout)
        spacerItem = QtWidgets.QSpacerItem(20, 10, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Fixed)
        self.verticalLayout.addItem(spacerItem)
        self.horizontalLayout_2 = QtWidgets.QHBoxLayout()
        self.horizontalLayout_2.setObjectName("horizontalLayout_2")
        self.label = QtWidgets.QLabel(DialogOpenSession)
        self.label.setObjectName("label")
        self.horizontalLayout_2.addWidget(self.label)
        self.filterBar = OpenSessionFilterBar(DialogOpenSession)
        self.filterBar.setObjectName("filterBar")
        self.horizontalLayout_2.addWidget(self.filterBar)
        self.verticalLayout.addLayout(self.horizontalLayout_2)
        self.sessionList = QtWidgets.QListWidget(DialogOpenSession)
        self.sessionList.setAlternatingRowColors(False)
        self.sessionList.setObjectName("sessionList")
        self.verticalLayout.addWidget(self.sessionList)
        self.buttonBox = QtWidgets.QDialogButtonBox(DialogOpenSession)
        self.buttonBox.setEnabled(True)
        self.buttonBox.setOrientation(QtCore.Qt.Horizontal)
        self.buttonBox.setStandardButtons(QtWidgets.QDialogButtonBox.Cancel|QtWidgets.QDialogButtonBox.Ok)
        self.buttonBox.setObjectName("buttonBox")
        self.verticalLayout.addWidget(self.buttonBox)

        self.retranslateUi(DialogOpenSession)
        self.buttonBox.accepted.connect(DialogOpenSession.accept)
        self.buttonBox.rejected.connect(DialogOpenSession.reject)
        QtCore.QMetaObject.connectSlotsByName(DialogOpenSession)

    def retranslateUi(self, DialogOpenSession):
        _translate = QtCore.QCoreApplication.translate
        DialogOpenSession.setWindowTitle(_translate("DialogOpenSession", "Open Session"))
        self.labelNsmFolder.setText(_translate("DialogOpenSession", "Sessions Folder :"))
        self.currentNsmFolder.setText(_translate("DialogOpenSession", "/home/user/NSM Sessions"))
        self.toolButtonFolder.setText(_translate("DialogOpenSession", "Folder"))
        self.label.setText(_translate("DialogOpenSession", "Filter :"))
        self.sessionList.setSortingEnabled(True)

from opensessionfilterbar import OpenSessionFilterBar
