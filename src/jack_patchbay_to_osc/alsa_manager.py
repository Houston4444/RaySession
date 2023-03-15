
from dataclasses import dataclass
import time
from typing import TYPE_CHECKING, Iterator, Optional
from threading import Thread
    
from pyalsa import alsaseq
from pyalsa.alsaseq import (
    SEQ_USER_CLIENT,
    SEQ_PORT_CAP_NO_EXPORT,
    SEQ_PORT_CAP_READ,
    SEQ_PORT_CAP_SUBS_READ,
    SEQ_PORT_CAP_WRITE,
    SEQ_PORT_CAP_SUBS_WRITE,
    SEQ_PORT_TYPE_APPLICATION,
    SEQ_CLIENT_SYSTEM,
    SEQ_PORT_SYSTEM_ANNOUNCE,
    SEQ_EVENT_CLIENT_START,
    SEQ_EVENT_CLIENT_EXIT,
    SEQ_EVENT_PORT_START,
    SEQ_EVENT_PORT_EXIT,
    SEQ_EVENT_PORT_SUBSCRIBED,
    SEQ_EVENT_PORT_UNSUBSCRIBED,
    SequencerError
)
from port_data import PortData

if TYPE_CHECKING:
    from ray_jackpatch_to_osc import MainObject
    from osc_server import OscJackPatch

PORT_IS_INPUT = 0x1
PORT_IS_OUTPUT = 0x2
PORT_IS_PHYSICAL = 0x4

PORT_TYPE_MIDI_ALSA = 0x04

_PORT_READS = SEQ_PORT_CAP_READ | SEQ_PORT_CAP_SUBS_READ
_PORT_WRITES = SEQ_PORT_CAP_WRITE | SEQ_PORT_CAP_SUBS_WRITE


@dataclass
class AlsaPort:
    name: str
    id: int
    caps: int
    physical: bool


@dataclass
class AlsaConn:
    source_client_id: int
    source_port_id: int
    dest_client_id: int
    dest_port_id: int
    
    def as_port_names(self, clients: dict[int, 'AlsaClient']) -> Optional[tuple[str, str]]:
        src_client = clients.get(self.source_client_id)
        dest_client = clients.get(self.dest_client_id)
        
        if src_client is None or dest_client is None:
            return None
        
        src_port = src_client.ports.get(self.source_port_id)
        dest_port = dest_client.ports.get(self.dest_client_id)
        
        if src_port is None or dest_port is None:
            return None
        
        return (f":ALSA_OUT:{src_client.name}:{src_port.name}",
                f":ALSA_IN:{dest_client.name}:{dest_port.name}")


class AlsaClient:
    def __init__(self, alsa_mng: 'AlsaManager', name: str, id: int):
        self.alsa_mng = alsa_mng
        self.name = name
        self.id = id
        self.ports = dict[int, AlsaPort]()
            
    def __repr__(self) -> str:
        return f"AlsaClient({self.name}, {self.id})"
    
    def add_port(self, port_id: int):
        try:
            port_info = self.alsa_mng.seq.get_port_info(port_id, self.id)
            caps = port_info['capability']
        except:
            return

        if caps & SEQ_PORT_CAP_NO_EXPORT:
            return
        
        if not(caps & _PORT_READS == _PORT_READS
               or caps & _PORT_WRITES == _PORT_WRITES):
            return

        physical = not bool(port_info['type'] & SEQ_PORT_TYPE_APPLICATION)
        self.ports[port_id] = AlsaPort(port_info['name'], port_id, caps, physical)


