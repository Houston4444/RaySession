
from PyQt5.QtWidgets import QDialog, QApplication
from PyQt5.QtCore import Qt


from gui_tools import RS

import ui.canvas_options

_translate = QApplication.translate


class CanvasOptionsDialog(QDialog):
    def __init__(self, parent):
        QDialog.__init__(self, parent)
        self.ui = ui.canvas_options.Ui_Dialog()
        self.ui.setupUi(self)

        self.gracious_names = RS.settings.value(
            'Canvas/use_graceful_names', True, type=bool)
        self.a2j_grouped = RS.settings.value(
            'Canvas/group_a2j_ports', True, type=bool)
        self.use_shadows = RS.settings.value(
            'Canvas/box_shadows', False, type=bool)
        self.elastic_canvas = RS.settings.value(
            'Canvas/elastic', True, type=bool)
        self.prevent_overlap = RS.settings.value(
            'Canvas/prevent_overlap', True, type=bool)
        self.max_port_width = RS.settings.value(
            'Canvas/max_port_width', 170, type=int)

        self.ui.checkBoxGracefulNames.setChecked(
            self.gracious_names)
        self.ui.checkBoxA2J.setChecked(
            self.a2j_grouped)
        self.ui.checkBoxShadows.setChecked(
            self.use_shadows)
        self.ui.checkBoxElastic.setChecked(
            self.elastic_canvas)
        self.ui.checkBoxPreventOverlap.setChecked(
            self.prevent_overlap)

        self.ui.comboBoxTheme.addItem(_translate('patchbay', 'Silver Gold'))
        self.ui.comboBoxTheme.addItem(_translate('patchbay', 'Black Gold'))
        self.ui.comboBoxTheme.addItem(_translate('patchbay', 'Modern Dark'))

        current_theme = RS.settings.value('Canvas/theme', 'Silver Gold', type=str)
        if current_theme == "Black Gold":
            self.ui.comboBoxTheme.setCurrentIndex(1)
        elif current_theme == "Modern Dark":
            self.ui.comboBoxTheme.setCurrentIndex(2)
            
        self.ui.spinBoxMaxPortWidth.setValue(self.max_port_width)

        self.gracious_names_checked = self.ui.checkBoxGracefulNames.stateChanged
        self.a2j_grouped_checked = self.ui.checkBoxA2J.stateChanged
        self.group_shadows_checked = self.ui.checkBoxShadows.stateChanged
        self.theme_changed = self.ui.comboBoxTheme.currentIndexChanged
        self.elastic_checked = self.ui.checkBoxElastic.stateChanged
        self.prevent_overlap_checked = self.ui.checkBoxPreventOverlap.stateChanged
        self.max_port_width_changed = self.ui.spinBoxMaxPortWidth.valueChanged

    def get_gracious_names(self)->bool:
        return self.ui.checkBoxGracefulNames.isChecked()

    def get_a2j_grouped(self)->bool:
        return self.ui.checkBoxA2J.isChecked()

    def get_group_shadows(self)->bool:
        return self.ui.checkBoxShadows.isChecked()

    def get_elastic(self)->bool:
        return self.ui.checkBoxElastic.isChecked()

    def get_prevent_overlap(self)->bool:
        return self.ui.checkBoxPreventOverlap.isChecked()

    def get_max_port_width(self)->int:
        return self.ui.spinBoxMaxPortWidth.value()

    def closeEvent(self, event):
        RS.settings.setValue('Canvas/use_graceful_names',
                             self.get_gracious_names())
        RS.settings.setValue('Canvas/group_a2j_ports',
                             self.get_a2j_grouped())
        RS.settings.setValue('Canvas/box_shadows',
                             self.get_group_shadows())
        RS.settings.setValue('Canvas/elastic',
                             self.get_elastic())
        RS.settings.setValue('Canvas/prevent_overlap',
                             self.get_prevent_overlap())
        RS.settings.setValue('Canvas/max_port_width',
                             self.get_max_port_width())
        QDialog.closeEvent(self, event)
