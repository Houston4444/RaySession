
import os
import sys
from pathlib import Path
import logging
import time

times = dict[str, float]()
times['start'] = time.time()

from ruamel.yaml import YAML

times['aft import'] = time.time()

yaml = YAML()

times['aft instance'] = time.time()

for key, value in times.items():
    print(value, key)