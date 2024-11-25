
import logging

import jacklib
from jacklib.helpers import c_char_p_p_to_list
from jacklib.api import JackPortFlags, JackOptions, pointer, jack_client_t

import jack_callbacks
from bases import JackPort, PortMode, ProtoEngine, PortType


_logger = logging.getLogger(__name__)


class JackEngine(ProtoEngine):
    def __init__(self):
        super().__init__()
        self._jack_client: 'pointer[jack_client_t]' = None

    def init(self) -> bool:
        self._jack_client = jacklib.client_open(
            'ray-jackpatch',
            JackOptions.NO_START_SERVER,
            None)

        if not self._jack_client:
            _logger.error('Unable to make a jack client !')
            return False
        
        jack_callbacks.set_callbacks(self._jack_client)
        jacklib.activate(self._jack_client)
        return True

    def fill_ports_and_connections(
            self, all_ports: dict[PortMode, list[JackPort]],
            connection_list: list[tuple[str, str]]):
        '''get all current JACK ports and connections at startup'''
        port_name_list = c_char_p_p_to_list(
            jacklib.get_ports(self._jack_client, "", "", 0))

        for port_name in port_name_list:
            jack_port = JackPort()
            jack_port.name = port_name

            port_ptr = jacklib.port_by_name(self._jack_client, port_name)
            port_flags = jacklib.port_flags(port_ptr)

            if port_flags & JackPortFlags.IS_INPUT:
                jack_port.mode = PortMode.INPUT
            elif port_flags & JackPortFlags.IS_OUTPUT:
                jack_port.mode = PortMode.OUTPUT
            else:
                jack_port.mode = PortMode.NULL

            port_type_str = jacklib.port_type(port_ptr)
            if port_type_str == jacklib.JACK_DEFAULT_AUDIO_TYPE:
                jack_port.type = PortType.AUDIO
            elif port_type_str == jacklib.JACK_DEFAULT_MIDI_TYPE:
                jack_port.type = PortType.MIDI
            else:
                jack_port.type = PortType.NULL

            jack_port.is_new = True

            all_ports[jack_port.mode].append(jack_port)

            if jack_port.mode is PortMode.OUTPUT:
                for port_con_name in jacklib.port_get_all_connections(
                        self._jack_client, port_ptr):
                    connection_list.append((port_name, port_con_name))

    def connect_ports(self, port_out: str, port_in: str):
        jacklib.connect(self._jack_client, port_out, port_in)

    def disconnect_ports(self, port_out: str, port_in: str):
        jacklib.disconnect(self._jack_client, port_out, port_in)

    def quit(self):
        jacklib.deactivate(self._jack_client)
        jacklib.client_close(self._jack_client)
    