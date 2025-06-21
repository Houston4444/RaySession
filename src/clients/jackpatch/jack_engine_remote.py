'''When this module is used, ray-jackpatch is internal and is a 
remote for the patchbay daemon. This way, the client is not directly
related to JACK, so it never fails to stop.
'''

# Imports from standard library
from enum import IntFlag
import logging
import time
from typing import TYPE_CHECKING, Callable


# imports from shared
from patcher.bases import (
    EventHandler, Event, JackPort,
    PortMode, PortType, ProtoEngine, FullPortName)
from osclib import BunServerThread, OscMulTypes, OscPack
import osc_paths.ray as r
import osc_paths.ray.gui as rg

if TYPE_CHECKING:
    from daemon import patchbay_dmn_mng
else:
    import patchbay_dmn_mng


_logger = logging.getLogger(__name__)

_manage_wrappers = dict[str, Callable[[OscPack], bool]]()
_manage_types = dict[str, str]()


class JackPortFlag(IntFlag):
    'Port Flags as defined by JACK'
    IS_INPUT = 0x01
    IS_OUTPUT = 0x02
    IS_PHYSICAL = 0x04
    CAN_MONITOR = 0x08
    IS_TERMINAL = 0x10
    IS_CONTROL_VOLTAGE = 0x100


def manage(path: str, multypes: OscMulTypes):
    '''Decorator working like the @make_method decorator,
    but send methods with OscPack as argument.
    
    `path`: OSC str path

    `multypes`: str containing all accepted arg types
    '''
    def decorated(func: Callable):
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
    
        _manage_wrappers[path] = wrapper
        _manage_types[path] = multypes

        return wrapper
    return decorated


class PatchRemote(BunServerThread):
    def __init__(self, ev_handler: EventHandler):
        super().__init__(total_fake=True)
        self.ev = ev_handler
        self._patchbay_port = patchbay_dmn_mng.get_port()
        self.ports = dict[FullPortName, JackPort]()
        self.connections = list[tuple[FullPortName, FullPortName]]()
        self.startup_received = False
        self.add_nice_methods(_manage_types, self._generic_method)
    
    def _generic_method(self, osp: OscPack):
        '''Except the unknown messages, all messages received
        go through here.'''
        # run the method decorated with @manage
        if osp.path in _manage_wrappers:
            _manage_wrappers[osp.path](self, osp)

    def start(self):
        super().start()
        self.send(self._patchbay_port, r.patchbay.ADD_GUI, self.url)

    def send_patchbay(self, *args):
        self.send(self._patchbay_port, *args)

    @manage(rg.patchbay.ANNOUNCE, 'iiis')
    def _patchbay_announce(self, osp: OscPack):
        jack_running = osp.args[0]
        if not jack_running:
            self.ev.add_event(Event.JACK_STOPPED)
        
    @manage(rg.patchbay.CONNECTION_ADDED, 'ss')
    def _connection_added(self, osp: OscPack):
        port_out, port_in = osp.args
        if port_out not in self.ports:
            return

        self.connections.append((port_out, port_in))
        if self.startup_received:
            self.ev.add_event(Event.CONNECTION_ADDED, port_out, port_in)
    
    @manage(rg.patchbay.CONNECTION_REMOVED, 'ss')
    def _connection_removed(self, osp: OscPack):
        conn = (*osp.args,)
        if conn not in self.connections:
            return

        self.connections.remove(conn)
        self.ev.add_event(Event.CONNECTION_REMOVED, *conn)

    @manage(rg.patchbay.PORT_ADDED, 'siih')
    def _port_added(self, osp: OscPack):
        name, type_, flags, uuid = osp.args
        if flags & JackPortFlag.IS_OUTPUT:
            mode = PortMode.OUTPUT
        else:
            mode = PortMode.INPUT

        try:
            port_type = PortType(type_)
        except:
            return

        jack_port = JackPort()
        jack_port.name = name
        jack_port.type = port_type
        jack_port.mode = mode
        jack_port.id = uuid

        self.ports[name] = jack_port

        if self.startup_received:
            self.ev.add_event(Event.PORT_ADDED, name, mode, port_type)
        
    @manage(rg.patchbay.PORT_REMOVED, 's')
    def _port_removed(self, osp: OscPack):
        name = osp.args[0]
        jack_port = self.ports.get(name)
        if jack_port is None:
            return
        
        self.ports.pop(name)
        
        self.ev.add_event(Event.PORT_REMOVED, name,
                          jack_port.mode, jack_port.type)
    
    @manage(rg.patchbay.PORT_RENAMED, 'ss|ssi')
    def _port_renamed(self, osp: OscPack):
        old = osp.args[0]
        new = osp.args[1]
        
        jack_port = self.ports.get(old)
        if jack_port is None:
            return
        
        jack_port.name = new
        self.ports[new] = self.ports.pop(old)

        self.ev.add_event(Event.PORT_RENAMED, old, new,
                          jack_port.mode, jack_port.type)
    
    @manage(rg.patchbay.BIG_PACKETS, 'i')
    def _big_packets(self, osp: OscPack):
        if osp.args[0]:
            self.startup_received = True
    
    @manage(rg.patchbay.SERVER_STOPPED, '')
    def _server_stopped(self, osp: OscPack):
        self.ev.add_event(Event.JACK_STOPPED)


class JackEngine(ProtoEngine):
    def __init__(self, event_handler: EventHandler):
        super().__init__(event_handler)
        self.remote = PatchRemote(event_handler)

    def init(self) -> bool:
        self.remote.start()
        return True

    def fill_ports_and_connections(
            self, all_ports: dict[PortMode, list[JackPort]],
            connection_list: list[tuple[str, str]]):
        '''get all current JACK ports and connections at startup'''

        while not self.remote.startup_received:
            time.sleep(0.001)

        for jack_port in self.remote.ports.values():
            all_ports[jack_port.mode].append(jack_port)
                
        for conn in self.remote.connections:
            connection_list.append(conn)                

    def connect_ports(self, port_out: str, port_in: str):
        self.remote.send_patchbay(r.patchbay.CONNECT, port_out, port_in)

    def disconnect_ports(self, port_out: str, port_in: str):
        self.remote.send_patchbay(r.patchbay.DISCONNECT, port_out, port_in)

    def quit(self):
        self.remote.stop()
