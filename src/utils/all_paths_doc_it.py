from pathlib import Path

all_paths_path = Path(__file__).parent / 'osc_paths' / 'all_paths'

doc_path = Path(__file__).parents[1] / 'control' / 'help_en_US'

with open(all_paths_path, 'r') as f:
    contents = f.read()

with open(doc_path, 'r') as f:
    full_doc = f.read()
    
server_doc_lines = list[str]()

started = False
for line in full_doc.splitlines():
    if line.startswith('* SERVER_COMMANDS:'):
        started = True
        continue
    if not started:
        continue
    if line.startswith('* '):
        break
    server_doc_lines.append(line)
    

out_lines = list[str]()


print('\n'.join(server_doc_lines))


# for line in contents.splitlines()