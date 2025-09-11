'''When this module is used, ray-alsapatch is internal and is a 
remote for the patchbay daemon. It allows to not create another ALSA
client.
'''

# Imports from standard library
from enum import IntFlag
import logging
import time
from typing import TYPE_CHECKING

from patshared import PortMode, PortType

# imports from shared
from patcher.bases import (
    EventHandler, Event, PortData,
    ProtoEngine, FullPortName)
from osclib import BunServerThread, OscPack, bun_manage
import osc_paths.ray as r
import osc_paths.ray.patchbay.monitor as rpm

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
        self.ports = dict[FullPortName, PortData]()
        self.connections = list[tuple[FullPortName, FullPortName]]()
        self.startup_received = False

    def send_patchbay(self, *args):
        self.send(self._patchbay_port, *args)

    @bun_manage(rpm.ANNOUNCE, 'iiiis')
    def _patchbay_announce(self, osp: OscPack):
        alsa_lib_ok = osp.args[1]
        if not alsa_lib_ok:
            _logger.critical(
                'python ALSA lib is not installed or too old, will quit.')
            self.ev.add_event(Event.JACK_STOPPED)

    @bun_manage(rpm.CONNECTION_ADDED, 'ss')
    def _connection_added(self, osp: OscPack):
        osp_args: tuple[str, str] = osp.args # type:ignore
        port_out, port_in = osp_args
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
    
    @bun_manage(rpm.CONNECTION_REMOVED, 'ss')
    def _connection_removed(self, osp: OscPack):
        osp_args: tuple[str, str] = osp.args # type:ignore
        port_out, port_in = osp_args
        jport_out = self.ports.get(port_out)
        jport_in = self.ports.get(port_in)
        if jport_out is None or jport_in is None:
            return
        
        conn = (jport_out.name, jport_in.name)
        if conn not in self.connections:
            return

        self.connections.remove(conn)
        self.ev.add_event(Event.CONNECTION_REMOVED, *conn)

    @bun_manage(rpm.PORT_ADDED, 'siih')
    def _port_added(self, osp: OscPack):
        osp_args: tuple[str, int, int, int] = osp.args # type:ignore
        name, type_, flags, uuid = osp_args
        if type_ != 4:
            return

        if (name.count(':') < 5
                and not (name.startswith(':ALSA_IN:')
                         or name.startswith(':ALSA_OUT:'))):
            return
        
        if flags & JackPortFlag.IS_OUTPUT:
            mode = PortMode.OUTPUT
        else:
            mode = PortMode.INPUT

        port_data = PortData()
        port_data.name = ':'.join(name.split(':')[4:])
        port_data.type = PortType.MIDI_ALSA
        port_data.mode = mode
        port_data.id = uuid

        self.ports[name] = port_data

        if self.startup_received:
            self.ev.add_event(
                Event.PORT_ADDED, port_data.name, mode, port_data.type)
        
    @bun_manage(rpm.PORT_REMOVED, 's')
    def _port_removed(self, osp: OscPack):
        name: str = osp.args[0] # type:ignore
        jack_port = self.ports.get(name)
        if jack_port is None:
            return
        
        self.ports.pop(name)
        
        self.ev.add_event(Event.PORT_REMOVED, jack_port.name,
                          jack_port.mode, jack_port.type)
    
        
    @bun_manage(rpm.CLIENT_ADDED, 's')
    def _client_added(self, osp: OscPack):
        self.ev.add_event(Event.CLIENT_ADDED, osp.args[0])
    
    @bun_manage(rpm.CLIENT_REMOVED, 's')
    def _client_removed(self, osp: OscPack):
        self.ev.add_event(Event.CLIENT_REMOVED, osp.args[0])
    
    @bun_manage(rpm.BIG_PACKETS, 'i')
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
            self, all_ports: dict[PortMode, list[PortData]],
            connections: set[tuple[str, str]]):
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
            connections.add(conn)                

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
