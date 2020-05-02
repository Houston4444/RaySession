#!/bin/bash

future_session_runs_same_script(){
    check_path="$RAY_FUTURE_SESSION_PATH"
    
    ray_scripts_dirname=$(dirname "$RAY_SCRIPTS_DIR")

    while [ -n "$check_path" ];do
        [[ "$check_path" == "$ray_scripts_dirname" ]] && return 0
        
        # another script dir for this session
        [ -d "$check_path/ray-scripts" ] && return 1
        
        [[ "$ray_scripts_dirname" =~ ^"$check_path" ]] && return 1
        
        check_path="${check_path%/*}"
    done
    
    return 1
}

close_all_if_needed=''

if $RAY_SWITCHING_SESSION;then
    future_session_runs_same_script || close_all_if_needed=close_all
fi

ray_control run_step $close_all_if_needed

if ! future_session_runs_same_script;then
    "$RAY_SCRIPTS_DIR/reload_exconfig.sh" && ray_control hide_script_info
fi

exit 0
