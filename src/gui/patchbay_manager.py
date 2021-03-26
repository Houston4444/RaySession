import time
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
GROUP_WRAPPED_UNSPLITTED = 0x08
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
        
        fast_operation = PatchbayManager.optimized_operation
        
        patchcanvas.connectPorts(
            self.connection_id,
            self.port_out.group_id, self.port_out.port_id,
            self.port_in.group_id, self.port_in.port_id,
            fast=fast_operation)
        
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
    set_the_one_on_pair = False
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

    def set_the_one(self):
        self.display_name += ' 1'
        self.set_the_one_on_pair = False
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
        #if not self.use_graceful_names:
            display_name = self.full_name.partition(':')[2]

        is_alternate = False
        if self.flags & PORT_IS_CONTROL_VOLTAGE:
            is_alternate = True
        if self.type == PORT_TYPE_MIDI and self.full_name.startswith('a2j:'):
            for group in PatchbayManager.groups:
                if group.group_id == self.group_id:
                    if group.name != 'a2j':
                        is_alternate = True
                        break
        
        self.in_canvas = True

        fast_operation = PatchbayManager.optimized_operation

        patchcanvas.addPort(
            self.group_id, self.port_id, display_name,
            port_mode, self.type, is_alternate, fast=fast_operation)
    
    def remove_from_canvas(self):
        if not self.in_canvas:
            return
        
        fast_operation = PatchbayManager.optimized_operation
        
        patchcanvas.removePort(self.group_id, self.port_id, fast=fast_operation)
        self.in_canvas = False
    
    def change_canvas_properties(self):
        if not self.in_canvas:
            return
        
        display_name = self.display_name
        if not PatchbayManager.use_graceful_names:
            display_name = self.full_name.partition(':')[2]
        
        patchcanvas.changePortProperties(self.group_id, self.port_id,
                                         self.portgroup_id, display_name)


class Portgroup:
    # Portgroup is a stereo pair of ports
    # but could be a group of more ports
    def __init__(self, group_id: int, portgroup_id: int, port_mode: int):
        self.group_id = group_id
        self.portgroup_id = portgroup_id
        self.port_mode = port_mode
        self.ports = []
        self.in_canvas = False

    def add_ports(self, *ports):
        for port in ports:
            port.portgroup_id = self.portgroup_id
            self.ports.append(port)

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
        
        port_mode = self.ports[0].mode()
        port_type = self.ports[0].type

        self.in_canvas = True
        
        fast_operation = PatchbayManager.optimized_operation
        
        patchcanvas.addPortGroup(self.group_id, self.portgroup_id,
                                 self.port_mode, port_type,
                                 [port.port_id for port in self.ports],
                                 fast=fast_operation)

    def remove_from_canvas(self):
        if not self.in_canvas:
            return
        
        fast_operation = PatchbayManager.optimized_operation
        
        patchcanvas.removePortGroup(self.group_id, self.portgroup_id,
                                    fast=fast_operation)
        self.in_canvas = False


