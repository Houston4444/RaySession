
from PyQt5.QtWidgets import QDialog, QApplication, QInputDialog, QMessageBox
from PyQt5.QtGui import QIcon
from PyQt5.QtCore import Qt, pyqtSignal, QProcess


from gui_tools import RS, RayIcon, is_dark_theme
from patchcanvas import patchcanvas
import ui.canvas_options

_translate = QApplication.translate


class CanvasOptionsDialog(QDialog):
    theme_changed = pyqtSignal(str)
    
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

        self.ui.comboBoxTheme.activated.connect(
            self._theme_box_activated)
        self.ui.pushButtonEditTheme.clicked.connect(
            self._edit_theme)
        self.ui.pushButtonDuplicateTheme.clicked.connect(
            self._duplicate_theme)
        
        self._current_theme_ref = ''
        self._theme_list = []
            
        self.ui.spinBoxMaxPortWidth.setValue(self.max_port_width)

        self.gracious_names_checked = self.ui.checkBoxGracefulNames.stateChanged
        self.a2j_grouped_checked = self.ui.checkBoxA2J.stateChanged
        self.group_shadows_checked = self.ui.checkBoxShadows.stateChanged
        self.elastic_checked = self.ui.checkBoxElastic.stateChanged
        self.prevent_overlap_checked = self.ui.checkBoxPreventOverlap.stateChanged
        self.max_port_width_changed = self.ui.spinBoxMaxPortWidth.valueChanged

    def _theme_box_activated(self):
        current_theme_ref_id = self.ui.comboBoxTheme.currentData(Qt.UserRole)
        if current_theme_ref_id == self._current_theme_ref:
            return
        
        for theme_dict in self._theme_list:
            if theme_dict['ref_id'] == current_theme_ref_id:
                self.ui.pushButtonEditTheme.setEnabled(bool(theme_dict['editable']))
                break

        self.theme_changed.emit(current_theme_ref_id)
        
    def _duplicate_theme(self):
        current_theme_ref_id = self.ui.comboBoxTheme.currentData(Qt.UserRole)
        
        new_theme_name, ok = QInputDialog.getText(
            self, _translate('patchbay_theme', 'New Theme Name'),
            _translate('patchbay_theme', 'Choose a name for the new theme :'))
        
        if not new_theme_name:
            return
        
        new_theme_name = new_theme_name.replace('/', '⁄')

        err = patchcanvas.copy_and_load_current_theme(new_theme_name)
        
        if err:
            message = _translate(
                'patchbay_theme', 'The copy of the theme directory failed')
            
            QMessageBox.warning(
                self, _translate('patchbay_theme', 'Copy failed !'), message)

    def _edit_theme(self):
        current_theme_ref_id = self.ui.comboBoxTheme.currentData(Qt.UserRole)
        
        for theme_dict in self._theme_list:
            if theme_dict['ref_id'] == current_theme_ref_id:
                if not theme_dict['editable']:
                    patchcanvas.copy_theme_to_editable_path_and_load(
                        theme_dict['file_path'])

                # start the text editor process
                QProcess.startDetached('xdg-open', [theme_dict['file_path']])
                break

    def set_theme_list(self, theme_list: list):
        self.ui.comboBoxTheme.clear()
        del self._theme_list
        self._theme_list = theme_list

        dark = is_dark_theme(self)
        for theme_dict in theme_list:
            if theme_dict['editable']:
                self.ui.comboBoxTheme.addItem(
                    RayIcon('im-user', dark), theme_dict['name'], theme_dict['ref_id'])
            else:
                self.ui.comboBoxTheme.addItem(theme_dict['name'], theme_dict['ref_id'])

    def set_theme(self, theme_ref: str):
        for i in range(self.ui.comboBoxTheme.count()):
            ref_id = self.ui.comboBoxTheme.itemData(i, Qt.UserRole)
            if ref_id == theme_ref:
                self.ui.comboBoxTheme.setCurrentIndex(i)
                break
        else:
            # the new theme has not been found
            # update the list and select it if it exists
            self.set_theme_list(patchcanvas.list_themes())
            for i in range(self.ui.comboBoxTheme.count()):
                ref_id = self.ui.comboBoxTheme.itemData(i, Qt.UserRole)
                if ref_id == theme_ref:
                    self.ui.comboBoxTheme.setCurrentIndex(i)
                    break

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

    def showEvent(self, event):
        self.set_theme_list(patchcanvas.list_themes())
        self.set_theme(patchcanvas.get_theme())
        QDialog.showEvent(self, event)

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
        RS.settings.setValue('Canvas/theme',
                             self.ui.comboBoxTheme.currentData())
        QDialog.closeEvent(self, event)
