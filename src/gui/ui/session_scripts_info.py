# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file 'resources/ui/session_scripts_info.ui'
#
# Created by: PyQt5 UI code generator 5.11.3
#
# WARNING! All changes made in this file will be lost!

from PyQt5 import QtCore, QtGui, QtWidgets

class Ui_Dialog(object):
    def setupUi(self, Dialog):
        Dialog.setObjectName("Dialog")
        Dialog.resize(502, 565)
        self.verticalLayout = QtWidgets.QVBoxLayout(Dialog)
        self.verticalLayout.setObjectName("verticalLayout")
        self.label = QtWidgets.QLabel(Dialog)
        self.label.setToolTip("")
        self.label.setWordWrap(True)
        self.label.setObjectName("label")
        self.verticalLayout.addWidget(self.label)
        spacerItem = QtWidgets.QSpacerItem(20, 6, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Fixed)
        self.verticalLayout.addItem(spacerItem)
        self.groupBox = QtWidgets.QGroupBox(Dialog)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.groupBox.sizePolicy().hasHeightForWidth())
        self.groupBox.setSizePolicy(sizePolicy)
        self.groupBox.setObjectName("groupBox")
        self.verticalLayout_3 = QtWidgets.QVBoxLayout(self.groupBox)
        self.verticalLayout_3.setObjectName("verticalLayout_3")
        self.textSessionScripts = QtWidgets.QTextEdit(self.groupBox)
        self.textSessionScripts.setReadOnly(True)
        self.textSessionScripts.setObjectName("textSessionScripts")
        self.verticalLayout_3.addWidget(self.textSessionScripts)
        self.verticalLayout.addWidget(self.groupBox)
        self.checkBoxNotAgain = QtWidgets.QCheckBox(Dialog)
        self.checkBoxNotAgain.setChecked(True)
        self.checkBoxNotAgain.setObjectName("checkBoxNotAgain")
        self.verticalLayout.addWidget(self.checkBoxNotAgain)
        self.buttonBox = QtWidgets.QDialogButtonBox(Dialog)
        self.buttonBox.setOrientation(QtCore.Qt.Horizontal)
        self.buttonBox.setStandardButtons(QtWidgets.QDialogButtonBox.Abort|QtWidgets.QDialogButtonBox.Ok)
        self.buttonBox.setObjectName("buttonBox")
        self.verticalLayout.addWidget(self.buttonBox)

        self.retranslateUi(Dialog)
        self.buttonBox.accepted.connect(Dialog.accept)
        self.buttonBox.rejected.connect(Dialog.reject)
        QtCore.QMetaObject.connectSlotsByName(Dialog)

    def retranslateUi(self, Dialog):
        _translate = QtCore.QCoreApplication.translate
        Dialog.setWindowTitle(_translate("Dialog", "Session Scripts Infos"))
        self.label.setText(_translate("Dialog", "<html><head/><body><p>You create a session with the basic session scripts.<br/>If you don\'t know what a script is, or you have absolutely no knowledge in shell scripting, you don\'t belong here, get out of here right now.</p><p>While you\'ve not edited the scripts, session will behave as a normal session.</p><p>You will find in the session folder a <span style=\" font-style:italic;\">ray-scripts</span> folder.<br/>In the <span style=\" font-style:italic;\">ray-scripts </span>folder you will find 3 files:</p><ul style=\"margin-top: 0px; margin-bottom: 0px; margin-left: 0px; margin-right: 0px; -qt-list-indent: 1;\"><li style=\" margin-top:12px; margin-bottom:0px; margin-left:0px; margin-right:0px; -qt-block-indent:0; text-indent:0px;\">load.sh</li><li style=\" margin-top:0px; margin-bottom:0px; margin-left:0px; margin-right:0px; -qt-block-indent:0; text-indent:0px;\">save.sh</li><li style=\" margin-top:0px; margin-bottom:12px; margin-left:0px; margin-right:0px; -qt-block-indent:0; text-indent:0px;\">close.sh</li></ul><p>In theses 3 scripts you can edit some actions to do before or after load, save, or close the session.<br/>If you don\'t need custom actions at one of theses 3 steps, you can safely remove its file.</p></body></html>"))
        self.groupBox.setTitle(_translate("Dialog", "Session Scripts Infos"))
        self.textSessionScripts.setDocumentTitle(_translate("Dialog", "Session Scripts Infos"))
        self.textSessionScripts.setHtml(_translate("Dialog", "<!DOCTYPE HTML PUBLIC \"-//W3C//DTD HTML 4.0//EN\" \"http://www.w3.org/TR/REC-html40/strict.dtd\">\n"
"<html><head><meta name=\"qrichtext\" content=\"1\" /><title>Session Scripts Infos</title><style type=\"text/css\">\n"
"p, li { white-space: pre-wrap; }\n"
"</style></head><body style=\" font-family:\'Noto Sans\'; font-size:10pt; font-weight:400; font-style:normal;\">\n"
"<p style=\" margin-top:0px; margin-bottom:0px; margin-left:0px; margin-right:0px; -qt-block-indent:0; text-indent:0px;\">Session scripts are located in the <span style=\" font-style:italic;\">ray-scripts</span> folder in the session folder, but they could also be located in a <span style=\" font-style:italic;\">ray-scripts</span> folder in a parent folder of the session folder.</p>\n"
"<p style=\" margin-top:12px; margin-bottom:12px; margin-left:0px; margin-right:0px; -qt-block-indent:0; text-indent:0px;\">For example:</p>\n"
"<p style=\" margin-top:12px; margin-bottom:12px; margin-left:0px; margin-right:0px; -qt-block-indent:0; text-indent:0px;\">the scripts folder for this new session will be:<br /><span style=\" font-weight:600;\">%s</span></p>\n"
"<p style=\" margin-top:12px; margin-bottom:12px; margin-left:0px; margin-right:0px; -qt-block-indent:0; text-indent:0px;\">But could just as well be:<br /><span style=\" font-weight:600;\">%s</span></p>\n"
"<p style=\" margin-top:12px; margin-bottom:12px; margin-left:0px; margin-right:0px; -qt-block-indent:0; text-indent:0px;\">and thus apply to all sessions contained in <span style=\" font-weight:600;\">%s</span>.</p></body></html>"))
        self.checkBoxNotAgain.setText(_translate("Dialog", "Do not show this message again"))

