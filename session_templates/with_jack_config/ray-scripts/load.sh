#!/bin/bash

########################################################################
#                                                                      #
#  Here you can edit the script runned                                 #
#  each time daemon order this session to be loaded                    #
#  WARNING: You can be here in a switch situation,                     #
#           some clients may be still alive                            #
#           if they are NSM compatible and capable of switch,          #
#           or if they are not NSM compatible at all                   #
#           but launched with NSM protocol.                            #
#                                                                      #
#  You have access the following environment variables                 #
#  RAY_SESSION_PATH : Folder of the current session                    #
#  RAY_SCRIPTS_DIR  : Folder containing this script                    #
#     ray-scripts folder can be directly in current session            #
#     or in a parent folder.                                           #
#  RAY_PARENT_SCRIPT_DIR : Folder containing the scripts that would    #
#     be runned if RAY_SCRIPTS_DIR would not exists                    #
#  RAY_SWITCHING_SESSION: 'true' or 'false'                            #
#     'true' if session is switching from another session              #
#     and probably some clients are still alive.                       #
#                                                                      #
#  To get any other session informations, refers to ray_control help   #
#     typing: ray_control --help                                       #
#                                                                      #
########################################################################

# set it to 'false' if you want the script
# not to handle the ports of the PulseAudio -> JACK bridge
export RAY_MANAGE_PULSEAUDIO=true

# set it to 'false' if you want the script
# if you want the script to trust the parameters of JACK
export RAY_JACK_RELIABILITY_CHECK=true

# set it to 'false' if you want the script to not consider hostname
# then, a session can not be open on another machine
# if it doesn't have the same sound interface
export RAY_HOSTNAME_SENSIBLE=true

ray-jack_config_script load || exit 0
ray_control hide_script_info
ray_control run_step
