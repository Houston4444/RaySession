from typing import TYPE_CHECKING

from qtpy.QtCore import QCoreApplication
from osclib.bases import OscPack

import ray
import osc_paths.ray.gui as rg
import osc_paths.nsm as nsm

from daemon_tools import highlight_text, RS

from .session_op import SessionOp

if TYPE_CHECKING:
    from session_operating import OperatingSession


_translate = QCoreApplication.translate


class Load(SessionOp):
    def __init__(self, session: 'OperatingSession', open_off=False):
        super().__init__(session)
        self.script_step = 'load'
        self.open_off = open_off
        self.routine = [
            self.stop_clients,
            self.kill_clients,
            self.switch_or_start_clients,
            self.wait_client_replies,
            self.final_adjusts]

    def start_from_script(self, script_osp: OscPack):
        if 'open_off' in script_osp.args:
            self.open_off = True
        self.start()
    
    def stop_clients(self, open_off=False):
        session = self.session
        session.clean_expected()
        session.clients_to_quit.clear()

        # first quit unneeded clients
        # It has probably been done but we can't know if during the load script
        # some clients could have been stopped.
        # Because adding client is not allowed
        # during the load script before run_step,
        # we can assume all these clients are needed if they are running.
        # 'open_off' decided during the load script
        # is a good reason to stop all clients.

        for client in session.clients.__reversed__():
            if (open_off
                    or not client.is_running
                    or (client.is_reply_pending()
                        and not client.is_dumb_client())
                    or client.switch_state is not ray.SwitchState.RESERVED):
                session.clients_to_quit.append(client)
                session.expected_clients.append(client)
            else:
                client.switch_state = ray.SwitchState.NEEDED

        session.timer_quit.start()
        self.next(ray.WaitFor.QUIT, timeout=5000)

    def kill_clients(self):
        session = self.session
        for client in session.expected_clients:
            client.kill()
            
        self.next(ray.WaitFor.QUIT, timeout=1000)

    def switch_or_start_clients(self):
        session = self.session
        session.clean_expected()

        session.load_locked = False
        session.send_gui_message(
            _translate('GUIMSG', "-- Opening session %s --")
                % highlight_text(session.short_path_name))

        for trashed_client in session.future_trashed_clients:
            session.trashed_clients.append(trashed_client)
            trashed_client.send_gui_client_properties(removed=True)

        session.message("Commanding smart clients to switch")
        has_switch = False
        new_client_id_list = list[str]()

        # remove stopped clients
        rm_indexes = list[int]()
        for i, client in enumerate(session.clients):
            if not client.is_running:
                rm_indexes.append(i)

        rm_indexes.reverse()
        for i in rm_indexes:
            session._remove_client(session.clients[i])

        # Lie to the GUIs saying all clients are removed.
        # Clients will reappear just in a few time
        # It prevents GUI to have 2 clients with the same client_id
        # in the same time
        for client in session.clients:
            client.set_status(ray.ClientStatus.REMOVED)
            client.sent_to_gui = False

        for future_client in session.future_clients:
            client = None

            # This part needs care
            # we add future_clients to clients.
            # At this point,
            # running clients waiting for switch have SwitchState NEEDED,
            # running clients already choosen for switch have SwitchState DONE,
            # clients just added from future clients without switch
            # have SwitchState NONE.

            if future_client.auto_start:
                for client in session.clients:
                    if (client.switch_state is ray.SwitchState.NEEDED
                            and client.client_id == future_client.client_id
                            and client.can_switch_with(future_client)):
                        # we found the good existing client
                        break
                else:
                    for client in session.clients:
                        if (client.switch_state is ray.SwitchState.NEEDED
                                and client.can_switch_with(future_client)):
                            # we found a switchable client
                            break
                    else:
                        client = None

            if client:
                client.switch_state = ray.SwitchState.DONE
                session.send_monitor_event(
                    f"switched_to:{future_client.client_id}",
                    client.client_id)
                client.client_id = future_client.client_id
                client.eat_attributes(future_client)
                has_switch = True
            else:
                if not session._add_client(future_client):
                    continue

                if (future_client.auto_start
                        and not (session.is_dummy or self.open_off)):
                    session.clients_to_launch.append(future_client)

                    if (not future_client.executable
                            in RS.non_active_clients):
                        session.expected_clients.append(future_client)

            new_client_id_list.append(future_client.client_id)

        for client in session.clients:
            if client.switch_state is ray.SwitchState.DONE:
                client.switch()

        session._re_order_clients(new_client_id_list)
        session.send_gui(rg.session.SORT_CLIENTS, *new_client_id_list)
        
        # send initial monitor infos for all monitors
        # Note that a monitor client starting here with the session
        # will not receive theses messages, because it is not known as capable
        # of ':monitor:' yet.
        # However, a monitor client capable of :switch: 
        # will get theses messages.
        # An outside monitor (saved in server.monitor_list) 
        # will get theses messages in all cases. 
        server = session.get_server()
        if server is not None:
            for monitor_addr in server.monitor_list:
                session.send_initial_monitor(monitor_addr, False)
                
            for client in session.clients:
                if client.addr and client.is_running and client.can_monitor:
                    session.send_initial_monitor(client.addr, True)

        session._no_future()

        if has_switch:
            session.set_server_status(ray.ServerStatus.SWITCH)
        else:
            session.set_server_status(ray.ServerStatus.LAUNCH)

        #* this part is a little tricky... the clients need some time to
        #* send their 'announce' messages before we can send them 'open'
        #* and know that a reply is pending and we should continue waiting
        #* until they finish.

        #* dumb clients will never send an 'announce message', so we need
        #* to give up waiting on them fairly soon. */

        session.timer_launch.start()

        wait_time = 4000 + len(session.expected_clients) * 1000

        self.next(ray.WaitFor.ANNOUNCE, timeout=wait_time)

    def wait_client_replies(self):
        session = self.session
        for client in session.expected_clients:
            if not client.executable in RS.non_active_clients:
                RS.non_active_clients.append(client.executable)

        RS.settings.setValue('daemon/non_active_list', RS.non_active_clients)

        session.clean_expected()

        session.set_server_status(ray.ServerStatus.OPEN)

        for client in session.clients:
            if client.nsm_active and client.is_reply_pending():
                session.expected_clients.append(client)
            elif client.is_running and client.is_dumb_client():
                client.set_status(ray.ClientStatus.NOOP)

        if session.expected_clients:
            n_expected = len(session.expected_clients)
            if n_expected == 1:
                session.send_gui_message(
                    _translate('GUIMSG',
                               'waiting for %s to load its project...')
                    % session.expected_clients[0].gui_msg_style)
            else:
                session.send_gui_message(
                    _translate('GUIMSG',
                               'waiting for %s clients to load their project...')
                    % n_expected)

        wait_time = 8000 + len(session.expected_clients) * 2000
        for client in session.expected_clients:
            wait_time = int(max(2 * 1000 * client.last_open_duration, wait_time))

        self.next(ray.WaitFor.REPLY, timeout=wait_time)

    def final_adjusts(self):
        session = self.session
        session.clean_expected()

        if session.has_server_option(ray.Option.DESKTOPS_MEMORY):
            session.desktops_memory.replace()

        session.message("Telling all clients that session is loaded...")
        for client in session.clients:
            client.tell_client_session_is_loaded()

        session.message('Loaded')
        session.send_gui_message(
            _translate('GUIMSG', 'session %s is loaded.')
                % highlight_text(session.short_path_name))
        session.send_gui(rg.session.NAME, session.name, str(session.path))

        session.switching_session = False

        # display optional GUIs we want to be shown now
        if session.has_server_option(ray.Option.GUI_STATES):
            for client in session.clients:
                if (client.is_running
                        and client.can_optional_gui
                        and not client.start_gui_hidden
                        and not client.gui_has_been_visible):
                    client.send_to_self_address(nsm.client.SHOW_OPTIONAL_GUI)

        self.next()
    