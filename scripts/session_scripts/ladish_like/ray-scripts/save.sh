#!/bin/bash

finished(){
    ray_control run_step
    exit 0
}
echo sad1
contents="hostname:$(hostname)
" || finished

parameters_py="$RAY_SCRIPTS_DIR/tools/jack_parameters.py"
echo "$parameters_py"
if [ -x "$parameters_py" ];then 
    echo zefo
    jack_parameters=`"$parameters_py"` || finished
    echo zeof
else
    echo qsod
fi
echo sad3
contents+="$jack_parameters"
echo sad4
echo "$contents" > "$RAY_SESSION_PATH/jack_parameters"
echo sad5
finished
