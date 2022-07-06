
from PyQt5.QtWidgets import QDialog

import ui.canvas_port_info

class CanvasPortInfoDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.ui = ui.canvas_port_info.Ui_Dialog()
        self.ui.setupUi(self)

    def set_infos(self, port_full_name: str, port_uuid: int,
                  port_type: str, port_flags: str,
                  pretty_name: str, port_order: int,
                  portgroup_name: str):
        self.ui.lineEditFullPortName.setText(port_full_name)
        self.ui.lineEditUuid.setText(str(port_uuid))
        self.ui.labelPortType.setText(port_type)
        self.ui.labelPortFlags.setText(port_flags)
        self.ui.labelPrettyName.setText(pretty_name)
        self.ui.labelPortOrder.setText(port_order)
        self.ui.labelPortGroup.setText(portgroup_name)

        if not (pretty_name or port_order or portgroup_name):
            self.ui.groupBoxMetadatas.setVisible(False)