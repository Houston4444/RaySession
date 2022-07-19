#!/usr/bin/python3

import os
import sys

if __name__ == '__main__':
    resource_dirs = ('scalable', 'app_icons',
                     'fonts', 'canvas', 'cursors')

    contents = '<RCC version="1.0">\n'
    contents += '   <qresource prefix="/">\n'

    os.chdir(os.path.dirname(sys.argv[0]))

    for resource_dir in resource_dirs:
        for root, dirs, files in os.walk(resource_dir):
            #exclude hidden files and dirs
            files = [f for f in files if not f.startswith('.')]
            dirs[:] = [d for d in dirs if not d.startswith('.')]

            for file in files:
                contents += '       <file>%s/%s</file>\n' % (root, file)

    contents += '   </qresource>\n'
    contents += '</RCC>\n'

    resources_file = open('resources.qrc', 'w')
    resources_file.write(contents)
