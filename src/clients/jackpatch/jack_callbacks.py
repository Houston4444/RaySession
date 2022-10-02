from ctypes import c_char_p, pointer

import jacklib
from bases import EventHandler, Event, PortMode, PortType, b2str

_jack_client: 'pointer[jacklib.jack_port_t]'

# ---- JACK callbacks executed in JACK thread -----

def _shutdown(arg=None) -> int:
    EventHandler.add_event(Event.JACK_STOPPED)
    
    return 0

def _port_registration(port_id, register: bool, arg=None) -> int:
    port_ptr = jacklib.port_by_id(_jack_client, port_id)
    port_flags = jacklib.port_flags(port_ptr)
    port_name = jacklib.port_name(port_ptr)

    if port_flags & jacklib.JackPortIsInput:
        port_mode = PortMode.INPUT
    elif port_flags & jacklib.JackPortIsOutput:
        port_mode = PortMode.OUTPUT
    else:
        port_mode = PortMode.NULL

    port_type_str = jacklib.port_type(port_ptr)
    if port_type_str == jacklib.JACK_DEFAULT_AUDIO_TYPE:
        port_type = PortType.AUDIO
    elif port_type_str == jacklib.JACK_DEFAULT_MIDI_TYPE:
        port_type = PortType.MIDI
    else:
        port_type = PortType.NULL

    EventHandler.add_event(
        Event.PORT_ADDED if register else Event.PORT_REMOVED,
        port_name, port_mode, port_type)

    return 0

def _port_rename(
        port_id, old_name: c_char_p, new_name: c_char_p, arg=None) -> int:
    port_ptr = jacklib.port_by_id(_jack_client, port_id)
    port_flags = jacklib.port_flags(port_ptr)

    if port_flags & jacklib.JackPortIsInput:
        port_mode = PortMode.INPUT
    elif port_flags & jacklib.JackPortIsOutput:
        port_mode = PortMode.OUTPUT
    else:
        port_mode = PortMode.NULL

    port_type_str = jacklib.port_type(port_ptr)
    if port_type_str == jacklib.JACK_DEFAULT_AUDIO_TYPE:
        port_type = PortType.AUDIO
    elif port_type_str == jacklib.JACK_DEFAULT_MIDI_TYPE:
        port_type = PortType.MIDI
    else:
        port_type = PortType.NULL

    EventHandler.add_event(
        Event.PORT_RENAMED,
        (b2str(old_name), b2str(new_name), port_mode, port_type))

    return 0

def _port_connect(port_id_a, port_id_b, connect: bool, arg=None) -> int:
    port_ptr_a = jacklib.port_by_id(_jack_client, port_id_a)
    port_ptr_b = jacklib.port_by_id(_jack_client, port_id_b)

    port_str_a = jacklib.port_name(port_ptr_a)
    port_str_b = jacklib.port_name(port_ptr_b)

    EventHandler.add_event(
        Event.CONNECTION_ADDED if connect else Event.CONNECTION_REMOVED,
        port_str_a, port_str_b)

    return 0

# --- end of JACK callbacks ----

def set_callbacks(jclient):
    global _jack_client
    _jack_client = jclient

    jacklib.set_port_registration_callback(
        _jack_client, _port_registration, None)
    jacklib.set_port_connect_callback(
        _jack_client, _port_connect, None)
    jacklib.set_port_rename_callback(
        _jack_client, _port_rename, None)
    jacklib.on_shutdown(_jack_client, _shutdown, None)