
import json
import os
import sys
import time
from PyQt5.QtGui import QCursor, QIcon, QGuiApplication
from PyQt5.QtWidgets import QMenu, QAction, QLabel, QMessageBox
from PyQt5.QtCore import pyqtSlot, QTimer, QPoint

import ray

from gui_tools import RS

from patchcanvas import patchcanvas
from patchcanvas import PortMode, PortType, CallbackAct, IconType
from gui_server_thread import GuiServerThread
from patchbay_tools import PatchbayToolsWidget, CanvasMenu, CanvasPortInfoDialog

import canvas_options


# Port Flags
PORT_IS_INPUT = 0x01
PORT_IS_OUTPUT = 0x02
PORT_IS_PHYSICAL = 0x04
PORT_CAN_MONITOR = 0x08
PORT_IS_TERMINAL = 0x10
PORT_IS_CONTROL_VOLTAGE = 0x100

# Group Position Flags
GROUP_CONTEXT_AUDIO = 0x01
GROUP_CONTEXT_MIDI = 0x02
GROUP_SPLITTED = 0x04
GROUP_WRAPPED_INPUT = 0x10
GROUP_WRAPPED_OUTPUT = 0x20
GROUP_HAS_BEEN_SPLITTED = 0x40

# Portgroup Origin
PORTGROUP_FROM_DETECTION = 0
PORTGROUP_FROM_METADATA = 1
PORTGROUP_FROM_USER = 2

# Meta data (taken from pyjacklib)
_JACK_METADATA_PREFIX = "http://jackaudio.org/metadata/"
JACK_METADATA_CONNECTED = _JACK_METADATA_PREFIX + "connected"
JACK_METADATA_EVENT_TYPES = _JACK_METADATA_PREFIX + "event-types"
JACK_METADATA_HARDWARE = _JACK_METADATA_PREFIX + "hardware"
JACK_METADATA_ICON_LARGE = _JACK_METADATA_PREFIX + "icon-large"
JACK_METADATA_ICON_NAME = _JACK_METADATA_PREFIX + "icon-name"
JACK_METADATA_ICON_SMALL = _JACK_METADATA_PREFIX + "icon-small"
JACK_METADATA_ORDER = _JACK_METADATA_PREFIX + "order"
JACK_METADATA_PORT_GROUP = _JACK_METADATA_PREFIX + "port-group"
JACK_METADATA_PRETTY_NAME = _JACK_METADATA_PREFIX + "pretty-name"
JACK_METADATA_SIGNAL_TYPE = _JACK_METADATA_PREFIX + "signal-type"

_translate = QGuiApplication.translate

def enum_to_flag(enum: int) -> int:
    return 2 ** (enum - 1)


class Connection:
    def __init__(self, connection_id: int, port_out, port_in):
        self.connection_id = connection_id
        self.port_out = port_out
        self.port_in = port_in
        self.in_canvas = False

    def port_type(self)->int:
        return self.port_out.type

    def add_to_canvas(self):
        if PatchbayManager.very_fast_operation:
            return

        if self.in_canvas:
            return

        if not PatchbayManager.port_type_shown(self.port_type()):
            return

        self.in_canvas = True

        patchcanvas.connect_ports(
            self.connection_id,
            self.port_out.group_id, self.port_out.port_id,
            self.port_in.group_id, self.port_in.port_id)

    def remove_from_canvas(self):
        if PatchbayManager.very_fast_operation:
            return

        if not self.in_canvas:
            return

        patchcanvas.disconnect_ports(self.connection_id)
        self.in_canvas = False

    def semi_hide(self, yesno: bool):
        if not self.in_canvas:
            return
        
        patchcanvas.semi_hide_connection(
            self.connection_id, yesno)
    
    def set_in_front(self):
        if not self.in_canvas:
            return
        
        patchcanvas.set_connection_in_front(self.connection_id)

class Port:
    display_name = ''
    group_id = -1
    portgroup_id = 0
    prevent_stereo = False
    last_digit_to_add = ''
    in_canvas = False
    order = None
    uuid = 0 # will contains the real JACK uuid

    # given by JACK metadatas
    pretty_name = ''
    mdata_portgroup = ''

    def __init__(self, port_id: int, name: str,
                 port_type: int, flags: int, uuid: int):
        self.port_id = port_id
        self.full_name = name
        self.type = port_type
        self.flags = flags
        self.uuid = uuid

    def mode(self):
        if self.flags & PORT_IS_OUTPUT:
            return PortMode.OUTPUT
        elif self.flags & PORT_IS_INPUT:
            return PortMode.INPUT
        else:
            return PortMode.NULL

    def short_name(self)->str:
        if self.full_name.startswith('a2j:'):
            long_name = self.full_name.partition(':')[2]
            if ': ' in long_name:
                # normal case for a2j
                return long_name.partition(': ')[2]

        if self.full_name.startswith('Midi-Bridge:'):
            # supress 'Midi-Bridge:' at port name begginning
            long_name = self.full_name.partition(':')[2]
            if ') ' in long_name:
                # normal case, name is after ') '
                return long_name.partition(') ')[2]

            if ': ' in long_name:
                # pipewire jack.filter_name = True
                # Midi-bridge names starts with 'MidiBridge:ClientName:'
                return long_name.partition(': ')[2]

        return self.full_name.partition(':')[2]

    def add_the_last_digit(self):
        self.display_name += ' ' + self.last_digit_to_add
        self.last_digit_to_add = ''
        self.rename_in_canvas()

    def add_to_canvas(self):
        if PatchbayManager.very_fast_operation:
            return
        
        if self.in_canvas:
            return

        if not PatchbayManager.port_type_shown(self.type):
            return
    
        #if not PatchbayManager.port_types_view & self.type:
            #return

        port_mode = PortMode.NULL
        if self.flags & PORT_IS_INPUT:
            port_mode = PortMode.INPUT
        elif self.flags & PORT_IS_OUTPUT:
            port_mode = PortMode.OUTPUT
        else:
            return

        display_name = self.display_name
        
        if self.pretty_name:
            display_name = self.pretty_name
        
        if not PatchbayManager.use_graceful_names:
            display_name = self.short_name()
        
        is_alternate = False
        if self.flags & PORT_IS_CONTROL_VOLTAGE:
            is_alternate = True
        if (self.type == PortType.MIDI_JACK
                and self.full_name.startswith(('a2j:', 'Midi-Bridge:'))):
            for group in PatchbayManager.groups:
                if group.group_id == self.group_id:
                    is_alternate = True
                    break

        self.in_canvas = True

        patchcanvas.add_port(
            self.group_id, self.port_id, display_name,
            port_mode, self.type, is_alternate)

    def remove_from_canvas(self):
        if PatchbayManager.very_fast_operation:
            return
        
        if not self.in_canvas:
            return

        patchcanvas.remove_port(self.group_id, self.port_id)
        self.in_canvas = False

    def rename_in_canvas(self):
        if not self.in_canvas:
            return

        display_name = self.display_name
        if self.pretty_name:
            display_name = self.pretty_name

        if not PatchbayManager.use_graceful_names:
            display_name = self.short_name()

        patchcanvas.rename_port(
            self.group_id, self.port_id, display_name)

    def __lt__(self, other):
        if self.type != other.type:
            return (self.type < other.type)

        if (self.flags & PORT_IS_CONTROL_VOLTAGE
                !=  other.flags & PORT_IS_CONTROL_VOLTAGE):
            return not bool(self.flags & PORT_IS_CONTROL_VOLTAGE)

        if (self.full_name.startswith('a2j:')
                != other.full_name.startswith('a2j:')):
            return not self.full_name.startswith('a2j:')

        if self.mode() != other.mode():
            return (self.mode() < other.mode())

        if self.order is None and other.order is None:
            return self.port_id < other.port_id
        if self.order is None:
            return False
        if other.order is None:
            return True

        return bool(self.order < other.order)


