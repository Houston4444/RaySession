#!/usr/bin/python3 -u
import sys
from pathlib import Path
from typing import TYPE_CHECKING

# set src/shared/* as libs
sys.path.insert(1, str(Path(__file__).parents[2] / 'shared'))

# set src/clients/jackpatch/* as libs
# this way it can share main_loop and bases
sys.path.insert(1, str(Path(__file__).parents[1] / 'jackpatch'))

if TYPE_CHECKING:
    import src.clients.jackpatch.main_loop as main_loop
else:
    import main_loop

main_loop.run()