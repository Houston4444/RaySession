#!/usr/bin/python3 -u
import sys
from pathlib import Path

# import src/shared
sys.path.insert(1, str(Path(__file__).parents[2] / 'shared'))

import main_loop

main_loop.run()