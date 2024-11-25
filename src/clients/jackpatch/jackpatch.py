#!/usr/bin/python3 -u
import sys
from pathlib import Path

# import custom pyjacklib and shared
sys.path.insert(1, str(Path(__file__).parents[3] / 'pyjacklib'))
sys.path.insert(1, str(Path(__file__).parents[2] / 'shared'))

import main_loop

main_loop.run()