#!/bin/bash

# This script can be used to transform all ardour5 executables to ardour6
# in all sessions.
# If you want to use it for other executables,
# just change old_executable and new_executable values

old_executable=ardour5
new_executable=ardour6

if ! which ray_control >/dev/null;then
    echo "ray_control is missing, abort."
    exit 1
fi

all_sessions=`ray_control list_sessions`
ns=`echo "$all_sessions"|wc -l` #number of sessions

if [ -z "$all_sessions" ];then
    echo "No sessions...quit."
    exit 0
fi

# parse all sessions
for ((i=1; i<=$ns; i++));do
    session=`echo "$all_sessions"|sed -n ${i}p`
    
    # open session ('off' means -> without launching any client)
    if ! ray_control open_session_off "$session";then
        echo "failed to open session: $session"
        continue
    fi
    
    echo "treating session: $session"
    
    # parse all proxy clients of the session
    for client_id in `ray_control list_clients "executable:$old_executable"`;do
        # change executable from old_executable to new_executable
        if ray_control client $client_id set_properties "executable:$new_executable";then
            echo "  done for $client_id."
        else
            echo "  abort for client $client_id. Impossible to change its executable."
        fi
    done
done
