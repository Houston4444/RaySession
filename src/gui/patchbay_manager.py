
import json
import os
import sys

from PyQt5.QtGui import QCursor, QIcon, QGuiApplication
from PyQt5.QtWidgets import QMenu, QAction, QLabel, QMessageBox
from PyQt5.QtCore import pyqtSlot

import ray

from gui_tools import RS

from patchcanvas import patchcanvas
from gui_server_thread import GUIServerThread
from patchbay_tools import PatchbayToolsWidget

import canvas_options

# Port Type
PORT_TYPE_NULL = 0
PORT_TYPE_AUDIO = 1
PORT_TYPE_MIDI = 2

# Port Mode
PORT_MODE_NULL = 0
PORT_MODE_INPUT = 1
PORT_MODE_OUTPUT = 2

# Port Flags
PORT_IS_INPUT = 0x01
PORT_IS_OUTPUT = 0x02
PORT_IS_PHYSICAL = 0x04
PORT_CAN_MONITOR = 0x08
PORT_IS_TERMINAL = 0x10
PORT_IS_CONTROL_VOLTAGE = 0x100

USE_ALIAS_NONE = 0
USE_ALIAS_1 = 1
USE_ALIAS_2 = 2

GROUP_CONTEXT_AUDIO = 0x01
GROUP_CONTEXT_MIDI = 0x02
GROUP_SPLITTED = 0x04
GROUP_WRAPPED_INPUT = 0x10
GROUP_WRAPPED_OUTPUT = 0x20

_translate = QGuiApplication.translate

class Connection:
    def __init__(self, connection_id: int, port_out, port_in):
        self.connection_id = connection_id
        self.port_out = port_out
        self.port_in = port_in
        self.in_canvas = False
    
    def port_type(self)->int:
        return self.port_out.type
    
    def add_to_canvas(self):
        if self.in_canvas:
            return
        
        self.in_canvas = True
        
        patchcanvas.connectPorts(
            self.connection_id,
            self.port_out.group_id, self.port_out.port_id,
            self.port_in.group_id, self.port_in.port_id,
            fast=PatchbayManager.optimized_operation)
        
    def remove_from_canvas(self):
        if not self.in_canvas:
            return

        patchcanvas.disconnectPorts(self.connection_id,
                                    fast=PatchbayManager.optimized_operation)
        self.in_canvas = False


class Port:
    display_name = ''
    group_id = -1
    portgroup_id = 0
    prevent_stereo = False
    last_digit_to_add = ''
    in_canvas = False

    def __init__(self, port_id: int, name: str, alias_1: str, alias_2: str,
                 port_type: int, flags: int, metadata: str):
        self.port_id = port_id
        self.full_name = name
        self.alias_1 = alias_1
        self.alias_2 = alias_2
        self.type = port_type
        self.flags = flags
        self.metadata = metadata

    def mode(self):
        if self.flags & PORT_IS_OUTPUT:
            return PORT_MODE_OUTPUT
        elif self.flags & PORT_IS_INPUT:
            return PORT_MODE_INPUT
        else:
            return PORT_MODE_NULL

    def short_name(self)->str:
        if self.full_name.startswith('a2j:'):
            long_name = self.full_name.partition(':')[2]
            return long_name.partition(': ')[2]
            
        return self.full_name.partition(':')[2]

    def add_the_last_digit(self):
        self.display_name += ' ' + self.last_digit_to_add
        self.last_digit_to_add = ''
        self.change_canvas_properties()

    def add_to_canvas(self):
        if self.in_canvas:
            return
        
        port_mode = PORT_MODE_NULL
        if self.flags & PORT_IS_INPUT:
            port_mode = PORT_MODE_INPUT
        elif self.flags & PORT_IS_OUTPUT:
            port_mode = PORT_MODE_OUTPUT
        else:
            return

        display_name = self.display_name
        if not PatchbayManager.use_graceful_names:
            display_name = self.short_name()

        is_alternate = False
        if self.flags & PORT_IS_CONTROL_VOLTAGE:
            is_alternate = True
        if self.type == PORT_TYPE_MIDI and self.full_name.startswith('a2j:'):
            for group in PatchbayManager.groups:
                if group.group_id == self.group_id:
                    is_alternate = True
                    break
        
        self.in_canvas = True

        patchcanvas.addPort(
            self.group_id, self.port_id, display_name,
            port_mode, self.type, is_alternate,
            fast=PatchbayManager.optimized_operation)
    
    def remove_from_canvas(self):
        if not self.in_canvas:
            return
        
        patchcanvas.removePort(self.group_id, self.port_id,
                               fast=PatchbayManager.optimized_operation)
        self.in_canvas = False
    
    def change_canvas_properties(self):
        if not self.in_canvas:
            return
        
        display_name = self.display_name
        if not PatchbayManager.use_graceful_names:
            display_name = self.short_name()
        
        patchcanvas.changePortProperties(self.group_id, self.port_id,
                                         self.portgroup_id, display_name)


class Portgroup:
    # Portgroup is a stereo pair of ports
    # but could be a group of more ports
    def __init__(self, group_id: int, portgroup_id: int,
                 port_mode: int, ports: tuple):
        self.group_id = group_id
        self.portgroup_id = portgroup_id
        self.port_mode = port_mode
        self.ports = tuple(ports)
        self.in_canvas = False
        
        for port in self.ports:
            port.portgroup_id = portgroup_id

    def port_type(self):
        if not self.ports:
            return PORT_TYPE_NULL
        
        return self.ports[0].type
    
    def update_ports_in_canvas(self):
        for port in self.ports:
            port.change_canvas_properties()

    def add_to_canvas(self):
        if self.in_canvas:
            return
        
        if len(self.ports) < 2:
            return
        
        for port in self.ports:
            if not port.in_canvas:
                return
        
        port_mode = self.ports[0].mode()
        port_type = self.ports[0].type

        self.in_canvas = True

        port_id_list = [port.port_id for port in self.ports]
        port_id_list = tuple(port_id_list)
        
        patchcanvas.addPortGroup(self.group_id, self.portgroup_id,
                                 self.port_mode, port_type,
                                 port_id_list,
                                 fast=PatchbayManager.optimized_operation)

    def remove_from_canvas(self):
        if not self.in_canvas:
            return
        
        patchcanvas.removePortGroup(self.group_id, self.portgroup_id,
                                    fast=PatchbayManager.optimized_operation)
        self.in_canvas = False


