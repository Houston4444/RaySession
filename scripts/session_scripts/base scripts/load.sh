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



# script here some actions to run before loading the session.


# set this var true if you want all running clients to stop (see top of this file).
clear_all_clients=false

if $clear_all_clients;then
    ray_control clear_clients
fi

# order daemon to load the session
ray_control run_step


# script here some actions to run once the session is loaded.


