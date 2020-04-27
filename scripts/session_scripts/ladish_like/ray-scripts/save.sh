#!/bin/bash

finished(){
    ray_control run_step
    exit 0
}

source "$RAY_SCRIPTS_DIR/shared.sh" || finished
contents=$(get_current_parameters) || finished
echo "$contents" > "$RAY_SESSION_PATH/jack_parameters"
finished
