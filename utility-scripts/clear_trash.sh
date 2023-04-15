#!/bin/bash

ray_control get_session_path >/dev/null || exit 1

trashed_clients=`ray_control list_trashed_clients`
for trashed in $trashed_clients;do
    ray_control trashed_client $trashed remove_definitely
done