class AlsaManager:
    def __init__(self, jack_mng: 'MainObject'):
        self._jack_mng = jack_mng
        self._osc_server = self._jack_mng.osc_server
        self.seq = alsaseq.Sequencer(clientname='raysession')

        self._all_alsa_connections = list[AlsaConn]()
        self._connections = list[AlsaConn]()
        self._clients = dict[int, AlsaClient]()
        self._clients_names = dict[int, str]()

        self._stopping = False
        self._event_thread = Thread(target=self.read_events)

        port_caps = (SEQ_PORT_CAP_WRITE
                     | SEQ_PORT_CAP_SUBS_WRITE
                     | SEQ_PORT_CAP_NO_EXPORT)
        input_id = self.seq.create_simple_port(
            name="raysession_port",
            type=SEQ_PORT_TYPE_APPLICATION,
            caps=port_caps)

        self.seq.connect_ports(
            (SEQ_CLIENT_SYSTEM, SEQ_PORT_SYSTEM_ANNOUNCE),
            (self.seq.client_id, input_id))

    def get_the_graph(self):
        if self.seq is None:
            return
        
        clients = self.seq.connection_list()
        
        self._clients_names.clear()
        self._clients.clear()
        self._all_alsa_connections.clear()

        for client in clients:
            client_name, client_id, port_list = client
            self._clients_names[client_id] = client_name
            self._clients[client_id] = AlsaClient(
                self, client_name, client_id)
            for port_name, port_id, connection_list in port_list:
                self._clients[client_id].add_port(port_id)
      
                connections = connection_list[0]
                for connection in connections:
                    conn_client_id, conn_port_id = connection[:2]                    
                    self._all_alsa_connections.append(
                        AlsaConn(client_id, port_id,
                                 conn_client_id, conn_port_id))

    def add_port_to_patchbay(self, client: AlsaClient, port: AlsaPort):
        port_flags = 0
        if port.physical:
            port_flags = PORT_IS_PHYSICAL
        
        if port.caps & _PORT_READS == _PORT_READS:
            self._osc_server.port_added(
                f':ALSA_OUT:{client.name}:{port.name}',
                PORT_TYPE_MIDI_ALSA,
                port_flags | PORT_IS_OUTPUT,
                client.id * 0x10000 + port.id)

        if port.caps & _PORT_WRITES == _PORT_WRITES:
            self._osc_server.port_added(
                f':ALSA_IN:{client.name}:{port.name}',
                PORT_TYPE_MIDI_ALSA,
                port_flags | PORT_IS_INPUT,
                client.id * 0x10000 + port.id)

    def remove_port_from_patchbay(self, client: AlsaClient, port: AlsaPort):
        if port.caps & _PORT_READS == _PORT_READS:
            self._osc_server.port_removed(
                f":ALSA_OUT:{client.name}:{port.name}")
        if port.caps & _PORT_WRITES == _PORT_WRITES:
            self._osc_server.port_removed(
                f":ALSA_IN:{client.name}:{port.name}")

    def add_all_ports(self):        
        if self._event_thread.is_alive():
            self.stop_events_loop()

        self.get_the_graph()

        for client in self._clients.values():
            if client.name == 'System':
                continue

            for port in client.ports.values():
                self.add_port_to_patchbay(client, port)
                
        for conn in self._all_alsa_connections:
            source_client = self._clients.get(conn.source_client_id)
            dest_client = self._clients.get(conn.dest_client_id)
            if source_client is None or dest_client is None:
                continue
            
            source_port = source_client.ports.get(conn.source_port_id)
            dest_port = dest_client.ports.get(conn.dest_port_id)
            
            if source_port is None or dest_port is None:
                continue
            
            self._connections.append(conn)
            
            self._osc_server.connection_added(
                (f":ALSA_OUT:{source_client.name}:{source_port.name}",
                 f":ALSA_IN:{dest_client.name}:{dest_port.name}")
            )
    
        self._event_thread.start()
    
    def parse_ports_and_flags(self) -> Iterator[PortData]:
        for client_id, client in self._clients.items():
            if client.name == 'System':
                continue
            
            for port_id, port in client.ports.items():
                port_flags = 0
                if port.physical:
                    port_flags = PORT_IS_PHYSICAL

                if port.caps & _PORT_READS == _PORT_READS:
                    yield PortData(
                        f':ALSA_OUT:{client.name}:{port.name}',
                        PORT_TYPE_MIDI_ALSA,
                        port_flags | PORT_IS_OUTPUT,
                        client.id * 0x10000 + port.id)
                
                if port.caps & _PORT_WRITES == _PORT_WRITES:
                    yield PortData(
                        f':ALSA_IN:{client.name}:{port.name}',
                        PORT_TYPE_MIDI_ALSA,
                        port_flags | PORT_IS_INPUT,
                        client.id * 0x10000 + port.id)
    
    def parse_connections(self) -> Iterator[tuple[str, str]]:
        for conn in self._connections:
            src_client = self._clients.get(conn.source_client_id)
            dest_client = self._clients.get(conn.dest_client_id)
            if src_client is None or dest_client is None:
                continue
            
            src_port = src_client.ports.get(conn.source_port_id)
            dest_port = dest_client.ports.get(conn.dest_port_id)
            
            if src_port is None or dest_port is None:
                continue
            
            yield (f':ALSA_OUT:{src_client.name}:{src_port.name}',
                   f':ALSA_IN:{dest_client.name}:{dest_port.name}')
    
    def connect_ports(self, port_out_name: str, port_in_name: str,
                      disconnect=False):
        _, alsa_key, src_client_name, *rest = port_out_name.split(':')
        src_port_name = ':'.join(rest)
        _, alsa_key, dest_client_name, *rest = port_in_name.split(':')
        dest_port_name = ':'.join(rest)
        
        port_out_name = port_out_name.replace(':ALSA_OUT:', '', 1)
        port_in_name = port_in_name.replace(':ALSA_IN:', '', 1)

        for src_client_id, src_client in self._clients.items():
            if src_client.name == src_client_name:
                break
        else:
            return
        
        for src_port_id, src_port in src_client.ports.items():
            if src_port.name == src_port_name:
                break
        else:
            return
        
        for dest_client_id, dest_client in self._clients.items():
            if dest_client.name == dest_client_name:
                break
        else:
            return
        
        for dest_port_id, dest_port in dest_client.ports.items():
            if dest_port.name == dest_port_name:
                break
        else:
            return
        
        try:
            if disconnect:
                self.seq.disconnect_ports(
                    (src_client_id, src_port_id),
                    (dest_client_id, dest_port_id))
            else: 
                self.seq.connect_ports(
                    (src_client_id, src_port_id),
                    (dest_client_id, dest_port_id),
                    0, 0, 0, 0)
        except:
            # TODO log something
            pass
        
    def read_events(self):
        while True:
            if self._stopping:
                break

            event_list = self.seq.receive_events(timeout=128, maxevents=1)

            for event in event_list:
                data = event.get_data()

                if event.type == SEQ_EVENT_CLIENT_START:
                    try:
                        client_id = data['addr.client']
                        client_info = self.seq.get_client_info(client_id)
                    except:
                        continue

                    # Sometimes client name is not ready
                    if client_info['name'] == f'Client-{client_id}':
                        time.sleep(0.010)
                        client_info = self.seq.get_client_info(client_id)

                    self._clients[client_id] = AlsaClient(
                        self, client_info['name'], client_id)

                elif event.type == SEQ_EVENT_CLIENT_EXIT:
                    client_id = data['addr.client']
                    client = self._clients.get(client_id)
                    if client is not None:
                        for port in client.ports.values():
                            self.remove_port_from_patchbay(client, port)

                        del self._clients[client_id]
                    
                elif event.type == SEQ_EVENT_PORT_START:
                    client_id, port_id = data['addr.client'], data['addr.port']
                    client = self._clients.get(client_id)
                    if client is None:
                        continue
                    
                    client.add_port(port_id)
                    port = client.ports.get(port_id)
                    if port is None:
                        continue
                    
                    self.add_port_to_patchbay(client, port)
                    
                elif event.type == SEQ_EVENT_PORT_EXIT:
                    client_id, port_id = data['addr.client'], data['addr.port']
                    client = self._clients.get(client_id)
                    if client is None:
                        continue

                    port = client.ports.get(port_id)
                    if port is None:
                        continue
                    
                    to_rm_conns = list[AlsaConn]()
                    
                    for conn in self._connections:
                        if (client_id, port_id) in ((conn.source_client_id, conn.source_port_id),
                                                    (conn.dest_client_id, conn.dest_port_id)):
                            to_rm_conns.append(conn)
                            
                    for conn in to_rm_conns:
                        port_names = conn.as_port_names(self._clients)
                        if port_names is not None:
                            self._osc_server.connection_removed(port_names)
                    
                    self.remove_port_from_patchbay(client, port)
                    
                elif event.type == SEQ_EVENT_PORT_SUBSCRIBED:
                    sender_client = self._clients.get(data['connect.sender.client'])
                    dest_client = self._clients.get(data['connect.dest.client'])
                    if sender_client is None or dest_client is None:
                        continue
                    
                    sender_port = sender_client.ports.get(data['connect.sender.port'])
                    dest_port = dest_client.ports.get(data['connect.dest.port'])
                    
                    if sender_port is None or dest_port is None:
                        continue

                    self._connections.append(
                        AlsaConn(sender_client.id, sender_port.id,
                                 dest_client.id, dest_port.id))

                    self._osc_server.connection_added(
                        (f":ALSA_OUT:{sender_client.name}:{sender_port.name}",
                         f":ALSA_IN:{dest_client.name}:{dest_port.name}")
                    )

                elif event.type == SEQ_EVENT_PORT_UNSUBSCRIBED:
                    sender_client = self._clients.get(data['connect.sender.client'])
                    dest_client = self._clients.get(data['connect.dest.client'])
                    if sender_client is None or dest_client is None:
                        continue

                    sender_port = sender_client.ports.get(data['connect.sender.port'])
                    dest_port = dest_client.ports.get(data['connect.dest.port'])

                    if sender_port is None or dest_port is None:
                        continue

                    for conn in self._connections:
                        if (conn.source_client_id == sender_client.id
                                and conn.source_port_id == sender_port.id
                                and conn.dest_client_id == dest_client.id
                                and conn.dest_port_id == dest_port.id):
                            self._connections.remove(conn)
                            break 

                    self._osc_server.connection_removed(
                        (f":ALSA_OUT:{sender_client.name}:{sender_port.name}",
                         f":ALSA_IN:{dest_client.name}:{dest_port.name}")
                    )
                
    def stop_events_loop(self):
        if not self._event_thread.is_alive():
            return

        self._stopping = True
        self._event_thread.join()
        
        for client in self._clients.values():
            for port in client.ports.values():
                self.remove_port_from_patchbay(client, port)
        
        del self._event_thread
        self._stopping = False
        self._event_thread = Thread(target=self.read_events)
    
    def exit(self):
        self.seq.exit()
    