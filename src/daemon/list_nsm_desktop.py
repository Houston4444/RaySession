#!/usr/bin/python3

import os
import time

desk_path_list = (
    '%s/.local' % os.getenv('HOME'),
    '/usr/local',
    '/usr')

application_dicts = []

for desk_path in desk_path_list:
    full_desk_path = "%s/share/applications" % desk_path

    if not os.path.isdir(full_desk_path):
        # applications folder doesn't exists
        continue

    if not os.access(full_desk_path, os.R_OK):
        # no permission to read this applications folder
        continue

    for root, dirs, files in os.walk(full_desk_path):
        for f in files:
            if not f.endswith('.desktop'):
                continue
            
            if f in [apd['desktop_file'] for apd in application_dicts]:
                continue

            full_desk_file = os.path.join(root, f)
            
            try:
                file = open(full_desk_file, 'r')
                contents = file.read()
            except:
                continue

            nsm_capable = False
            executable = ''
            nsm_forbidden = False
            
            for line in contents.splitlines():
                if line.startswith('Exec='):
                    executable_and_args = line.partition('=')[2]
                    executable = executable_and_args.partition(' ')[0]
                
                elif line.lower().strip() == 'X-NSM-Capable=true'.lower():
                    nsm_capable = True
                
                elif line.lower().strip() == 'X-NSM-Capable=false'.lower():
                    nsm_forbidden = True
            
            if nsm_capable and executable:
                application_dicts.append(
                    {'executable': executable,
                     'desktop_file': f,
                     'forbidden': nsm_forbidden})
    
    for application_dict in application_dicts:
        if application_dict['forbidden']:
            continue

        print('Executable:', application_dict['executable'])
        print('  Desktop :', application_dict['desktop_file'])