class Portgroup:
    # Portgroup is a stereo pair of ports
    # but could be a group of more ports
    def __init__(self, group_id: int, portgroup_id: int,
                 port_mode: int, ports: tuple[Port]):
        self.group_id = group_id
        self.portgroup_id = portgroup_id
        self.port_mode = port_mode
        self.ports = tuple(ports)

        self.mdata_portgroup = ''
        self.above_metadatas = False

        self.in_canvas = False


        for port in self.ports:
            port.portgroup_id = portgroup_id

    def port_type(self):
        if not self.ports:
            return PortType.NULL

        return self.ports[0].type

    def update_ports_in_canvas(self):
        for port in self.ports:
            port.rename_in_canvas()

    def sort_ports(self):
        port_list = list(self.ports)
        port_list.sort()
        self.ports = tuple(port_list)

    def add_to_canvas(self):
        if PatchbayManager.very_fast_operation:
            return
        
        if self.in_canvas:
            return
    
        if not PatchbayManager.port_type_shown(self.port_type()):
            return

        #if not PatchbayManager.port_types_view & self.port_type():
            #return

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

        patchcanvas.add_portgroup(self.group_id, self.portgroup_id,
                                  self.port_mode, port_type,
                                  port_id_list)

    def remove_from_canvas(self):
        if PatchbayManager.very_fast_operation:
            return
        
        if not self.in_canvas:
            return

        patchcanvas.remove_portgroup(self.group_id, self.portgroup_id)
        self.in_canvas = False


