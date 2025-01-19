
import logging
from typing import TYPE_CHECKING
    
from osclib import (
    Server, Address, are_on_same_machine, get_free_osc_port, TCP)

if TYPE_CHECKING:
    from src.patchbay_daemon.patchbay_daemon import MainObject, TransportPosition


_logger = logging.getLogger(__name__)


class OscJackPatch(Server):
    def __init__(self, main_object: 'MainObject'):
        tcp_port = get_free_osc_port(4444, TCP)
        
        Server.__init__(self, tcp_port, TCP)
        self.add_method('/ray/patchbay/add_gui', 's',
                        self._ray_patchbay_add_gui)
        self.add_method('/ray/patchbay/gui_disannounce', 's',
                        self._ray_patchbay_gui_disannounce)
        self.add_method('/ray/patchbay/port/set_alias', 'sis',
                        self._ray_patchbay_port_set_alias)
        self.add_method('/ray/patchbay/connect', 'ss',
                        self._ray_patchbay_connect)
        self.add_method('/ray/patchbay/disconnect', 'ss',
                        self._ray_patchbay_disconnect)
        self.add_method('/ray/patchbay/set_buffer_size', 'i',
                        self._ray_patchbay_set_buffersize)
        self.add_method('/ray/patchbay/refresh', '',
                        self._ray_patchbay_refresh)
        self.add_method('/ray/patchbay/set_metadata', 'hss',
                        self._ray_patchbay_set_metadata)
        self.add_method('/ray/patchbay/transport_play', 'i',
                        self._ray_patchbay_transport_play)
        self.add_method('/ray/patchbay/transport_stop', '',
                         self._ray_patchbay_transport_stop)
        self.add_method('/ray/patchbay/transport_relocate', 'i',
                        self._ray_patchbay_transport_relocate)
        self.add_method('/ray/patchbay/activate_dsp_load', 'i',
                        self._ray_patchbay_activate_dsp_load)
        self.add_method('/ray/patchbay/activate_transport', 'i',
                        self._ray_patchbay_activate_transport)

        self.main_object = main_object
        self.port_list = main_object.port_list
        self.connection_list = main_object.connection_list
        self.metadata_list = main_object.metadata_list
        self.metadatas = main_object.metadatas
        self.client_list = main_object.client_list
        self.gui_list = list[Address]()
        self._tmp_gui_url = ''
        self._terminate = False

    def set_tmp_gui_url(self, gui_url: str):
        self._tmp_gui_url = gui_url
    
    def _ray_patchbay_add_gui(self, path, args):
        self.add_gui(args[0])

    def _ray_patchbay_gui_disannounce(self, path, args):
        url: str = args[0]

        for gui_addr in self.gui_list:
            if gui_addr.url == url:
                # possible because we break the loop
                self.gui_list.remove(gui_addr)
                break

        if not self.gui_list:
            # no more GUI connected, no reason to exists anymore
            self._terminate = True

    def _ray_patchbay_port_set_alias(self, path, args, types, src_addr):
        ...

    def _ray_patchbay_connect(self, path, args):
        port_out_name, port_in_name = args
        # connect here
        self.main_object.connect_ports(port_out_name, port_in_name)
    
    def _ray_patchbay_disconnect(self, path, args):
        port_out_name, port_in_name = args
        # disconnect here
        self.main_object.connect_ports(
            port_out_name, port_in_name, disconnect=True)

    def _ray_patchbay_set_buffersize(self, path, args):
        buffer_size = args[0]
        self.main_object.set_buffer_size(buffer_size)

    def _ray_patchbay_refresh(self, path, args):
        self.main_object.refresh()

    def _ray_patchbay_set_metadata(self, path, args):
        uuid, key, value = args
        self.main_object.set_metadata(uuid, key, value)

    def _ray_patchbay_transport_play(self, path, args):
        self.main_object.transport_play(bool(args[0]))
    
    def _ray_patchbay_transport_stop(self, path, args):
        self.main_object.transport_stop()
    
    def _ray_patchbay_transport_relocate(self, path, args):
        self.main_object.transport_relocate(args[0])

    def _ray_patchbay_activate_dsp_load(self, path, args):
        self.main_object.dsp_wanted = bool(args[0])
        
    def _ray_patchbay_activate_transport(self, path, args):
        self.main_object.set_transport_wanted(args[0])

    def send_gui(self, *args):
        rm_gui = list[Address]()
        
        for gui_addr in self.gui_list:
            try:
                self.send(gui_addr, *args)
            except OSError:
                rm_gui.append(gui_addr)
            except BaseException as e:
                _logger.warning(str(e))
        
        for gui_addr in rm_gui:
            self.gui_list.remove(gui_addr)

    def multi_send(self, src_addr_list: list[Address], *args):
        for src_addr in src_addr_list:
            self.send(src_addr, *args)

    def send_distant_data(self, src_addr_list: list[Address]):
        self.multi_send(src_addr_list, '/ray/gui/patchbay/big_packets', 0)
        
        for port in self.port_list:
            self.multi_send(src_addr_list, '/ray/gui/patchbay/port_added',
                            port.name, port.type, port.flags, port.uuid)
            
        for connection in self.connection_list:
            self.multi_send(src_addr_list,
                            '/ray/gui/patchbay/connection_added',
                            connection[0], connection[1])
        
        for uuid, key_dict in self.metadatas.items():
            for key, value in key_dict.items():
                self.multi_send(
                    src_addr_list,
                    '/ray/gui/patchbay/metadata_updated',
                    uuid, key, value)
            
        if self.main_object.alsa_mng is not None:
            alsa_mng = self.main_object.alsa_mng
            for port in alsa_mng.parse_ports_and_flags():
                self.multi_send(src_addr_list, '/ray/gui/patchbay/port_added',
                                port.name, port.type, port.flags, port.uuid)
                
            for conn in alsa_mng.parse_connections():
                self.multi_send(
                    src_addr_list,
                    '/ray/gui/patchbay/connection_added',
                    *conn)
                
        self.multi_send(src_addr_list, '/ray/gui/patchbay/big_packets', 1)

    def add_gui(self, gui_url: str):
        gui_addr = Address(gui_url)
        if gui_addr is None:
            return

        try:
            self.send(gui_addr, '/ray/gui/patchbay/announce',
                    int(self.main_object.jack_running),
                    self.main_object.samplerate,
                    self.main_object.buffer_size,
                    self.url)
            self.send(gui_addr, '/ray/gui/patchbay/dsp_load',
                    self.main_object.last_sent_dsp_load)

            tpos = self.main_object.last_transport_pos
            self.send(gui_addr, '/ray/gui/patchbay/transport_position',
                    tpos.frame, int(tpos.rolling), int(tpos.valid_bbt),
                    tpos.bar, tpos.beat, tpos.tick, tpos.beats_per_minutes)

            self.send_distant_data([gui_addr])
            
            self.gui_list.append(gui_addr)

        except OSError:
            _logger.error(f'Failed to send TCP message to GUI at {gui_url}')
        
        except BaseException as e:
            _logger.error(str(e))

    def server_restarted(self):
        self.send_gui('/ray/gui/patchbay/server_started')
        self.send_samplerate()
        self.send_buffersize()
        
        local_guis = []
        distant_guis = []
        
        for gui_addr in self.gui_list:
            if are_on_same_machine(self.url, gui_addr.url):
                local_guis.append(gui_addr)
            else:
                distant_guis.append(gui_addr)
        
        self.send_distant_data(self.gui_list)

    def client_name_and_uuid(self, client_name: str, uuid: int):
        self.send_gui('/ray/gui/patchbay/client_name_and_uuid',
                      client_name, uuid)

    def port_added(self, pname: str, ptype: int, pflags: int, puuid: int):
        self.send_gui('/ray/gui/patchbay/port_added',
                      pname, ptype, pflags, puuid) 

    def port_renamed(self, ex_name: str, new_name):
        self.send_gui('/ray/gui/patchbay/port_renamed', ex_name, new_name)
    
    def port_removed(self, port_name: str):
        self.send_gui('/ray/gui/patchbay/port_removed', port_name)
    
    def metadata_updated(self, uuid: int, key: str, value: str):
        self.send_gui('/ray/gui/patchbay/metadata_updated', uuid, key, value)
    
    def connection_added(self, connection: tuple[str, str]):
        self.send_gui('/ray/gui/patchbay/connection_added',
                     connection[0], connection[1])

    def connection_removed(self, connection: tuple[str, str]):
        self.send_gui('/ray/gui/patchbay/connection_removed',
                     connection[0], connection[1])
    
    def server_stopped(self):
        # here server is JACK (or Pipewire JACK)
        self.send_gui('/ray/gui/patchbay/server_stopped')
    
    def send_transport_position(self, tpos: 'TransportPosition'):
        self.send_gui('/ray/gui/patchbay/transport_position',
                      tpos.frame, int(tpos.rolling), int(tpos.valid_bbt),
                      tpos.bar, tpos.beat, tpos.tick, tpos.beats_per_minutes)
    
    def send_dsp_load(self, dsp_load: int):
        self.send_gui('/ray/gui/patchbay/dsp_load', dsp_load)
    
    def send_one_xrun(self):
        self.send_gui('/ray/gui/patchbay/add_xrun')
    
    def send_buffersize(self):
        self.send_gui('/ray/gui/patchbay/buffer_size',
                     self.main_object.buffer_size)
    
    def send_samplerate(self):
        self.send_gui('/ray/gui/patchbay/sample_rate',
                     self.main_object.samplerate)
    
    def is_terminate(self):
        return self._terminate
    
    def send_server_lose(self):
        self.send_gui('/ray/gui/patchbay/server_lose')
        
        # In the case server is not responding
        # and gui has not yet been added to gui_list
        # but gui url stocked in self._tmp_gui_url
        if not self.gui_list and self._tmp_gui_url:
            try:
                addr = Address(self._tmp_gui_url)
            except:
                return
        
        self.send(addr, '/ray/gui/patchbay/server_lose')
