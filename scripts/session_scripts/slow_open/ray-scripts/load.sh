#!/bin/bash

#########################################################################
#                                                                       #
#  Here you can edit the script runned                                  #
#  each time daemon order this session to be loaded                     #
#  WARNING: You can be here in a switch situation,                      #
#           some clients may be still alive                             #
#           if they are NSM compatible and capable of switch            #
#           or if they are not NSM compatible at all                    #
#                 and launched directly (not via proxy)                 #
#                                                                       #
#  You have access the following environment variables                  #
#  RAY_SESSION_PATH : Folder of the current session                     #
#  RAY_SCRIPTS_DIR  : Folder containing this script                     #
#     ray-scripts folder can be directly in current session             #
#     or in a parent folder.                                            #
#                                                                       #
#  To get any other session informations, refers to ray_control help    #
#     typing: ray_control --help                                        #
#                                                                       #
#########################################################################


# Load the session without start any client
ray_control run_step open_off

# Start all clients supposed to be started at session load
# But each time, wait the client to be ready to start the next
for client_id in ray_control list_clients auto_start;do
    ray_control client "$client_id" open
done
