#!/bin/bash
PATH="$HOME/RaySession/src/bin:$PATH"

# This script works for Hydrogen but could not works for any client
# It depends on the way the client saves its files under NSM (in a folder..)
executable=hydrogen

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

for ((i=1; i<=$ns; i++));do
    session=`echo "$all_sessions"|sed -n ${i}p`

    if ! ray_control open_session_off "$session";then
        echo "failed to open session: $session"
        continue
    fi
    
    session_name=$(ray_control get_session_name)
    echo "treating session: $session"
    
    for client_id in `ray_control list_clients "executable:ray-proxy"`;do
        client_files=`ray_control client $client_id list_files`
        proxy_properties=`ray_control client $client_id get_proxy_properties`
        
        if ! echo "$proxy_properties"|grep ^"executable:$executable"$ >/dev/null;then
            echo "  skipping client $client_id"
            continue
        fi
        
        if [ -z "$client_files" ] || [ -z "$proxy_properties" ];then
            echo "  client untreated $client_id"
            continue
        fi
        
        if [ `echo "$client_files"|wc -l` != 1 ];then
            echo "  client untreated $client_id"
            echo "  A proxy should only contains one directory. and no more files."
            echo "$client_files"
            continue
        fi
        
        echo "  treating client $client_id"
        
        config_file=$(echo "$proxy_properties" |grep ^"config_file:" |sed 's/^config_file://' \
                        |sed "s/\$RAY_SESSION_NAME/$session_name/g" \
                        |sed "s/\${RAY_SESSION_NAME}/$session_name/g")
        
        proxy_dir="$client_files"
        full_config_file="$proxy_dir/$config_file"
        
        if ! [ -f "$full_config_file" ];then
            echo "    file $full_config_file doesn't exists"
            continue
        fi
        
        config_file_short=`basename "$config_file"`
        
        extension="${config_file_short##*.}"
        config_file_base="${config_file_short%.*}"
        
        if ! ray_control client $client_id set_properties "executable:$executable";then
            echo "  abort for client $client_id. Impossible to change its executable."
            continue
        fi
        
        if ! mv "$full_config_file" "$proxy_dir.$extension";then
            echo "  Impossible to move $full_config_file to $proxydir.$extension. abort"
            ray_control client $client_id set_properties "executable:ray-proxy"
            continue
        fi
        
        if [[ `ls "$proxy_dir"` == 'ray-proxy.xml' ]];then
            rm -R "$proxy_dir"
        else
            echo "  $proxy_dir has not been removed because it still contains other files"
        fi
    done
done
        
        
        
