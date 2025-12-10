_ray_complete() {
    PY_FILE=XXX_PYCOMPLETION_XXX
    IFS=$'\n'
    COMPREPLY=($(compgen -W "$(python3 "$PY_FILE" "${COMP_WORDS[@]}")" -- "${COMP_WORDS[COMP_CWORD]}"))
    unset IFS
}

complete -F _ray_complete ray_control
