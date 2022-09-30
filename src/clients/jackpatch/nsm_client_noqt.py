# -*- coding: utf-8 -*-

from enum import IntEnum
import os
from liblo import Server, make_method, Address
from typing import Callable


class NsmCallback(IntEnum):
    OPEN = 1
    SAVE = 2
    SESSION_IS_LOADED = 3
    SHOW_OPTIONAL_GUI = 4
    HIDE_OPTIONAL_GUI = 5
    MONITOR_CLIENT_STATE = 6
    MONITOR_CLIENT_EVENT = 7


class NsmThread(Server):
    def __init__(self, daemon_address: Address):
        Server.__init__(self)
        self._daemon_address = daemon_address
        self._server_capabilities = ""
        
        self._callbacks = dict[NsmCallback, Callable]()

    @make_method('/reply', None)
    def serverReply(self, path, args):
        if args:
            reply_path = args[0]
        else:
            return

        if reply_path == '/nsm/server/announce':
            self._server_capabilities = args[3]

    @make_method('/nsm/client/open', 'sss')
    def nsmClientOpen(self, path, args):
        self._exec_callback(NsmCallback.OPEN, *args)

    @make_method('/nsm/client/save', '')
    def nsmClientSave(self, path, args):
        self._exec_callback(NsmCallback.SAVE)

    @make_method('/nsm/client/session_is_loaded', '')
    def nsmClientSessionIsLoaded(self, path, args):
        self._exec_callback(NsmCallback.SESSION_IS_LOADED)

    @make_method('/nsm/client/show_optional_gui', '')
    def nsmClientShow_optional_gui(self, path, args):
        self._exec_callback(NsmCallback.SHOW_OPTIONAL_GUI)

    @make_method('/nsm/client/hide_optional_gui', '')
    def nsmClientHide_optional_gui(self, path, args):
        self._exec_callback(NsmCallback.HIDE_OPTIONAL_GUI)
    
    @make_method('/nsm/client/monitor/client_state', 'si')
    def nsm_client_brother_client_state(self, path, args):
        self._exec_callback(NsmCallback.MONITOR_CLIENT_STATE, *args)
    
    @make_method('/nsm/client/monitor/client_event', 'ss')
    def nsm_client_monitor_event(self, path, args):
        self._exec_callback(NsmCallback.MONITOR_CLIENT_EVENT, *args)

    def set_callback(self, on_event: NsmCallback, func: Callable):
        self._callbacks[on_event] = func

    def _exec_callback(self, event: NsmCallback, *args):
        if event in self._callbacks.keys():
            self._callbacks[event](*args)

    def get_server_capabilities(self):
        return self._server_capabilities

    def send_to_daemon(self, *args):
        self.send(self._daemon_address, *args)

    def announce(self, client_name: str, capabilities: str, executable_path: str):
        major = 1
        minor = 0
        pid = os.getpid()

        self.send_to_daemon(
            '/nsm/server/announce',
            client_name,
            capabilities,
            executable_path,
            major,
            minor,
            pid)

    def open_reply(self):
        self.send_to_daemon('/reply', '/nsm/client/open', 'Ready')

    def save_reply(self):
        self.send_to_daemon('/reply', '/nsm/client/save', 'Saved')

    def send_dirty_state(self, dirty: bool):
        if dirty:
            self.send_to_daemon('/nsm/client/is_dirty')
        else:
            self.send_to_daemon('/nsm/client/is_clean')

    def send_gui_state(self, state: bool):
        if state:
            self.send_to_daemon('/nsm/client/gui_is_shown')
        else:
            self.send_to_daemon('/nsm/client/gui_is_hidden')
