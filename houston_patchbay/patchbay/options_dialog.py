
from PyQt5.QtWidgets import QDialog, QApplication, QInputDialog, QMessageBox, QWidget
from PyQt5.QtGui import QIcon
from PyQt5.QtCore import Qt, pyqtSignal, QProcess, QSettings


from .patchcanvas import patchcanvas
from .ui.canvas_options import Ui_CanvasOptions

_translate = QApplication.translate


class CanvasOptionsDialog(QDialog):
    theme_changed = pyqtSignal(str)
    
    def __init__(self, parent: QWidget, settings=None):
        QDialog.__init__(self, parent)
        self.ui = Ui_CanvasOptions()
        self.ui.setupUi(self)
        
        if settings is not None:
            assert isinstance(settings, QSettings)
        self._settings = settings
        self._user_theme_icon = QIcon()

        gracious_names = True
        a2j_grouped = True
        use_shadows = False
        elastic_canvas = True
        borders_navigation = True
        prevent_overlap = True
        max_port_width = 170

        if settings is not None:
            gracious_names = settings.value(
                'Canvas/use_graceful_names', True, type=bool)
            a2j_grouped = settings.value(
                'Canvas/group_a2j_ports', True, type=bool)
            use_shadows = settings.value(
                'Canvas/box_shadows', False, type=bool)
            elastic_canvas = settings.value(
                'Canvas/elastic', True, type=bool)
            borders_navigation = settings.value(
                'Canvas/borders_navigation', True, type=bool)
            prevent_overlap = settings.value(
                'Canvas/prevent_overlap', True, type=bool)
            max_port_width = settings.value(
                'Canvas/max_port_width', 170, type=int)

        self.ui.checkBoxGracefulNames.setChecked(gracious_names)
        self.ui.checkBoxA2J.setChecked(a2j_grouped)
        self.ui.checkBoxShadows.setChecked(use_shadows)
        self.ui.checkBoxElastic.setChecked(elastic_canvas)
        self.ui.checkBoxBordersNavigation.setChecked(borders_navigation)
        self.ui.checkBoxPreventOverlap.setChecked(prevent_overlap)
        self.ui.spinBoxMaxPortWidth.setValue(max_port_width)

        self.ui.comboBoxTheme.activated.connect(self._theme_box_activated)
        self.ui.pushButtonEditTheme.clicked.connect(self._edit_theme)
        self.ui.pushButtonDuplicateTheme.clicked.connect(self._duplicate_theme)
        
        self._current_theme_ref = ''
        self._theme_list = []

        # all these variables are pyqtSignal 
        self.gracious_names_checked = self.ui.checkBoxGracefulNames.stateChanged
        self.a2j_grouped_checked = self.ui.checkBoxA2J.stateChanged
        self.group_shadows_checked = self.ui.checkBoxShadows.stateChanged
        self.elastic_checked = self.ui.checkBoxElastic.stateChanged
        self.borders_nav_checked = self.ui.checkBoxBordersNavigation.stateChanged
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
        new_theme_name, ok = QInputDialog.getText(
            self, _translate('patchbay_theme', 'New Theme Name'),
            _translate('patchbay_theme', 'Choose a name for the new theme :'))
        
        if not new_theme_name or not ok:
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

    def set_theme_list(self, theme_list: list[dict]):
        self.ui.comboBoxTheme.clear()
        del self._theme_list
        self._theme_list = theme_list

        for theme_dict in theme_list:
            if theme_dict['editable']:
                self.ui.comboBoxTheme.addItem(
                    self._user_theme_icon, theme_dict['name'], theme_dict['ref_id'])
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

    def set_user_theme_icon(self, icon: QIcon):
        self._user_theme_icon = icon

    def get_gracious_names(self) -> bool:
        return self.ui.checkBoxGracefulNames.isChecked()

    def get_a2j_grouped(self) -> bool:
        return self.ui.checkBoxA2J.isChecked()

    def get_group_shadows(self) -> bool:
        return self.ui.checkBoxShadows.isChecked()

    def get_elastic(self) -> bool:
        return self.ui.checkBoxElastic.isChecked()

    def get_borders_nav(self) -> bool:
        return self.ui.checkBoxBordersNavigation.isChecked()

    def get_prevent_overlap(self) -> bool:
        return self.ui.checkBoxPreventOverlap.isChecked()

    def get_max_port_width(self) -> int:
        return self.ui.spinBoxMaxPortWidth.value()

    def showEvent(self, event):
        self.set_theme_list(patchcanvas.list_themes())
        self.set_theme(patchcanvas.get_theme())
        QDialog.showEvent(self, event)

    def closeEvent(self, event):
        if self._settings is not None:
            self._settings.setValue('Canvas/use_graceful_names',
                                    self.get_gracious_names())
            self._settings.setValue('Canvas/group_a2j_ports',
                                    self.get_a2j_grouped())
            self._settings.setValue('Canvas/box_shadows',
                                    self.get_group_shadows())
            self._settings.setValue('Canvas/elastic',
                                    self.get_elastic())
            self._settings.setValue('Canvas/borders_navigation',
                                    self.get_borders_nav())
            self._settings.setValue('Canvas/prevent_overlap',
                                    self.get_prevent_overlap())
            self._settings.setValue('Canvas/max_port_width',
                                    self.get_max_port_width())
            self._settings.setValue('Canvas/theme',
                                    self.ui.comboBoxTheme.currentData())
        QDialog.closeEvent(self, event)
