# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file 'resources/ui/save_template_session.ui'
#
# Created by: PyQt5 UI code generator 5.11.3
#
# WARNING! All changes made in this file will be lost!

from PyQt5 import QtCore, QtGui, QtWidgets

class Ui_DialogSaveTemplateSession(object):
    def setupUi(self, DialogSaveTemplateSession):
        DialogSaveTemplateSession.setObjectName("DialogSaveTemplateSession")
        DialogSaveTemplateSession.setWindowModality(QtCore.Qt.NonModal)
        DialogSaveTemplateSession.resize(371, 112)
        DialogSaveTemplateSession.setModal(False)
        self.verticalLayout = QtWidgets.QVBoxLayout(DialogSaveTemplateSession)
        self.verticalLayout.setObjectName("verticalLayout")
        spacerItem = QtWidgets.QSpacerItem(20, 40, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Expanding)
        self.verticalLayout.addItem(spacerItem)
        self.labelNewTemplateName = QtWidgets.QLabel(DialogSaveTemplateSession)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.labelNewTemplateName.sizePolicy().hasHeightForWidth())
        self.labelNewTemplateName.setSizePolicy(sizePolicy)
        self.labelNewTemplateName.setObjectName("labelNewTemplateName")
        self.verticalLayout.addWidget(self.labelNewTemplateName)
        self.lineEdit = QtWidgets.QLineEdit(DialogSaveTemplateSession)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.lineEdit.sizePolicy().hasHeightForWidth())
        self.lineEdit.setSizePolicy(sizePolicy)
        self.lineEdit.setObjectName("lineEdit")
        self.verticalLayout.addWidget(self.lineEdit)
        spacerItem1 = QtWidgets.QSpacerItem(20, 40, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Expanding)
        self.verticalLayout.addItem(spacerItem1)
        self.horizontalLayout = QtWidgets.QHBoxLayout()
        self.horizontalLayout.setSizeConstraint(QtWidgets.QLayout.SetFixedSize)
        self.horizontalLayout.setObjectName("horizontalLayout")
        spacerItem2 = QtWidgets.QSpacerItem(40, 20, QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum)
        self.horizontalLayout.addItem(spacerItem2)
        self.pushButtonAccept = QtWidgets.QPushButton(DialogSaveTemplateSession)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.pushButtonAccept.sizePolicy().hasHeightForWidth())
        self.pushButtonAccept.setSizePolicy(sizePolicy)
        icon = QtGui.QIcon.fromTheme("dialog-ok")
        self.pushButtonAccept.setIcon(icon)
        self.pushButtonAccept.setObjectName("pushButtonAccept")
        self.horizontalLayout.addWidget(self.pushButtonAccept)
        self.pushButtonCancel = QtWidgets.QPushButton(DialogSaveTemplateSession)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.pushButtonCancel.sizePolicy().hasHeightForWidth())
        self.pushButtonCancel.setSizePolicy(sizePolicy)
        icon = QtGui.QIcon.fromTheme("dialog-cancel")
        self.pushButtonCancel.setIcon(icon)
        self.pushButtonCancel.setObjectName("pushButtonCancel")
        self.horizontalLayout.addWidget(self.pushButtonCancel)
        self.verticalLayout.addLayout(self.horizontalLayout)

        self.retranslateUi(DialogSaveTemplateSession)
        self.pushButtonCancel.clicked.connect(DialogSaveTemplateSession.reject)
        QtCore.QMetaObject.connectSlotsByName(DialogSaveTemplateSession)

    def retranslateUi(self, DialogSaveTemplateSession):
        _translate = QtCore.QCoreApplication.translate
        DialogSaveTemplateSession.setWindowTitle(_translate("DialogSaveTemplateSession", "New Template"))
        self.labelNewTemplateName.setText(_translate("DialogSaveTemplateSession", "Session Template Name :"))
        self.pushButtonAccept.setText(_translate("DialogSaveTemplateSession", "Create Template"))
        self.pushButtonCancel.setText(_translate("DialogSaveTemplateSession", "Cancel"))

