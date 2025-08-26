
# Imports from standard library
from pathlib import Path
from typing import TYPE_CHECKING
import xml.etree.ElementTree as ET
import os
import logging
import sys
import yaml

# Imports from src/shared
import ray
from jack_renaming_tools import (
    port_belongs_to_client, port_name_client_replaced)

if TYPE_CHECKING:
    from session_operating import OperatingSession

_logger = logging.getLogger(__name__)
    
def rewrite_jack_patch_files(
        session: 'OperatingSession',
        old_client_id: str, new_client_id: str,
        old_jack_name: str, new_jack_name: str):
    for client in session.clients + session.trashed_clients:
        if client.protocol not in (ray.Protocol.NSM, ray.Protocol.INTERNAL):
            continue

        yaml_path = Path(str(client.get_project_path()) + '.yaml')
        patch_path = Path(str(client.get_project_path()) + '.xml')
        has_modifs = False
        
        if yaml_path.exists():
            if not os.access(yaml_path, os.W_OK):
                continue
            
            try:
                with open(yaml_path, 'r') as f:
                    contents = f.read()
                    patch_dict = yaml.safe_load(contents)
                    assert isinstance(patch_dict, dict)
                    patch_app = patch_dict.get('app')
                    assert patch_app in ('RAY-JACKPATCH', 'RAY-ALSAPATCH')
            except:
                continue
            
            brothers = patch_dict.get('nsm_brothers')
            brothers_ = dict[str, str]()
            if isinstance(brothers, dict):
                for nsm_name, jack_name in brothers.items():
                    if (isinstance(nsm_name, str)
                            and isinstance(jack_name, str)):
                        brothers_[nsm_name] = jack_name
                                
            connections = patch_dict.get('connections')
            if isinstance(connections, list):
                for conn in connections:
                    if not isinstance(conn, dict):
                        continue
                    
                    port_from_ = conn.get('from')
                    port_to_ = conn.get('to')
                    
                    if not (isinstance(port_from_, str)
                            and isinstance(port_to_, str)):
                        continue
                    
                    if port_belongs_to_client(port_from_, old_jack_name):
                        has_modifs = True
                        conn['from'] = port_name_client_replaced(
                            port_from_, old_jack_name, new_jack_name)
                    
                    if port_belongs_to_client(port_to_, old_jack_name):
                        conn['to'] = port_name_client_replaced(
                            port_to_, old_jack_name, new_jack_name)
        
            if not has_modifs:
                continue
            
            try:
                with open(yaml_path, 'w') as f:
                    f.write(yaml.dump(patch_dict, sort_keys=False))
            except:
                _logger.error(
                    f"Unable to rewrite the patch file {yaml_path}")
            continue
        
        if not patch_path.exists():
            continue
        
        if not os.access(patch_path, os.W_OK):
            continue
        
        try:
            with open(patch_path, 'r') as f:
                tree = ET.parse(f)
            root = tree.getroot()
            assert root.tag in ('RAY-JACKPATCH', 'RAY-ALSAPATCH')
        except:
            continue

        for child in root:
            if child.tag == 'connection':
                port_from: str = child.attrib.get('from', '')
                port_to: str = child.attrib.get('to', '')
                
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

        try:
            tree.write(str(patch_path), encoding="utf8")
        except:
            _logger.error(f"Unable to rewrite the patch file {patch_path}")

        

            
            
    