class Group:
    def __init__(self, group_id: int, name: str):
        self.group_id = group_id
        self.name = name
        self.display_name = name
        self.ports = []
        self.portgroups = []
        self._is_hardware = False
        self.client_icon = ''
        self.a2j_group = False
        self.in_canvas = False
        self.splitted = False

    def update_ports_in_canvas(self):
        for port in self.ports:
            port.change_canvas_properties()

    def add_to_canvas(self, split=patchcanvas.SPLIT_UNDEF):
        if self.in_canvas:
            return
        
        icon_type = patchcanvas.ICON_APPLICATION
        icon_name = ""

        icon_name = self.name.partition('.')[0].lower()
        
        if split == patchcanvas.SPLIT_UNDEF:
            if self._is_hardware:
                split = patchcanvas.SPLIT_YES
            else:
                split = patchcanvas.SPLIT_NO
        
        if self._is_hardware:
            split = patchcanvas.SPLIT_YES
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
        patchcanvas.addGroup(self.group_id, self.display_name,
                             patchcanvas.SPLIT_UNDEF,
                             icon_type, icon_name,
                             fast=PatchbayManager.optimized_operation)
    
    def remove_from_canvas(self):
        if not self.in_canvas:
            return
        
        patchcanvas.removeGroup(self.group_id,
                                fast=PatchbayManager.optimized_operation)
        self.in_canvas = False

    def move_boxes(self, null_xy: tuple, in_xy: tuple, out_xy: tuple,
                   anim=True):
        if not self.in_canvas:
            return
        
        patchcanvas.moveGroupBoxes(
            self.group_id, null_xy, in_xy, out_xy, animate=anim)

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
        
        self.ports.append(port)
    
    def remove_port(self, port):
        if port in self.ports:
            self.ports.remove(port)
    
    def remove_portgroup(self, portgroup):
        if portgroup in self.portgroups:
            self.portgroups.remove(portgroup)
    
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
        
        #display_name = port.display_name
        display_name = port.full_name.partition(':')[2]
        if port.full_name.startswith('a2j') and client_name != 'a2j':
            display_name = display_name.partition(': ')[2]
            
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
            name_1, colon, name_2 = display_name.partition(':')
            if name_2:
                display_name = name_2
                
                if display_name.startswith(' '):
                    display_name = display_name[1:]
                
                display_name = cut_end(display_name, ' Port-0', ' MIDI 1')
                    
        elif client_name in ('ardour', 'Ardour'):
            display_name, num = split_end_digits(display_name)
            if num:
                display_name = cut_end(display_name,
                                       '/audio_out ', '/audio_in ',
                                       '/midi_out ', '/midi_in ')
                if num == '1':
                    port.set_the_one_on_pair = True
                else:
                    display_name += ' ' + num
        
        elif client_name == 'Qtractor':
            display_name, num = split_end_digits(display_name)
            if num:
                display_name = cut_end(display_name,
                                       '/in_', '/out_')
                if num == '1':
                    port.set_the_one_on_pair = True
                else:
                    display_name += ' ' + num
        
        elif client_name in ('SooperLooper', 'sooperlooper'):
            display_name, num = split_end_digits(display_name)
            if num:
                display_name = cut_end(display_name,
                                       '_in_', '_out_')
                if num == '1':
                    port.set_the_one_on_pair = True
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
            if display_name.lower().endswith(' left'):
                display_name = display_name[:-5] + ' L'
            elif display_name.lower().endswith(' right'):
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
    
    def change_audio_midi_view(self, audio_midi_view: int):
        # first add group to canvas if not already
        self.add_to_canvas()

        for portgroup in self.portgroups:
            if not audio_midi_view & portgroup.port_type():
                portgroup.remove_from_canvas()
        
        for port in self.ports:
            if not audio_midi_view & port.type:
                port.remove_from_canvas()
                
        for port in self.ports:
            if audio_midi_view & port.type:
                port.add_to_canvas()
        
        for portgroup in self.portgroups:
            if audio_midi_view & portgroup.port_type():
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

        
class PatchbayManager:
    use_graceful_names = True
    audio_midi_view = PORT_TYPE_AUDIO + PORT_TYPE_MIDI
    optimized_operation = False
    groups = []
    
    def __init__(self, session):
        self.session = session
        
        self.tools_widget = PatchbayToolsWidget()
        self.tools_widget.audio_midi_change_order.connect(
            self.change_audio_midi_view)
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
        self._next_portgroup_id = 1
        self._next_connection_id = 0
        
        self.use_alias = USE_ALIAS_NONE
        
        self.set_graceful_names(RS.settings.value(
            'Canvas/use_graceful_names', True, type=bool))
        self.group_a2j_hw = RS.settings.value(
            'Canvas/group_a2j_ports', True, type=bool)
        
        self.wait_join_group_id = None
        self.join_animation_connected = False
        
        
    @classmethod
    def set_use_graceful_names(cls, yesno: bool):
        cls.use_graceful_names = yesno
    
    @classmethod
    def optimize_operation(cls, yesno: bool):
        cls.optimized_operation = yesno
    
    def send_to_patchbay_daemon(self, *args):
        server = GUIServerThread.instance()
        if not server:
            return
        
        if server.patchbay_addr is None:
            return
            
        server.send(server.patchbay_addr, *args)

    def send_to_daemon(self, *args):
        server = GUIServerThread.instance()
        if not server:
            return
        server.toDaemon(*args)

    def join_animation_finished(self):
        if self.wait_join_group_id is not None:
            patchcanvas.joinGroup(self.wait_join_group_id)
            
            for group in self.groups:
                if group.group_id == self.wait_join_group_id:
                    group.splitted = False
                    break
                
            self.wait_join_group_id = None

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
                    group.splitted = True
                    break

        elif action == patchcanvas.ACTION_GROUP_JOIN:
            group_id = value1
            self.wait_join_group_id = group_id
            if not self.join_animation_connected:
                patchcanvas.canvas.qobject.move_boxes_finished.connect(
                    self.join_animation_finished)
                self.join_animation_connected = True
            patchcanvas.animateBeforeJoin(group_id)
        
        elif action == patchcanvas.ACTION_GROUP_MOVE:
            group_id = value1
            port_mode = value2
            x_y_str = value_str
            
            str_x, colon, str_y = x_y_str.partition(':')
            x = int(str_x)
            y = int(str_y)
            
            for group in self.groups:
                if group.group_id == group_id:
                    for gpos in self.group_positions:
                        if (gpos.group_name == group.name
                                and gpos.context == self.audio_midi_view):
                            break
                    else:
                        gpos = ray.GroupPosition()
                        gpos.context = self.audio_midi_view
                        gpos.group_name = group.name
                        if port_mode != PORT_MODE_NULL:
                            gpos.flags = GROUP_SPLITTED
                        self.group_positions.append(gpos)
                            
                    if port_mode == PORT_MODE_NULL:
                        gpos.null_xy = (x, y)
                    elif port_mode == PORT_MODE_INPUT:
                        gpos.in_xy = (x, y)
                    elif port_mode == PORT_MODE_OUTPUT:
                        gpos.out_xy = (x, y)
                    
                    print('tu nenvoi', group.name)
                    self.send_to_daemon(
                        '/ray/server/patchbay/save_group_position',
                        *gpos.spread())
                    break
        
        elif action == patchcanvas.ACTION_GROUP_WRAP:
            group_id = value1
            splitted_mode = value2
            wrap = bool(value_str == 'True')
            
            patchcanvas.wrapGroupBox(group_id, splitted_mode, wrap)
        
        elif action == patchcanvas.ACTION_PORT_GROUP_ADD:
            g_id, p_mode, p_type, p_id1, p_id2 =  [
                int(i) for i in value_str.split(":")]
            
            portgroup = Portgroup(g_id, self._next_portgroup_id, p_mode)
            self._next_portgroup_id += 1
            
            for port_id in p_id1, p_id2:
                port = self.get_port_from_id(port_id)
                portgroup.add_ports(port)
            
            for group in self.groups:
                if group.group_id == g_id:
                    group.add_portgroup(portgroup)

            portgroup.add_to_canvas()
        
        elif action == patchcanvas.ACTION_PORT_GROUP_REMOVE:
            
            group_id = value1
            portgrp_id = value2

            for group in self.groups:
                if group.group_id == group_id:
                    for portgroup in group.portgroups:
                        if portgroup.portgroup_id == portgrp_id:
                            group.portgroups.remove(portgroup)
                            portgroup.remove_from_canvas()
                            break
                    break
        
        elif action == patchcanvas.ACTION_PORT_INFO:
            pass

        elif action == patchcanvas.ACTION_PORT_RENAME:
            pass

        elif action == patchcanvas.ACTION_PORTS_CONNECT:
            g_out, p_out, g_in, p_in = [int(i) for i in value_str.split(":")]

            port_out = self.get_port_from_id(p_out)
            port_in = self.get_port_from_id(p_in)
            
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
            action_fullscreen.triggered.connect(self.toggle_full_screen)
            
            action_refresh = menu.addAction(
                _translate('patchbay', "Refresh the canvas"))
            action_refresh.setIcon(QIcon.fromTheme('view-refresh'))
            action_refresh.triggered.connect(self.refresh)

            action_options = menu.addAction(
                _translate('patchbay', "Canvas options"))
            action_options.setIcon(QIcon.fromTheme("configure"))
            action_options.triggered.connect(self.show_options_dialog)

            menu.exec(QCursor.pos())

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
    
    def get_port_from_id(self, port_id: int):
        for group in self.groups:
            for port in group.ports:
                if port.port_id == port_id:
                    return port
    
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
            group = Group(self._next_group_id, group_name)
            group.a2j_group = a2j_group
            group.set_client_icon(self.get_client_icon(group_name))
            
            self._next_group_id += 1
            self.groups.append(group)
            group_is_new = True
        
        group.add_port(port, self.use_alias)
        group.graceful_port(port)
        
        split = patchcanvas.SPLIT_UNDEF
        for group_position in self.group_positions:
            if (group_position.group_name == group.name
                    and group_position.context == self.audio_midi_view):
                if group_position.flags & GROUP_SPLITTED:
                    split = patchcanvas.SPLIT_YES
                else:
                    split = patchcanvas.SPLIT_NO
                break
        
        if group_is_new and self.audio_midi_view & port_type:
            new_group_pos = patchcanvas.CanvasGetNewGroupPositions()
            group.add_to_canvas(split=split)

            for gp in self.group_positions:
                if (gp.group_name == group.name
                        and gp.context == self.audio_midi_view):
                    patchcanvas.moveGroupBoxes(
                        group.group_id, gp.null_xy, gp.in_xy, gp.out_xy,
                        animate=False)

                    self.send_to_daemon(
                        '/ray/server/patchbay/save_group_position',
                        *gp.spread())
                    break
            else:
                print('sdfmsdfllsfllf', group.group_id)
                patchcanvas.moveGroupBoxes(group.group_id, *new_group_pos)

        if self.audio_midi_view & port_type:
            group.add_to_canvas(split=split)
            port.add_to_canvas()

        # detect left audio port if it is a right one
        other_port = group.stereo_detection(port)
        if other_port is not None:
            portgroup = Portgroup(group.group_id, self._next_portgroup_id,
                                  port.mode())
            self._next_portgroup_id += 1
            portgroup.add_ports(other_port, port)
            group.add_portgroup(portgroup)
            
            if other_port.set_the_one_on_pair:
                other_port.set_the_one()
            
            if group.in_canvas:
                portgroup.add_to_canvas()

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
                group = Group(self._next_group_id, new_group_name)
                self._next_group_id += 1
                group.add_port(port)
                if self.audio_midi_view & port.type:
                    group.add_to_canvas()
            
            if self.audio_midi_view & port.type:
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
        if connection.port_type() & self.audio_midi_view:
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
        print('taeliteltek', args)
        
        # remember group position and move boxes if needed
        gpos = ray.GroupPosition.newFrom(*args)
        
        for group_position in self.group_positions:
            if group_position.group_name == gpos.group_name:
                group_position.update(*args)
        else:
            self.group_positions.append(gpos)
        
        if gpos.context != self.audio_midi_view:
            return
        
        for group in self.groups:
            if group.name == gpos.group_name:
                group.move_boxes(gpos.null_xy, gpos.in_xy, gpos.out_xy)
                break

    def update_portgroup(self, group_name: str, port_mode: int,
                         port1: str, port2:str):
        pass
    
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


    def change_audio_midi_view(self, audio_midi_view: int):
        self.audio_midi_view = audio_midi_view
        self.optimize_operation(True)
        
        
        
        for connection in self.connections:
            if (connection.in_canvas
                    and not audio_midi_view & connection.port_type()):
                connection.remove_from_canvas()

        for group in self.groups:
            group.change_audio_midi_view(audio_midi_view)
        
        for connection in self.connections:
            if (not connection.in_canvas
                    and audio_midi_view & connection.port_type()):
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
    
    def patchbay_announce(self, jack_running: int, samplerate: int,
                          buffer_size: int):
        self.tools_widget.set_samplerate(samplerate)
        self.tools_widget.set_buffer_size(buffer_size)
        self.tools_widget.set_jack_running(jack_running)
        self.session._main_win.add_patchbay_tools(self.tools_widget)
