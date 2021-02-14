# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file 'resources/ui/template_slot.ui'
#
# Created by: PyQt5 UI code generator 5.11.3
#
# WARNING! All changes made in this file will be lost!

from PyQt5 import QtCore, QtGui, QtWidgets

class Ui_Frame(object):
    def setupUi(self, Frame):
        Frame.setObjectName("Frame")
        Frame.resize(369, 33)
        self.horizontalLayout_2 = QtWidgets.QHBoxLayout(Frame)
        self.horizontalLayout_2.setContentsMargins(4, 2, 4, 2)
        self.horizontalLayout_2.setObjectName("horizontalLayout_2")
        self.toolButtonIcon = FakeToolButton(Frame)
        self.toolButtonIcon.setStyleSheet("QToolButton {border: none}")
        self.toolButtonIcon.setIconSize(QtCore.QSize(22, 22))
        self.toolButtonIcon.setObjectName("toolButtonIcon")
        self.horizontalLayout_2.addWidget(self.toolButtonIcon)
        self.label = QtWidgets.QLabel(Frame)
        self.label.setObjectName("label")
        self.horizontalLayout_2.addWidget(self.label)
        spacerItem = QtWidgets.QSpacerItem(40, 20, QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum)
        self.horizontalLayout_2.addItem(spacerItem)
        self.toolButtonUser = QtWidgets.QToolButton(Frame)
        self.toolButtonUser.setStyleSheet("QToolButton::menu-indicator{ image: url(none.jpg);}\n"
"QToolButton {border: none}")
        icon = QtGui.QIcon()
        icon.addPixmap(QtGui.QPixmap(":/scalable/breeze/im-user.svg"), QtGui.QIcon.Normal, QtGui.QIcon.Off)
        self.toolButtonUser.setIcon(icon)
        self.toolButtonUser.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self.toolButtonUser.setObjectName("toolButtonUser")
        self.horizontalLayout_2.addWidget(self.toolButtonUser)
        self.toolButtonFavorite = favoriteToolButton(Frame)
        self.toolButtonFavorite.setStyleSheet("QToolButton {border: none}")
        icon1 = QtGui.QIcon()
        icon1.addPixmap(QtGui.QPixmap(":/scalable/breeze/draw-star.svg"), QtGui.QIcon.Normal, QtGui.QIcon.Off)
        self.toolButtonFavorite.setIcon(icon1)
        self.toolButtonFavorite.setObjectName("toolButtonFavorite")
        self.horizontalLayout_2.addWidget(self.toolButtonFavorite)

        self.retranslateUi(Frame)
        QtCore.QMetaObject.connectSlotsByName(Frame)

    def retranslateUi(self, Frame):
        _translate = QtCore.QCoreApplication.translate
        Frame.setWindowTitle(_translate("Frame", "Frame"))
        self.toolButtonIcon.setText(_translate("Frame", "..."))
        self.label.setText(_translate("Frame", "Template Name"))
        self.toolButtonUser.setText(_translate("Frame", "..."))
        self.toolButtonFavorite.setText(_translate("Frame", "..."))

from surclassed_widgets import FakeToolButton, favoriteToolButton
import resources_rc
