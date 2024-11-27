
# Imports from standard library
from dataclasses import dataclass
import time
from typing import TYPE_CHECKING, Iterator, Optional
from threading import Thread

# third party imports
from pyalsa import alsaseq
from pyalsa.alsaseq import (
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
)

# imports from jackpatch
if TYPE_CHECKING:
    from src.clients.jackpatch.bases import (
        Glob, EventHandler, Event, PortMode, PortType)
else:
    from bases import (
        Glob, EventHandler, Event, PortMode, PortType)


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
    
    def as_port_names(
            self, clients: dict[int, 'AlsaClient']) -> \
                Optional[tuple[str, str]]:
        src_client = clients.get(self.source_client_id)
        dest_client = clients.get(self.dest_client_id)
        
        if src_client is None or dest_client is None:
            return None
        
        src_port = src_client.ports.get(self.source_port_id)
        dest_port = dest_client.ports.get(self.dest_port_id)
        
        if src_port is None or dest_port is None:
            return None
        
        return (f"{src_client.name}:{src_port.name}",
                f"{dest_client.name}:{dest_port.name}")


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
    def __init__(self):
        self.seq = alsaseq.Sequencer(clientname='ray-alsapatch')

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
            name="alsapatch_read_port",
            type=SEQ_PORT_TYPE_APPLICATION,
            caps=port_caps)

        self.seq.connect_ports(
            (SEQ_CLIENT_SYSTEM, SEQ_PORT_SYSTEM_ANNOUNCE),
            (self.seq.client_id, input_id))
        
        self.get_the_graph()
        self._event_thread.start()

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
            
        for client in self._clients.values():
            for port in client.ports.values():
                if port.caps & _PORT_READS == _PORT_READS:
                    EventHandler.add_event(
                        Event.PORT_ADDED, f'{client.name}:{port.name}',
                        PortMode.OUTPUT, PortType.MIDI)
                if port.caps & _PORT_WRITES == _PORT_WRITES:
                    EventHandler.add_event(
                        Event.PORT_ADDED, f'{client.name}:{port.name}',
                        PortMode.INPUT, PortType.MIDI)

        for conn in self._connections:
            port_names = conn.as_port_names(self._clients)
            if port_names is not None:
                EventHandler.add_event(
                    Event.CONNECTION_ADDED, *port_names)
    
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
            
            yield (f'{src_client.name}:{src_port.name}',
                   f'{dest_client.name}:{dest_port.name}')
    
    def connect_ports(self, port_out_name: str, port_in_name: str,
                      disconnect=False):
        src_client_name, _, src_port_name = port_out_name.partition(':')
        dest_client_name, _, dest_port_name = port_in_name.partition(':')

        src_clients = [c for c in self._clients.values() if c.name == src_client_name]
        dest_clients = [c for c in self._clients.values() if c.name == dest_client_name]
        
        if not (src_clients and dest_clients):
            return
        
        for src_client in src_clients:
            for src_port_id, src_port in src_client.ports.items():
                if src_port.name == src_port_name:
                    for dest_client in dest_clients:
                        for dest_port_id, dest_port in dest_client.ports.items():
                            if dest_port.name == dest_port_name:
                                try:
                                    if disconnect:
                                        self.seq.disconnect_ports(
                                            (src_client.id, src_port_id),
                                            (dest_client.id, dest_port_id))
                                    else: 
                                        self.seq.connect_ports(
                                            (src_client.id, src_port_id),
                                            (dest_client.id, dest_port_id),
                                            0, 0, 0, 0)
                                except:
                                    # TODO log something
                                    continue
        
    def read_events(self):
        while True:
            if Glob.terminate:
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

                    n_tries = 0
                    client_outed = False

                    # Sometimes client name is not ready
                    while client_info['name'] == f'Client-{client_id}':
                        time.sleep(0.010)
                        try:
                            client_info = self.seq.get_client_info(client_id)
                        except:
                            client_outed = True
                            break
                        
                        n_tries += 1
                        if n_tries >= 5:
                            break
                    
                    if client_outed:
                        continue

                    self._clients[client_id] = AlsaClient(
                        self, client_info['name'], client_id)
                    # EventHandler.add_event(
                    #     Event.CLIENT_ADDED, client_info['name'])

                elif event.type == SEQ_EVENT_CLIENT_EXIT:
                    client_id = data['addr.client']
                    client = self._clients.get(client_id)
                    if client is not None:
                        # EventHandler.add_event(
                        #     Event.CLIENT_REMOVED, self._clients[client_id].name)
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
                    
                    if port.caps & _PORT_READS == _PORT_READS:
                        EventHandler.add_event(
                            Event.PORT_ADDED, f'{client.name}:{port.name}',
                            PortMode.OUTPUT, PortType.MIDI)
                    if port.caps & _PORT_WRITES == _PORT_WRITES:
                        EventHandler.add_event(
                            Event.PORT_ADDED, f'{client.name}:{port.name}',
                            PortMode.INPUT, PortType.MIDI)
                    
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
                        self._connections.remove(conn)
                        EventHandler.add_event(
                            Event.CONNECTION_REMOVED, *conn.as_port_names(self._clients))
                    if port.caps & _PORT_READS == _PORT_READS:
                        EventHandler.add_event(
                            Event.PORT_REMOVED, f'{client.name}:{port.name}',
                            PortMode.OUTPUT, PortType.MIDI)
                    if port.caps & _PORT_WRITES == _PORT_WRITES:
                        EventHandler.add_event(
                            Event.PORT_REMOVED, f'{client.name}:{port.name}',
                            PortMode.INPUT, PortType.MIDI)

                elif event.type == SEQ_EVENT_PORT_SUBSCRIBED:
                    sender_client = self._clients.get(data['connect.sender.client'])
                    dest_client = self._clients.get(data['connect.dest.client'])
                    if sender_client is None or dest_client is None:
                        continue
                    
                    sender_port = sender_client.ports.get(data['connect.sender.port'])
                    dest_port = dest_client.ports.get(data['connect.dest.port'])
                    
                    if sender_port is None or dest_port is None:
                        continue
                    
                    alsa_conn = AlsaConn(
                        sender_client.id, sender_port.id,
                        dest_client.id, dest_port.id)
                    
                    self._connections.append(alsa_conn)
                    
                    port_names = alsa_conn.as_port_names(self._clients)
                    
                    if port_names is not None:
                        EventHandler.add_event(
                            Event.CONNECTION_ADDED, *port_names)

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
                            EventHandler.add_event(
                                Event.CONNECTION_REMOVED, *conn.as_port_names(self._clients))
                            self._connections.remove(conn)
                            break
    