from pathlib import Path

from osclib import OscPack

from session import Session
import session_op as sop


class DummySession(Session):
    '''A dummy session allows to make such operations on not current session.
    
    It is used for session preview, or duplicate a session for example.
    When a session is dummy, it has no server options
    (bookmarks, snapshots, session scripts...).
    All clients are dummy and can't be started.
    Their file copier is not dummy, it can send OSC messages to gui,
    That is why we need a session_id to find it '''
    steps_order: list[sop.SessionOp]

    def __init__(self, root: Path, session_id=0):
        Session.__init__(self, root, session_id)
        self.is_dummy = True
        self.canvas_saver.is_dummy = True

    def dummy_load_and_template(self, session_full_name: str, template_name: str):
        self.steps_order = [
            sop.Preload(self, session_full_name),
            sop.TakePlace(self),
            sop.Load(self),
            sop.SaveSessionTemplate(self, template_name, net=True)]
        self.next_session_op()

    def dummy_duplicate(self, osp: OscPack):
        self.steps_osp = osp
        osp_args: tuple[str, str, str] = osp.args # type:ignore
        session_to_load, new_session_full_name, sess_root = osp_args
        self.steps_order = [
            sop.Preload(self, session_to_load),
            sop.TakePlace(self),
            sop.Load(self),
            sop.Duplicate(self, new_session_full_name),
            sop.Success(self, msg='Duplicate only done')]
        self.next_session_op()

    def ray_server_save_session_template(
            self, osp: OscPack, session_name: str, template_name: str, net: bool):
        self.steps_osp = osp
        self.steps_order = [
            sop.Preload(self, session_name),
            sop.TakePlace(self),
            sop.Load(self),
            sop.SaveSessionTemplate(self, template_name, net=net)]
        self.next_session_op()

    def ray_server_rename_session(self, osp: OscPack):
        self.steps_osp = osp
        osp_args: tuple[str, str] = osp.args # type:ignore
        full_session_name, new_session_name = osp_args

        self.steps_order = [
            sop.Preload(self, full_session_name),
            sop.TakePlace(self),
            sop.Load(self),
            sop.Rename(self, new_session_name),
            sop.Save(self),
            sop.Success(self, msg='Session renamed')]
        self.next_session_op()
    
    def ray_server_get_session_preview(
            self, osp: OscPack, folder_sizes: list[dict[str, str | int]]):
        session_name: str = osp.args[0] # type:ignore
        self.steps_order = [
            sop.Preload(self, session_name, auto_create=False),
            sop.TakePlace(self),
            sop.Load(self),
            sop.SendPreview(self, osp.src_addr, folder_sizes)]
        self.next_session_op()
    
    def dummy_load(self, session_name: str):
        self.steps_order = [
            sop.Preload(self, session_name, auto_create=False),
            sop.TakePlace(self),
            sop.Load(self)]
        self.next_session_op()
