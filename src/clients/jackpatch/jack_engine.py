
# Imports from standard library
import logging
from typing import Optional

# Third party
import jack

# imports from shared
from patcher.bases import (
    EventHandler, Event, JackPort,
    PortMode, PortType, ProtoEngine)


_logger = logging.getLogger(__name__)


def mode_type(port: jack.Port) -> tuple[PortMode, PortType]:
    port_mode = PortMode.NULL    
    if port.is_input:
        port_mode = PortMode.INPUT
    elif port.is_output:
        port_mode = PortMode.OUTPUT
    
    port_type = PortType.NULL
    if port.is_audio:
        port_type = PortType.AUDIO
    elif port.is_midi:
        port_type = PortType.MIDI

    return port_mode, port_type


class JackEngine(ProtoEngine):
    def __init__(self, event_handler: EventHandler):
        super().__init__(event_handler)
        self._client: Optional[jack.Client] = None

    def init(self) -> bool:
        try:
            self._client = jack.Client('ray-jackpatch', no_start_server=True)
        except jack.JackOpenError:
            _logger.error('Unable to make a jack client !')
            return False
        
        if self._client is None:
            return False
        
        @self._client.set_port_registration_callback
        def port_registration(port: jack.Port, register: bool):
            self.ev_handler.add_event(
                Event.PORT_ADDED if register else Event.PORT_REMOVED,
                port.name, *mode_type(port))
        
        @self._client.set_port_rename_callback
        def port_rename(port: jack.Port, old: str, new: str):
            self.ev_handler.add_event(
                Event.PORT_RENAMED(old, new, *mode_type(port)))
            
        @self._client.set_port_connect_callback
        def port_connect(port_a: jack.Port, port_b: jack.Port, connect: bool):
            self.ev_handler.add_event(
                Event.CONNECTION_ADDED if connect
                else Event.CONNECTION_REMOVED,
                port_a.name, port_b.name)
            
        @self._client.set_shutdown_callback
        def on_shutdown(status: jack.Status, reason: str):
            self.ev_handler.add_event(Event.JACK_STOPPED)
            
        self._client.activate()
        return True

    def fill_ports_and_connections(
            self, all_ports: dict[PortMode, list[JackPort]],
            connection_list: list[tuple[str, str]]):
        '''get all current JACK ports and connections at startup'''
        for port in self._client.get_ports():
            jack_port = JackPort()
            jack_port.name = port.name
            port_mode, port_type = mode_type(port)
            jack_port.mode = port_mode
            jack_port.type = port_type
            jack_port.is_new = True
            all_ports[jack_port.mode].append(jack_port)
            
            if jack_port.mode is PortMode.OUTPUT:
                for oth_port in self._client.get_all_connections(port):
                    connection_list.append((jack_port.name, oth_port.name))

    def connect_ports(self, port_out: str, port_in: str):
        self._client.connect(port_out, port_in)

    def disconnect_ports(self, port_out: str, port_in: str):
        self._client.disconnect(port_out, port_in)

    def quit(self):
        self._client.deactivate()
        self._client.close()
    