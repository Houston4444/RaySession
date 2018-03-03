#!/bin/bash

case "$1" in
    copy)
        shift
        
        dest_dir="$1"
        shift
        
        while [ $# -ge 1 ];do
            cp -R "$1" "$dest_dir"
            shift
        done
        ;;
    check)
        shift
        
        total_size=0
        
        until [ $# == 0 ];do
            file_size=$(du -sb "$1"|sed 's/\t.*//')
            total_size=$(($total_size+$file_size))
            shift
        done
        
        echo "$total_size"
        ;;
esac
