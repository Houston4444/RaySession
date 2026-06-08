#!/usr/bin/python3

import os
from pathlib import Path
import sys

def generate_in_source():
    scals = Path(__file__).parent / 'scalables'
    
    
    contents = 'from resources.scalables import breeze, transport, misc, box_icons\n\n'
    
def _generate_scalables():
    scalables = Path(__file__).parent / 'scalables'
    scalables_dict = dict[str, dict[str, str]]()

    for theme in 'dark', 'light':
        theme_path = scalables / theme
        
        for section in theme_path.iterdir():
            if not section.is_dir():
                continue
            for file_path in section.iterdir():
                if not file_path.is_file():
                    continue
                
                if not file_path.name.endswith(('.svg', '.svgz')):
                    continue
                
                folder = file_path.parent.name
                folder_dict = scalables_dict.get(folder)
                if folder_dict is None:
                    folder_dict = scalables_dict[folder] = dict[str, str]()
                name = \
                    file_path.name.partition('.')[0].upper().replace('-', '_')
                folder_dict[name] = str(file_path.relative_to(theme_path))

    lines = ['from pathlib import Path',
             '',
             '# Imports from HoustonPatchbay',
             'from resources.scalables import *',
             '']

    for folder, folder_dict in scalables_dict.items():
        lines.append('')
        lines.append(f'class {folder}({folder}):')
        for name, path in folder_dict.items():
            lines.append(f'    {name} = "{path}"')
    
    generated_resources = Path(__file__).parents[1] / 'src' / 'gui' / 'rresources'
    generated_scalables = generated_resources / 'scalables'
    generated_scalables.mkdir(parents=True, exist_ok=True)
    
    with open(generated_scalables / '__init__.py', 'w') as f:
        f.write('\n'.join(lines))


if __name__ == '__main__':
    _generate_scalables()
    
    resource_dirs = ('main_icon', 'scalable', 'app_icons', 'fonts')

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
