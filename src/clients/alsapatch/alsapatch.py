#!/usr/bin/python3 -u

# Starter for ray-alsapatch

import sys
from pathlib import Path
from typing import TYPE_CHECKING


# set src/shared/* as libs
sys.path.insert(1, str(Path(__file__).parents[2] / 'shared'))

from proc_name import set_proc_name
set_proc_name('ray-alsapatch')

from .main_loop import run as main_loop_run

def run():
    main_loop_run()
