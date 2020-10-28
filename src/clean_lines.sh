#!/bin/bash

cd $(dirname "$0")
for py_file in daemon/*.py gui/*.py;do
    case "$py_file" in
        ui_*.py|resources_rc.py)
            continue
    esac

    [ -f "$py_file" ] || continue
    [ -L "$py_file" ] && continue

    echo "clean file: $py_file"
    sed -i 's/ *$//' "$py_file"
done
