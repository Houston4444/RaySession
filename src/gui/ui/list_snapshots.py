# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file 'resources/ui/list_snapshots.ui'
#
# Created by: PyQt5 UI code generator 5.11.3
#
# WARNING! All changes made in this file will be lost!

from PyQt5 import QtCore, QtGui, QtWidgets

class Ui_Dialog(object):
    def setupUi(self, Dialog):
        Dialog.setObjectName("Dialog")
        Dialog.setWindowModality(QtCore.Qt.NonModal)
        Dialog.resize(399, 338)
        Dialog.setModal(False)
        self.verticalLayout = QtWidgets.QVBoxLayout(Dialog)
        self.verticalLayout.setObjectName("verticalLayout")
        self.label = QtWidgets.QLabel(Dialog)
        self.label.setObjectName("label")
        self.verticalLayout.addWidget(self.label)
        spacerItem = QtWidgets.QSpacerItem(20, 40, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Expanding)
        self.verticalLayout.addItem(spacerItem)
        self.horizontalLayout = QtWidgets.QHBoxLayout()
        self.horizontalLayout.setObjectName("horizontalLayout")
        spacerItem1 = QtWidgets.QSpacerItem(40, 20, QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum)
        self.horizontalLayout.addItem(spacerItem1)
        self.pushButtonSnapshotNow = QtWidgets.QPushButton(Dialog)
        icon = QtGui.QIcon.fromTheme("camera-photo")
        self.pushButtonSnapshotNow.setIcon(icon)
        self.pushButtonSnapshotNow.setObjectName("pushButtonSnapshotNow")
        self.horizontalLayout.addWidget(self.pushButtonSnapshotNow)
        spacerItem2 = QtWidgets.QSpacerItem(40, 20, QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum)
        self.horizontalLayout.addItem(spacerItem2)
        self.verticalLayout.addLayout(self.horizontalLayout)
        self.snapshotsList = QtWidgets.QTreeWidget(Dialog)
        self.snapshotsList.setAlternatingRowColors(False)
        self.snapshotsList.setAllColumnsShowFocus(False)
        self.snapshotsList.setHeaderHidden(True)
        self.snapshotsList.setColumnCount(1)
        self.snapshotsList.setObjectName("snapshotsList")
        self.verticalLayout.addWidget(self.snapshotsList)
        self.checkBoxAutoSnapshot = QtWidgets.QCheckBox(Dialog)
        self.checkBoxAutoSnapshot.setObjectName("checkBoxAutoSnapshot")
        self.verticalLayout.addWidget(self.checkBoxAutoSnapshot)
        self.buttonBox = QtWidgets.QDialogButtonBox(Dialog)
        self.buttonBox.setEnabled(True)
        self.buttonBox.setOrientation(QtCore.Qt.Horizontal)
        self.buttonBox.setStandardButtons(QtWidgets.QDialogButtonBox.Cancel|QtWidgets.QDialogButtonBox.Ok)
        self.buttonBox.setObjectName("buttonBox")
        self.verticalLayout.addWidget(self.buttonBox)

        self.retranslateUi(Dialog)
        self.buttonBox.accepted.connect(Dialog.accept)
        self.buttonBox.rejected.connect(Dialog.reject)
        QtCore.QMetaObject.connectSlotsByName(Dialog)

    def retranslateUi(self, Dialog):
        _translate = QtCore.QCoreApplication.translate
        Dialog.setWindowTitle(_translate("Dialog", "Snapshots Manager"))
        self.label.setText(_translate("Dialog", "<html><head/><body><p>Select from the list below the snapshot to be recalled<br/>to return to a past state of the session :</p></body></html>"))
        self.pushButtonSnapshotNow.setText(_translate("Dialog", "Take a snapshot now !"))
        self.checkBoxAutoSnapshot.setToolTip(_translate("Dialog", "<html><head/><body><p>Make a snapshot at each session save.</p></body></html>"))
        self.checkBoxAutoSnapshot.setText(_translate("Dialog", "Auto snapshot at save for this session"))

