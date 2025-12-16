from pathlib import Path

# Imports from standard library

# third party imports

# Imports from src/shared

# Local imports
comments = {'standard': '# Imports from standard library',
            'third': '# third party imports',
            'shared': '# Imports from src/shared',
            'local': '# Local imports'}
used_keys = set[str]()

dir = Path(__file__).parents[2] / 'daemon' / 'session_op'
locals = [p.name[:-3] for p in dir.parent.iterdir() if p.name.endswith('.py')]
print('locals', locals)

for module in dir.iterdir():
    if not module.name.endswith('.py'):
        continue
    
    if not module.is_file():
        continue
    
    with open(module, 'r') as f:
        contents = f.read()
    
    out_lines = list[str]()
    
    out_lines.append(comments['standard'])
    used_keys.add('standard')

    for line in contents.splitlines():
        if 'third' not in used_keys:
            if line.startswith('from qtpy.'):
                out_lines.append(comments['third'])
                used_keys.add('third')
        
        if 'shared' not in used_keys:
            if line.startswith(('import ray', 'import osc_paths')):
                out_lines.append(comments['shared'])
                used_keys.add('shared')
                
        if 'local' not in used_keys:
            if (line.startswith(('import ', 'from '))
                    and line.partition(' ')[2].startswith(tuple(locals))):
                out_lines.append(comments['local'])
                used_keys.add('local')
        
        out_lines.append(line)
    
    with open(module, 'w') as f:
        f.write('\n'.join(out_lines))