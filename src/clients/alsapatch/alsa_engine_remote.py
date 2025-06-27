'''When this module is used, ray-alsapatch is internal and is a 
remote for the patchbay daemon. It allows to not create another ALSA
client.
'''

# Imports from standard library
from enum import IntFlag
import logging
import time
from typing import TYPE_CHECKING


# imports from shared
from patcher.bases import (
    EventHandler, Event, JackPort,
    PortMode, PortType, ProtoEngine, FullPortName)
from osclib import BunServerThread, OscPack, bun_manage
import osc_paths.ray as r
import osc_paths.ray.gui as rg

from .check_internal import IS_PATCHBAY_INTERNAL

if TYPE_CHECKING:
    from daemon import patchbay_dmn_mng
else:
    import patchbay_dmn_mng


_logger = logging.getLogger(__name__)


class JackPortFlag(IntFlag):
    'Port Flags as defined by JACK'
    IS_INPUT = 0x01
    IS_OUTPUT = 0x02
    IS_PHYSICAL = 0x04
    CAN_MONITOR = 0x08
    IS_TERMINAL = 0x10
    IS_CONTROL_VOLTAGE = 0x100


class PatchRemote(BunServerThread):
    def __init__(self, ev_handler: EventHandler):
        super().__init__(total_fake=IS_PATCHBAY_INTERNAL)
        self.add_managed_methods()
        self.ev = ev_handler
        patchbay_dmn_mng.start(self.url)
        self._patchbay_port = patchbay_dmn_mng.get_port()
        self.ports = dict[FullPortName, JackPort]()
        self.connections = list[tuple[FullPortName, FullPortName]]()
        self.startup_received = False

    def send_patchbay(self, *args):
        self.send(self._patchbay_port, *args)

    # @bun_manage(rg.patchbay.ANNOUNCE, 'iiis')
    # def _patchbay_announce(self, osp: OscPack):
    #     ...
        
    @bun_manage(rg.patchbay.CONNECTION_ADDED, 'ss')
    def _connection_added(self, osp: OscPack):
        port_out, port_in = osp.args
        if port_out not in self.ports:
            return

        jport_out = self.ports.get(port_out)
        jport_in = self.ports.get(port_in)
        if jport_out is None or jport_in is None:
            return

        self.connections.append((jport_out.name, jport_in.name))
        if self.startup_received:
            self.ev.add_event(
                Event.CONNECTION_ADDED, jport_out.name, jport_in.name)
    
    @bun_manage(rg.patchbay.CONNECTION_REMOVED, 'ss')
    def _connection_removed(self, osp: OscPack):
        port_out, port_in = osp.args
        jport_out = self.ports.get(port_out)
        jport_in = self.ports.get(port_in)
        if jport_out is None or jport_in is None:
            return
        
        conn = (jport_out.name, jport_in.name)
        if conn not in self.connections:
            return

        self.connections.remove(conn)
        self.ev.add_event(Event.CONNECTION_REMOVED, *conn)

    @bun_manage(rg.patchbay.PORT_ADDED, 'siih')
    def _port_added(self, osp: OscPack):
        name, type_, flags, uuid = osp.args
        
        if (name.count(':') < 5
                and not (name.startswith(':ALSA_IN:')
                         or name.startswith(':ALSA_OUT:'))):
            return
        
        if flags & JackPortFlag.IS_OUTPUT:
            mode = PortMode.OUTPUT
        else:
            mode = PortMode.INPUT

        if type_ != 4:
            return

        jack_port = JackPort()
        jack_port.name = ':'.join(name.split(':')[4:])
        jack_port.type = PortType.MIDI
        jack_port.mode = mode
        jack_port.id = uuid

        self.ports[name] = jack_port

        if self.startup_received:
            self.ev.add_event(
                Event.PORT_ADDED, jack_port.name, mode, jack_port.type)
        
    @bun_manage(rg.patchbay.PORT_REMOVED, 's')
    def _port_removed(self, osp: OscPack):
        name = osp.args[0]
        jack_port = self.ports.get(name)
        if jack_port is None:
            return
        
        self.ports.pop(name)
        
        self.ev.add_event(Event.PORT_REMOVED, jack_port.name,
                          jack_port.mode, jack_port.type)
    
    # @bun_manage(rg.patchbay.PORT_RENAMED, 'ss|ssi')
    # def _port_renamed(self, osp: OscPack):
    #     ...
    
    @bun_manage(rg.patchbay.BIG_PACKETS, 'i')
    def _big_packets(self, osp: OscPack):
        if osp.args[0]:
            self.startup_received = True

    def stop(self):
        self.send_patchbay(r.patchbay.GUI_DISANNOUNCE, self.url)
        super().stop()


class AlsaEngine(ProtoEngine):
    def __init__(self, event_handler: EventHandler):
        super().__init__(event_handler)
        self.remote = PatchRemote(event_handler)

    def init(self) -> bool:
        self.remote.start()
        return True

    def fill_ports_and_connections(
            self, all_ports: dict[PortMode, list[JackPort]],
            connection_list: list[tuple[str, str]]):
        '''get all current ALSA ports and connections at startup'''

        for i in range(100):
            if self.remote.startup_received:
                break
            time.sleep(0.010)
        else:
            _logger.error(
                'Failed to get ports and connections from patchbay_daemon, '
                'will quit.')
            return

        for jack_port in self.remote.ports.values():
            all_ports[jack_port.mode].append(jack_port)
                
        for conn in self.remote.connections:
            connection_list.append(conn)                

    def connect_ports(self, port_out: str, port_in: str):
        for jport_out_name, jport_out in self.remote.ports.items():
            if jport_out.name != port_out:
                continue
            
            for jport_in_name, jport_in in self.remote.ports.items():
                if jport_in.name != port_in:
                    continue
                
                self.remote.send_patchbay(
                    r.patchbay.CONNECT, jport_out_name, jport_in_name)

    def disconnect_ports(self, port_out: str, port_in: str):
        for jport_out_name, jport_out in self.remote.ports.items():
            if jport_out.name != port_out:
                continue
            
            for jport_in_name, jport_in in self.remote.ports.items():
                if jport_in.name != port_in:
                    continue
                
                self.remote.send_patchbay(
                    r.patchbay.DISCONNECT, jport_out_name, jport_in_name)

    def quit(self):
        self.remote.stop()
