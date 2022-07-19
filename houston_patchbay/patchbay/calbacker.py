from typing import TYPE_CHECKING
from PyQt5.QtCore import QPoint

from . import patchcanvas
from .patchcanvas import CallbackAct, PortMode, PortType, BoxLayoutMode
from .base_elements import Port, GroupPosFlag, PortgroupMem
from .tools_widgets import CanvasPortInfoDialog

if TYPE_CHECKING:
    from .patchbay_manager import PatchbayManager


class Callbacker:
    def __init__(self, manager: 'PatchbayManager'):
        self.mng = manager
        self.patchcanvas = patchcanvas
    
    def receive(self, action: CallbackAct, args: tuple):
        ''' receives a callback from patchcanvas and execute
            the function with action name in lowercase.'''
        func_name = '_' + action.name.lower()
        if func_name in self.__dir__():
            self.__getattribute__(func_name)(*args)
    
    # ￬￬￬ functions connected to CallBackAct ￬￬￬
    
    def _group_info(self, group_id: int):
        pass
    
    def _group_rename(self, group_id: int):
        pass
    
    def _group_split(self, group_id: int):        
        group = self.mng.get_group_from_id(group_id)
        if group is not None:
            on_place = not bool(
                group.current_position.flags & GroupPosFlag.HAS_BEEN_SPLITTED)
            self.patchcanvas.split_group(group_id, on_place=on_place)
            group.current_position.flags |= GroupPosFlag.SPLITTED
            group.current_position.flags |= GroupPosFlag.HAS_BEEN_SPLITTED
            group.save_current_position()

    def _group_join(self, group_id: int):
        self.patchcanvas.animate_before_join(group_id)
    
    def _group_joined(self, group_id: int):
        group = self.mng.get_group_from_id(group_id)
        if group is not None:
            group.current_position.flags &= ~GroupPosFlag.SPLITTED
            group.save_current_position()
    
    def _group_move(self, group_id: int, port_mode: PortMode, x: int, y: int):
        group = self.mng.get_group_from_id(group_id)
        if group is not None:
            gpos = group.current_position
            if port_mode == PortMode.NULL:
                gpos.null_xy = (x, y)
            elif port_mode == PortMode.INPUT:
                gpos.in_xy = (x, y)
            elif port_mode == PortMode.OUTPUT:
                gpos.out_xy = (x, y)

            group.save_current_position()
    
    def _group_wrap(self, group_id: int, splitted_mode, yesno: bool):
        group = self.mng.get_group_from_id(group_id)
        if group is not None:
            group.wrap_box(splitted_mode, yesno)
    
    def _group_layout_change(self, group_id: int, port_mode: PortMode,
                            layout_mode: BoxLayoutMode):
        group = self.mng.get_group_from_id(group_id)
        if group is not None:
            group.set_layout_mode(port_mode, layout_mode)
    
    def _portgroup_add(self, group_id: int, port_mode: PortMode,
                       port_type: PortType, port_ids: tuple[int]):
        port_list = list[Port]()
        above_metadatas = False

        for port_id in port_ids:
            port = self.mng.get_port_from_id(group_id, port_id)
            if port.mdata_portgroup:
                above_metadatas = True
            port_list.append(port)

        portgroup = self.mng.new_portgroup(group_id, port_mode, port_list)
        group = self.mng.get_group_from_id(group_id)
        if group is None:
            return

        group.add_portgroup(portgroup)

        pg_mem = PortgroupMem()
        pg_mem.group_name = group.name
        pg_mem.port_type = portgroup.port_type()
        pg_mem.port_mode = portgroup.port_mode
        pg_mem.above_metadatas = above_metadatas
        pg_mem.port_names = [p.short_name() for p in port_list]

        self.mng.add_portgroup_memory(pg_mem)
        self.mng.save_portgroup_memory(pg_mem)

        portgroup.add_to_canvas()
    
    def _portgroup_remove(self, group_id: int, portgroup_id: int):
        group = self.mng.get_group_from_id(group_id)
        if group is None:
            return

        for portgroup in group.portgroups:
            if portgroup.portgroup_id == portgroup_id:
                for port in portgroup.ports:
                    # save a fake portgroup with one port only
                    # it will be considered as a forced mono port
                    # (no stereo detection)
                    pg_mem = PortgroupMem()
                    pg_mem.group_name = group.name
                    pg_mem.port_type = port.type
                    pg_mem.port_mode = portgroup.port_mode
                    pg_mem.above_metadatas = bool(port.mdata_portgroup)
                    pg_mem.port_names = [port.short_name()]
                    self.mng.add_portgroup_memory(pg_mem)
                    self.mng.save_portgroup_memory(pg_mem)

                group.remove_portgroup(portgroup)
                break

    def _port_info(self, group_id: int, port_id: int):
        port = self.mng.get_port_from_id(group_id, port_id)
        if port is None:
            return

        dialog = CanvasPortInfoDialog(self.mng.main_win)
        dialog.set_port(port)
        dialog.show()

    def _port_rename(self, group_id: int, port_id: int):
        pass
    
    def _ports_connect(self, group_out_id: int, port_out_id: int,
                       group_in_id: int, port_in_id: int):
        pass

    def _ports_disconnect(self, connection_id: int):
        pass

    def _bg_right_click(self, x: int, y: int):
        if self.mng.canvas_menu is not None:
            self.mng.canvas_menu.exec(QPoint(x, y))
    
    def _bg_double_click(self):
        self.mng.sg.full_screen_toggle_wanted.emit()
    
    def _client_show_gui(self, group_id: int, visible: int):
        pass
                    
    def _theme_changed(self, theme_ref: str):
        if self.mng.options_dialog is not None:
            self.mng.options_dialog.set_theme(theme_ref)

        self.mng.remove_and_add_all()