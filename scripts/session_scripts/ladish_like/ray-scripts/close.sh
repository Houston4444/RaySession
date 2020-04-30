#!/bin/bash

ray_control run_step

if ! $RAY_SWITCHING_SESSION;then
    if "$RAY_SCRIPTS_DIR/reload_exconfig.sh";then
        ray_control hide_script_info
    fi
fi

exit 0
