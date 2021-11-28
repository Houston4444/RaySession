#!/usr/bin/python3

import os

def get_nsm_capable_apps_from_desktop_file()->list:
    ''' returns a list of tuples 
        {'executable': str, 'desktop_file': str, nsm_capable: bool} '''
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
                    # desktop file already seen in a prior desk_path
                    continue

                full_desk_file = os.path.join(root, f)
                
                try:
                    file = open(full_desk_file, 'r')
                    contents = file.read()
                except:
                    continue

                executable = ''
                has_nsm_mention = False
                nsm_capable = True
                
                for line in contents.splitlines():
                    if line.startswith('Exec='):
                        executable_and_args = line.partition('=')[2]
                        executable = executable_and_args.partition(' ')[0]
                    
                    elif line.lower().startswith('x-nsm-capable='):
                        has_nsm_mention = True
                        value = line.partition('=')[2]
                        nsm_capable = bool(value.strip().lower() == 'true')
                
                if has_nsm_mention and executable:
                    application_dicts.append(
                        {'executable': executable,
                         'desktop_file': f,
                         'nsm_capable': nsm_capable})
    
    return [a for a in application_dicts if a['nsm_capable']]

application_dicts = get_nsm_capable_apps_from_desktop_file()
for a in application_dicts:
    print(a['executable'])
