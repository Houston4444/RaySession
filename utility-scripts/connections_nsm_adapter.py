#!/usr/bin/python3

import xml.etree.ElementTree as ET
import sys

READ_OFF = 0
READ_FILE_PATH = 1
READ_OLD_NAME = 2
READ_NEW_NAME = 3
READ_BIG_VAR = 4


def main_process():
    input_file_path = ''
    read_mode = READ_FILE_PATH
    all_groups = []
    new_group = {'old_name': '', 'new_name': ''}
    
    for arg in sys.argv[1:]:
        if read_mode == READ_FILE_PATH:
            input_file_path = arg
            read_mode = READ_OFF
        elif arg == '-g':
            read_mode = READ_OLD_NAME
        elif read_mode == READ_OLD_NAME:
            new_group['old_name'] = arg
            read_mode = READ_NEW_NAME
        elif read_mode == READ_NEW_NAME:
            new_group['new_name'] = arg
            all_groups.append(new_group)
            new_group = {'old_name': '', 'new_name': ''}
            read_mode = READ_OFF
        elif arg.startswith('old_name:'):
            read_mode = READ_BIG_VAR
            for line in arg.splitlines():
                if line.startswith('old_name:'):
                    new_group['old_name'] = line.replace('old_name:', '', 1)
                elif line.startswith('new_name:'):
                    new_group['new_name'] = line.replace('new_name:', '', 1)
                    all_groups.append(new_group)
                    new_group = {'old_name': '', 'new_name': ''}
            read_mode = READ_OFF
    
    if not input_file_path:
        sys.stderr.write('no input file, nothing to do.\n')
        sys.exit(1)
    
    if read_mode != READ_OFF:
        sys.stderr.write('malformed arguments\n')
        sys.exit(1)
    
    try:
        tree = ET.parse(input_file_path)
    except:
        sys.stderr.write('fail to parse %s as a XML file\n' % input_file_path)
        sys.exit(1)
    
    jackpatch_lines = []
    
    root = tree.getroot()
    for child in root:
        port_from = ''
        port_to = ''
        
        for key in child.attrib.keys():
            if key == 'from':
                port_from = child.attrib[key]
            elif key == 'to':
                port_to = child.attrib[key]
            
            if port_from and port_to:
                break
        else:
            continue
        
        jackpatch_lines.append("%s |> %s" % (port_from, port_to))

        new_port_from = ''
        new_port_to = ''

        for group in all_groups:
            if port_from.startswith((group['old_name'] + ':',
                                group['old_name'] + '/')):
                new_port_from = port_from.replace(
                    group['old_name'], group['new_name'], 1)
                
            if port_to.startswith((group['old_name'] + ':',
                                    group['old_name'] + '/')):
                new_port_to = port_to.replace(
                    group['old_name'], group['new_name'], 1)
            
            if new_port_from and new_port_to:
                break
        
        if new_port_from:
            if new_port_to:
                jackpatch_lines.append("%s |> %s" % (new_port_from, new_port_to))
            jackpatch_lines.append("%s |> %s" % (new_port_from, port_to))
        if new_port_to:
            jackpatch_lines.append("%s |> %s" % (port_from, new_port_to))

    print('\n'.join(jackpatch_lines))


if __name__ == '__main__':
    main_process()
