# -*- coding: utf-8 -*-

from enum import IntEnum
import os
from liblo import Server, make_method, Address
from typing import Callable, Optional


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


class NsmServer(Server):
    def __init__(self, daemon_address: Address):
        Server.__init__(self)
        self._daemon_address = daemon_address
        self._server_capabilities = ""
        
        self._callbacks = dict[NsmCallback, Callable]()

    @make_method('/reply', None)
    def _reply(self, path, args):
        if args:
            reply_path = args[0]
        else:
            return

        if reply_path == '/nsm/server/announce':
            self._server_capabilities = args[3]

    @make_method('/nsm/client/open', 'sss')
    def _nsm_client_open(self, path, args):
        ret = self._exec_callback(NsmCallback.OPEN, *args)
        if ret is None:
            return
        
        err, err_text = ret
        if err is Err.OK:
            self._send_to_daemon('/reply', path, 'Ready')
        else:
            self._send_to_daemon('/error', path, err, err_text)

    @make_method('/nsm/client/save', '')
    def _nsm_client_save(self, path, args):
        ret = self._exec_callback(NsmCallback.SAVE)
        if ret is None:
            return
        
        err, err_text = ret
        if err is Err.OK:
            self._send_to_daemon('/reply', path, 'Saved')
        else:
            self._send_to_daemon('/error', path, err_text)

    @make_method('/nsm/client/session_is_loaded', '')
    def _nsm_client_session_is_loaded(self, path, args):
        self._exec_callback(NsmCallback.SESSION_IS_LOADED)

    @make_method('/nsm/client/show_optional_gui', '')
    def _nsm_client_show_optional_gui(self, path, args):
        self._exec_callback(NsmCallback.SHOW_OPTIONAL_GUI)

    @make_method('/nsm/client/hide_optional_gui', '')
    def _nsm_client_hide_optional_gui(self, path, args):
        self._exec_callback(NsmCallback.HIDE_OPTIONAL_GUI)
    
    @make_method('/nsm/client/monitor/client_state', 'ssi')
    def _nsm_client_monitor_client_state(self, path, args):
        self._exec_callback(NsmCallback.MONITOR_CLIENT_STATE, *args)
    
    @make_method('/nsm/client/monitor/client_event', 'ss')
    def _nsm_client_monitor_client_event(self, path, args):
        self._exec_callback(NsmCallback.MONITOR_CLIENT_EVENT, *args)

    @make_method('/nsm/client/monitor/client_updated', 'ssi')
    def _nsm_client_monitor_client_properties(self, path, args):
        self._exec_callback(NsmCallback.MONITOR_CLIENT_UPDATED, *args)
    
    def set_callback(self, on_event: NsmCallback, func: Callable):
        self._callbacks[on_event] = func

    def _exec_callback(self, event: NsmCallback, *args) -> Optional[tuple[Err, str]]:
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
            '/nsm/server/announce',
            client_name,
            capabilities,
            executable_path,
            MAJOR,
            MINOR,
            pid)

    def send_dirty_state(self, dirty: bool):
        if dirty:
            self._send_to_daemon('/nsm/client/is_dirty')
        else:
            self._send_to_daemon('/nsm/client/is_clean')

    def send_gui_state(self, state: bool):
        if state:
            self._send_to_daemon('/nsm/client/gui_is_shown')
        else:
            self._send_to_daemon('/nsm/client/gui_is_hidden')
            
    def send_monitor_reset(self):
        if ':monitor:' in self._server_capabilities:
            self._send_to_daemon('/nsm/server/monitor_reset')