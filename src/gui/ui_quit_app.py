# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file 'resources/ui/quit_app.ui'
#
# Created by: PyQt5 UI code generator 5.11.3
#
# WARNING! All changes made in this file will be lost!

from PyQt5 import QtCore, QtGui, QtWidgets

class Ui_DialogQuitApp(object):
    def setupUi(self, DialogQuitApp):
        DialogQuitApp.setObjectName("DialogQuitApp")
        DialogQuitApp.setWindowModality(QtCore.Qt.NonModal)
        DialogQuitApp.resize(376, 159)
        DialogQuitApp.setModal(False)
        self.verticalLayout = QtWidgets.QVBoxLayout(DialogQuitApp)
        self.verticalLayout.setObjectName("verticalLayout")
        self.labelExecutable = QtWidgets.QLabel(DialogQuitApp)
        self.labelExecutable.setAlignment(QtCore.Qt.AlignCenter)
        self.labelExecutable.setObjectName("labelExecutable")
        self.verticalLayout.addWidget(self.labelExecutable)
        self.horizontalLayout = QtWidgets.QHBoxLayout()
        self.horizontalLayout.setObjectName("horizontalLayout")
        self.pushButtonSaveQuit = QtWidgets.QPushButton(DialogQuitApp)
        icon = QtGui.QIcon.fromTheme("document-save")
        self.pushButtonSaveQuit.setIcon(icon)
        self.pushButtonSaveQuit.setObjectName("pushButtonSaveQuit")
        self.horizontalLayout.addWidget(self.pushButtonSaveQuit)
        self.pushButtonQuitNoSave = QtWidgets.QPushButton(DialogQuitApp)
        icon = QtGui.QIcon.fromTheme("dialog-close")
        self.pushButtonQuitNoSave.setIcon(icon)
        self.pushButtonQuitNoSave.setObjectName("pushButtonQuitNoSave")
        self.horizontalLayout.addWidget(self.pushButtonQuitNoSave)
        self.pushButtonCancel = QtWidgets.QPushButton(DialogQuitApp)
        icon = QtGui.QIcon.fromTheme("dialog-cancel")
        self.pushButtonCancel.setIcon(icon)
        self.pushButtonCancel.setObjectName("pushButtonCancel")
        self.horizontalLayout.addWidget(self.pushButtonCancel)
        self.verticalLayout.addLayout(self.horizontalLayout)

        self.retranslateUi(DialogQuitApp)
        self.pushButtonCancel.clicked.connect(DialogQuitApp.reject)
        QtCore.QMetaObject.connectSlotsByName(DialogQuitApp)

    def retranslateUi(self, DialogQuitApp):
        _translate = QtCore.QCoreApplication.translate
        DialogQuitApp.setWindowTitle(_translate("DialogQuitApp", "Quit RaySession"))
        self.labelExecutable.setText(_translate("DialogQuitApp", "<p>Session <bold>%s</bold> is running.</p><p>RaySession will be closed.</p><p>Do you want to save session ?"))
        self.pushButtonSaveQuit.setText(_translate("DialogQuitApp", "Save && Quit"))
        self.pushButtonQuitNoSave.setText(_translate("DialogQuitApp", "Quit Without Saving"))
        self.pushButtonCancel.setText(_translate("DialogQuitApp", "Cancel"))

