#!/usr/bin/python3

# run this script if you were using a2j bridge with unique port names
# (aka port name including the ALSA client ID)
# and you now use a2j bridge without unique port names.
# The script parse all sessions and modify all RAY-JACKPATCH xml files
# directly present in the session folder.

# for example:
#   a2j:USB Keystation 61es [24] (capture): USB Keystation 61es MIDI 1
# will become :
#   a2j:USB Keystation 61es (capture): USB Keystation 61es MIDI 1
# in all RAY-JACKPATCH files.

import xml.etree.ElementTree as ET
from typing import Iterator, Optional
import subprocess
import os

def ray_control(*args: list[str]) -> Optional[str]:
    process: subprocess.CompletedProcess[bytes] = subprocess.run(
        ['ray_control', *args], capture_output=True)
    stdout_bytes = process.stdout
    
    if stdout_bytes is None:
        print('ray_control', ' '.join(args), 'returns empty output')
        return None
    
    stdout_str = stdout_bytes.decode()
    if stdout_str.endswith('\n'):
        stdout_str = stdout_str[:-1]
    return stdout_str

def modify_file(file_path: str) -> bool:
    try:
        tree = ET.parse(file_path)
    except BaseException as e:
        print(e)
        return False
    
    root = tree.getroot()
    if root.tag != 'RAY-JACKPATCH':
        print(f"{file_path} is not a RAY-JACKPATCH xml file")
        return False

    # prepare avoid duplicated connections
    reworked_conns = set[tuple[str, str]]()
    childs_to_remove = list[ET.Element]()
    file_worked = False

    for child in root:
        if child.tag == 'connection':
            port_from: str = child.attrib.get('from')
            port_to: str = child.attrib.get('to')
            conn_worked = False
            
            if port_from.startswith('a2j:') and '] (capture): ' in port_from:
                prefix, ch, suffix = port_from.partition('] (capture): ')
                while prefix and prefix[-1].isdigit():
                    prefix = prefix[:-1]
                if prefix.endswith('['):
                    prefix = prefix[:-1]
                    conn_worked = True
                    child.attrib['from'] = f"{prefix}(capture): {suffix}"
            
            if port_to.startswith('a2j:') and '] (playback): ' in port_to:
                prefix, ch, suffix = port_to.partition('] (playback): ')
                while prefix and prefix[-1].isdigit():
                    prefix = prefix[:-1]
                if prefix.endswith('['):
                    prefix = prefix[:-1]
                    conn_worked = True
                    child.attrib['to'] = f"{prefix}(playback): {suffix}"
                    
            if ((child.attrib.get('from'), child.attrib.get('to'))
                    in reworked_conns):
                childs_to_remove.append(child)

            if conn_worked:
                reworked_conns.add(
                    (child.attrib.get('from'), child.attrib.get('to')))
                file_worked = True

    if not file_worked:
        print('nothing to do in', file_path)
        return False

    for child in childs_to_remove:
        root.remove(child)
    
    print('modifying', file_path)
    
    tree = ET.ElementTree(root)
    try:
        tree.write(file_path)
    except Exception as e:
        print(e)
        return False
    
    return True

def list_patch_files() -> Iterator[str]:
    session_root = ray_control('get_root')
    all_sessions = ray_control('list_sessions')
        
    for session_name in all_sessions.splitlines():
        session_dir = f"{session_root}/{session_name}"
        for xml_file in os.listdir(session_dir):
            if xml_file.endswith('.xml'):
                if xml_file == 'raysession.xml':
                    continue
                yield f"{session_dir}/{xml_file}"


if __name__ == '__main__':
    for patchfile in list_patch_files():
        modify_file(patchfile)
