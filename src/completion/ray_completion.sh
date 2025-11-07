#!/usr/bin/env bash

PY_FILE=XXX_PYCOMPLETION_XXX

ray_complete() {
    IFS=$'\n'
    COMPREPLY=($(compgen -W "$(python3 "$PY_FILE" "${COMP_WORDS[@]}")" -- "${COMP_WORDS[COMP_CWORD]}"))
    unset IFS
}

complete -F ray_complete ray_control
