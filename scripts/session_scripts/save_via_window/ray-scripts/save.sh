#!/bin/bash

########################################################################
#                                                                      #
#  Here you can edit the script runned each time the session is saved  #
#                                                                      #
#  You have access the following environment variables                 #
#  RAY_SESSION_PATH : Folder of the current session                    #
#  RAY_SCRIPTS_DIR  : Folder containing this script                    #
#     ray-scripts folder can be directly in current session            #
#     or in a parent folder                                            #
#                                                                      #
#  To get any other session informations, refers to ray_control help   #
#     typing: ray_control --help                                       #
#                                                                      #
########################################################################

for executable in xdotool;do
    if ! which "$executable" >/dev/null;then
        ray_control run_step
        exit
    fi
done

if [ -n "$WAYLAND_DISPLAY" ];then
    ray_control run_step
    exit
fi

start_win=$(xdotool getactivewindow)
focus_changed=false

for client_id in `ray_control list_clients no_save_level`;do
    executable_line="$(ray_control client $client_id get_proxy_properties|grep ^executable:)"
    executable="$(basename "${executable_line#*:}")"
    
    [ -n "$executable" ] || continue
    
    wins=$(xdotool search --class "$executable")
    
    for windowid in $wins;do
        if [[ "$(xdotool getwindowname "$windowid")" ~= "*" ]];then
            focus_changed=true
            xdotool windowactivate "$windowid"
            xdotool key ctrl+s
            break
        fi
    done
done
            
if $focus_changed;then
    xdotool windowactivate "$start_win"
fi

# currentWin=$(xdotool getactivewindow)
# 
# for windowid in "$@";do
#     xdotool windowactivate "$windowid"
#     xdotool key ctrl+s
# done
# 
# [ "$currentWin" ] && xdotool windowactivate "$currentWin"
# 
# exit 0


ray_control run_step