class Group:
    def __init__(self, group_id: int, name: str, group_position):
        self.group_id = group_id
        self.name = name
        self.display_name = name
        self.ports = []
        self.portgroups = []
        self._is_hardware = False
        self.client_icon = ''
        self.a2j_group = False
        self.in_canvas = False
        self.current_position = group_position
    
    def update_ports_in_canvas(self):
        for port in self.ports:
            port.change_canvas_properties()

    def add_to_canvas(self, split=patchcanvas.SPLIT_UNDEF):
        if self.in_canvas:
            return
        
        icon_type = patchcanvas.ICON_APPLICATION
        icon_name = ""

        icon_name = self.name.partition('.')[0].lower()
        
        do_split = bool(self.current_position.flags & GROUP_SPLITTED)
        split = patchcanvas.SPLIT_YES if do_split else patchcanvas.SPLIT_NO
        
        if self._is_hardware:
            icon_type = patchcanvas.ICON_HARDWARE
            if self.a2j_group:
                icon_name = "a2j"
                
        if self.client_icon:
            icon_type = patchcanvas.ICON_CLIENT
            icon_name = self.client_icon

        if (self.name.startswith("PulseAudio ")
                and not self.client_icon):
            self.display_name = self.name.replace(' ', '/', 1)
            if "sink" in self.name.lower():
                icon_type = patchcanvas.ICON_INTERNAL
                icon_name = "audio-volume-medium.svg"
            elif "source" in self.name.lower():
                icon_type = patchcanvas.ICON_INTERNAL
                icon_name = "audio-input-microphone.svg"
        
        self.in_canvas = True
        
        gpos = self.current_position

        patchcanvas.addGroup(
            self.group_id, self.display_name, split,
            icon_type, icon_name, fast=PatchbayManager.optimized_operation,
            null_xy=gpos.null_xy, in_xy=gpos.in_xy, out_xy=gpos.out_xy)
        
        if split == patchcanvas.SPLIT_YES:
            patchcanvas.wrapGroupBox(
                self.group_id, PORT_MODE_INPUT,
                bool(gpos.flags & GROUP_WRAPPED_INPUT))
            patchcanvas.wrapGroupBox(
                self.group_id, PORT_MODE_OUTPUT,
                bool(gpos.flags & GROUP_WRAPPED_OUTPUT))
        else:
            patchcanvas.wrapGroupBox(
                self.group_id, PORT_MODE_NULL,
                bool(gpos.flags & GROUP_WRAPPED_INPUT
                     and gpos.flags & GROUP_WRAPPED_OUTPUT))
    
    def remove_from_canvas(self):
        if not self.in_canvas:
            return
        
        patchcanvas.removeGroup(self.group_id,
                                fast=PatchbayManager.optimized_operation)
        self.in_canvas = False

    def remove_all_ports(self):
        if self.in_canvas:
            for portgroup in self.portgroups:
                portgroup.remove_from_canvas()
            
            for port in self.ports:
                port.remove_from_canvas()
        
        self.portgroups.clear()
        self.ports.clear()

    def add_port(self, port, use_alias: int):
        port_full_name = port.full_name
        
        if use_alias == USE_ALIAS_1:
            port_full_name = port.alias_1
        elif use_alias == USE_ALIAS_2:
            port_full_name = port.alias_2
        
        port.group_id = self.group_id
        
        if (port_full_name.startswith('a2j:')
                and not port.flags & PORT_IS_PHYSICAL):
            port_full_name = port_full_name.partition(':')[2]
        port.display_name = port_full_name.partition(':')[2]

        if not self.ports:
            # we are adding the first port of the group
            if port.flags & PORT_IS_PHYSICAL:
                self._is_hardware = True
            
            if not self.current_position.fully_set:
                if self._is_hardware:
                    self.current_position.flags |= GROUP_SPLITTED
                self.current_position.fully_set = True
                self.save_current_position()
        
        self.ports.append(port)
    
    def remove_port(self, port):
        if port in self.ports:
            self.ports.remove(port)
    
    def remove_portgroup(self, portgroup):
        if portgroup in self.portgroups:
            self.portgroups.remove(portgroup)
   
    def portgroup_memory_added(self, portgroup_mem):
        if portgroup_mem.group_name != self.name:
            return
        
        remove_list = []
        
        # first remove any existing portgroup with one of the porgroup_mem ports
        for portgroup in self.portgroups:
            if (portgroup.port_mode != portgroup_mem.port_mode
                    or portgroup.port_type() != portgroup_mem.port_type):
                continue

            for port in portgroup.ports:
                if port.short_name() in portgroup_mem.port_names:
                    remove_list.append(portgroup)
        
        for portgroup in remove_list:
            portgroup.remove_from_canvas()
            self.remove_portgroup(portgroup)
        
        # add a portgroup if all needed ports are present and consecutive
        port_list = []
        
        for port in self.ports:
            if (port.mode != portgroup_mem.port_mode
                    or port.type != portgroup_mem.port_type):
                continue
            
            if port.short_name() == portgroup_mem.port_names[len(port_list)]:
                port_list.append(port)

                if len(port_list) == len(portgroup_mem.port_names):
                    # all ports are presents, create the portgroup
                    portgroup = PatchbayManager.new_portgroup(
                        self.group_id, port.port_mode, port_list)
                    self.portgroups.append(portgroup)
                    portgroup.add_to_canvas()

            elif port_list:
                # here it is a port breaking the consecutivity of the portgroup
                break

    def save_current_position(self):
        PatchbayManager.send_to_daemon(
            '/ray/server/patchbay/save_group_position',
            *self.current_position.spread())
    
    def set_group_position(self, group_position):
        ex_gpos_flags = self.current_position.flags
        self.current_position = group_position
        gpos = self.current_position
        
        if not self.in_canvas:
            return

        patchcanvas.moveGroupBoxes(
            self.group_id, gpos.null_xy, gpos.in_xy, gpos.out_xy)
        
        if (gpos.flags & GROUP_SPLITTED
                and not ex_gpos_flags & GROUP_SPLITTED):
            patchcanvas.splitGroup(self.group_id)
            
        patchcanvas.wrapGroupBox(self.group_id, PORT_MODE_INPUT,
                                 bool(gpos.flags & GROUP_WRAPPED_INPUT))
        patchcanvas.wrapGroupBox(self.group_id, PORT_MODE_OUTPUT,
                                 bool(gpos.flags & GROUP_WRAPPED_OUTPUT))
        
        if (ex_gpos_flags & GROUP_SPLITTED
                and not gpos.flags & GROUP_SPLITTED):
            patchcanvas.animateBeforeJoin(self.group_id)
    
    def wrap_box(self, port_mode: int, yesno: bool):
        wrap_flag = GROUP_WRAPPED_OUTPUT | GROUP_WRAPPED_INPUT
        if port_mode == PORT_MODE_INPUT:
            wrap_flag = GROUP_WRAPPED_INPUT
        elif port_mode == PORT_MODE_OUTPUT:
            wrap_flag = GROUP_WRAPPED_OUTPUT
            
        if yesno:
            self.current_position.flags |= wrap_flag
        else:
            self.current_position.flags &= ~wrap_flag

        self.save_current_position()
        
        if not self.in_canvas:
            return
        
        patchcanvas.wrapGroupBox(self.group_id, port_mode, yesno)
    
    def set_client_icon(self, icon_name:str):
        self.client_icon = icon_name
    
    def get_pretty_client(self):
        for client_name in ('firewire_pcm', 'a2j',
                            'Hydrogen', 'ardour', 'Ardour', 'Qtractor',
                            'SooperLooper', 'sooperlooper', 'Luppp',
                            'seq64', 'calfjackhost'):
            if self.name == client_name:
                return client_name

            if self.name.startswith(client_name + '_'):
                if self.name.replace(client_name + '_', '', 1).isdigit():
                    return client_name
            
            if self.name.startswith(client_name + '.'):
                # TODO or to check what happens
                return client_name
        return ''
    
    def graceful_port(self, port):
        def split_end_digits(name: str)->tuple:
            num = ''
            while name and name[-1].isdigit():
                num = name[-1] + num
                name = name[:-1]
            
            return (name, num)
        
        def cut_end(name: str, *ends: str)->str:
            for end in ends:
                if name.endswith(end):
                    return name.rsplit(end)[0]
            return name
            
        client_name = self.get_pretty_client()
        
        # same graceful names for physical a2j ports
        # if they are grouped or not
        if (not client_name
                and port.full_name.startswith('a2j:')
                and port.flags & PORT_IS_PHYSICAL):
            client_name = 'a2j'
        
        display_name = port.short_name()
        s_display_name = display_name
        
        if client_name == 'firewire_pcm':
            if '(' in display_name and ')' in display_name:
                after_para = display_name.partition('(')[2]
                display_name = after_para.rpartition(')')[0]
                display_name, num = split_end_digits(display_name)
                
                if num:
                    if display_name.endswith(':'):
                        display_name = display_name[:-1]
                    display_name += ' ' + num
            else:
                display_name = display_name.partition('_')[2]
                display_name = cut_end(display_name, '_in', '_out')
                display_name = display_name.replace(':', ' ')
                
        elif client_name == 'Hydrogen':
            if display_name.startswith('Track_'):
                display_name = display_name.replace('Track_', '', 1)
                
                num, udsc, name = display_name.partition('_')
                if num.isdigit():
                    display_name = num + ' ' + name
            
            if display_name.endswith('_Main_L'):
                display_name = display_name.replace('_Main_L', ' L', 1)
            elif display_name.endswith('_Main_R'):
                display_name = display_name.replace('_Main_R', ' R', 1)
        
        elif client_name == 'a2j':
            display_name, num = split_end_digits(display_name)
            if num:
                if display_name.endswith(' MIDI '):
                    display_name = cut_end(display_name, ' MIDI ')
                    
                    if num == '1':
                        port.last_digit_to_add = '1'
                    else:
                        display_name += ' ' + num
                        
                elif display_name.endswith(' Port-'):
                    display_name = cut_end(display_name, ' Port-')
                    
                    if num == '0':
                        port.last_digit_to_add = '0'
                    else:
                        display_name += ' ' + num
                    
        elif client_name in ('ardour', 'Ardour'):
            display_name, num = split_end_digits(display_name)
            if num:
                display_name = cut_end(display_name,
                                       '/audio_out ', '/audio_in ',
                                       '/midi_out ', '/midi_in ')
                if num == '1':
                    port.last_digit_to_add = '1'
                else:
                    display_name += ' ' + num
        
        elif client_name == 'Qtractor':
            display_name, num = split_end_digits(display_name)
            if num:
                display_name = cut_end(display_name,
                                       '/in_', '/out_')
                if num == '1':
                    port.last_digit_to_add = '1'
                else:
                    display_name += ' ' + num
        
        elif client_name in ('SooperLooper', 'sooperlooper'):
            display_name, num = split_end_digits(display_name)
            if num:
                display_name = cut_end(display_name,
                                       '_in_', '_out_')
                if num == '1':
                    port.last_digit_to_add = '1'
                else:
                    display_name += ' ' + num
                    
        elif client_name == 'Luppp':
            if display_name.endswith('\n'):
                display_name = display_name[:-1]
            
            display_name = display_name.replace('_', ' ')
        
        elif client_name == 'seq64':
            display_name = display_name.replace('seq64 midi ', '', 1)
        
        elif client_name == 'calfjackhost':
            display_name, num = split_end_digits(display_name)
            if num:
                display_name = cut_end(display_name,
                                       ' Out #', ' In #')
                
                display_name += " " + num
        
        elif not client_name:
            display_name = display_name.replace('_', ' ')
            if display_name.lower().endswith(('-left', ' left')):
                display_name = display_name[:-5] + ' L'
            elif display_name.lower().endswith(('-right', ' right')):
                display_name = display_name[:-6] + ' R'
            elif display_name.lower() == 'left in':
                display_name = 'In L'
            elif display_name.lower() == 'right in':
                display_name = 'In R'
            elif display_name.lower() == 'left out':
                display_name = 'Out L'
            elif display_name.lower() == 'right out':
                display_name = 'Out R'
        
        port.display_name = display_name if display_name else s_display_name
    
    def add_portgroup(self, portgroup):
        self.portgroups.append(portgroup)
    
    def change_port_types_view(self, port_types_view: int):
        # first add group to canvas if not already
        self.add_to_canvas()

        for portgroup in self.portgroups:
            if not port_types_view & portgroup.port_type():
                portgroup.remove_from_canvas()
        
        for port in self.ports:
            if not port_types_view & port.type:
                port.remove_from_canvas()
                
        for port in self.ports:
            if port_types_view & port.type:
                port.add_to_canvas()
        
        for portgroup in self.portgroups:
            if port_types_view & portgroup.port_type():
                portgroup.add_to_canvas()

        # remove group from canvas if no visible ports
        for port in self.ports:
            if port.in_canvas:
                break
        else:
            self.remove_from_canvas()
    
    def stereo_detection(self, port):
        if port.type != PORT_TYPE_AUDIO:
            return
        
        if port.flags & PORT_IS_CONTROL_VOLTAGE:
            return
        
        # find the last port with same type and mode in the group
        for other_port in reversed(self.ports):
            if other_port == port:
                continue
            
            if (other_port.type == port.type
                    and other_port.mode() == port.mode()
                    and not other_port.flags & PORT_IS_CONTROL_VOLTAGE
                    and not other_port.portgroup_id
                    and not other_port.prevent_stereo):
                for portgroup_mem in PatchbayManager.portgroups_memory:
                    if (portgroup_mem.group_name == self.name
                        and portgroup_mem.port_mode == other_port.mode()
                        and portgroup_mem.port_type == other_port.type
                        and other_port.short_name() in portgroup_mem.port_names):
                        # other_port (left) is in a remembered portgroup
                        # prevent stereo detection
                        return
                break
        else:
            return

        may_match_list = []
        
        port_name = port.full_name.replace(self.name + ':', '', 1)
        other_port_name = other_port.full_name.replace(self.name + ':', '', 1)

        if port.flags & PORT_IS_PHYSICAL:
            # force stereo detection for system ports
            # it forces it for firewire long and strange names
            may_match_list.append(other_port_name)
        
        elif port_name[-1].isdigit():
            # Port ends with digit
            base_port = port_name[:-1]
            in_num = port_name[-1]

            while base_port[-1].isdigit():
                in_num = base_port[-1] + in_num
                base_port = base_port[:-1]
            
            # if Port ends with Ldigits or Rdigits
            if base_port.endswith('R'):
                may_match_list.append(base_port[:-1] + 'L' + in_num)
            else:
                may_match_list.append(base_port + str(int(in_num) -1))
                
                if int(in_num) in (1, 2):
                    if base_port.endswith((' ', ('_'))):
                        may_match_list.append(base_port[:-1])
                    else:
                        may_match_list.append(base_port)
        else:
            # Port ends with non digit
            if port_name.endswith('R'):
                may_match_list.append(port_name[:-1] + 'L')
                if len(port_name) >= 2:
                    if port_name[-2] == ' ':
                        may_match_list.append(port_name[:-2])
                    else:
                        may_match_list.append(port_name[:-1])
            
            elif port_name.endswith('right'):
                may_match_list.append(port_name[:-5] + 'left')
                
            elif port_name.endswith('Right'):
                may_match_list.append(port_name[:-5] + 'Left')
                
            elif port_name.endswith('(Right)'):
                may_match_list.append(port_name[:-7] + '(Left)')
                
            elif port_name.endswith('.r'):
                may_match_list.append(port_name[:-2] + '.l')
            
            elif port_name.endswith('_r'):
                may_match_list.append(port_name[:-2] + '_l')
            
            elif port_name.endswith('_r\n'):
                may_match_list.append(port_name[:-3] + '_l\n')
            
            for x in ('out', 'Out', 'output', 'Output', 'in', 'In',
                      'input', 'Input', 'audio input', 'audio output'):
                if port_name.endswith('R ' + x):
                    may_match_list.append('L ' + x)
                    
                elif port_name.endswith('right ' + x):
                    may_match_list.append('left ' + x)
                    
                elif port_name.endswith('Right ' + x):
                    may_match_list.append('Left ' + x)
        
        if other_port_name in may_match_list:
            return other_port
        
    def check_for_portgroup_on_last_port(self):
        if not self.ports:
            return

        last_port = self.ports[-1]
        last_port_name = last_port.short_name()
        
        # check in the saved portgroups if we need to make a portgroup
        # or prevent stereo detection
        for portgroup_mem in PatchbayManager.portgroups_memory:
            if (portgroup_mem.group_name == self.name
                    and portgroup_mem.port_type == last_port.type
                    and portgroup_mem.port_mode == last_port.mode()
                    and last_port_name == portgroup_mem.port_names[-1]):
                if (len(portgroup_mem.port_names) == 1
                    or portgroup_mem.port_names.index(last_port_name) + 1
                        != len(portgroup_mem.port_names)):
                    return
                
                port_list = []
                
                for port in self.ports:
                    if (port.type == last_port.type
                            and port.mode() == last_port.mode()):
                        if (port.short_name()
                                == portgroup_mem.port_names[len(port_list)]):
                            port_list.append(port)
                            
                            if len(port_list) == len(portgroup_mem.port_names):
                                portgroup = PatchbayManager.new_portgroup(
                                    self.group_id, port.mode(), port_list)
                                self.portgroups.append(portgroup)
                                for port in port_list:
                                    if not port.in_canvas:
                                        break
                                else:
                                    portgroup.add_to_canvas()
                            
                        elif port_list:
                            return
        
        # detect left audio port if it is a right one
        other_port = self.stereo_detection(last_port)
        if other_port is not None:
            portgroup = PatchbayManager.new_portgroup(
                self.group_id, last_port.mode(), (other_port, last_port))
            self.add_portgroup(portgroup)
            
            if self.in_canvas:
                portgroup.add_to_canvas()
    
    def check_for_display_name_on_last_port(self):
        if not self.ports:
            return
        
        last_port = self.ports[-1]
        last_digit = last_port.full_name[-1]
        
        if last_digit not in ('1', '2'):
            return
        
        for port in reversed(self.ports):
            if (port.type == last_port.type
                    and port.mode() == last_port.mode()
                    and port is not last_port):
                if (port.full_name[:-1] == last_port.full_name[:-1]
                        and ((port.last_digit_to_add == '0'
                              and last_digit == '1'))
                             or (port.last_digit_to_add == '1'
                                 and last_digit == '2')):
                        port.add_the_last_digit()
                break
        
