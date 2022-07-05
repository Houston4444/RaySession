from typing import TYPE_CHECKING
from PyQt5.QtCore import QPoint

import ray
import patchcanvas
from patchcanvas import CallbackAct, PortMode, PortType, BoxLayoutMode
from patchbay_elements import Port
from patchbay_tools import CanvasPortInfoDialog

if TYPE_CHECKING:
    from patchbay_manager import PatchbayManager

# Group Position Flags
GROUP_CONTEXT_AUDIO = 0x01
GROUP_CONTEXT_MIDI = 0x02
GROUP_SPLITTED = 0x04
GROUP_WRAPPED_INPUT = 0x10
GROUP_WRAPPED_OUTPUT = 0x20
GROUP_HAS_BEEN_SPLITTED = 0x40


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
    
    def _group_info(self, group_id: int):
        pass
    
    def _group_rename(self, group_id: int):
        pass
    
    def _group_split(self, group_id: int):        
        group = self.mng._groups_by_id.get(group_id)
        if group is not None:
            on_place = not bool(
                group.current_position.flags & GROUP_HAS_BEEN_SPLITTED)
            self.patchcanvas.split_group(group_id, on_place=on_place)
            group.current_position.flags |= GROUP_SPLITTED
            group.current_position.flags |= GROUP_HAS_BEEN_SPLITTED
            group.save_current_position()

    def _group_join(self, group_id: int):
        self.patchcanvas.animate_before_join(group_id)
    
    def _group_joined(self, group_id: int):
        group = self.mng._groups_by_id.get(group_id)
        if group is not None:
            group.current_position.flags &= ~GROUP_SPLITTED
            group.save_current_position()
    
    def _group_move(self, group_id: int, port_mode: PortMode, x: int, y: int):
        group = self.mng._groups_by_id.get(group_id)
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
        group = self.mng._groups_by_id.get(group_id)
        if group is not None:
            group.wrap_box(splitted_mode, yesno)
    
    def _group_layout_change(self, group_id: int, port_mode: PortMode,
                            layout_mode: BoxLayoutMode):
        group = self.mng._groups_by_id.get(group_id)
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
        group = self.mng._groups_by_id.get(group_id)
        if group is not None:
            group.add_portgroup(portgroup)

            new_portgroup_mem = ray.PortGroupMemory.new_from(
                group.name, portgroup.port_type(),
                portgroup.port_mode, int(above_metadatas),
                *[p.short_name() for p in port_list])

            self.mng.add_portgroup_memory(new_portgroup_mem)

            self.mng.send_to_daemon(
                '/ray/server/patchbay/save_portgroup',
                *new_portgroup_mem.spread())

        portgroup.add_to_canvas()
    
    def _portgroup_remove(self, group_id: int, portgroup_id: int):
        group = self.mng._groups_by_id.get(group_id)
        if group is None:
            return

        for portgroup in group.portgroups:
            if portgroup.portgroup_id == portgroup_id:
                for port in portgroup.ports:
                    # save a fake portgroup with one port only
                    # it will be considered as a forced mono port
                    # (no stereo detection)
                    above_metadatas = bool(port.mdata_portgroup)

                    new_portgroup_mem = ray.PortGroupMemory.new_from(
                        group.name, portgroup.port_type(),
                        portgroup.port_mode, int(above_metadatas),
                        port.short_name())
                    self.mng.add_portgroup_memory(new_portgroup_mem)

                    self.mng.send_to_daemon(
                        '/ray/server/patchbay/save_portgroup',
                        *new_portgroup_mem.spread())

                portgroup.remove_from_canvas()
                group.portgroups.remove(portgroup)
                break

    def _port_info(self, group_id: int, port_id: int):
        port = self.mng.get_port_from_id(group_id, port_id)
        if port is None:
            return

        dialog = CanvasPortInfoDialog(self.mng.session.main_win)
        dialog.set_port(port)
        dialog.show()

    def _port_rename(self, group_id: int, port_id: int):
        pass

    def _ports_connect(self, group_out_id: int, port_out_id: int,
                       group_in_id: int, port_in_id: int):
        port_out = self.mng.get_port_from_id(group_out_id, port_out_id)
        port_in = self.mng.get_port_from_id(group_in_id, port_in_id)

        if port_out is None or port_in is None:
            return

        self.mng.send_to_patchbay_daemon(
            '/ray/patchbay/connect',
            port_out.full_name, port_in.full_name)

    def _ports_disconnect(self, connection_id: int):
        for connection in self.mng.connections:
            if connection.connection_id == connection_id:
                self.mng.send_to_patchbay_daemon(
                    '/ray/patchbay/disconnect',
                    connection.port_out.full_name,
                    connection.port_in.full_name)
                break

    def _bg_right_click(self, x: int, y: int):
        self.mng.canvas_menu.exec(QPoint(x, y))
    
    def _bg_double_click(self):
        self.mng.toggle_full_screen()
    
    def _client_show_gui(self, group_id: int, visible: int):
        group = self.mng._groups_by_id.get(group_id)
        if group is None:
            return

        for client in self.mng.session.client_list:
            if client.can_be_own_jack_client(group.name):
                show = 'show' if visible else 'hide'
                self.mng.send_to_daemon(
                    '/ray/client/%s_optional_gui' % show,
                    client.client_id)
                break
            
    def _theme_changed(self, theme_ref: str):
        if self.mng.options_dialog is not None:
            self.mng.options_dialog.set_theme(theme_ref)

        self.mng.remove_and_add_all()