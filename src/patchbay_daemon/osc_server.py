
import logging
from typing import TYPE_CHECKING
    
from osclib import (BunServer, Address, MegaSend,
                    are_on_same_machine, are_same_osc_port)
import osc_paths.ray as r
import osc_paths.ray.gui as rg

if TYPE_CHECKING:
    from patchbay_daemon import MainObject, TransportPosition


_logger = logging.getLogger(__name__)

class OscJackPatch(BunServer):
    def __init__(self, main_object: 'MainObject'):
        BunServer.__init__(self)
        self.add_method(r.patchbay.ADD_GUI, 's',
                        self._ray_patchbay_add_gui)
        self.add_method(r.patchbay.GUI_DISANNOUNCE, 's',
                        self._ray_patchbay_gui_disannounce)
        self.add_method(r.patchbay.CONNECT, 'ss',
                        self._ray_patchbay_connect)
        self.add_method(r.patchbay.DISCONNECT, 'ss',
                        self._ray_patchbay_disconnect)
        self.add_method(r.patchbay.SET_BUFFER_SIZE, 'i',
                        self._ray_patchbay_set_buffersize)
        self.add_method(r.patchbay.REFRESH, '',
                        self._ray_patchbay_refresh)
        self.add_method(r.patchbay.TRANSPORT_PLAY, 'i',
                        self._ray_patchbay_transport_play)
        self.add_method(r.patchbay.TRANSPORT_STOP, '',
                         self._ray_patchbay_transport_stop)
        self.add_method(r.patchbay.TRANSPORT_RELOCATE, 'i',
                        self._ray_patchbay_transport_relocate)
        self.add_method(r.patchbay.ACTIVATE_DSP_LOAD, 'i',
                        self._ray_patchbay_activate_dsp_load)
        self.add_method(r.patchbay.ACTIVATE_TRANSPORT, 'i',
                        self._ray_patchbay_activate_transport)
        self.add_method(r.patchbay.GROUP_PRETTY_NAME, 'sss',
                        self._ray_patchbay_group_pretty_name)
        self.add_method(r.patchbay.PORT_PRETTY_NAME, 'sss',
                        self._ray_patchbay_port_pretty_name)
        self.add_method(r.patchbay.SAVE_GROUP_PRETTY_NAME, 'ssi',
                        self._ray_patchbay_set_group_pretty_name)
        self.add_method(r.patchbay.SAVE_PORT_PRETTY_NAME, 'ssi',
                        self._ray_patchbay_set_port_pretty_name)
        self.add_method(r.patchbay.ENABLE_JACK_PRETTY_NAMING, 'i',
                        self._ray_patchbay_enable_jack_pretty_naming)
        self.add_method(r.patchbay.QUIT, '',
                        self._ray_patchbay_quit)

        self.main_object = main_object
        self.port_list = main_object.port_list
        self.connection_list = main_object.connection_list
        self.metadatas = main_object.metadatas
        self.client_name_uuids = main_object.client_name_uuids
        self.pretty_names = main_object.pretty_names
        self.gui_list = list[Address]()
        self._tmp_gui_url = ''
        self._terminate = False

    def set_tmp_gui_url(self, gui_url: str):
        self._tmp_gui_url = gui_url
    
    def can_have_gui(self) -> bool:
        if self._tmp_gui_url:
            return True
        if self.gui_list:
            return True
        return False
    
    def _ray_patchbay_add_gui(self, path, args):
        self.add_gui(args[0])

    def _ray_patchbay_gui_disannounce(self, path, args, types, src_addr):
        url: str = args[0]

        for gui_addr in self.gui_list:
            if are_same_osc_port(gui_addr.url, src_addr.url):
                # possible because we break the loop
                self.gui_list.remove(gui_addr)
                break

        if not self.gui_list and not self.main_object.pretty_name_active:
            # no more GUI connected, and no pretty-names to export,
            # no reason to exists anymore
            self._terminate = True

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

    def _ray_patchbay_group_pretty_name(self, path, args):
        if args[0]:
            self.pretty_names.save_group(*args)
        
    def _ray_patchbay_port_pretty_name(self, path, args):
        if args[0]:
            self.pretty_names.save_port(*args)
        else:
            # empty string received,
            # listing is finished, lets apply pretty names to JACK
            self.main_object.set_all_pretty_names()

    def _ray_patchbay_set_group_pretty_name(self, path, args):
        group_name, pretty_name, save_in_jack = args
        self.pretty_names.save_group(group_name, pretty_name)
        if save_in_jack:
            self.main_object.write_group_pretty_name(group_name, pretty_name)
    
    def _ray_patchbay_set_port_pretty_name(self, path, args):
        port_name, pretty_name, save_in_jack = args
        self.pretty_names.save_port(port_name, pretty_name)
        if save_in_jack:
            self.main_object.write_port_pretty_name(port_name, pretty_name)

    def _ray_patchbay_enable_jack_pretty_naming(self, path, args):
        export_pretty_names = bool(args[0])
        self.main_object.set_pretty_name_active(export_pretty_names)
        if not export_pretty_names and not self.gui_list:
            self._terminate = True

    def _ray_patchbay_quit(self, path, args):
        self._terminate = True

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

    def send_distant_data(self, src_addrs: list[Address]):
        ms = MegaSend('patchbay_ports')        
        ms.add(rg.patchbay.BIG_PACKETS, 0)

        for port in self.port_list:
            ms.add(rg.patchbay.PORT_ADDED,
                   port.name, port.type, port.flags, port.uuid)

        for client_name, client_uuid in self.client_name_uuids.items():
            ms.add(rg.patchbay.CLIENT_NAME_AND_UUID,
                   client_name, client_uuid)

        for connection in self.connection_list:
            ms.add(rg.patchbay.CONNECTION_ADDED,
                   connection[0], connection[1])

        for uuid, key_dict in self.metadatas.items():
            for key, value in key_dict.items():
                ms.add(rg.patchbay.METADATA_UPDATED,
                       uuid, key, value)
            
        if self.main_object.alsa_mng is not None:
            alsa_mng = self.main_object.alsa_mng
            for port in alsa_mng.parse_ports_and_flags():
                ms.add(rg.patchbay.PORT_ADDED,
                       port.name, port.type, port.flags, port.uuid)
                
            for conn in alsa_mng.parse_connections():
                ms.add(rg.patchbay.CONNECTION_ADDED, *conn)
        
        ms.add(rg.patchbay.BIG_PACKETS, 1)
        
        self.mega_send(src_addrs, ms)

    def add_gui(self, gui_url: str):
        gui_addr = Address(gui_url)
        if gui_addr is None:
            return

        try:
            self.send(gui_addr, rg.patchbay.ANNOUNCE,
                      int(self.main_object.jack_running),
                      self.main_object.samplerate,
                      self.main_object.buffer_size,
                      self.url)
            self.send(gui_addr, rg.patchbay.DSP_LOAD,
                      self.main_object.last_sent_dsp_load)

            tpos = self.main_object.last_transport_pos
            self.send(gui_addr, rg.patchbay.TRANSPORT_POSITION,
                      tpos.frame, int(tpos.rolling), int(tpos.valid_bbt),
                      tpos.bar, tpos.beat, tpos.tick, tpos.beats_per_minutes)

            self.gui_list.append(gui_addr)
            self.send_distant_data([gui_addr])

        except OSError as e:
            _logger.error(f'Failed to send message to GUI at {gui_url}')
            _logger.error(str(e))
        
        except BaseException as e:
            _logger.error(str(e))

    def server_restarted(self):
        self.send_gui(rg.patchbay.SERVER_STARTED)
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
        self.send_gui(rg.patchbay.CLIENT_NAME_AND_UUID,
                      client_name, uuid)

    def port_added(self, pname: str, ptype: int, pflags: int, puuid: int):
        self.send_gui(rg.patchbay.PORT_ADDED,
                      pname, ptype, pflags, puuid) 

    def port_renamed(self, ex_name: str, new_name, uuid=0):
        if uuid:
            self.send_gui(
                rg.patchbay.PORT_RENAMED, ex_name, new_name, uuid)
        else:
            self.send_gui(
                rg.patchbay.PORT_RENAMED, ex_name, new_name)
    
    def port_removed(self, port_name: str):
        self.send_gui(rg.patchbay.PORT_REMOVED, port_name)
    
    def metadata_updated(self, uuid: int, key: str, value: str):
        self.send_gui(rg.patchbay.METADATA_UPDATED, uuid, key, value)
    
    def connection_added(self, connection: tuple[str, str]):
        self.send_gui(rg.patchbay.CONNECTION_ADDED,
                     connection[0], connection[1])

    def connection_removed(self, connection: tuple[str, str]):
        self.send_gui(rg.patchbay.CONNECTION_REMOVED,
                     connection[0], connection[1])
    
    def server_stopped(self):
        # here server is JACK (or Pipewire JACK)
        self.send_gui(rg.patchbay.SERVER_STOPPED)
    
    def send_transport_position(self, tpos: 'TransportPosition'):
        self.send_gui(rg.patchbay.TRANSPORT_POSITION,
                      tpos.frame, int(tpos.rolling), int(tpos.valid_bbt),
                      tpos.bar, tpos.beat, tpos.tick, tpos.beats_per_minutes)
    
    def send_dsp_load(self, dsp_load: int):
        self.send_gui(rg.patchbay.DSP_LOAD, dsp_load)
    
    def send_one_xrun(self):
        self.send_gui(rg.patchbay.ADD_XRUN)
    
    def send_buffersize(self):
        self.send_gui(rg.patchbay.BUFFER_SIZE,
                     self.main_object.buffer_size)
    
    def send_samplerate(self):
        self.send_gui(rg.patchbay.SAMPLE_RATE,
                     self.main_object.samplerate)

    def is_terminate(self):
        return self._terminate
    
    def send_server_lose(self):
        self.send_gui(rg.patchbay.SERVER_LOSE)

        # In the case server is not responding
        # and gui has not yet been added to gui_list
        # but gui url stocked in self._tmp_gui_url
        if not self.gui_list and self._tmp_gui_url:
            try:
                addr = Address(self._tmp_gui_url)
            except:
                return

        self.send(addr, rg.patchbay.SERVER_LOSE)

    def ask_pretty_names(self, port: int):
        self.pretty_names.clear()

        addr = Address(port)
        self.send(addr, r.server.PATCHBAY_DAEMON_READY)