class PatchbayManager:
    use_graceful_names = True
    port_types_view = PORT_TYPE_AUDIO + PORT_TYPE_MIDI
    optimized_operation = False
    groups = []
    portgroups_memory = []
    _next_portgroup_id = 1
    
    def __init__(self, session):
        self.session = session
        
        self.tools_widget = PatchbayToolsWidget()
        self.tools_widget.audio_midi_change_order.connect(
            self.change_port_types_view)
        self.tools_widget.buffer_size_change_order.connect(
            self.change_buffersize)

        self.options_dialog = canvas_options.CanvasOptionsDialog(None)
        self.options_dialog.gracious_names_checked.connect(
            self.set_graceful_names)
        self.options_dialog.a2j_grouped_checked.connect(
            self.set_a2j_grouped)
        self.options_dialog.group_shadows_checked.connect(
            self.set_group_shadows)
        self.options_dialog.theme_changed.connect(
            self.change_theme)
        self.options_dialog.elastic_checked.connect(
            self.set_elastic_canvas)

        self.group_positions = []
        self.connections = []
        self._next_group_id = 0
        self._next_port_id = 0
        self._next_connection_id = 0
        
        self.use_alias = USE_ALIAS_NONE
        
        self.set_graceful_names(RS.settings.value(
            'Canvas/use_graceful_names', True, type=bool))
        self.group_a2j_hw = RS.settings.value(
            'Canvas/group_a2j_ports', True, type=bool)
        
        self._wait_join_group_ids = []
        self.join_animation_connected = False
    
    
    @staticmethod
    def send_to_patchbay_daemon(*args):
        server = GUIServerThread.instance()
        if not server:
            return
        
        if server.patchbay_addr is None:
            return
            
        server.send(server.patchbay_addr, *args)

    @staticmethod
    def send_to_daemon(*args):
        server = GUIServerThread.instance()
        if not server:
            return
        server.toDaemon(*args)
        
    @classmethod
    def set_use_graceful_names(cls, yesno: bool):
        cls.use_graceful_names = yesno
    
    @classmethod
    def optimize_operation(cls, yesno: bool):
        cls.optimized_operation = yesno

    @classmethod
    def new_portgroup(cls, group_id: int, port_mode: int, ports: tuple):
        portgroup = Portgroup(group_id, cls._next_portgroup_id,
                              port_mode, ports)
        cls._next_portgroup_id += 1
        return portgroup

    def canvas_callbacks(self, action, value1, value2, value_str):
        if action == patchcanvas.ACTION_GROUP_INFO:
            pass

        elif action == patchcanvas.ACTION_GROUP_RENAME:
            pass

        elif action == patchcanvas.ACTION_GROUP_SPLIT:
            group_id = value1
            patchcanvas.splitGroup(group_id)
            for group in self.groups:
                if group.group_id == group_id:
                    group.current_position.flags |= GROUP_SPLITTED
                    group.save_current_position()
                    break

        elif action == patchcanvas.ACTION_GROUP_JOIN:
            group_id = value1
            patchcanvas.animateBeforeJoin(group_id)
        
        elif action == patchcanvas.ACTION_GROUP_JOINED:
            group_id = value1
            
            for group in self.groups:
                if group.group_id == group_id:
                    group.current_position.flags &= ~GROUP_SPLITTED
                    group.save_current_position()
                    break
        
        elif action == patchcanvas.ACTION_GROUP_MOVE:
            group_id = value1
            port_mode = value2
            x_y_str = value_str
            
            str_x, colon, str_y = x_y_str.partition(':')
            x = int(str_x)
            y = int(str_y)
            
            for group in self.groups:
                if group.group_id == group_id:
                    gpos = group.current_position
                    if port_mode == PORT_MODE_NULL:
                        gpos.null_xy = (x, y)
                    elif port_mode == PORT_MODE_INPUT:
                        gpos.in_xy = (x, y)
                    elif port_mode == PORT_MODE_OUTPUT:
                        gpos.out_xy = (x, y)
                        
                    group.save_current_position()
                    break
        
        elif action == patchcanvas.ACTION_GROUP_WRAP:
            group_id = value1
            splitted_mode = value2
            yesno = bool(value_str == 'True')
            
            for group in self.groups:
                if group.group_id == group_id:
                    group.wrap_box(splitted_mode, yesno)
                    break
        
        elif action == patchcanvas.ACTION_PORTGROUP_ADD:
            g_id, p_mode, p_type, p_id1, p_id2 =  [
                int(i) for i in value_str.split(":")]

            port_list = []
            
            for port_id in p_id1, p_id2:
                port = self.get_port_from_id(g_id, port_id)
                port_list.append(port)
            
            portgroup = self.new_portgroup(g_id, p_mode, port_list)
            
            for group in self.groups:
                if group.group_id == g_id:
                    group.add_portgroup(portgroup)
            
                    new_portgroup_mem = ray.PortGroupMemory.newFrom(
                        group.name, portgroup.port_type(), portgroup.port_mode,
                        *[port.short_name() for port in port_list])
                    
                    self.add_portgroup_memory(new_portgroup_mem)

                    self.send_to_daemon(
                        '/ray/server/patchbay/save_portgroup',
                        group.name, portgroup.port_type(), portgroup.port_mode,
                        *[port.short_name() for port in port_list])
                    break

            portgroup.add_to_canvas()
        
        elif action == patchcanvas.ACTION_PORTGROUP_REMOVE:
            group_id = value1
            portgroup_id = value2

            for group in self.groups:
                if group.group_id == group_id:
                    for portgroup in group.portgroups:
                        if portgroup.portgroup_id == portgroup_id:
                            for port in portgroup.ports:
                                # save a fake portgroup with one port only
                                # it will be considered as a forced mono port
                                # (no stereo detection)
                                new_portgroup_mem = ray.PortGroupMemory.newFrom(
                                    group.name, portgroup.port_type(),
                                    portgroup.port_mode, port.short_name())
                                self.add_portgroup_memory(new_portgroup_mem)
                                
                                self.send_to_daemon(
                                    '/ray/server/patchbay/save_portgroup',
                                    group.name, port.type, port.mode(),
                                    port.short_name())

                            portgroup.remove_from_canvas()
                            group.portgroups.remove(portgroup)
                            
                            break
                    break
        
        elif action == patchcanvas.ACTION_PORT_INFO:
            group_id = value1
            port_id = value2
            
            port = self.get_port_from_id(group_id, port_id)
            if port is None:
                return
            
            port_type_str = _translate('patchbay', "Audio")
            if port.type == PORT_TYPE_MIDI:
                port_type_str = _translate('patchbay', "MIDI")
                
            flags_list = []
            
            dict_flag_str = {
                PORT_IS_INPUT: _translate('patchbay', 'Input'),
                PORT_IS_OUTPUT: _translate('patchbay', 'Output'),
                PORT_IS_PHYSICAL: _translate('patchbay', 'Physical'),
                PORT_CAN_MONITOR: _translate('patchbay', 'Monitor'),
                PORT_IS_TERMINAL: _translate('patchbay', 'Terminal'),
                PORT_IS_CONTROL_VOLTAGE: _translate('patchbay', 'Control Voltage')}
            
            for key in dict_flag_str.keys():
                if port.flags & key:
                    flags_list.append(dict_flag_str[key])
            
            port_flags_str = ' | '.join(flags_list)
            
            self.session._main_win.show_canvas_port_info(
                port.full_name, port_type_str, port_flags_str)

        elif action == patchcanvas.ACTION_PORT_RENAME:
            pass

        elif action == patchcanvas.ACTION_PORTS_CONNECT:
            g_out, p_out, g_in, p_in = [int(i) for i in value_str.split(":")]

            port_out = self.get_port_from_id(g_out, p_out)
            port_in = self.get_port_from_id(g_in, p_in)
            
            if port_out is None or port_in is None:
                return

            self.send_to_patchbay_daemon(
                '/ray/patchbay/connect',
                port_out.full_name, port_in.full_name)

        elif action == patchcanvas.ACTION_PORTS_DISCONNECT:
            connection_id = value1
            for connection in self.connections:
                if connection.connection_id == connection_id:
                    self.send_to_patchbay_daemon(
                        '/ray/patchbay/disconnect',
                        connection.port_out.full_name, 
                        connection.port_in.full_name)
                    break

        elif action == patchcanvas.ACTION_BG_RIGHT_CLICK:
            menu = QMenu()
            
            action_fullscreen = menu.addAction(
                _translate('patchbay', "Toggle Full Screen"))
            action_fullscreen.setIcon(QIcon.fromTheme('view-fullscreen'))
            
            port_types_menu = QMenu(_translate('patchbay', 'Type filter'))
            port_types_menu.setIcon(QIcon.fromTheme('view-filter'))
            action_audio_midi = port_types_menu.addAction(
                _translate('patchbay', 'Audio + Midi'))
            action_audio = port_types_menu.addAction(
                _translate('patchbay', 'Audio only'))
            action_midi = port_types_menu.addAction(
                _translate('patchbay', 'MIDI only'))
            menu.addMenu(port_types_menu)
            
            zoom_menu = QMenu(_translate('patchbay', 'Zoom'))
            zoom_menu.setIcon(QIcon.fromTheme('zoom'))
            
            autofit = zoom_menu.addAction(
                _translate('patchbay', 'auto-fit'))
            autofit.setIcon(QIcon.fromTheme('zoom-select-fit'))
            autofit.setShortcut('Home')
            
            zoom_in = zoom_menu.addAction(
                _translate('patchbay', 'Zoom +'))
            zoom_in.setIcon(QIcon.fromTheme('zoom-in'))
            zoom_in.setShortcut('Ctrl++')
            
            zoom_out = zoom_menu.addAction(
                _translate('patchbay', 'Zoom -'))
            zoom_out.setIcon(QIcon.fromTheme('zoom-out'))
            zoom_out.setShortcut('Ctrl+-')
            
            zoom_orig = zoom_menu.addAction(
                _translate('patchbay', 'Zoom 100%'))
            zoom_orig.setIcon(QIcon.fromTheme('zoom'))
            zoom_orig.setShortcut('Ctrl+1')
            
            menu.addMenu(zoom_menu)
            
            action_refresh = menu.addAction(
                _translate('patchbay', "Refresh the canvas"))
            action_refresh.setIcon(QIcon.fromTheme('view-refresh'))

            action_options = menu.addAction(
                _translate('patchbay', "Canvas options"))
            action_options.setIcon(QIcon.fromTheme("configure"))

            act_sel = menu.exec(QCursor.pos())
            
            if act_sel == action_fullscreen:
                self.toggle_full_screen()
            elif act_sel == action_audio_midi:
                self.change_port_types_view(
                    GROUP_CONTEXT_AUDIO | GROUP_CONTEXT_MIDI)
            elif act_sel == action_audio:
                self.change_port_types_view(GROUP_CONTEXT_AUDIO)
            elif act_sel == action_midi:
                self.change_port_types_view(GROUP_CONTEXT_MIDI)
            elif act_sel == autofit:
                patchcanvas.canvas.scene.zoom_fit()
            elif act_sel == zoom_in:
                patchcanvas.canvas.scene.zoom_in()
            elif act_sel == zoom_out:
                patchcanvas.canvas.scene.zoom_out()
            elif act_sel == zoom_orig:
                patchcanvas.canvas.scene.zoom_reset()
            elif act_sel == action_refresh:
                self.refresh()
            elif act_sel == action_options:
                self.show_options_dialog()

        elif action == patchcanvas.ACTION_DOUBLE_CLICK:
            self.toggle_full_screen()

    def show_options_dialog(self):
        self.options_dialog.move(QCursor.pos())
        self.options_dialog.show()

    def set_graceful_names(self, yesno: int):
        if self.use_graceful_names != yesno:
            self.toggle_graceful_names()
            
    def set_a2j_grouped(self, yesno: int):
        if self.group_a2j_hw != bool(yesno):
            self.group_a2j_hw = bool(yesno)
            self.refresh()
            
    def set_group_shadows(self, yesno: int):
        if yesno:
            patchcanvas.options.eyecandy = patchcanvas.EYECANDY_SMALL
        else:
            patchcanvas.options.eyecandy = patchcanvas.EYECANDY_NONE
        self.refresh()

    def change_theme(self, index:int):
        idx = 0
        
        if index == 0:
            idx = 0
        elif index == 1:
            idx = 1
        elif index == 2:
            idx = 2
        
        patchcanvas.changeTheme(idx)
        
        theme_name = patchcanvas.getThemeName(idx)
        RS.settings.setValue('Canvas/theme', theme_name)
    
    def set_elastic_canvas(self, yesno: int):
        patchcanvas.setElastic(yesno)

    def toggle_graceful_names(self):
        PatchbayManager.set_use_graceful_names(not self.use_graceful_names)
        for group in self.groups:
            group.update_ports_in_canvas()

    def toggle_full_screen(self):
        self.session._main_win.toggleSceneFullScreen()

    def refresh(self):
        self.clear_all()
        self.send_to_patchbay_daemon('/ray/patchbay/refresh')

    def get_port_from_name(self, port_name: str):
        for group in self.groups:
            for port in group.ports:
                if port.full_name == port_name:
                    return port
    
    def get_port_from_id(self, group_id: int, port_id: int):
        for group in self.groups:
            if group.group_id == group_id:
                for port in group.ports:
                    if port.port_id == port_id:
                        return port
                break
    
    def get_client_icon(self, group_name: str)->str:
        group_name = group_name.partition('/')[0]

        for client in self.session.client_list:
            client_num = ''
            if client.client_id and client.client_id[-1].isdigit():
                client_num = '_' + client.client_id.rpartition('_')[2]
            
            if (group_name == client.name + client_num
                    or group_name == client.name + '.' + client.client_id):
                return client.icon
                
        return ''
    
    def get_group_position(self, group_name):
        for gpos in self.group_positions:
            if (gpos.port_types_view == self.port_types_view
                    and gpos.group_name == group_name):
                return gpos

        # prevent move to a new position in case of port_types_view change
        # if there is no remembered position for this group in new view
        for group in self.groups:
            if group.name == group_name:
                # copy the group_position
                gpos = ray.GroupPosition.newFrom(
                    *group.current_position.spread())
                gpos.port_types_view = self.port_types_view
                self.group_positions.append(gpos)
                return gpos

        # group position doesn't already exists, create one
        gpos = ray.GroupPosition()
        gpos.fully_set = False
        gpos.port_types_view = self.port_types_view
        gpos.group_name = group_name
        gpos.null_xy, gpos.in_xy, gpos.out_xy =  \
            patchcanvas.CanvasGetNewGroupPositions()
        self.group_positions.append(gpos)
        self.send_to_daemon(
            '/ray/server/patchbay/save_group_position', *gpos.spread())
        return gpos

    def add_portgroup_memory(self, portgroup_mem):
        remove_list = []
        
        for pg_mem in self.portgroups_memory:
            if pg_mem.has_a_common_port_with(portgroup_mem):
                remove_list.append(pg_mem)
        
        for pg_mem in remove_list:
            self.portgroups_memory.remove(pg_mem)
            
        self.portgroups_memory.append(portgroup_mem)

    def add_port(self, name: str, alias_1: str, alias_2: str,
                 port_type: int, flags: int, metadata: str):
        port = Port(self._next_port_id, name, alias_1, alias_2,
                    port_type, flags, metadata)
        self._next_port_id += 1

        full_port_name = name
        if self.use_alias == USE_ALIAS_1:
            full_port_name = alias_1
        elif self.use_alias == USE_ALIAS_2:
            full_port_name = alias_2
        
        group_name, colon, port_name = full_port_name.partition(':')
        
        a2j_group = False
        group_is_new = False
        
        if (full_port_name.startswith('a2j:')
                and (not self.group_a2j_hw
                     or not port.flags & PORT_IS_PHYSICAL)):
            group_name, colon, port_name = port_name.partition(':')
            group_name = group_name.rpartition(' [')[0]
            if port.flags & PORT_IS_PHYSICAL:
                a2j_group = True

        for group in self.groups:
            if group.name == group_name:
                break
        else:
            # port is an non existing group, create the group
            gpos = self.get_group_position(group_name)
            group = Group(self._next_group_id, group_name, gpos)
            group.a2j_group = a2j_group
            group.set_client_icon(self.get_client_icon(group_name))
            
            self._next_group_id += 1
            self.groups.append(group)
            group_is_new = True
        
        group.add_port(port, self.use_alias)
        group.graceful_port(port)
        
        if group_is_new and self.port_types_view & port_type:
            gpos = self.get_group_position(group_name)
            group.set_group_position(gpos)
            group.add_to_canvas()

        if self.port_types_view & port_type:
            group.add_to_canvas()
            port.add_to_canvas()

        group.check_for_portgroup_on_last_port()
        group.check_for_display_name_on_last_port()

    def remove_port(self, name: str):
        port = self.get_port_from_name(name)
        if port is None:
            return
        
        for group in self.groups:
            if group.group_id == port.group_id:
                # remove portgroup first if port is in a portgroup
                if port.portgroup_id:
                    for portgroup in group.portgroups:
                        if portgroup.portgroup_id == port.portgroup_id:
                            group.portgroups.remove(portgroup)
                            portgroup.remove_from_canvas()
                            break

                group.remove_port(port)
                port.remove_from_canvas()

                if not group.ports:
                    group.remove_from_canvas()
                    self.groups.remove(group)
                break
    
    def rename_port(self, name: str, new_name: str):
        port = self.get_port_from_name(name)
        if port is None:
            sys.stderr.write(
                "RaySession:PatchbayManager::rename_port" 
                + "\"%s\" to \"%s\", port doesn't exists\n"
                    % (name, new_name))
            return
        
        group_name = name.partition(':')[0]
        new_group_name = new_name.partition(':')[0]
        
        # In case a port rename implies another group for the port
        if (self.use_alias == USE_ALIAS_NONE
                and group_name != new_group_name):
            for group in self.groups:
                if group.name == group_name:
                    group.remove_port(port)
                    if not group.ports:
                        self.groups.remove(group)
                    break
            
            port.remove_from_canvas()
            port.full_name = new_name

            for group in self.groups:
                if group.name == new_group_name:
                    group.add_port(port)
                    break
            else:
                # copy the group_position to not move the group
                # because group has been renamed
                orig_gpos = self.get_group_position(group_name)
                gpos = ray.GroupPosition.newFrom(*orig_gpos.spread())
                gpos.group_name = new_group_name
                
                group = Group(self._next_group_id, new_group_name, gpos)
                self._next_group_id += 1
                group.add_port(port)
                if self.port_types_view & port.type:
                    group.add_to_canvas()
            
            if self.port_types_view & port.type:
                port.add_to_canvas()
            return
        
        for group in self.groups:
            if group.group_id == port.group_id:
                port.full_name = new_name
                group.graceful_port(port)
                port.change_canvas_properties()
                break
    
    def add_connection(self, port_out_name: str, port_in_name: str):
        port_out = self.get_port_from_name(port_out_name)
        port_in = self.get_port_from_name(port_in_name)
        
        if port_out is None or port_in is None:
            return
        
        for connection in self.connections:
            if (connection.port_out == port_out
                    and connection.port_in == port_in):
                return
        
        connection = Connection(self._next_connection_id, port_out, port_in)
        self._next_connection_id += 1
        self.connections.append(connection)
        if connection.port_type() & self.port_types_view:
            connection.add_to_canvas()
    
    def remove_connection(self, port_out_name: str, port_in_name: str):
        port_out = self.get_port_from_name(port_out_name)
        port_in = self.get_port_from_name(port_in_name)
        
        if port_out is None or port_in is None:
            return
        
        for connection in self.connections:
            if (connection.port_out == port_out
                    and connection.port_in == port_in):
                self.connections.remove(connection)
                connection.remove_from_canvas()
                break
    
    def update_group_position(self, *args):
        # remember group position and move boxes if needed
        gpos = ray.GroupPosition.newFrom(*args)
        
        for group_position in self.group_positions:
            if (group_position.port_types_view == gpos.port_types_view
                    and group_position.group_name == gpos.group_name):
                group_position.update(*args)
        else:
            self.group_positions.append(gpos)
        
        if gpos.port_types_view == self.port_types_view:
            for group in self.groups:
                if group.name == gpos.group_name:
                    group.set_group_position(gpos)
                    break

    def update_portgroup(self, *args):
        portgroup_mem = ray.PortGroupMemory.newFrom(*args)
        self.add_portgroup_memory(portgroup_mem)

        for group in self.groups:
            if group.name == portgroup_mem.group_name:
                group.portgroup_memory_added(portgroup_mem)
                break
                
    def clear_all(self):
        self.optimize_operation(True)
        for connection in self.connections:
            connection.remove_from_canvas()
        
        for group in self.groups:
            group.remove_all_ports()
            group.remove_from_canvas()
        
        self.optimize_operation(False)
        
        self.connections.clear()
        self.groups.clear()
        
        self._next_group_id = 0
        self._next_port_id = 0
        self._next_portgroup_id = 1
        self._next_connection_id = 0


    def change_port_types_view(self, port_types_view: int):
        if port_types_view == self.port_types_view:
            return

        self.port_types_view = port_types_view
        # Prevent visual update at each canvas item creation
        # because we may create a lot of ports here
        self.optimize_operation(True) 
        
        for connection in self.connections:
            if (connection.in_canvas
                    and not port_types_view & connection.port_type()):
                connection.remove_from_canvas()

        for group in self.groups:
            in_canvas = group.in_canvas
            group.change_port_types_view(port_types_view)
            gpos = self.get_group_position(group.name)
            group.set_group_position(gpos)
        
        for connection in self.connections:
            if (not connection.in_canvas
                    and port_types_view & connection.port_type()):
                connection.add_to_canvas()
        
        self.optimize_operation(False)
        patchcanvas.updateAllPositions()

    def disannounce(self):
        self.send_to_patchbay_daemon('/ray/patchbay/gui_disannounce')
        self.clear_all()
    
    def server_started(self):
        self.tools_widget.set_jack_running(True)
    
    def server_stopped(self):
        self.tools_widget.set_jack_running(False)
        self.clear_all()
    
    def server_lose(self):
        self.tools_widget.set_jack_running(False)
        self.clear_all()

        ret = QMessageBox.critical(
            self.session._main_win,
            _translate('patchbay', "JACK server lose"),
            _translate('patchbay', "JACK server seems to be totally busy... ;("))
    
    def set_dsp_load(self, dsp_load: int):
        self.tools_widget.set_dsp_load(dsp_load)
    
    def add_xrun(self):
        self.tools_widget.add_xrun()

    def change_buffersize(self, buffer_size):
        self.send_to_patchbay_daemon('/ray/patchbay/set_buffer_size',
                                     buffer_size)
        
    def buffer_size_changed(self, buffer_size):
        self.tools_widget.set_buffer_size(buffer_size)
        
    def sample_rate_changed(self, samplerate):
        self.tools_widget.set_samplerate(samplerate)
    
    def receive_big_packets(self, state: int):
        self.optimize_operation(not bool(state))
        if state:
            patchcanvas.updateAllPositions()
    
    def fast_temp_file_memory(self, temp_path):
        canvas_data = {}
        with open(temp_path, 'r') as file:
            canvas_data = json.load(file)

        for key in canvas_data.keys():
            if key == 'group_positions':
                for gpos_dict in canvas_data[key]:
                    gpos = ray.GroupPosition()
                    gpos.write_from_dict(gpos_dict)
                    self.update_group_position(*gpos.spread())
            
            elif key == 'portgroups':
                for pg_dict in canvas_data[key]:
                    portgroup_mem = ray.PortGroupMemory()
                    portgroup_mem.write_from_dict(pg_dict)
                    self.update_portgroup(*portgroup_mem.spread())
                    
        os.remove(temp_path)
        
    def fast_temp_file_running(self, temp_path):
        file = open(temp_path, 'r')
        patchbay_data = json.load(file)

        self.optimize_operation(True)

        for key in patchbay_data.keys():
            if key == 'ports':
                for p in patchbay_data[key]:
                    self.add_port(
                        p['name'], p['alias_1'], p['alias_2'], p['type'],
                        p['flags'], p['metadata'])
            
            elif key == 'connections':
                for c in patchbay_data[key]:
                    self.add_connection(c['port_out_name'], c['port_in_name'])

        self.optimize_operation(False)
        patchcanvas.updateAllPositions()
        
        os.remove(temp_path)
    
    def patchbay_announce(self, jack_running: int, samplerate: int,
                          buffer_size: int):
        self.tools_widget.set_samplerate(samplerate)
        self.tools_widget.set_buffer_size(buffer_size)
        self.tools_widget.set_jack_running(jack_running)
        self.session._main_win.add_patchbay_tools(self.tools_widget)
