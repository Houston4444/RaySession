#!/bin/bash

if "$RAY_SCRIPTS_DIR/setup_jack.sh";then
    ray_control hide_script_info
    ray_control run_step
fi
