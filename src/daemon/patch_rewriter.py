
# Imports from standard library
from pathlib import Path
from typing import TYPE_CHECKING
import xml.etree.ElementTree as ET
import os
import logging
import sys

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

# Imports from src/shared
import ray
from jack_renaming_tools import Renamer

if TYPE_CHECKING:
    from session_operating import OperatingSession

_logger = logging.getLogger(__name__)


def _yaml_rewrite(
        yaml_path: Path, old_client_id: str, new_client_id: str,
        old_jack_name: str, new_jack_name: str):
    if not os.access(yaml_path, os.W_OK):
        return
    
    yaml = YAML()
    
    try:
        with open(yaml_path, 'r') as f:
            contents = f.read()
            patch_map = yaml.load(contents)
            assert isinstance(patch_map, CommentedMap)
            patch_app = patch_map.get('app')
            assert patch_app in ('RAY-JACKPATCH', 'RAY-ALSAPATCH')
    except:
        _logger.info(f"Will not rewrite {yaml_path} "
                     f"because it seems to not be a patcher file")
        return
    
    _logger.debug(f"Check yaml rewrite for {yaml_path}")
    
    renamer = Renamer(
        old_client_id, new_client_id, old_jack_name, new_jack_name)
    
    scenarios = patch_map.get('scenarios')
    if isinstance(scenarios, CommentedSeq):
        for scenario in scenarios:
            if not isinstance(scenario, CommentedMap):
                continue
            
            rules = scenario.get('rules')
            if isinstance(rules, CommentedMap):
                for rule_key in ('present_clients', 'absent_clients'):
                    pres_seq = rules.get(rule_key)
                    if not isinstance(pres_seq, CommentedSeq):
                        continue
                    
                    for i, group_name in enumerate(pres_seq):
                        if not isinstance(group_name, str):
                            continue
                        
                        if renamer.group_belongs(group_name):
                            pres_seq[i] = renamer.group_renamed(group_name)
            
            for scn_key in ('capture_redirections', 'playback_redirections'):
                scn_seq = scenario.get(scn_key)
                if not isinstance(scn_seq, CommentedSeq):
                    continue
                
                for map in scn_seq:
                    if not isinstance(map, CommentedMap):
                        continue

                    for key in ('origin', 'destination'):
                        value = map.get(key)
                        if isinstance(value, str):
                            if renamer.port_belongs(value):
                                map[key] = renamer.port_renamed(value)
            
            for scn_key in ('connect_domain', 'no_connect_domain',
                            'connections', 'forbidden_connections'):
                scn_seq = scenario.get(scn_key)
                if not isinstance(scn_seq, CommentedSeq):
                    continue
                
                for map in scn_seq:
                    if not isinstance(map, CommentedMap):
                        continue

                    for key in ('from', 'to'):
                        value = map.get(key)
                        if isinstance(value, str):
                            if renamer.port_belongs(value):
                                map[key] = renamer.port_renamed(value)

    for map_key in ('connections', 'forbidden_connections'):
        conns_seq = patch_map.get(map_key)
        if not isinstance(conns_seq, CommentedSeq):
            continue
        
        for map in conns_seq:
            if not isinstance(map, CommentedMap):
                continue
            
            for key in ('from', 'to'):
                value = map.get(key)
                if isinstance(value, str):
                    if renamer.port_belongs(value):
                        map[key] = renamer.port_renamed(value)
    
    graph = patch_map.get('graph')
    if isinstance(graph, dict):
        belongers = set[str]()
        for group_name in graph.keys():
            if not isinstance(group_name, str):
                continue
            
            if renamer.group_belongs(group_name):
                belongers.add(group_name)
        
        for group_name in belongers:
            new_group_name = renamer.group_renamed(group_name)
            graph[new_group_name] = graph.pop(group_name)
    
    brothers = patch_map.get('nsm_brothers')
    if isinstance(brothers, dict):
        if old_client_id in brothers.keys():
            brothers.pop(old_client_id)
        brothers[new_client_id] = new_jack_name
    
    try:
        with open(yaml_path, 'w') as f:
            _logger.info(
                f'patch file {yaml_path} rewritten '
                f'for client {old_client_id} -> {new_client_id}')
            yaml.dump(patch_map, f)
            # f.write(yaml.dump(patch_map))
    except:
        _logger.error(
            f"Unable to rewrite the patch file {yaml_path}")

def _xml_rewrite(xml_path: Path, old_client_id: str, new_client_id: str,
                 old_jack_name: str, new_jack_name: str):
    if not os.access(xml_path, os.W_OK):
        return
    
    try:
        with open(xml_path, 'r') as f:
            tree = ET.parse(f)
        root = tree.getroot()
        assert root.tag in ('RAY-JACKPATCH', 'RAY-ALSAPATCH')
    except:
        return

    has_modifs = False
    renamer = Renamer(old_client_id, new_client_id,
                      old_jack_name, new_jack_name)

    for child in root:
        if child.tag == 'connection':
            port_from: str = child.attrib.get('from', '')
            port_to: str = child.attrib.get('to', '')
            
            if renamer.port_belongs(port_from):                
                has_modifs = True
                child.attrib['from'] = renamer.port_renamed(port_from)
                child.attrib['nsm_client_from'] = new_client_id
            if renamer.port_belongs(port_to):
                has_modifs = True
                child.attrib['to'] = renamer.port_renamed(port_to)
                child.attrib['nsm_client_to'] = new_client_id

    if not has_modifs:
        return
                
    if sys.version_info >= (3, 9):
        # we can indent the xml tree since python3.9
        ET.indent(root, space='  ', level=0)
        
    tree = ET.ElementTree(root)

    try:
        tree.write(str(xml_path), encoding="utf8")
    except:
        _logger.error(f"Unable to rewrite the patch file {xml_path}")

def rewrite_jack_patch_files(
        session: 'OperatingSession',
        old_client_id: str, new_client_id: str,
        old_jack_name: str, new_jack_name: str):
    for client in session.clients + session.trashed_clients:
        if client.protocol not in (ray.Protocol.NSM, ray.Protocol.INTERNAL):
            continue

        yaml_path = Path(str(client.get_project_path()) + '.yaml')        
        if yaml_path.exists():
            _yaml_rewrite(yaml_path, old_client_id, new_client_id,
                          old_jack_name, new_jack_name)
            continue
        
        xml_path = Path(str(client.get_project_path()) + '.xml')
        if xml_path.exists():
            _xml_rewrite(xml_path, old_client_id, new_client_id,
                         old_jack_name, new_jack_name)
            continue
        
        

        

            
            
    

