#!/bin/bash

close_all_if_needed=''

if [[ "$RAY_FUTURE_SCRIPTS_DIR" != "$RAY_SCRIPTS_DIR" ]] &&\
        ! [ -f "$RAY_FUTURE_SCRIPTS_DIR/.jack_config_script" ];then
    close_all_if_needed=close_all
fi

ray_control run_step $close_all_if_needed

if [ -n "$close_all_if_needed" ];then
    ray-jack_config_script putback && ray_control hide_script_info
fi

exit 0
