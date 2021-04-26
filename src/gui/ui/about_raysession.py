# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file 'resources/ui/about_raysession.ui'
#
# Created by: PyQt5 UI code generator 5.11.3
#
# WARNING! All changes made in this file will be lost!

from PyQt5 import QtCore, QtGui, QtWidgets

class Ui_DialogAboutRaysession(object):
    def setupUi(self, DialogAboutRaysession):
        DialogAboutRaysession.setObjectName("DialogAboutRaysession")
        DialogAboutRaysession.resize(550, 310)
        self.verticalLayout = QtWidgets.QVBoxLayout(DialogAboutRaysession)
        self.verticalLayout.setObjectName("verticalLayout")
        self.horizontalLayout = QtWidgets.QHBoxLayout()
        self.horizontalLayout.setObjectName("horizontalLayout")
        self.label_2 = QtWidgets.QLabel(DialogAboutRaysession)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Preferred)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.label_2.sizePolicy().hasHeightForWidth())
        self.label_2.setSizePolicy(sizePolicy)
        self.label_2.setAlignment(QtCore.Qt.AlignLeading|QtCore.Qt.AlignLeft|QtCore.Qt.AlignTop)
        self.label_2.setObjectName("label_2")
        self.horizontalLayout.addWidget(self.label_2)
        self.verticalLayout_3 = QtWidgets.QVBoxLayout()
        self.verticalLayout_3.setObjectName("verticalLayout_3")
        self.labelRayAndVersion = QtWidgets.QLabel(DialogAboutRaysession)
        self.labelRayAndVersion.setAlignment(QtCore.Qt.AlignLeading|QtCore.Qt.AlignLeft|QtCore.Qt.AlignTop)
        self.labelRayAndVersion.setObjectName("labelRayAndVersion")
        self.verticalLayout_3.addWidget(self.labelRayAndVersion)
        self.labelAllText = QtWidgets.QLabel(DialogAboutRaysession)
        self.labelAllText.setWordWrap(True)
        self.labelAllText.setOpenExternalLinks(True)
        self.labelAllText.setObjectName("labelAllText")
        self.verticalLayout_3.addWidget(self.labelAllText)
        self.horizontalLayout.addLayout(self.verticalLayout_3)
        self.verticalLayout.addLayout(self.horizontalLayout)
        self.buttonBox = QtWidgets.QDialogButtonBox(DialogAboutRaysession)
        self.buttonBox.setOrientation(QtCore.Qt.Horizontal)
        self.buttonBox.setStandardButtons(QtWidgets.QDialogButtonBox.Ok)
        self.buttonBox.setObjectName("buttonBox")
        self.verticalLayout.addWidget(self.buttonBox)

        self.retranslateUi(DialogAboutRaysession)
        self.buttonBox.accepted.connect(DialogAboutRaysession.accept)
        self.buttonBox.rejected.connect(DialogAboutRaysession.reject)
        QtCore.QMetaObject.connectSlotsByName(DialogAboutRaysession)

    def retranslateUi(self, DialogAboutRaysession):
        _translate = QtCore.QCoreApplication.translate
        DialogAboutRaysession.setWindowTitle(_translate("DialogAboutRaysession", "About RaySession"))
        self.label_2.setText(_translate("DialogAboutRaysession", "<html><head/><body><p><img src=\":/128x128/raysession.png\"/></p></body></html>"))
        self.labelRayAndVersion.setText(_translate("DialogAboutRaysession", "<html><head/><body><p><span style=\" font-weight:600;\">RaySession</span></p><p>version : %s</p></body></html>"))
        self.labelAllText.setText(_translate("DialogAboutRaysession", "<html><head/><body><p>Ray Session is a Qt interface for the ray-daemon.</p><p>Its goal is to manage together audio programs as Ardour, Carla, Qtractor, Non-Timeline in an unique session.</p><p>Programs just have to be compatible with the <a href=\"http://non.tuxfamily.org/wiki/Non%20Session%20Manager\"><span style=\" text-decoration: underline; color:#2980b9;\">NSM</span></a> API to work with Ray Session.<br/></p><p align=\"right\">Copyright (C) 2016-2021 houston4444</p><p><br/></p></body></html>"))

import resources_rc
