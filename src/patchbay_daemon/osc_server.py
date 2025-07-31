
import logging
from typing import TYPE_CHECKING

from osclib import (BunServer, Address, MegaSend,
                    are_on_same_machine, are_same_osc_port,
                    OscPack, bun_manage)
import osc_paths.ray as r
import osc_paths.ray.patchbay.monitor as rpm

from alsa_lib_check import ALSA_LIB_OK
from patshared.base_enums import PrettyDiff

if TYPE_CHECKING:
    from patchbay_daemon import MainObject, TransportPosition


_logger = logging.getLogger(__name__)


class PatchbayDaemonServer(BunServer):
    def __init__(self, main_object: 'MainObject'):
        BunServer.__init__(self)
        self.add_managed_methods()

        self.main_object = main_object
        self.pretty_names = main_object.pretty_names
        self.gui_list = list[Address]()
        self._tmp_gui_url = ''
        self.terminate = False
    
    @bun_manage(r.patchbay.ADD_GUI, 's')
    def _ray_patchbay_add_gui(self, osp: OscPack):
        self.add_gui(osp.args[0])

    @bun_manage(r.patchbay.GUI_DISANNOUNCE, 's')
    def _ray_patchbay_gui_disannounce(self, osp: OscPack):
        url: str = osp.args[0]

        for gui_addr in self.gui_list:
            if are_same_osc_port(gui_addr.url, osp.src_addr.url):
                # possible because we break the loop
                self.gui_list.remove(gui_addr)
                break

        if not self.gui_list and not self.main_object.pretty_names_export:
            # no more GUI connected, and no pretty-names to export,
            # no reason to exists anymore
            self.terminate = True

    @bun_manage(r.patchbay.CONNECT, 'ss')
    def _ray_patchbay_connect(self, osp: OscPack):
        port_out_name, port_in_name = osp.args
        # connect here
        self.main_object.connect_ports(port_out_name, port_in_name)
    
    @bun_manage(r.patchbay.DISCONNECT, 'ss')
    def _ray_patchbay_disconnect(self, osp: OscPack):
        port_out_name, port_in_name = osp.args
        # disconnect here
        self.main_object.connect_ports(
            port_out_name, port_in_name, disconnect=True)

    @bun_manage(r.patchbay.SET_BUFFER_SIZE, 'i')
    def _ray_patchbay_set_buffersize(self, osp: OscPack):
        buffer_size = osp.args[0]
        self.main_object.set_buffer_size(buffer_size)

    @bun_manage(r.patchbay.REFRESH, '')
    def _ray_patchbay_refresh(self, osp: OscPack):
        self.main_object.refresh()

    @bun_manage(r.patchbay.TRANSPORT_PLAY, 'i')
    def _ray_patchbay_transport_play(self, osp: OscPack):
        self.main_object.transport_play(bool(osp.args[0]))
    
    @bun_manage(r.patchbay.TRANSPORT_STOP, '')
    def _ray_patchbay_transport_stop(self, osp: OscPack):
        self.main_object.transport_stop()
    
    @bun_manage(r.patchbay.TRANSPORT_RELOCATE, 'i')
    def _ray_patchbay_transport_relocate(self, osp: OscPack):
        self.main_object.transport_relocate(osp.args[0])

    @bun_manage(r.patchbay.ACTIVATE_DSP_LOAD, 'i')
    def _ray_patchbay_activate_dsp_load(self, osp: OscPack):
        self.main_object.dsp_wanted = bool(osp.args[0])
    
    @bun_manage(r.patchbay.ACTIVATE_TRANSPORT, 'i')
    def _ray_patchbay_activate_transport(self, osp: OscPack):
        self.main_object.set_transport_wanted(osp.args[0])

    @bun_manage(r.patchbay.GROUP_PRETTY_NAME, 'sss')
    def _ray_patchbay_group_pretty_name(self, osp: OscPack):
        if osp.args[0]:
            self.pretty_names.save_group(*osp.args)

    @bun_manage(r.patchbay.PORT_PRETTY_NAME, 'sss')
    def _ray_patchbay_port_pretty_name(self, osp: OscPack):
        if osp.args[0]:
            self.pretty_names.save_port(*osp.args)
        else:
            # empty string received,
            # listing is finished, lets apply pretty names to JACK
            self.main_object.set_all_pretty_names()

    @bun_manage(r.patchbay.SAVE_GROUP_PRETTY_NAME, 'ssi')
    def _ray_patchbay_save_group_pretty_name(self, osp: OscPack):
        group_name, pretty_name, save_in_jack = osp.args
        self.pretty_names.save_group(group_name, pretty_name)
        if save_in_jack:
            self.main_object.write_group_pretty_name(group_name, pretty_name)
    
    @bun_manage(r.patchbay.SAVE_PORT_PRETTY_NAME, 'ssi')
    def _ray_patchbay_save_port_pretty_name(self, osp: OscPack):
        port_name, pretty_name, save_in_jack = osp.args
        self.pretty_names.save_port(port_name, pretty_name)
        if save_in_jack:
            self.main_object.write_port_pretty_name(port_name, pretty_name)

    @bun_manage(r.patchbay.ENABLE_JACK_PRETTY_NAMING, 'i')
    def _ray_patchbay_enable_jack_pretty_naming(self,  osp: OscPack):
        export_pretty_names = bool(osp.args[0])
        self.main_object.set_pretty_names_auto_export(export_pretty_names)
        if not export_pretty_names and not self.gui_list:
            self.terminate = True

    @bun_manage(r.patchbay.EXPORT_ALL_PRETTY_NAMES, '')
    def _ray_patchbay_export_all_pretty_names(self, osp: OscPack):
        self.main_object.export_all_pretty_names_to_jack_now()
        
    @bun_manage(r.patchbay.IMPORT_ALL_PRETTY_NAMES, '')
    def _ray_patchbay_import_all_pretty_names(self, osp: OscPack):
        self._import_all_pretty_names()

    @bun_manage(r.patchbay.CLEAR_ALL_PRETTY_NAMES, '')
    def _ray_patchbay_clear_all_pretty_names(self, osp: OscPack):
        self.main_object.clear_all_pretty_names_from_jack()

    @bun_manage(r.patchbay.QUIT, '')
    def _ray_patchbay_quit(self, osp: OscPack):
        self.terminate = True

    def _import_all_pretty_names(self):
        clients_dict, ports_dict = \
            self.main_object.import_all_pretty_names_from_jack()
        
        ms = MegaSend('send imported pretty names to daemon')
        ms_gui = MegaSend('send imported pretty names to GUIs')

        for client_name, pretty_name in clients_dict.items():
            ms.add(r.server.patchbay.SAVE_GROUP_PRETTY_NAME,
                   client_name, pretty_name, '', 0)
            ms_gui.add(rpm.UPDATE_GROUP_PRETTY_NAME, client_name, pretty_name)
        
        for port_name, pretty_name in ports_dict.items():
            ms.add(r.server.patchbay.SAVE_PORT_PRETTY_NAME,
                   port_name, pretty_name, '', 0)
            ms_gui.add(rpm.UPDATE_PORT_PRETTY_NAME, port_name, pretty_name)
            
        self.mega_send(self.main_object.daemon_port, ms)
        self.mega_send(self.gui_list, ms_gui)

    def set_tmp_gui_url(self, gui_url: str):
        self._tmp_gui_url = gui_url

    def can_have_gui(self) -> bool:
        if self._tmp_gui_url:
            return True
        if self.gui_list:
            return True
        return False

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
        if not src_addrs:
            return
        
        ms = MegaSend('patchbay_ports')        
        ms.add(rpm.BIG_PACKETS, 0)

        for port in self.main_object.ports:
            ms.add(rpm.PORT_ADDED,
                   port.name, port.type, port.flags, port.uuid)

        for client_name, client_uuid \
                in self.main_object.client_name_uuids.items():
            ms.add(rpm.CLIENT_NAME_AND_UUID,
                   client_name, client_uuid)

        for connection in self.main_object.connections:
            ms.add(rpm.CONNECTION_ADDED,
                   connection[0], connection[1])

        for uuid, key_dict in self.main_object.metadatas.items():
            for key, value in key_dict.items():
                ms.add(rpm.METADATA_UPDATED,
                       uuid, key, value)

        if self.main_object.alsa_mng is not None:
            alsa_mng = self.main_object.alsa_mng
            for port in alsa_mng.parse_ports_and_flags():
                ms.add(rpm.PORT_ADDED,
                       port.name, port.type, port.flags, port.uuid)
                
            for conn in alsa_mng.parse_connections():
                ms.add(rpm.CONNECTION_ADDED, *conn)
        
        ms.add(rpm.BIG_PACKETS, 1)
        self.mega_send(src_addrs, ms)

    def add_gui(self, gui_url: str):
        gui_addr = Address(gui_url)
        if gui_addr is None:
            return

        try:
            self.send(gui_addr, rpm.ANNOUNCE,
                      int(self.main_object.jack_running),
                      int(ALSA_LIB_OK),
                      self.main_object.samplerate,
                      self.main_object.buffer_size,
                      self.url)
            self.send(gui_addr, rpm.DSP_LOAD,
                      self.main_object.last_sent_dsp_load)

            tpos = self.main_object.last_transport_pos
            self.send(gui_addr, rpm.TRANSPORT_POSITION,
                      tpos.frame, int(tpos.rolling), int(tpos.valid_bbt),
                      tpos.bar, tpos.beat, tpos.tick, tpos.beats_per_minutes)
            self.send(gui_addr, rpm.PRETTY_NAMES_LOCKED,
                      int(self.main_object.pretty_names_locked))

            self.gui_list.append(gui_addr)
            self.send_distant_data([gui_addr])

        except OSError as e:
            _logger.error(f'Failed to send message to GUI at {gui_url}')
            _logger.error(str(e))
        
        except BaseException as e:
            _logger.error(str(e))

    def server_restarted(self):
        self.send_gui(rpm.SERVER_STARTED)
        self.send_samplerate()
        self.send_buffersize()
        
        local_guis = list[Address]()
        distant_guis = list[Address]()
        
        for gui_addr in self.gui_list:
            if are_on_same_machine(self.url, gui_addr.url):
                local_guis.append(gui_addr)
            else:
                distant_guis.append(gui_addr)
        
        self.send_distant_data(self.gui_list)

    def associate_client_name_and_uuid(self, client_name: str, uuid: int):
        self.send_gui(rpm.CLIENT_NAME_AND_UUID, client_name, uuid)

    def port_added(self, pname: str, ptype: int, pflags: int, puuid: int):
        self.send_gui(rpm.PORT_ADDED, pname, ptype, pflags, puuid) 

    def port_renamed(self, ex_name: str, new_name, uuid=0):
        if uuid:
            self.send_gui(rpm.PORT_RENAMED, ex_name, new_name, uuid)
        else:
            self.send_gui(rpm.PORT_RENAMED, ex_name, new_name)
    
    def port_removed(self, port_name: str):
        self.send_gui(rpm.PORT_REMOVED, port_name)
    
    def metadata_updated(self, uuid: int, key: str, value: str):
        self.send_gui(rpm.METADATA_UPDATED, uuid, key, value)
    
    def connection_added(self, connection: tuple[str, str]):
        self.send_gui(rpm.CONNECTION_ADDED, connection[0], connection[1])

    def connection_removed(self, connection: tuple[str, str]):
        self.send_gui(rpm.CONNECTION_REMOVED, connection[0], connection[1])
    
    def server_stopped(self):
        # here server is JACK (or Pipewire JACK)
        self.send_gui(rpm.SERVER_STOPPED)
    
    def send_transport_position(self, tpos: 'TransportPosition'):
        self.send_gui(rpm.TRANSPORT_POSITION,
                      tpos.frame, int(tpos.rolling), int(tpos.valid_bbt),
                      tpos.bar, tpos.beat, tpos.tick, tpos.beats_per_minutes)
    
    def send_dsp_load(self, dsp_load: int):
        self.send_gui(rpm.DSP_LOAD, dsp_load)
    
    def send_one_xrun(self):
        self.send_gui(rpm.ADD_XRUN)
    
    def send_buffersize(self):
        self.send_gui(rpm.BUFFER_SIZE, self.main_object.buffer_size)
    
    def send_samplerate(self):
        self.send_gui(rpm.SAMPLE_RATE, self.main_object.samplerate)

    def send_pretty_names_locked(self, locked: bool):
        self.send_gui(rpm.PRETTY_NAMES_LOCKED, int(locked))
    
    def send_server_lose(self):
        self.send_gui(rpm.SERVER_LOSE)

        # In the case server is not responding
        # and gui has not yet been added to gui_list
        # but gui url stocked in self._tmp_gui_url
        if not self.gui_list and self._tmp_gui_url:
            try:
                addr = Address(self._tmp_gui_url)
            except:
                return

        self.send(addr, rpm.SERVER_LOSE)

    def make_one_shot_act(self, one_shot_act: str):
        match one_shot_act:
            case r.patchbay.EXPORT_ALL_PRETTY_NAMES:
                self.main_object.export_all_pretty_names_to_jack_now()
            case r.patchbay.IMPORT_ALL_PRETTY_NAMES:
                self._import_all_pretty_names()
            case r.patchbay.CLEAR_ALL_PRETTY_NAMES:
                self.main_object.clear_all_pretty_names_from_jack()
        

    def set_ready_for_daemon(self):
        self.pretty_names.clear()
        self.send(self.main_object.daemon_port,
                  r.server.PATCHBAY_DAEMON_READY)
