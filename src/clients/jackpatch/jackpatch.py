#!/usr/bin/python3 -u

# Starter for ray-jackpatch.
# ray-jackpatch is an executable launchable in NSM (or Ray) session.
# It restores JACK connections.
# To avoid many problems, the connection processus is slow.
# Connections are made one by one, waiting to receive from jack
# the callback that a connection has been made to make the 
# following one.
# It also disconnects connections undesired in the session.
# To determinate that a connection is undesired, all the present ports
# are saved in the save file. If a connection is not saved in the file,
# and its ports were present at save time, this connection will be disconnected
# at session open.
# This disconnect behavior is (probably) not suitable if we start the 
# ray-jackpatch client once the session is already loaded.
# The only way we've got to know that the entire session is opening, 
# is to check if session_is_loaded message is received.

import sys
from pathlib import Path

# import custom pyjacklib and shared
sys.path.insert(1, str(Path(__file__).parents[3] / 'pyjacklib'))
sys.path.insert(1, str(Path(__file__).parents[2] / 'shared'))

import main_loop

main_loop.run()