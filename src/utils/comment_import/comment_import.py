from pathlib import Path

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
    
    if module.name == '__init__.py':
        continue
    
    if not module.is_file():
        continue
    
    with open(module, 'r') as f:
        contents = f.read()
    
    print(f'\n ----- {module} -----')
    
    out_lines = list[str]()
    used_keys.clear()

    for line in contents.splitlines():
        if line.startswith(('import ', 'from ')):
            impmodule = line.split(' ')[1]
            if impmodule.startswith('.'):
                impmodule = '.' + impmodule[1:].partition('.')[0]
            else:
                impmodule = impmodule.partition('.')[0]

            print(f'{impmodule=}')
            if 'standard' not in used_keys:
                out_lines.append(comments['standard'])
                used_keys.add('standard')
            
            if 'third' not in used_keys:
                if impmodule in ('qtpy',):
                    out_lines.append(comments['third'])
                    used_keys.add('third')
            
            if 'shared' not in used_keys:
                if impmodule in ('ray', 'osc_paths', 'osclib'):
                    out_lines.append(comments['shared'])
                    used_keys.add('shared')
                    
            if 'local' not in used_keys:
                if impmodule.startswith('.') or impmodule in tuple(locals):
                    out_lines.append(comments['local'])
                    used_keys.add('local')
        
        out_lines.append(line)
    
    print('\n'.join(out_lines))
    # break
    
    with open(module, 'w') as f:
        f.write('\n'.join(out_lines))