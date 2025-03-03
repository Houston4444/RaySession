import json

fama = ['trala', 14, 15.9, True, False, None, (0, 40, 87, 14), float('inf')]
json_file = 'json_chime'

with open(json_file, 'w') as f:
    json.dump(fama, f)
    
with open(json_file, 'r') as f:
    new_fama = json.load(f)
    
for i in range(len(fama)):
    print('x', fama[i], new_fama[i], type(fama[i]), type(new_fama[i]))