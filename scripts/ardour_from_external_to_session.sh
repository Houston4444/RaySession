#!/bin/bash

# pass as argument to this script a *.ardour session file or an ardour session dir
# if it has been made with ardour not launched from RaySession.
# It will create (or load) a RaySession session with the same name
# and move (or copy) the ardour session files to the new RaySession session

executable=ardour

if [[ "$1" == "--executable" ]];then
    shift
    executable="$1"
    shift
fi

if [ -f "$1" ] && [[ "$1" =~ ".ardour"$ ]];then
    # argument is a file and an ardour session
    ardour_session_dir=`dirname "$1"`
    ardour_session_name=`basename "$ardour_session_dir"`
    
    if ! [ -f "$ardour_session_dir/$ardour_session_name.ardour" ];then
        # argument is not the main ardour snapshot of the session
        # moves it to be the main
        if ! mv "$1" "$ardour_session_dir/$ardour_session_name.ardour";then
            echo "$1 is not the main snapshot of the session, and it can't be moved to. abort."
            exit 6
        fi
    fi
else
    ardour_session_dir="$1"
    [ -z "$1" ] && ardour_session_dir="$PWD"
    ardour_session_name=`basename "$ardour_session_dir"`
    
    if ! [ -f "$ardour_session_dir/$ardour_session_name.ardour" ];then
        echo "$ardour_session_dir/$ardour_session_name.ardour doesn't exists."
        echo "It means it is probably not an ardour session. abort."
        exit 1
    fi
fi

if ! ray_control start;then
    echo "can not start ray_control. abort."
    exit 2
fi
    
ray_root=`ray_control get_root`

if ! ray_control open_session_off "$ardour_session_name";then
    echo "impossible to load $ardour_session_name with RaySession. abort."
    exit 3
fi

ray_control add_factory_client_template "JACK Connections"
client_id=`ray_control add_executable $executable not_start`

if [ -z "$client_id" ];then
    echo "impossible to add $executable to session $ardour_session_name. abort."
    exit 4
fi

echo "client_id:$client_id"

# check if we move or copy the ardour session folder
# if session is on the same partition than RaySession root folder -> move, else copy
move_or_copy=mv
[ `stat -c '%d' "$ardour_session_dir"` == `stat -c '%d' "$ray_root"` ] || move_or_copy="cp -R -v"

new_ardour_session_dir="$ray_root/$ardour_session_name/$ardour_session_name.$client_id"

if [[ "$move_or_copy" == mv ]];then
    echo -n "moving "
else
    echo -n "copying "
fi

echo "$ardour_session_dir to $new_ardour_session_dir"

$move_or_copy "$ardour_session_dir" "$new_ardour_session_dir"

if ! mv "$new_ardour_session_dir/interchange/$ardour_session_name" \
        "$new_ardour_session_dir/interchange/$ardour_session_name.$client_id";then
    # file copy/move failed. abort
    ray_control client $client_id trash
    exit 5
fi


echo "Done. Open RaySession if not done and start the ardour client to start the ardour session."
exit 0
