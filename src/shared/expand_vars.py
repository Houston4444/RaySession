
_varprog = None


def expand_vars(vars: dict[str, str], string: str) -> str:
    '''Expand shell variables of form $var and ${var}.  Unknown variables
    are left unchanged. Largely inspired from os.path.expandvars'''
    global _varprog
    
    if '$' not in string:
        return string
    if not _varprog:
        import re
        _varprog = re.compile(r'\$(\w+|\{[^}]*\})', re.ASCII)

    start, end = '{', '}'
    i = 0

    while True:
        m = _varprog.search(string, i)
        if not m:
            break

        i, j = m.span(0)
        name = m.group(1)
        if name.startswith(start) and name.endswith(end):
            name = name[1:-1]

        try:
            value = vars[name]
        except KeyError:
            i = j
        else:
            tail = string[j:]
            string = string[:i] + value
            i = len(string)
            string += tail

    return string