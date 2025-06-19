# -*- coding: utf-8 -*-

from enum import IntEnum
import os
from typing import Callable, Optional

from osclib import BunServer, Address, OscMulTypes, OscPack
import osc_paths
import osc_paths.nsm as nsm


_manage_wrappers = dict[str, Callable[[OscPack], bool]]()
_manage_types = dict[str, str]()


def manage(path: str, multypes: OscMulTypes):
    '''Decorator working like the @make_method decorator,
    but send methods with OscPack as argument.
    
    `path`: OSC str path

    `multypes`: str containing all accepted arg types
    '''
    def decorated(func: Callable):
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
    
        _manage_wrappers[path] = wrapper
        _manage_types[path] = multypes

        return wrapper
    return decorated


class Err(IntEnum):
    OK =  0
    GENERAL_ERROR = -1
    INCOMPATIBLE_API = -2
    BLACKLISTED = -3
    LAUNCH_FAILED = -4
    NO_SUCH_FILE = -5
    NO_SESSION_OPEN = -6
    UNSAVED_CHANGES = -7
    NOT_NOW = -8
    BAD_PROJECT = -9
    CREATE_FAILED = -10
    SESSION_LOCKED = -11
    OPERATION_PENDING = -12


class NsmCallback(IntEnum):
    OPEN = 1
    SAVE = 2
    SESSION_IS_LOADED = 3
    SHOW_OPTIONAL_GUI = 4
    HIDE_OPTIONAL_GUI = 5
    MONITOR_CLIENT_STATE = 6
    MONITOR_CLIENT_EVENT = 7
    MONITOR_CLIENT_UPDATED = 8


class NsmServer(BunServer):
    def __init__(self, daemon_address: Address, total_fake=False):
        super().__init__(total_fake=total_fake)
        self.add_nice_methods(_manage_types, self._generic_method)

        self._daemon_address = daemon_address
        self._server_capabilities = ""
        
        self._callbacks = dict[NsmCallback, Callable]()

    def _generic_method(self, osp: OscPack):
        '''Except the unknown messages, all messages received
        go through here.'''
        
        # run the method decorated with @manage
        if osp.path in _manage_wrappers:
            _manage_wrappers[osp.path](self, osp)

    @manage(osc_paths.REPLY, '.*')
    def _reply(self, osp: OscPack):
        if osp.args:
            reply_path = osp.args[0]
        else:
            return

        if reply_path == nsm.server.ANNOUNCE:
            self._server_capabilities = osp.args[3]

    @manage(nsm.client.OPEN, 'sss')
    def _nsm_client_open(self, osp: OscPack):
        ret = self._exec_callback(NsmCallback.OPEN, *osp.args)
        if ret is None:
            return
        
        err, err_text = ret
        if err is Err.OK:
            self._send_to_daemon(osc_paths.REPLY, osp.path, 'Ready')
        else:
            self._send_to_daemon(osc_paths.ERROR, osp.path, err, err_text)

    @manage(nsm.client.SAVE, '')
    def _nsm_client_save(self, osp: OscPack):
        ret = self._exec_callback(NsmCallback.SAVE)
        if ret is None:
            return
        
        err, err_text = ret
        if err is Err.OK:
            self._send_to_daemon(osc_paths.REPLY, osp.path, 'Saved')
        else:
            self._send_to_daemon(osc_paths.ERROR, osp.path, err_text)

    @manage(nsm.client.SESSION_IS_LOADED, '')
    def _nsm_client_session_is_loaded(self, osp: OscPack):
        self._exec_callback(NsmCallback.SESSION_IS_LOADED)

    @manage(nsm.client.SHOW_OPTIONAL_GUI, '')
    def _nsm_client_show_optional_gui(self, osp: OscPack):
        self._exec_callback(NsmCallback.SHOW_OPTIONAL_GUI)

    @manage(nsm.client.HIDE_OPTIONAL_GUI, '')
    def _nsm_client_hide_optional_gui(self, osp: OscPack):
        self._exec_callback(NsmCallback.HIDE_OPTIONAL_GUI)
    
    @manage(nsm.client.monitor.CLIENT_STATE, 'ssi')
    def _nsm_client_monitor_client_state(self, osp: OscPack):
        self._exec_callback(NsmCallback.MONITOR_CLIENT_STATE, *osp.args)
    
    @manage(nsm.client.monitor.CLIENT_EVENT, 'ss')
    def _nsm_client_monitor_client_event(self, osp: OscPack):
        self._exec_callback(NsmCallback.MONITOR_CLIENT_EVENT, *osp.args)

    @manage(nsm.client.monitor.CLIENT_UPDATED, 'ssi')
    def _nsm_client_monitor_client_properties(self, osp: OscPack):
        self._exec_callback(NsmCallback.MONITOR_CLIENT_UPDATED, *osp.args)
    
    def set_callback(self, on_event: NsmCallback, func: Callable):
        self._callbacks[on_event] = func

    def set_callbacks(self, cb_dict: dict[NsmCallback, Callable]):
        for on_event, func in cb_dict.items():
            self._callbacks[on_event] = func

    def _exec_callback(
            self, event: NsmCallback, *args) -> Optional[tuple[Err, str]]:
        if event in self._callbacks.keys():
            return self._callbacks[event](*args)

    def get_server_capabilities(self):
        return self._server_capabilities

    def _send_to_daemon(self, *args):
        self.send(self._daemon_address, *args)

    def announce(self, client_name: str, capabilities: str, executable_path: str):
        MAJOR, MINOR = 1, 0
        pid = os.getpid()

        self._send_to_daemon(
            nsm.server.ANNOUNCE,
            client_name,
            capabilities,
            executable_path,
            MAJOR,
            MINOR,
            pid)

    def send_dirty_state(self, dirty: bool):
        if dirty:
            self._send_to_daemon(nsm.client.IS_DIRTY)
        else:
            self._send_to_daemon(nsm.client.IS_CLEAN)

    def send_gui_state(self, state: bool):
        if state:
            self._send_to_daemon(nsm.client.GUI_IS_SHOWN)
        else:
            self._send_to_daemon(nsm.client.GUI_IS_HIDDEN)
            
    def send_monitor_reset(self):
        if ':monitor:' in self._server_capabilities:
            self._send_to_daemon(nsm.server.MONITOR_RESET)
