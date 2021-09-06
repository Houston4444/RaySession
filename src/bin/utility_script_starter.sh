#!/bin/bash

terminal_title="Ray utility script"

if [[ "$1" == "--terminal-title" ]];then
    shift
    terminal_title="$1"
    shift
fi

script="$1"
shift

main_command="$(dirname "$(dirname "$(dirname "$BASH_SOURCE")")")/scripts/$script"
echo "$command"

terminals=""

# get the terminal to launch with the desktop environment
case $XDG_CURRENT_DESKTOP in
    GNOME )
        terminals=gnome-terminal
    ;;
    KDE )
        terminals=konsole
    ;;
    MATE )
        terminals=mate-terminal
    ;;
    XFCE )
        terminals="xfce-terminal xfce4-terminal"
    ;;
    LXDE )
        terminals=lxterminal
    ;;
esac

terminals="${terminals} gnome-terminal mate-terminal xfce4-terminal xterm konsole lxterminal rxvt"
terminal=""

for term in $terminals; do
    if which $term > /dev/null;then
        terminal="$term"
        break
    fi
done

if [ -z "$terminal" ];then
    echo "No terminal found, abort." >2
    exit 1
fi

# execute the good terminal with good arguments
case $terminal in
    gnome-terminal )
        gnome-terminal --hide-menubar -- "$main_command" "$@"
    ;;
    konsole )
        konsole --hide-tabbar --hide-menubar -p tabtitle="$terminal_title" -e "$main_command" "$@"
    ;;
    mate-terminal )
        mate-terminal --hide-menubar --title "$terminal_title" -- "$main_command" "$@"
    ;;
    xfce4-terminal )
        xfce4-terminal --hide-menubar --hide-toolbar -T "$terminal_title" -e "$main_command" "$@"
    ;;
    * )
        $terminal -e "$main_command" "$@"
    ;;
esac

