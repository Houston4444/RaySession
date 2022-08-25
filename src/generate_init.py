 
import os

def dirname(*args) -> str:
    return os.path.dirname(*args)

def basename(*args) -> str:
    return os.path.basename(*args)

def get_ui_dir() -> str:
    return dirname(os.path.realpath(__file__)) + '/gui/ui'

os.chdir(get_ui_dir())

contents = "from . import (\n"
content_lines = list[str]()

for file in os.listdir('.'):
    if file.endswith('.py') and not file.startswith('__'):
        content_lines.append('    ' + file.rpartition('.')[0] + ',')

contents += '\n'.join(content_lines)
contents = contents[:-1]
contents += ')'

file_path = f"{dirname(os.path.realpath(__file__))}/gui/ui/__init__.py"
file = open(file_path, 'w')
file.write(contents)
file.close()