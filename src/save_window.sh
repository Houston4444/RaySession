#!/bin/bash

#This script could be used in a future version for saving incompatible clients via fake Ctrl+s on window

wclass="$1"
filename="$2"
windowid=$(xdotool search --class "$wclass" search --name "$filename")

[ "$windowid" ] || exit

currentWin=$(xdotool getactivewindow)

xdotool windowactivate "$windowid"
xdotool key ctrl+s

[ "$currentWin" ] && xdotool windowactivate "$currentWin"

exit 0
