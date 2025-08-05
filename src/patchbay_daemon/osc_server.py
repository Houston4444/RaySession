
import logging
from typing import TYPE_CHECKING

from patch_engine import ALSA_LIB_OK
from patshared import TransportWanted

from osclib import (BunServer, Address, MegaSend,
                    are_same_osc_port, OscPack, bun_manage, OscPath)
import osc_paths.ray as r
import osc_paths.ray.patchbay.monitor as rpm


if TYPE_CHECKING:
    from patchbay_daemon import PatchEngine


_logger = logging.getLogger(__name__)


class PatchbayDaemonServer(BunServer):
    def __init__(self, patch_engine: 'PatchEngine', daemon_port: int):
        BunServer.__init__(self)
        self.add_managed_methods()

        self.pe = patch_engine
        self.daemon_port = daemon_port
        self.pretty_names = patch_engine.pretty_names
        self.gui_list = list[Address]()
        self._tmp_gui_url = ''
    
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

    @bun_manage(r.patchbay.CONNECT, 'ss')
    def _ray_patchbay_connect(self, osp: OscPack):
        port_out_name, port_in_name = osp.args
        # connect here
        self.pe.connect_ports(port_out_name, port_in_name)
    
    @bun_manage(r.patchbay.DISCONNECT, 'ss')
    def _ray_patchbay_disconnect(self, osp: OscPack):
        port_out_name, port_in_name = osp.args
        # disconnect here
        self.pe.connect_ports(
            port_out_name, port_in_name, disconnect=True)

    @bun_manage(r.patchbay.SET_BUFFER_SIZE, 'i')
    def _ray_patchbay_set_buffersize(self, osp: OscPack):
        buffer_size = osp.args[0]
        self.pe.set_buffer_size(buffer_size)

    @bun_manage(r.patchbay.REFRESH, '')
    def _ray_patchbay_refresh(self, osp: OscPack):
        self.pe.refresh()

    @bun_manage(r.patchbay.TRANSPORT_PLAY, 'i')
    def _ray_patchbay_transport_play(self, osp: OscPack):
        self.pe.transport_play(bool(osp.args[0]))
    
    @bun_manage(r.patchbay.TRANSPORT_STOP, '')
    def _ray_patchbay_transport_stop(self, osp: OscPack):
        self.pe.transport_stop()
    
    @bun_manage(r.patchbay.TRANSPORT_RELOCATE, 'i')
    def _ray_patchbay_transport_relocate(self, osp: OscPack):
        self.pe.transport_relocate(osp.args[0])

    @bun_manage(r.patchbay.ACTIVATE_DSP_LOAD, 'i')
    def _ray_patchbay_activate_dsp_load(self, osp: OscPack):
        self.pe.dsp_wanted = bool(osp.args[0])
    
    @bun_manage(r.patchbay.ACTIVATE_TRANSPORT, 'i')
    def _ray_patchbay_activate_transport(self, osp: OscPack):
        try:
            transport_wanted = TransportWanted(osp.args[0])
        except:
            transport_wanted = TransportWanted.FULL
        self.pe.transport_wanted = transport_wanted

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
            self.pe.apply_pretty_names_export()

    @bun_manage(r.patchbay.SAVE_GROUP_PRETTY_NAME, 'ssi')
    def _ray_patchbay_save_group_pretty_name(self, osp: OscPack):
        group_name, pretty_name, save_in_jack = osp.args
        self.pretty_names.save_group(group_name, pretty_name)
        if save_in_jack:
            self.pe.write_group_pretty_name(group_name, pretty_name)
    
    @bun_manage(r.patchbay.SAVE_PORT_PRETTY_NAME, 'ssi')
    def _ray_patchbay_save_port_pretty_name(self, osp: OscPack):
        port_name, pretty_name, save_in_jack = osp.args
        self.pretty_names.save_port(port_name, pretty_name)
        if save_in_jack:
            self.pe.write_port_pretty_name(port_name, pretty_name)

    @bun_manage(r.patchbay.ENABLE_JACK_PRETTY_NAMING, 'i')
    def _ray_patchbay_enable_jack_pretty_naming(self,  osp: OscPack):
        export_pretty_names = bool(osp.args[0])
        self.pe.set_pretty_names_auto_export(export_pretty_names)

    @bun_manage(r.patchbay.EXPORT_ALL_PRETTY_NAMES, '')
    def _ray_patchbay_export_all_pretty_names(self, osp: OscPack):
        self.pe.export_all_pretty_names_to_jack_now()
        
    @bun_manage(r.patchbay.IMPORT_ALL_PRETTY_NAMES, '')
    def _ray_patchbay_import_all_pretty_names(self, osp: OscPack):
        self._import_all_pretty_names()

    @bun_manage(r.patchbay.CLEAR_ALL_PRETTY_NAMES, '')
    def _ray_patchbay_clear_all_pretty_names(self, osp: OscPack):
        self.pe.clear_all_pretty_names_from_jack()

    @property
    def can_leave(self) -> bool:
        if self._tmp_gui_url:
            return False
        if self.gui_list:
            return False
        return True

    def _import_all_pretty_names(self):
        clients_dict, ports_dict = \
            self.pe.import_all_pretty_names_from_jack()
        
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
            
        self.mega_send(self.daemon_port, ms)
        self.mega_send(self.gui_list, ms_gui)

    def set_tmp_gui_url(self, gui_url: str):
        self._tmp_gui_url = gui_url

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

    def send_distant_data(self, src_addrs: list[Address]):
        if not src_addrs:
            return
        
        ms = MegaSend('patchbay_ports')        
        ms.add(rpm.BIG_PACKETS, 0)

        for port in self.pe.ports:
            ms.add(rpm.PORT_ADDED,
                   port.name, port.type, port.flags, port.uuid)

        for client_name, client_uuid \
                in self.pe.client_name_uuids.items():
            ms.add(rpm.CLIENT_NAME_AND_UUID,
                   client_name, client_uuid)

        for connection in self.pe.connections:
            ms.add(rpm.CONNECTION_ADDED,
                   connection[0], connection[1])

        for uuid, key_dict in self.pe.metadatas.items():
            for key, value in key_dict.items():
                ms.add(rpm.METADATA_UPDATED,
                       uuid, key, value)

        if self.pe.alsa_mng is not None:
            alsa_mng = self.pe.alsa_mng
            for port in alsa_mng.parse_ports_and_flags():
                ms.add(rpm.PORT_ADDED,
                       port.name, port.type, port.flags, port.uuid)
                
            for conn in alsa_mng.parse_connections():
                ms.add(rpm.CONNECTION_ADDED, *conn)
        
        ms.add(rpm.BIG_PACKETS, 1)
        self.mega_send(src_addrs, ms)

    def add_gui(self, gui_url: str):
        try:
            gui_addr = Address(gui_url)
            self._tmp_gui_url = ''

            self.send(gui_addr, rpm.ANNOUNCE,
                      int(self.pe.jack_running),
                      int(ALSA_LIB_OK),
                      self.pe.samplerate,
                      self.pe.buffer_size,
                      self.url)
            self.send(gui_addr, rpm.DSP_LOAD,
                      self.pe.last_sent_dsp_load)

            tpos = self.pe.last_transport_pos
            self.send(gui_addr, rpm.TRANSPORT_POSITION,
                      tpos.frame, int(tpos.rolling), int(tpos.valid_bbt),
                      tpos.bar, tpos.beat, tpos.tick, tpos.beats_per_minutes)
            self.send(gui_addr, rpm.PRETTY_NAMES_LOCKED,
                      int(bool(self.pe.pretty_names_lockers)))

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
        self.send_distant_data(self.gui_list)
    
    def send_buffersize(self):
        self.send_gui(rpm.BUFFER_SIZE, self.pe.buffer_size)
    
    def send_samplerate(self):
        self.send_gui(rpm.SAMPLE_RATE, self.pe.samplerate)
    
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

    def make_one_shot_act(self, one_shot_act: OscPath):
        match one_shot_act:
            case r.patchbay.EXPORT_ALL_PRETTY_NAMES:
                self.pe.export_all_pretty_names_to_jack_now()
            case r.patchbay.IMPORT_ALL_PRETTY_NAMES:
                self._import_all_pretty_names()
            case r.patchbay.CLEAR_ALL_PRETTY_NAMES:
                self.pe.clear_all_pretty_names_from_jack()

    def set_ready_for_daemon(self):
        self.pretty_names.clear()
        self.send(self.daemon_port, r.server.PATCHBAY_DAEMON_READY)
