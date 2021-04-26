# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file 'resources/ui/canvas_options.ui'
#
# Created by: PyQt5 UI code generator 5.11.3
#
# WARNING! All changes made in this file will be lost!

from PyQt5 import QtCore, QtGui, QtWidgets

class Ui_Dialog(object):
    def setupUi(self, Dialog):
        Dialog.setObjectName("Dialog")
        Dialog.resize(201, 172)
        self.verticalLayout_2 = QtWidgets.QVBoxLayout(Dialog)
        self.verticalLayout_2.setObjectName("verticalLayout_2")
        self.verticalLayout = QtWidgets.QVBoxLayout()
        self.verticalLayout.setObjectName("verticalLayout")
        spacerItem = QtWidgets.QSpacerItem(20, 40, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Expanding)
        self.verticalLayout.addItem(spacerItem)
        self.checkBoxGracefulNames = QtWidgets.QCheckBox(Dialog)
        self.checkBoxGracefulNames.setObjectName("checkBoxGracefulNames")
        self.verticalLayout.addWidget(self.checkBoxGracefulNames)
        self.checkBoxA2J = QtWidgets.QCheckBox(Dialog)
        self.checkBoxA2J.setObjectName("checkBoxA2J")
        self.verticalLayout.addWidget(self.checkBoxA2J)
        self.checkBoxShadows = QtWidgets.QCheckBox(Dialog)
        self.checkBoxShadows.setObjectName("checkBoxShadows")
        self.verticalLayout.addWidget(self.checkBoxShadows)
        self.checkBoxElastic = QtWidgets.QCheckBox(Dialog)
        self.checkBoxElastic.setObjectName("checkBoxElastic")
        self.verticalLayout.addWidget(self.checkBoxElastic)
        self.horizontalLayout = QtWidgets.QHBoxLayout()
        self.horizontalLayout.setObjectName("horizontalLayout")
        self.label = QtWidgets.QLabel(Dialog)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Preferred)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.label.sizePolicy().hasHeightForWidth())
        self.label.setSizePolicy(sizePolicy)
        self.label.setObjectName("label")
        self.horizontalLayout.addWidget(self.label)
        self.comboBoxTheme = QtWidgets.QComboBox(Dialog)
        self.comboBoxTheme.setObjectName("comboBoxTheme")
        self.horizontalLayout.addWidget(self.comboBoxTheme)
        self.verticalLayout.addLayout(self.horizontalLayout)
        spacerItem1 = QtWidgets.QSpacerItem(20, 40, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Expanding)
        self.verticalLayout.addItem(spacerItem1)
        self.verticalLayout_2.addLayout(self.verticalLayout)

        self.retranslateUi(Dialog)
        QtCore.QMetaObject.connectSlotsByName(Dialog)

    def retranslateUi(self, Dialog):
        _translate = QtCore.QCoreApplication.translate
        Dialog.setWindowTitle(_translate("Dialog", "Canvas Options"))
        self.checkBoxGracefulNames.setToolTip(_translate("Dialog", "<html><head/><body><p>Display shorter and more readable ports and groups names.</p><p>If unchecked, displayed port names will be the trought port names.</p></body></html>"))
        self.checkBoxGracefulNames.setText(_translate("Dialog", "Use graceful names"))
        self.checkBoxA2J.setText(_translate("Dialog", "Group A2J hardware ports"))
        self.checkBoxShadows.setText(_translate("Dialog", "Boxes have shadows"))
        self.checkBoxElastic.setToolTip(_translate("Dialog", "<html><head/><body><p>Always resize the canvas scene to the mininum contents.</p><p>This way, the view is directly optimized while moving boxes.</p></body></html>"))
        self.checkBoxElastic.setText(_translate("Dialog", "Elastic canvas"))
        self.label.setText(_translate("Dialog", "Theme :"))

