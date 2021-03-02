# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file 'resources/ui/abort_session.ui'
#
# Created by: PyQt5 UI code generator 5.11.3
#
# WARNING! All changes made in this file will be lost!

from PyQt5 import QtCore, QtGui, QtWidgets

class Ui_AbortSession(object):
    def setupUi(self, AbortSession):
        AbortSession.setObjectName("AbortSession")
        AbortSession.setWindowModality(QtCore.Qt.NonModal)
        AbortSession.resize(342, 72)
        AbortSession.setModal(False)
        self.verticalLayout = QtWidgets.QVBoxLayout(AbortSession)
        self.verticalLayout.setObjectName("verticalLayout")
        self.labelExecutable = QtWidgets.QLabel(AbortSession)
        self.labelExecutable.setAlignment(QtCore.Qt.AlignCenter)
        self.labelExecutable.setObjectName("labelExecutable")
        self.verticalLayout.addWidget(self.labelExecutable)
        self.horizontalLayout = QtWidgets.QHBoxLayout()
        self.horizontalLayout.setObjectName("horizontalLayout")
        self.pushButtonAbort = QtWidgets.QPushButton(AbortSession)
        icon = QtGui.QIcon.fromTheme("list-remove")
        self.pushButtonAbort.setIcon(icon)
        self.pushButtonAbort.setObjectName("pushButtonAbort")
        self.horizontalLayout.addWidget(self.pushButtonAbort)
        self.pushButtonCancel = QtWidgets.QPushButton(AbortSession)
        icon = QtGui.QIcon.fromTheme("dialog-cancel")
        self.pushButtonCancel.setIcon(icon)
        self.pushButtonCancel.setObjectName("pushButtonCancel")
        self.horizontalLayout.addWidget(self.pushButtonCancel)
        self.verticalLayout.addLayout(self.horizontalLayout)

        self.retranslateUi(AbortSession)
        self.pushButtonCancel.clicked.connect(AbortSession.reject)
        QtCore.QMetaObject.connectSlotsByName(AbortSession)

    def retranslateUi(self, AbortSession):
        _translate = QtCore.QCoreApplication.translate
        AbortSession.setWindowTitle(_translate("AbortSession", "Abort Session ?"))
        self.labelExecutable.setText(_translate("AbortSession", "<html><head/><body><p>Are you sure to want to abort session without saving ?</p></body></html>"))
        self.pushButtonAbort.setText(_translate("AbortSession", "Abort"))
        self.pushButtonCancel.setText(_translate("AbortSession", "Cancel"))

