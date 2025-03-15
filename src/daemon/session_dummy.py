from pathlib import Path

from osclib import OscPack

from session_operating import OperatingSession


class DummySession(OperatingSession):
    '''A dummy session allows to make such operations on not current session.
    
    It is used for session preview, or duplicate a session for example.
    When a session is dummy, it has no server options
    (bookmarks, snapshots, session scripts...).
    All clients are dummy and can't be started.
    Their file copier is not dummy, it can send OSC messages to gui,
    That is why we need a session_id to find it '''

    def __init__(self, root: Path, session_id=0):
        OperatingSession.__init__(self, root, session_id)
        self.is_dummy = True
        self.canvas_saver.is_dummy = True

    def dummy_load_and_template(self, session_full_name, template_name):
        self.steps_order = [(self.preload, session_full_name),
                            self.take_place,
                            self.load,
                            (self.save_session_template, template_name, True)]
        self.next_function()

    def dummy_duplicate(self, osp: OscPack):
        self.steps_osp = osp
        session_to_load, new_session_full_name, sess_root = osp.args
        self.steps_order = [(self.preload, session_to_load),
                            self.take_place,
                            self.load,
                            (self.duplicate, new_session_full_name),
                            self.duplicate_only_done]
        self.next_function()

    def ray_server_save_session_template(
            self, osp: OscPack, session_name: str, template_name: str, net: bool):
        self.steps_osp = osp
        self.steps_order = [(self.preload, session_name),
                            self.take_place,
                            self.load,
                            (self.save_session_template, template_name, net)]
        self.next_function()

    def ray_server_rename_session(self, osp: OscPack):
        self.steps_osp = osp
        full_session_name, new_session_name = osp.args

        self.steps_order = [(self.preload, full_session_name),
                            self.take_place,
                            self.load,
                            (self.rename, new_session_name),
                            self.save,
                            (self.rename_done, new_session_name)]
        self.next_function()
    
    def ray_server_get_session_preview(
            self, osp: OscPack, folder_sizes: list):
        session_name = osp.args[0]
        self.steps_order = [(self.preload, session_name, False),
                            self.take_place,
                            self.load,
                            (self.send_preview, osp.src_addr, folder_sizes)]
        self.next_function()
    
    def dummy_load(self, session_name):
        self.steps_order = [(self.preload, session_name, False),
                            self.take_place,
                            self.load]
        self.next_function()