class Group:
    def __init__(self, group_id: int, name: str, group_position):
        self.group_id = group_id
        self.name = name
        self.display_name = name
        self.ports = list[Port]()
        self.portgroups = list[Portgroup]()
        #self.ports_to_rename_queue = []
        self._is_hardware = False
        self.client_icon = ''
        self.a2j_group = False
        self.in_canvas = False
        self.current_position = group_position
        self.uuid = 0
        
        self.has_gui = False
        self.gui_visible = False

        self._icon_from_metadata = False

    def update_ports_in_canvas(self):
        for port in self.ports:
            port.rename_in_canvas()

    def add_to_canvas(self, split=patchcanvas.SPLIT_UNDEF):
        if self.in_canvas:
            return

        icon_type = IconType.APPLICATION
        icon_name = self.name.partition('.')[0].lower()

        do_split = bool(self.current_position.flags & GROUP_SPLITTED)
        split = patchcanvas.SPLIT_YES if do_split else patchcanvas.SPLIT_NO

        if self._is_hardware:
            icon_type = IconType.HARDWARE
            if self.a2j_group or self.display_name == "Midi-Bridge":
                icon_name = "a2j"

        if self.client_icon:
            icon_type = IconType.CLIENT
            icon_name = self.client_icon

        if (self.name.startswith("PulseAudio ")
                and not self.client_icon):
            if "sink" in self.name.lower():
                icon_type = IconType.INTERNAL
                #icon_name = "audio-volume-medium.svg"
                icon_name = 'monitor_playback'
            elif "source" in self.name.lower():
                icon_type = IconType.INTERNAL
                #icon_name = "audio-input-microphone.svg"
                icon_name = 'monitor_capture'

        elif (self.name.endswith(" Monitor")
                and not self.client_icon):
            # this group is (probably) a pipewire Monitor group
            icon_type = IconType.INTERNAL
            #icon_name = "audio-volume-medium.svg"
            icon_name = 'monitor_playback'

        self.in_canvas = True

        gpos = self.current_position

        self.display_name = self.display_name.replace('.0/', '/')
        self.display_name = self.display_name.replace('_', ' ')
        
        display_name = self.name
        if PatchbayManager.use_graceful_names:
            display_name = self.display_name
        
        layout_modes_ = {}
        for port_mode in (PortMode.INPUT, PortMode.OUTPUT,
                          PortMode.INPUT | PortMode.OUTPUT):
            layout_modes_[port_mode] = gpos.get_layout_mode(port_mode)
        
        patchcanvas.add_group(
            self.group_id, display_name, split,
            icon_type, icon_name, layout_modes=layout_modes_,
            null_xy=gpos.null_xy, in_xy=gpos.in_xy, out_xy=gpos.out_xy)

        if do_split:
            gpos.flags |= GROUP_HAS_BEEN_SPLITTED
            patchcanvas.wrap_group_box(
                self.group_id, PortMode.INPUT,
                bool(gpos.flags & GROUP_WRAPPED_INPUT),
                animate=False)
            patchcanvas.wrap_group_box(
                self.group_id, PortMode.OUTPUT,
                bool(gpos.flags & GROUP_WRAPPED_OUTPUT),
                animate=False)
        else:
            patchcanvas.wrap_group_box(
                self.group_id, PortMode.NULL,
                bool(gpos.flags & GROUP_WRAPPED_INPUT
                     and gpos.flags & GROUP_WRAPPED_OUTPUT),
                animate=False)
            
        if self.has_gui:
            patchcanvas.set_optional_gui_state(self.group_id, self.gui_visible)

    def remove_from_canvas(self):
        if not self.in_canvas:
            return

        patchcanvas.remove_group(self.group_id)
        self.in_canvas = False

    def redraw_in_canvas(self):
        if not self.in_canvas:
            return
        
        patchcanvas.redraw_group(self.group_id)

    def update_name_in_canvas(self):
        if not self.in_canvas:
            return
        
        display_name = self.name
        if PatchbayManager.use_graceful_names:
            display_name = self.display_name
        
        patchcanvas.rename_group(self.group_id, display_name)

    def semi_hide(self, yesno: bool):
        if not self.in_canvas:
            return 
        
        patchcanvas.semi_hide_group(self.group_id, yesno)

    def set_in_front(self):
        if not self.in_canvas:
            return
        
        patchcanvas.set_group_in_front(self.group_id)

    def get_number_of_boxes(self)->int:
        if not self.in_canvas:
            return 0

        return patchcanvas.get_number_of_boxes(self.group_id)

    def select_filtered_box(self, n_select=0):
        if not self.in_canvas:
            return
        
        patchcanvas.select_filtered_group_box(self.group_id, n_select)

    def set_optional_gui_state(self, visible: bool):
        self.has_gui = True
        self.gui_visible = visible
        
        if not self.in_canvas:
            return
        
        patchcanvas.set_optional_gui_state(self.group_id, visible)

    def remove_all_ports(self):
        if self.in_canvas:
            for portgroup in self.portgroups:
                portgroup.remove_from_canvas()

            for port in self.ports:
                port.remove_from_canvas()

        self.portgroups.clear()
        self.ports.clear()

    def add_port(self, port: Port):
        port_full_name = port.full_name

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
            portgroup.remove_from_canvas()
            for port in portgroup.ports:
                port.portgroup_id = 0
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
                        self.group_id, port.mode(), port_list)
                    self.portgroups.append(portgroup)
                    portgroup.add_to_canvas()
                    break

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

        patchcanvas.move_group_boxes(
            self.group_id, gpos.null_xy, gpos.in_xy, gpos.out_xy)

        if (gpos.flags & GROUP_SPLITTED
                and not ex_gpos_flags & GROUP_SPLITTED):
            patchcanvas.split_group(self.group_id)

        patchcanvas.wrap_group_box(self.group_id, PortMode.INPUT,
                                 bool(gpos.flags & GROUP_WRAPPED_INPUT))
        patchcanvas.wrap_group_box(self.group_id, PortMode.OUTPUT,
                                 bool(gpos.flags & GROUP_WRAPPED_OUTPUT))

        if (ex_gpos_flags & GROUP_SPLITTED
                and not gpos.flags & GROUP_SPLITTED):
            patchcanvas.animate_before_join(self.group_id)

    def set_layout_mode(self, port_mode: int, layout_mode: int):
        self.current_position.set_layout_mode(port_mode, layout_mode)
        self.save_current_position()
        
        if not self.in_canvas:
            return
        
        patchcanvas.set_group_layout_mode(self.group_id, port_mode, layout_mode)

    def wrap_box(self, port_mode: int, yesno: bool):
        wrap_flag = GROUP_WRAPPED_OUTPUT | GROUP_WRAPPED_INPUT
        if port_mode == PortMode.INPUT:
            wrap_flag = GROUP_WRAPPED_INPUT
        elif port_mode == PortMode.OUTPUT:
            wrap_flag = GROUP_WRAPPED_OUTPUT

        if yesno:
            self.current_position.flags |= wrap_flag
        else:
            self.current_position.flags &= ~wrap_flag

        self.save_current_position()

        if not self.in_canvas:
            return

        patchcanvas.wrap_group_box(self.group_id, port_mode, yesno)

    def set_client_icon(self, icon_name:str, from_metadata=False):
        # icon from metadata is the prority
        if not from_metadata and self._icon_from_metadata:
            return
        
        self._icon_from_metadata = from_metadata
        self.client_icon = icon_name
        if self.in_canvas:
            patchcanvas.set_group_icon(
                self.group_id, IconType.CLIENT, icon_name)

    def get_pretty_client(self):
        for client_name in ('firewire_pcm', 'a2j',
                            'Hydrogen', 'ardour', 'Ardour', 'Qtractor',
                            'SooperLooper', 'sooperlooper', 'Luppp',
                            'seq64', 'calfjackhost', 'rakarrack-plus',
                            'seq192', 'Non-Mixer', 'jack_mixer'):
            if self.name == client_name:
                return client_name

            if self.name.startswith(client_name + '.'):
                return client_name
            
            name = self.name.partition('/')[0]
            if name == client_name:
                return client_name
            
            if name.startswith(client_name + '_'):
                if name.replace(client_name + '_', '', 1).isdigit():
                    return client_name
            
            if ' (' in name and name.endswith(')'):
                name = name.partition(' (')[0]
                if name == client_name:
                    return client_name
                
                if name.startswith(client_name + '_'):
                    if name.replace(client_name + '_', '', 1).isdigit():
                        return client_name

        return ''

    def graceful_port(self, port):
        def split_end_digits(name: str)->tuple:
            num = ''
            while name and name[-1].isdigit():
                num = name[-1] + num
                name = name[:-1]

            if num.startswith('0') and num not in ('0', '09'):
                num = num[1:]

            return (name, num)

        def cut_end(name: str, *ends: str)->str:
            for end in ends:
                if name.endswith(end):
                    return name.rsplit(end)[0]
            return name

        client_name = self.get_pretty_client()

        if (not client_name
                and port.full_name.startswith(('a2j:', 'Midi-Bridge:'))
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
                display_name, num = split_end_digits(display_name)
                display_name = display_name + num

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
            for pt in ('audio', 'midi'):
                if display_name == "physical_%s_input_monitor_enable" % pt:
                    display_name = "physical monitor"
                    break
            else:
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
        
        elif client_name == 'Non-Mixer':
            display_name, num = split_end_digits(display_name)
            if num:
                display_name = cut_end(display_name, '/in-', '/out-')
                
                if num == '1':
                    port.last_digit_to_add = '1'
                else:
                    display_name += ' ' + num
        
        elif client_name == 'jack_mixer':
            prefix, out, side = display_name.rpartition(' Out')
            if out and side in (' L', ' R', ''):
                display_name = prefix + side
                        
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

        elif client_name == 'seq192':
            display_name = display_name.replace('seq192 ', '', 1)

        elif client_name == 'calfjackhost':
            display_name, num = split_end_digits(display_name)
            if num:
                display_name = cut_end(display_name,
                                       ' Out #', ' In #')

                display_name += " " + num

        elif client_name == 'rakarrack-plus':
            if display_name.startswith('rakarrack-plus '):
                display_name = display_name.replace('rakarrack-plus ', '', 1)
            display_name = display_name.replace('_', ' ')

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

            if display_name.startswith('Audio'):
                display_name = display_name.replace('Audio ', '')

        # reduce graceful name for pipewire Midi-Bridge with
        # option jack.filter_name = true
        if (port.full_name.startswith('Midi-Bridge')
                and display_name.startswith(('capture_', 'playback_'))):
            display_name = display_name.partition('_')[2]

        port.display_name = display_name if display_name else s_display_name

    def add_portgroup(self, portgroup):
        self.portgroups.append(portgroup)

    def change_port_types_view(self):
        # first add group to canvas if not already
        self.add_to_canvas()

        for portgroup in self.portgroups:
            if not PatchbayManager.port_type_shown(portgroup.port_type()):
                portgroup.remove_from_canvas()

        for port in self.ports:
            if not PatchbayManager.port_type_shown(port.type):
                port.remove_from_canvas()

        for port in self.ports:
            port.add_to_canvas()

        for portgroup in self.portgroups:
            portgroup.add_to_canvas()

        # remove group from canvas if no visible ports
        for port in self.ports:
            if port.in_canvas:
                break
        else:
            self.remove_from_canvas()

    def stereo_detection(self, port):
        if port.type != PortType.AUDIO_JACK:
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

    def sort_ports_in_canvas(self):
        already_optimized = PatchbayManager.optimized_operation
        PatchbayManager.optimize_operation(True)

        conn_list = []

        if not PatchbayManager.very_fast_operation:
            for conn in PatchbayManager.connections:
                for port in self.ports:
                    if (port in (conn.port_out, conn.port_in)
                            and conn not in conn_list):
                        conn_list.append(conn)
            
            for connection in conn_list:
                connection.remove_from_canvas()
            
            for portgroup in self.portgroups:
                portgroup.remove_from_canvas()

            for port in self.ports:
                port.remove_from_canvas()
        
        self.ports.sort()

        # search and remove existing portgroups with non consecutive ports
        portgroups_to_remove = []

        for portgroup in self.portgroups:
            search_index = 0
            previous_port = None
            seems_ok = False

            for port in self.ports:
                if not seems_ok and port is portgroup.ports[search_index]:
                    if (port.mdata_portgroup != portgroup.mdata_portgroup
                            and not portgroup.above_metadatas):
                        portgroups_to_remove.append(portgroup)
                        break

                    if (not portgroup.above_metadatas and not search_index
                            and previous_port is not None
                            and previous_port.mdata_portgroup
                            and previous_port.mdata_portgroup == port.mdata_portgroup):
                        # previous port had the same portgroup metadata
                        # that this port. we need to remove this portgroup.
                        portgroups_to_remove.append(portgroup)
                        break

                    search_index += 1
                    if search_index == len(portgroup.ports):
                        # all ports of portgroup are consecutive
                        # but still exists the risk that metadatas says
                        # that the portgroup has now more ports
                        seems_ok = True
                        if (portgroup.above_metadatas
                                or not portgroup.mdata_portgroup):
                            break

                elif search_index:
                    if (seems_ok
                            and (port.mdata_portgroup != previous_port.mdata_portgroup
                                 or port.type != portgroup.port_type()
                                 or port.mode() != portgroup.port_mode)):
                        # port after the portgroup has not to make
                        # the portgroup higher. We keep this portgroup
                        break

                    # this port breaks portgroup ports consecutivity.
                    # note that ports have been just sorted by type and mode
                    # so no risk that this port is falsely breaking portgroup
                    portgroups_to_remove.append(portgroup)
                    break

                previous_port = port
            else:
                if not seems_ok:
                    portgroups_to_remove.append(portgroup)

        for portgroup in portgroups_to_remove:
            self.remove_portgroup(portgroup)

        # add missing portgroups aboving metadatas from portgroup memory
        for portgroup_mem in PatchbayManager.portgroups_memory:
            if not portgroup_mem.above_metadatas:
                continue

            if portgroup_mem.group_name != self.name:
                continue

            founded_ports = []

            for port in self.ports:
                if (not port.portgroup_id
                        and port.type == portgroup_mem.port_type
                        and port.mode() == portgroup_mem.port_mode
                        and port.short_name()
                            == portgroup_mem.port_names[len(founded_ports)]):
                    founded_ports.append(port)
                    if len(founded_ports) == len(portgroup_mem.port_names):
                        new_portgroup = PatchbayManager.new_portgroup(
                            self.group_id, port.mode(), founded_ports)
                        self.portgroups.append(new_portgroup)
                        break

                elif founded_ports:
                    break

        # detect and add portgroups given from metadatas
        portgroups_mdata = [] # list of dicts

        for port in self.ports:
            if port.mdata_portgroup:
                pg_mdata = None
                if portgroups_mdata:
                    pg_mdata = portgroups_mdata[-1]

                if not port.portgroup_id:
                    if (pg_mdata is not None
                            and pg_mdata['pg_name'] == port.mdata_portgroup
                            and pg_mdata['port_type'] == port.type
                            and pg_mdata['port_mode'] == port.mode()):
                        pg_mdata['ports'].append(port)
                    else:
                        portgroups_mdata.append(
                            {'pg_name': port.mdata_portgroup,
                            'port_type': port.type,
                            'port_mode': port.mode(),
                            'ports':[port]})
        
        for pg_mdata in portgroups_mdata:
            if len(pg_mdata['ports']) < 2:
                continue

            new_portgroup = PatchbayManager.new_portgroup(
                self.group_id, pg_mdata['port_mode'], pg_mdata['ports'])
            new_portgroup.mdata_portgroup = pg_mdata['pg_name']
            self.portgroups.append(new_portgroup)
        
        # add missing portgroups from portgroup memory
        for portgroup_mem in PatchbayManager.portgroups_memory:
            if portgroup_mem.above_metadatas:
                continue

            if portgroup_mem.group_name != self.name:
                continue

            founded_ports = []

            for port in self.ports:
                if (not port.portgroup_id
                        and port.type == portgroup_mem.port_type
                        and port.mode() == portgroup_mem.port_mode
                        and port.short_name()
                            == portgroup_mem.port_names[len(founded_ports)]):
                    founded_ports.append(port)
                    if len(founded_ports) == len(portgroup_mem.port_names):
                        new_portgroup = PatchbayManager.new_portgroup(
                            self.group_id, port.mode(), founded_ports)
                        self.portgroups.append(new_portgroup)
                        break

                elif founded_ports:
                    break
        
        if not PatchbayManager.very_fast_operation:
            # ok for re-adding all items to canvas
            for port in self.ports:
                port.add_to_canvas()

            for portgroup in self.portgroups:
                portgroup.add_to_canvas()
        
            for connection in conn_list:
                connection.add_to_canvas()
        
        if not already_optimized:
            PatchbayManager.optimize_operation(False)
            self.redraw_in_canvas()

    def add_all_ports_to_canvas(self):
        for port in self.ports:
            port.add_to_canvas()

        for portgroup in self.portgroups:
            portgroup.add_to_canvas()

class PatchbayManager:
    use_graceful_names = True
    port_types_view = (enum_to_flag(PortType.AUDIO_JACK)
                       | enum_to_flag(PortType.MIDI_JACK))
    optimized_operation = False
    very_fast_operation = False
    groups = list[Group]()
    connections = list[Connection]()
    group_positions = list[ray.GroupPosition]()
    portgroups_memory = []
    _next_portgroup_id = 1
    orders_queue = []

    def __init__(self, session):
        self.session = session

        self.tools_widget = PatchbayToolsWidget()
        self.tools_widget.buffer_size_change_order.connect(
            self.change_buffersize)

        self._next_group_id = 0
        self._next_port_id = 0
        self._next_connection_id = 0

        self.set_graceful_names(RS.settings.value(
            'Canvas/use_graceful_names', True, type=bool))
        self.group_a2j_hw = RS.settings.value(
            'Canvas/group_a2j_ports', True, type=bool)

        self._wait_join_group_ids = []
        self.join_animation_connected = False
        self.options_dialog = None
        
        # all patchbay events are delayed
        # to reduce the patchbay comsumption.
        # Redraws in canvas are made once 50ms have passed without any event.
        # This prevent one group redraw per port added/removed
        # when a lot of ports are added/removed/renamed simultaneously
        self._orders_queue_timer = QTimer()
        self._orders_queue_timer.setInterval(50)
        self._orders_queue_timer.setSingleShot(True)
        self._orders_queue_timer.timeout.connect(
            self._order_queue_timeout)

    def finish_init(self):
        self.canvas_menu = CanvasMenu(self)
        self.options_dialog = canvas_options.CanvasOptionsDialog(
            self.session.main_win)
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
        self.options_dialog.prevent_overlap_checked.connect(
            self.set_prevent_overlap)
        self.options_dialog.max_port_width_changed.connect(
            patchcanvas.set_max_port_width)

    def save_patchcanvas_cache(self):
        patchcanvas.save_cache()

    @staticmethod
    def send_to_patchbay_daemon(*args):
        server = GuiServerThread.instance()
        if not server:
            return

        if server.patchbay_addr is None:
            return

        server.send(server.patchbay_addr, *args)

    @staticmethod
    def send_to_daemon(*args):
        server = GuiServerThread.instance()
        if not server:
            return
        server.to_daemon(*args)

    @classmethod
    def set_use_graceful_names(cls, yesno: bool):
        cls.use_graceful_names = yesno

    @classmethod
    def optimize_operation(cls, yesno: bool):
        cls.optimized_operation = yesno
        if patchcanvas.canvas is not None:
            patchcanvas.set_loading_items(yesno)

    @classmethod
    def set_very_fast_operation(cls, yesno: bool):
        cls.very_fast_operation = yesno

    @classmethod
    def new_portgroup(cls, group_id: int, port_mode: int, ports: tuple):
        portgroup = Portgroup(group_id, cls._next_portgroup_id,
                              port_mode, ports)
        cls._next_portgroup_id += 1
        return portgroup

    @classmethod
    def port_type_shown(cls, port_type: int):
        return bool(cls.port_types_view & enum_to_flag(port_type))

    def canvas_callbacks(self, action, value1, value2, value_str):
        if action == CallbackAct.GROUP_INFO:
            pass

        elif action == CallbackAct.GROUP_RENAME:
            pass

        elif action == CallbackAct.GROUP_SPLIT:
            group_id = value1
            for group in self.groups:
                if group.group_id == group_id:
                    on_place = not bool(
                        group.current_position.flags & GROUP_HAS_BEEN_SPLITTED)
                    patchcanvas.split_group(group_id, on_place=on_place)
                    group.current_position.flags |= GROUP_SPLITTED
                    group.current_position.flags |= GROUP_HAS_BEEN_SPLITTED
                    group.save_current_position()
                    break

        elif action == CallbackAct.GROUP_JOIN:
            group_id = value1
            patchcanvas.animate_before_join(group_id)

        elif action == CallbackAct.GROUP_JOINED:
            group_id = value1

            for group in self.groups:
                if group.group_id == group_id:
                    group.current_position.flags &= ~GROUP_SPLITTED
                    group.save_current_position()
                    break

        elif action == CallbackAct.GROUP_MOVE:
            group_id = value1
            port_mode = value2
            x_y_str = value_str

            str_x, colon, str_y = x_y_str.partition(':')
            x = int(str_x)
            y = int(str_y)

            for group in self.groups:
                if group.group_id == group_id:
                    gpos = group.current_position
                    if port_mode == PortMode.NULL:
                        gpos.null_xy = (x, y)
                    elif port_mode == PortMode.INPUT:
                        gpos.in_xy = (x, y)
                    elif port_mode == PortMode.OUTPUT:
                        gpos.out_xy = (x, y)

                    group.save_current_position()
                    break

        elif action == CallbackAct.GROUP_WRAP:
            group_id = value1
            splitted_mode = value2
            yesno = bool(value_str == 'True')

            for group in self.groups:
                if group.group_id == group_id:
                    group.wrap_box(splitted_mode, yesno)
                    break

        elif action == CallbackAct.GROUP_LAYOUT_CHANGE:
            group_id = value1
            port_mode = value2
            layout_mode = int(value_str)

            for group in self.groups:
                if group.group_id == group_id:
                    group.set_layout_mode(port_mode, layout_mode)
                    break

        elif action == CallbackAct.PORTGROUP_ADD:
            g_id, p_mode, p_type, p_id1, p_id2 =  [
                int(i) for i in value_str.split(":")]

            port_list = []
            above_metadatas = False

            for port_id in p_id1, p_id2:
                port = self.get_port_from_id(g_id, port_id)
                if port.mdata_portgroup:
                    above_metadatas = True
                port_list.append(port)

            portgroup = self.new_portgroup(g_id, p_mode, port_list)

            for group in self.groups:
                if group.group_id == g_id:
                    group.add_portgroup(portgroup)

                    new_portgroup_mem = ray.PortGroupMemory.new_from(
                        group.name, portgroup.port_type(),
                        portgroup.port_mode, int(above_metadatas),
                        *[port.short_name() for port in port_list])

                    self.add_portgroup_memory(new_portgroup_mem)

                    self.send_to_daemon(
                        '/ray/server/patchbay/save_portgroup',
                        *new_portgroup_mem.spread())
                    break

            portgroup.add_to_canvas()

        elif action == CallbackAct.PORTGROUP_REMOVE:
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
                                above_metadatas = bool(port.mdata_portgroup)

                                new_portgroup_mem = ray.PortGroupMemory.new_from(
                                    group.name, portgroup.port_type(),
                                    portgroup.port_mode, int(above_metadatas),
                                    port.short_name())
                                self.add_portgroup_memory(new_portgroup_mem)

                                self.send_to_daemon(
                                    '/ray/server/patchbay/save_portgroup',
                                    *new_portgroup_mem.spread())

                            portgroup.remove_from_canvas()
                            group.portgroups.remove(portgroup)

                            break
                    break

        elif action == CallbackAct.PORT_INFO:
            group_id = value1
            port_id = value2

            port = self.get_port_from_id(group_id, port_id)
            if port is None:
                return

            dialog = CanvasPortInfoDialog(self.session.main_win)
            dialog.set_port(port)
            dialog.show()

        elif action == CallbackAct.PORT_RENAME:
            pass

        elif action == CallbackAct.PORTS_CONNECT:
            g_out, p_out, g_in, p_in = [int(i) for i in value_str.split(":")]

            port_out = self.get_port_from_id(g_out, p_out)
            port_in = self.get_port_from_id(g_in, p_in)

            if port_out is None or port_in is None:
                return

            self.send_to_patchbay_daemon(
                '/ray/patchbay/connect',
                port_out.full_name, port_in.full_name)

        elif action == CallbackAct.PORTS_DISCONNECT:
            connection_id = value1
            for connection in self.connections:
                if connection.connection_id == connection_id:
                    self.send_to_patchbay_daemon(
                        '/ray/patchbay/disconnect',
                        connection.port_out.full_name,
                        connection.port_in.full_name)
                    break

        elif action == CallbackAct.BG_RIGHT_CLICK:
            x, y = value1, value2
            self.canvas_menu.exec(QPoint(x, y))

        elif action == CallbackAct.DOUBLE_CLICK:
            self.toggle_full_screen()
        
        elif action == CallbackAct.CLIENT_SHOW_GUI:
            group_id, int_visible = value1, value2
            for group in self.groups:
                if group.group_id == group_id:
                    for client in self.session.client_list:
                        if client.can_be_own_jack_client(group.name):
                            show = 'show' if int_visible else 'hide'
                            self.send_to_daemon(
                                '/ray/client/%s_optional_gui' % show,
                                client.client_id)
                            break
                    break
        
        elif action == CallbackAct.THEME_CHANGED:
            theme_ref = value_str
            if self.options_dialog is not None:
                self.options_dialog.set_theme(theme_ref)

            self.remove_and_add_all()

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
        self.remove_and_add_all()

    def change_theme(self, theme_name: str):
        if not theme_name:
            return
        patchcanvas.change_theme(theme_name)

    def set_elastic_canvas(self, yesno: int):
        patchcanvas.set_elastic(yesno)

    def set_prevent_overlap(self, yesno: int):
        patchcanvas.set_prevent_overlap(yesno)

    def toggle_graceful_names(self):
        PatchbayManager.set_use_graceful_names(not self.use_graceful_names)
        PatchbayManager.optimize_operation(True)
        for group in self.groups:
            group.update_ports_in_canvas()
            group.update_name_in_canvas()
        PatchbayManager.optimize_operation(False)
        patchcanvas.redraw_all_groups()

    def toggle_full_screen(self):
        self.session.main_win.toggle_scene_full_screen()

    def refresh(self):
        self.clear_all()
        self.send_to_patchbay_daemon('/ray/patchbay/refresh')

    def get_port_from_name(self, port_name: str) -> Port:
        for group in self.groups:
            for port in group.ports:
                if port.full_name == port_name:
                    return port

    def get_port_from_uuid(self, uuid:int) -> Port:
        for group in self.groups:
            for port in group.ports:
                if port.uuid == uuid:
                    return port

    def get_port_from_id(self, group_id: int, port_id: int) -> Port:
        for group in self.groups:
            if group.group_id == group_id:
                for port in group.ports:
                    if port.port_id == port_id:
                        return port
                break

    def get_group_position(self, group_name: str):
        for gpos in self.group_positions:
            if (gpos.port_types_view == PatchbayManager.port_types_view
                    and gpos.group_name == group_name):
                return gpos

        # prevent move to a new position in case of port_types_view change
        # if there is no remembered position for this group in new view
        for group in self.groups:
            if group.name == group_name:
                # copy the group_position
                gpos = ray.GroupPosition.new_from(
                    *group.current_position.spread())
                gpos.port_types_view = PatchbayManager.port_types_view
                self.group_positions.append(gpos)
                return gpos

        # group position doesn't already exists, create one
        gpos = ray.GroupPosition()
        gpos.fully_set = False
        gpos.port_types_view = PatchbayManager.port_types_view
        gpos.group_name = group_name
        gpos.null_xy, gpos.in_xy, gpos.out_xy =  \
            patchcanvas.utils.get_new_group_positions()
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

    def remove_and_add_all(self):
        self.optimize_operation(True)
            
        for connection in self.connections:
            connection.remove_from_canvas()
        
        for group in self.groups:
            for portgroup in group.portgroups:
                portgroup.remove_from_canvas()
            
            for port in group.ports:
                port.remove_from_canvas()
            group.remove_from_canvas()
            
            group.add_to_canvas()
            for port in group.ports:
                port.add_to_canvas()
            for portgroup in group.portgroups:
                portgroup.add_to_canvas()
        
        for connection in self.connections:
            connection.add_to_canvas()
        
        self.optimize_operation(False)
        patchcanvas.redraw_all_groups()

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

        patchcanvas.clear()

        self._next_group_id = 0
        self._next_port_id = 0
        self._next_portgroup_id = 1
        self._next_connection_id = 0

    def change_port_types_view(self, port_types_view: int):
        if port_types_view == PatchbayManager.port_types_view:
            return

        PatchbayManager.port_types_view = port_types_view

        # Prevent visual update at each canvas item creation
        # because we may create a lot of ports here
        self.optimize_operation(True)

        for connection in self.connections:
            if (connection.in_canvas
                    and not port_types_view & connection.port_type()):
                connection.remove_from_canvas()

        for group in self.groups:
            group.change_port_types_view()
            gpos = self.get_group_position(group.name)
            group.set_group_position(gpos)

        for connection in self.connections:
            #if (not connection.in_canvas
                    #and port_types_view & connection.port_type()):
            connection.add_to_canvas()

        self.optimize_operation(False)
        patchcanvas.redraw_all_groups()
        self.session.signaler.port_types_view_changed.emit(
            self.port_types_view)

    def get_json_contents_from_path(self, file_path: str)->dict:
        if not os.path.exists(file_path):
            return {}

        if not os.access(file_path, os.R_OK):
            return {}

        try:
            file = open(file_path, 'r')
        except IOError:
            return {}

        try:
            new_dict = json.load(file)
        except ImportError:
            return {}

        file.close()
        return new_dict

    def client_name_and_uuid(self, client_name: str, uuid: int):
        for group in self.groups:
            if group.name == client_name:
                group.uuid = uuid
                break

    def add_port(self, name: str, port_type: int, flags: int, uuid: int) -> int:
        ' adds port and returns the group_id '
        port = Port(self._next_port_id, name, port_type, flags, uuid)
        self._next_port_id += 1

        full_port_name = name
        group_name, colon, port_name = full_port_name.partition(':')

        a2j_group = False
        group_is_new = False

        if (full_port_name.startswith(('a2j:', 'Midi-Bridge:'))
                and (not self.group_a2j_hw
                     or not port.flags & PORT_IS_PHYSICAL)):
            group_name, colon, port_name = port_name.partition(':')
            if full_port_name.startswith('a2j:'):
                group_name = group_name.rpartition(' [')[0]
                
                # fix a2j wrongly substitute '.' with space
                for client in self.session.client_list:
                    if (client.status != ray.ClientStatus.STOPPED
                            and '.' in client.jack_client_name
                            and (client.jack_client_name.replace('.', ' ', 1)
                                 == group_name)):
                        group_name = group_name.replace(' ', '.' , 1)
                        break

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
            
            for client in self.session.client_list:
                if client.can_be_own_jack_client(group_name):
                    group.set_client_icon(client.icon)
                    
                    # in case of long jack naming (ClientName.ClientId)
                    # do not display ClientName if we have the icon
                    if (client.icon
                            and client.jack_client_name.endswith('.' + client.client_id)
                            and group.name.startswith(client.jack_client_name)):
                        group.display_name = group.display_name.partition('.')[2]
                    
                    if client.has_gui:
                        group.set_optional_gui_state(client.gui_state)
                    break

            self._next_group_id += 1
            self.groups.append(group)
            group_is_new = True

        group.add_port(port)
        group.graceful_port(port)

        if group_is_new:
            gpos = self.get_group_position(group_name)
            group.set_group_position(gpos)

        group.add_to_canvas()
        port.add_to_canvas()
        group.check_for_portgroup_on_last_port()
        group.check_for_display_name_on_last_port()
        
        return group.group_id

    def remove_port(self, name: str) -> int:
        port = self.get_port_from_name(name)
        if port is None:
            return None

        for connection in self.connections:
            if connection.port_out is port or connection.port_in is port:
                connection.remove_from_canvas()
                self.connections.remove(connection)
                break

        for group in self.groups:
            if group.group_id == port.group_id:
                # remove portgroup first if port is in a portgroup
                if port.portgroup_id:
                    for portgroup in group.portgroups:
                        if portgroup.portgroup_id == port.portgroup_id:
                            group.portgroups.remove(portgroup)
                            portgroup.remove_from_canvas()
                            break

                port.remove_from_canvas()
                group.remove_port(port)

                if not group.ports:
                    group.remove_from_canvas()
                    self.groups.remove(group)
                    return None
                
                return group.group_id

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
        if group_name != new_group_name:
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
                gpos = ray.GroupPosition.new_from(*orig_gpos.spread())
                gpos.group_name = new_group_name

                group = Group(self._next_group_id, new_group_name, gpos)
                self._next_group_id += 1
                group.add_port(port)
                group.add_to_canvas()

            port.add_to_canvas()
            return group.group_id

        for group in self.groups:
            if group.group_id == port.group_id:
                # because many ports may be renamed quicky
                # It is prefferable to rename all theses ports together.
                # It prevents too much widget update in canvas,
                # renames now could also prevent to find stereo detected portgroups
                # if one of the two ports has been renamed and not the other one.
                port.full_name = new_name
                group.graceful_port(port)
                port.rename_in_canvas()

                return group.group_id

    def optional_gui_state_changed(self, client_id: str, visible: bool):
        for client in self.session.client_list:
            if client.client_id == client_id:
                for group in self.groups:
                    if client.can_be_own_jack_client(group.name):
                        group.set_optional_gui_state(visible)
                break

    def metadata_update(self, uuid: int, key: str, value: str):
        if key == JACK_METADATA_ORDER:
            port = self.get_port_from_uuid(uuid)
            if port is None:
                return

            try:
                port_order = int(value)
            except:
                sys.stderr.write(
                    "RaySession:PatchbayManager::JACK_METADATA_ORDER "
                    + "value is not an int (%i,%s)\n" % (uuid, value))
                return

            port.order = port_order
            return port.group_id

        elif key == JACK_METADATA_PRETTY_NAME:
            port = self.get_port_from_uuid(uuid)
            if port is None:
                return

            port.pretty_name = value
            port.rename_in_canvas()
            return port.group_id

        elif key == JACK_METADATA_PORT_GROUP:
            port = self.get_port_from_uuid(uuid)
            if port is None:
                return

            port.mdata_portgroup = value
            return port.group_id

        elif key == JACK_METADATA_ICON_NAME:
            for group in self.groups:
                if group.uuid == uuid:
                    group.set_client_icon(value, from_metadata=True)
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
        gpos = ray.GroupPosition.new_from(*args)

        for group_position in self.group_positions:
            if (group_position.group_name == gpos.group_name
                    and group_position.port_types_view == gpos.port_types_view):
                group_position.update(*args)
        else:
            self.group_positions.append(gpos)

        if gpos.port_types_view == PatchbayManager.port_types_view:
            for group in self.groups:
                if group.name == gpos.group_name:
                    group.set_group_position(gpos)
                    break

    def update_portgroup(self, *args):
        portgroup_mem = ray.PortGroupMemory.new_from(*args)
        self.add_portgroup_memory(portgroup_mem)

        for group in self.groups:
            if group.name == portgroup_mem.group_name:
                group.portgroup_memory_added(portgroup_mem)
                break

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
            self.session.main_win,
            _translate('patchbay', "JACK server lose"),
            _translate('patchbay', "JACK server seems to be totally busy... ;("))

    def set_dsp_load(self, dsp_load: int):
        self.tools_widget.set_dsp_load(dsp_load)

    def add_xrun(self):
        self.tools_widget.add_xrun()

    def change_buffersize(self, buffer_size):
        self.send_to_patchbay_daemon('/ray/patchbay/set_buffer_size',
                                     buffer_size)

    def filter_groups(self, text: str, n_select=0)->int:
        ''' semi hides groups not matching with text
            and returns number of matching boxes '''
        opac_grp_ids = set()
        opac_conn_ids = set()
        
        if text.startswith(('cl:', 'client:')):
            client_ids = text.rpartition(':')[2].split(' ')
            jack_client_names = []
            
            for client in self.session.client_list:
                if (client.status != ray.ClientStatus.STOPPED
                        and client.client_id in client_ids):
                    jack_client_names.append(client.jack_client_name)
                    if not client.jack_client_name.endswith('.' + client.client_id):
                        jack_client_names.append(client.jack_client_name + '.0')
            
            for group in self.groups:
                opac = False
                for jack_client_name in jack_client_names:
                    if (group.name == jack_client_name
                            or group.name.startswith(jack_client_name + '/')
                            or (group.name.startswith(jack_client_name + ' (')
                                    and ')' in group.name)):
                        break
                else:
                    opac = True
                    opac_grp_ids.add(group.group_id)
                
                group.semi_hide(opac)

        else:
            for group in self.groups:
                opac = bool(text.lower() not in group.name.lower()
                            and text.lower() not in group.display_name.lower())
                if opac:
                    opac_grp_ids.add(group.group_id)

                group.semi_hide(opac)
        
        for conn in self.connections:
            opac_conn = bool(
                conn.port_out.group_id in opac_grp_ids
                and conn.port_in.group_id in opac_grp_ids)
            
            conn.semi_hide(opac_conn)
            if opac_conn:
                opac_conn_ids.add(conn.connection_id)
            
        for group in self.groups:
            if group.group_id in opac_grp_ids:
                group.set_in_front()
        
        for conn in self.connections:
            if conn.connection_id in opac_conn_ids:
                conn.set_in_front()
        
        for conn in self.connections:
            if conn.connection_id not in opac_conn_ids:
                conn.set_in_front()
        
        n_boxes = 0
        
        for group in self.groups:
            if group.group_id not in opac_grp_ids:
                group.set_in_front()
                n_grp_boxes = group.get_number_of_boxes()

                if n_select > n_boxes and n_select <= n_boxes + n_grp_boxes:
                    group.select_filtered_box(n_select - n_boxes)
                n_boxes += n_grp_boxes

        return n_boxes

    def set_semi_hide_opacity(self, opacity: float):
        patchcanvas.set_semi_hide_opacity(opacity)

    def buffer_size_changed(self, buffer_size):
        self.tools_widget.set_buffer_size(buffer_size)

    def sample_rate_changed(self, samplerate):
        self.tools_widget.set_samplerate(samplerate)

    def add_order_to_queue(self, order: str, *args):
        self.orders_queue.append({'order': order, 'args': args})
        self._orders_queue_timer.start()

    def _order_queue_timeout(self):
        self.optimize_operation(True)
        #self.very_fast_operation = True
        
        group_ids_to_update = set()
        group_ids_to_sort = set()
        some_groups_removed = False
        some_ports_removed = False
        
        for order_dict in self.orders_queue:
            order = order_dict['order']
            args = order_dict['args']
            
            if order == 'add_port':
                group_id = self.add_port(*args)
                group_ids_to_update.add(group_id)
                
            elif order == 'remove_port':
                group_id = self.remove_port(*args)
                if group_id is None:
                    some_groups_removed = True
                else:
                    group_ids_to_update.add(group_id)
                    
            elif order == 'rename_port':
                group_id = self.rename_port(*args)
                group_ids_to_update.add(group_id)
                
            elif order == 'add_connection':
                self.add_connection(*args)
                
            elif order == 'remove_connection':
                self.remove_connection(*args)
                
            elif order == 'update_metadata':
                group_id = self.metadata_update(*args)
                if group_id is not None:
                    group_ids_to_update.add(group_id)
                    group_ids_to_sort.add(group_id)
            else:
                sys.stderr.write(
                    '_order_queue_timeout wrong order: %s\n' % order)
        
        for group in self.groups:
            if group.group_id in group_ids_to_sort:
                group.sort_ports_in_canvas()

        self.optimize_operation(False)
        self.orders_queue.clear()
        
        for group in self.groups:
            if group.group_id in group_ids_to_update:
                group.redraw_in_canvas()

        if some_groups_removed:
            patchcanvas.canvas.scene.resize_the_scene()

    def receive_big_packets(self, state: int):
        self.optimize_operation(not bool(state))
        if state:
            patchcanvas.redraw_all_groups()

    def fast_temp_file_memory(self, temp_path):
        ''' receives a .json file path from daemon with groups positions
            and portgroups remembered from user. '''
        canvas_data = self.get_json_contents_from_path(temp_path)
        if not canvas_data:
            sys.stderr.write(
                "RaySession::Failed to load tmp file %s to get canvas positions\n"
                % temp_path)
            return

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
        ''' receives a .json file path from patchbay daemon with all ports, connections
            and jack metadatas'''
        patchbay_data = self.get_json_contents_from_path(temp_path)
        if not patchbay_data:
            sys.stderr.write(
                "RaySession::Failed to load tmp file %s to get JACK ports\n"
                % temp_path)
            return

        # optimize_operation allow to not redraw group at each port added.
        # however, if there is no group position
        # (i.e. if there is no config at all), it is prefferable to
        # know where finish the group boxes before to add another one.
        
        # very fast operation means that nothing is done in the patchcanvas
        # everything stays here in this file.
        
        if self.group_positions:
            self.optimize_operation(True)
            self.set_very_fast_operation(True)

        for key in patchbay_data.keys():
            if key == 'ports':
                for p in patchbay_data[key]:
                    self.add_port(p.get('name'), p.get('type'),
                                  p.get('flags'), p.get('uuid'))
        
            elif key == 'connections':
                for c in patchbay_data[key]:
                    self.add_connection(c.get('port_out_name'),
                                        c.get('port_in_name'))
        
        for key in patchbay_data.keys():
            if key == 'clients':
                for cnu in patchbay_data[key]:
                    self.client_name_and_uuid(cnu.get('name'), cnu.get('uuid'))
                break

        for key in patchbay_data.keys():
            if key == 'metadatas':
                for m in patchbay_data[key]:
                    self.metadata_update(
                        m.get('uuid'), m.get('key'), m.get('value'))

        for group in self.groups:
            group.sort_ports_in_canvas()

        self.set_very_fast_operation(False)
        
        for group in self.groups:
            group.add_all_ports_to_canvas()
        
        for conn in self.connections:
            conn.add_to_canvas()

        self.optimize_operation(False)
        patchcanvas.redraw_all_groups()

        try:
            os.remove(temp_path)
        except:
            # if this tmp file can not be removed
            # this is really not strong.
            pass

    def patchbay_announce(self, jack_running: int, samplerate: int,
                          buffer_size: int):
        self.tools_widget.set_samplerate(samplerate)
        self.tools_widget.set_buffer_size(buffer_size)
        self.tools_widget.set_jack_running(jack_running)
        self.session.main_win.add_patchbay_tools(
            self.tools_widget, self.canvas_menu)
