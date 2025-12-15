import logging
import os
from typing import TYPE_CHECKING

from qtpy.QtCore import QCoreApplication

import osc_paths.ray.gui as rg
from osclib import Address, MegaSend
import ray

from daemon_tools import highlight_text

from .session_op import SessionOp

if TYPE_CHECKING:
    from session_operating import OperatingSession


_translate = QCoreApplication.translate
_logger = logging.getLogger(__name__)


class SendPreview(SessionOp):
    def __init__(self, session: 'OperatingSession', src_addr: Address,
                 folder_sizes: list[dict[str, str | int]]):
        super().__init__(session)
        self.src_addr = src_addr
        self.folder_sizes = folder_sizes
        
        self.routine = [self.send_preview]

    def send_preview(self):
        session = self.session
        
        def send_state(preview_state: ray.PreviewState):
            session.send_even_dummy(
                self.src_addr, rg.preview.STATE,
                preview_state.value) 
        
        if session.path is None:
            return
        
        # prevent long list of OSC sends if preview order already changed
        server = session.get_server_even_dummy()
        if server and server.session_to_preview != session.short_path_name:
            return
        
        session.send_even_dummy(self.src_addr, rg.preview.CLEAR)        
        send_state(ray.PreviewState.STARTED)
        
        session.send_even_dummy(
            self.src_addr, rg.preview.NOTES, session.notes)
        send_state(ray.PreviewState.NOTES)

        ms = MegaSend('session_preview')

        for client in session.clients:
            ms.add(rg.preview.client.UPDATE,
                   *client.spread())
            
            ms.add(rg.preview.client.IS_STARTED,
                   client.client_id, int(client.auto_start))
            
            if client.is_ray_hack:
                ms.add(rg.preview.client.RAY_HACK_UPDATE,
                       client.client_id, *client.ray_hack.spread())

            elif client.is_ray_net:
                ms.add(rg.preview.client.RAY_NET_UPDATE,
                       client.client_id, *client.ray_net.spread())
                
        session.mega_send(self.src_addr, ms)

        send_state(ray.PreviewState.CLIENTS)

        mss = MegaSend('snapshots_preview')

        for snapshot in session.snapshoter.list():
            mss.add(rg.preview.SNAPSHOT, snapshot)
        
        session.mega_send(self.src_addr, mss)
        
        send_state(ray.PreviewState.SNAPSHOTS)

        # re check here if preview has not changed before calculate session size
        if server and server.session_to_preview != session.short_path_name:
            return

        total_size = 0
        size_unreadable = False

        # get last modified session folder to prevent recalculate
        # if we already know its size
        modified = int(os.path.getmtime(session.path))

        # check if size is already in memory
        for folder_size in self.folder_sizes:
            if folder_size['path'] == str(session.path):
                if folder_size['modified'] == modified:
                    folder_size_size = folder_size['size']
                    if isinstance(folder_size_size, int):
                        total_size = folder_size_size
                break

        # calculate session size
        if not total_size:
            for root, dirs, files in os.walk(session.path):
                # check each loop if it is still pertinent to walk
                if (server 
                        and (server.session_to_preview
                             != session.short_path_name)):
                    return

                # exclude symlinks directories from count
                dirs[:] = [dir for dir in dirs
                        if not os.path.islink(os.path.join(root, dir))]

                for file_path in files:
                    full_file_path = os.path.join(root, file_path)
                    
                    # ignore file if it is a symlink
                    if os.path.islink(os.path.join(root, file_path)):
                        continue

                    file_size = 0
                    try:
                        file_size = os.path.getsize(full_file_path)
                    except:
                        _logger.warning(
                            f'Unable to read {full_file_path} size')
                        size_unreadable = True
                        break

                    total_size += file_size
                    # total_size += os.path.getsize(full_file_path)
                
                if size_unreadable:
                    total_size = -1
                    break
        
        for folder_size in self.folder_sizes:
            if folder_size['path'] == str(session.path):
                folder_size['modified'] = modified
                folder_size['size'] = total_size
                break
        else:
            self.folder_sizes.append(
                {'path': str(session.path),
                 'modified': modified,
                 'size': total_size})

        session.send_even_dummy(
            self.src_addr, rg.preview.SESSION_SIZE, total_size)

        send_state(ray.PreviewState.FOLDER_SIZE)

        session.send_even_dummy(
            self.src_addr, rg.preview.STATE, 2)

        del session
