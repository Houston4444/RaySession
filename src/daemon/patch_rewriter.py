
from typing import TYPE_CHECKING
import xml.etree.ElementTree as ET
import os
import logging
import sys

import ray
from jack_renaming_tools import (port_belongs_to_client,
                                 port_name_client_replaced)
if TYPE_CHECKING:
    from session import OperatingSession

_logger = logging.getLogger(__name__)
    
def rewrite_jack_patch_files(
        session: 'OperatingSession',
        old_client_id: str, new_client_id: str,
        old_jack_name: str, new_jack_name: str):
    for client in session.clients + session.trashed_clients:
        if client.protocol != ray.Protocol.NSM:
            continue

        patch_path = client.get_project_path() + '.xml'
        if not os.path.exists(patch_path):
            continue
        
        if not os.access(patch_path, os.W_OK):
            continue
        
        try:
            with open(patch_path, 'r') as f:
                tree = ET.parse(f)
            root = tree.getroot()
            assert root.tag == 'RAY-JACKPATCH'
        except:
            continue

        has_modifs = False
        
        for child in root:
            if child.tag == 'connection':
                port_from: str = child.attrib.get('from')
                port_to: str = child.attrib.get('to')
                
                if port_belongs_to_client(port_from, old_jack_name):
                    has_modifs = True
                    child.attrib['from'] = port_name_client_replaced(
                        port_from, old_jack_name, new_jack_name)
                    child.attrib['nsm_client_from'] = new_client_id
                if port_belongs_to_client(port_to, old_jack_name):
                    has_modifs = True
                    child.attrib['to'] = port_name_client_replaced(
                        port_to, old_jack_name, new_jack_name)
                    child.attrib['nsm_client_to'] = new_client_id

        if not has_modifs:
            continue
                    
        if sys.version_info >= (3, 9):
            # we can indent the xml tree since python3.9
            ET.indent(root, space='  ', level=0)
            
        tree = ET.ElementTree(root)
        print('____', patch_path, '____')
        # print(tree.w)

        try:
            tree.write(patch_path, encoding="utf8")
        except:
            logging.error(f"Unable to rewrite the patch file {patch_path}")

        

            
            
    

