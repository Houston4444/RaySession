#!/bin/bash

message="Press any key to close this terminal"
case $LANG in
    fr_*)
        message="Appuyez sur n'importe quelle touche pour fermer ce terminal"
        ;;
esac

"$@" && read -n 1 -s -r -p "$message"
