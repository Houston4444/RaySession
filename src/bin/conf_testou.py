#!/usr/bin env python3

import configparser
from pathlib import Path
import sys

sys.path.insert(1, str(Path(__file__).parents[1] / 'shared'))

import xdg

conf_file = Path.home() / '.config' / 'RaySession' / 'RaySession.conf'
print(xdg.xdg_config_dirs())
print(conf_file, conf_file.exists())
conf = configparser.ConfigParser()
file_list = conf.read(conf_file)

print(conf, file_list)
for section in conf.values():
    print('kdek', section)
    if isinstance(section, configparser.SectionProxy):
        for key, value in section.items():
            print('  ', key, value, type(value))