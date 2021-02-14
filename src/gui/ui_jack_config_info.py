# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file 'resources/ui/jack_config_info.ui'
#
# Created by: PyQt5 UI code generator 5.11.3
#
# WARNING! All changes made in this file will be lost!

from PyQt5 import QtCore, QtGui, QtWidgets

class Ui_Dialog(object):
    def setupUi(self, Dialog):
        Dialog.setObjectName("Dialog")
        Dialog.resize(502, 575)
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
        spacerItem1 = QtWidgets.QSpacerItem(20, 40, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Expanding)
        self.verticalLayout.addItem(spacerItem1)
        self.groupBox_2 = QtWidgets.QGroupBox(Dialog)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.groupBox_2.sizePolicy().hasHeightForWidth())
        self.groupBox_2.setSizePolicy(sizePolicy)
        self.groupBox_2.setObjectName("groupBox_2")
        self.verticalLayout_4 = QtWidgets.QVBoxLayout(self.groupBox_2)
        self.verticalLayout_4.setObjectName("verticalLayout_4")
        self.textJackConfig = QtWidgets.QTextEdit(self.groupBox_2)
        self.textJackConfig.setReadOnly(True)
        self.textJackConfig.setObjectName("textJackConfig")
        self.verticalLayout_4.addWidget(self.textJackConfig)
        self.verticalLayout.addWidget(self.groupBox_2)
        spacerItem2 = QtWidgets.QSpacerItem(20, 40, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Expanding)
        self.verticalLayout.addItem(spacerItem2)
        self.checkBoxAutoStart = QtWidgets.QCheckBox(Dialog)
        self.checkBoxAutoStart.setChecked(True)
        self.checkBoxAutoStart.setObjectName("checkBoxAutoStart")
        self.verticalLayout.addWidget(self.checkBoxAutoStart)
        self.checkBoxNotAgain = QtWidgets.QCheckBox(Dialog)
        self.checkBoxNotAgain.setChecked(True)
        self.checkBoxNotAgain.setObjectName("checkBoxNotAgain")
        self.verticalLayout.addWidget(self.checkBoxNotAgain)
        self.buttonBox = QtWidgets.QDialogButtonBox(Dialog)
        self.buttonBox.setOrientation(QtCore.Qt.Horizontal)
        self.buttonBox.setStandardButtons(QtWidgets.QDialogButtonBox.Ok)
        self.buttonBox.setObjectName("buttonBox")
        self.verticalLayout.addWidget(self.buttonBox)

        self.retranslateUi(Dialog)
        self.buttonBox.accepted.connect(Dialog.accept)
        self.buttonBox.rejected.connect(Dialog.reject)
        QtCore.QMetaObject.connectSlotsByName(Dialog)
        Dialog.setTabOrder(self.checkBoxAutoStart, self.checkBoxNotAgain)

    def retranslateUi(self, Dialog):
        _translate = QtCore.QCoreApplication.translate
        Dialog.setWindowTitle(_translate("Dialog", "Jack Configuration Infos"))
        self.label.setText(_translate("Dialog", "<html><head/><body><p>You create a session from the JACK configuration reminder template.</p><p>This means that when you re-open this session, JACK may be restarted with the configuration used by that session.</p><p>This session callback is made from the session scripts.</p></body></html>"))
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
        self.groupBox_2.setTitle(_translate("Dialog", "Jack Config Script Infos"))
        self.textJackConfig.setHtml(_translate("Dialog", "<!DOCTYPE HTML PUBLIC \"-//W3C//DTD HTML 4.0//EN\" \"http://www.w3.org/TR/REC-html40/strict.dtd\">\n"
"<html><head><meta name=\"qrichtext\" content=\"1\" /><style type=\"text/css\">\n"
"p, li { white-space: pre-wrap; }\n"
"</style></head><body style=\" font-family:\'Noto Sans\'; font-size:10pt; font-weight:400; font-style:normal;\">\n"
"<p style=\" margin-top:0px; margin-bottom:0px; margin-left:0px; margin-right:0px; -qt-block-indent:0; text-indent:0px;\"><span style=\" font-weight:600;\">The principle is as follows:</span></p>\n"
"<p style=\" margin-top:12px; margin-bottom:12px; margin-left:0px; margin-right:0px; -qt-block-indent:0; text-indent:0px;\">Each time the session is saved, the JACK configuration is saved in the session.<br />Before opening, JACK is restarted if the session configuration is different from the current one.<br />After closing, JACK is restarted as it was configured before opening if needed.</p>\n"
"<p style=\" margin-top:12px; margin-bottom:12px; margin-left:0px; margin-right:0px; -qt-block-indent:0; text-indent:0px;\">If you open this session on another computer, the JACK configuration will not be recalled but will be overwritten when you save.</p>\n"
"<p style=\" margin-top:12px; margin-bottom:12px; margin-left:0px; margin-right:0px; -qt-block-indent:0; text-indent:0px;\">If you wish to open this session without reloading the JACK configuration, simply disable the session scripts.</p></body></html>"))
        self.checkBoxAutoStart.setToolTip(_translate("Dialog", "<html><head/><body><p>Unfortunately, at the moment it is not possible to get the current JACK configuration with certainty, so JACK will be restarted at the first session opening.<br/>You can work around this problem by automatically starting a light daemon at your desktop session startup.</p></body></html>"))
        self.checkBoxAutoStart.setText(_translate("Dialog", "Automatically start ray-jack_checker daemon at startup"))
        self.checkBoxNotAgain.setText(_translate("Dialog", "Do not show this message again"))

